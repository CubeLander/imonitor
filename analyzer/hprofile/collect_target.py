from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List


MSPROF_FLAG_ENV = {
    "MSPROF_ASCENDCL": "ascendcl",
    "MSPROF_RUNTIME_API": "runtime-api",
    "MSPROF_TASK_TIME": "task-time",
    "MSPROF_AICPU": "aicpu",
    "MSPROF_AI_CORE": "ai-core",
    "MSPROF_HCCL": "hccl",
    "MSPROF_MODEL_EXECUTION": "model-execution",
    "MSPROF_AIC_MODE": "aic-mode",
    "MSPROF_AIC_FREQ": "aic-freq",
    "MSPROF_AIC_METRICS": "aic-metrics",
    "MSPROF_TYPE": "type",
    "MSPROF_SYS_HARDWARE_MEM": "sys-hardware-mem",
    "MSPROF_SYS_HARDWARE_MEM_FREQ": "sys-hardware-mem-freq",
    "MSPROF_L2": "l2",
    "MSPROF_GE_API": "ge-api",
    "MSPROF_TASK_MEMORY": "task-memory",
}


def _env(env: Dict[str, str], name: str, default: str = "") -> str:
    value = env.get(name)
    if value is None:
        return default
    return str(value)


def _split_args(raw: str) -> List[str]:
    text = raw.strip()
    if not text:
        return []
    return shlex.split(text)


def _run(cmd: List[str], *, check: bool = True, cwd: Path | None = None, env: Dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, cwd=str(cwd) if cwd else None, text=True, env=env)


def _capture(cmd: List[str]) -> str:
    return subprocess.check_output(cmd, text=True)


def _mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _build_msprof_flag_args(env: Dict[str, str]) -> List[str]:
    args: List[str] = []
    for env_key, flag in MSPROF_FLAG_ENV.items():
        value = _env(env, env_key).strip()
        if value:
            args.append(f"--{flag}={value}")
    return args


def _resolve_container_name(env: Dict[str, str]) -> str:
    explicit = _env(env, "CONTAINER_NAME").strip()
    if explicit:
        return explicit

    out = _capture(["docker", "ps", "--format", "{{.Names}}\t{{.Image}}"])
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        name, image = parts
        if "vllm-ascend" in image:
            return name

    raise RuntimeError("no running vllm-ascend container found; set target.container/CONTAINER_NAME")


def _resolve_visible_devices(env: Dict[str, str]) -> str:
    explicit = _env(env, "TARGET_VISIBLE_DEVICES").strip() or _env(env, "SMOKE_VISIBLE_DEVICES").strip()
    if explicit:
        return explicit

    try:
        out = _capture(["npu-smi", "info"])
    except Exception:
        return ""

    free_ids = re.findall(r"No running processes found in NPU (\d+)", out)
    if not free_ids:
        return ""
    return ",".join(free_ids)


def _write_run_meta(path: Path, meta: Dict[str, str]) -> None:
    lines = [f"{k}={v}" for k, v in meta.items()]
    _write_text(path, "\n".join(lines) + "\n")


def _write_index_files(local_out: Path) -> None:
    prof_dirs = sorted([str(p) for p in local_out.glob("PROF_*") if p.is_dir()])
    _write_text(local_out / "prof_dirs.txt", "\n".join(prof_dirs) + ("\n" if prof_dirs else ""))

    key_files = sorted([str(p) for p in local_out.rglob("*") if p.is_file() and "mindstudio_profiler_output" in str(p)])
    _write_text(local_out / "key_files.txt", "\n".join(key_files) + ("\n" if key_files else ""))


def _resolve_target_script_for_docker(*, repo_root: Path, target_script_raw: str, remote_root: str, container: str) -> str:
    if target_script_raw.strip() == "":
        default_src = repo_root / "analyzer" / "workload" / "vllm_distributed_smoke.py"
        if not default_src.exists():
            raise FileNotFoundError(f"default workload not found: {default_src}")
        remote_rel = "workload/vllm_distributed_smoke.py"
        _run(["docker", "cp", str(default_src), f"{container}:{remote_root}/{remote_rel}"])
        return f"{remote_root}/{remote_rel}"

    local_candidate = Path(target_script_raw)
    if not local_candidate.is_absolute():
        local_candidate = (repo_root / target_script_raw).resolve()

    if local_candidate.exists() and local_candidate.is_file():
        remote_rel = f"workload/{local_candidate.name}"
        _run(["docker", "cp", str(local_candidate), f"{container}:{remote_root}/{remote_rel}"])
        return f"{remote_root}/{remote_rel}"

    # Not found on host: treat as in-container path.
    return target_script_raw


def _docker_collect(*, repo_root: Path, out_base: Path, run_id: str, env: Dict[str, str]) -> int:
    local_out = out_base / run_id
    _mkdir(local_out)

    container = _resolve_container_name(env)
    visible_devices = _resolve_visible_devices(env)
    timeout_seconds = _env(env, "MSPROF_TIMEOUT_SECONDS", "1800").strip() or "1800"

    target_command = _env(env, "TARGET_COMMAND")
    target_program = _env(env, "TARGET_PROGRAM", "python3")
    target_args = _env(env, "TARGET_ARGS")

    remote_root = f"/tmp/hprofile_collect_{int(time.time())}_{os.getpid()}"
    remote_out = f"{remote_root}/out"

    _run(["docker", "exec", container, "/bin/sh", "-c", f"mkdir -p '{remote_root}/workload'"])
    target_script = _resolve_target_script_for_docker(
        repo_root=repo_root,
        target_script_raw=_env(env, "TARGET_SCRIPT"),
        remote_root=remote_root,
        container=container,
    )

    remote_script = """#!/usr/bin/env sh
set -eu

: "${REMOTE_ROOT:?REMOTE_ROOT is required}"
REMOTE_OUT="$REMOTE_ROOT/out"
mkdir -p "$REMOTE_OUT"

if [ -n "${VISIBLE_DEVICES:-}" ]; then
  export ASCEND_RT_VISIBLE_DEVICES="$VISIBLE_DEVICES"
  export ASCEND_VISIBLE_DEVICES="$VISIBLE_DEVICES"
  export NPU_VISIBLE_DEVICES="$VISIBLE_DEVICES"
fi

workload_wrapper="$REMOTE_ROOT/workload_wrapper.sh"
cat > "$workload_wrapper" <<'EOF'
#!/usr/bin/env sh
set -eu
REMOTE_OUT="$REMOTE_ROOT/out"
mkdir -p "$REMOTE_OUT"
export WORKLOAD_OUTPUT_JSON="$REMOTE_OUT/workload_result.json"
export VLLM_PLUGINS="${VLLM_PLUGINS:-ascend}"

if [ -n "${TARGET_COMMAND:-}" ]; then
  exec /bin/sh -lc "$TARGET_COMMAND"
fi

if [ -n "${TARGET_ARGS:-}" ]; then
  # shellcheck disable=SC2086
  exec "$TARGET_PROGRAM" "$TARGET_SCRIPT" $TARGET_ARGS
fi

exec "$TARGET_PROGRAM" "$TARGET_SCRIPT"
EOF
chmod +x "$workload_wrapper"

set +e
timeout "${MSPROF_TIMEOUT_SECONDS}s" msprof --output="$REMOTE_OUT" ${MSPROF_FLAGS} "$workload_wrapper" > "$REMOTE_OUT/msprof.log" 2>&1
rc=$?
set -e

echo "$rc" > "$REMOTE_OUT/exit_code.txt"
find "$REMOTE_OUT" -maxdepth 2 -type d -name "PROF_*" > "$REMOTE_OUT/prof_dirs.txt" || true
find "$REMOTE_OUT" -type f -path "*/mindstudio_profiler_output/*" > "$REMOTE_OUT/key_files.txt" || true

exit "$rc"
"""

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".sh") as f:
        f.write(remote_script)
        tmp_runner = Path(f.name)

    try:
        tmp_runner.chmod(0o755)
        _run(["docker", "cp", str(tmp_runner), f"{container}:{remote_root}/run_msprof_target.sh"])

        msprof_flags = " ".join(_build_msprof_flag_args(env))
        env_pairs = {
            "REMOTE_ROOT": remote_root,
            "VISIBLE_DEVICES": visible_devices,
            "TARGET_COMMAND": target_command,
            "TARGET_PROGRAM": target_program,
            "TARGET_SCRIPT": target_script,
            "TARGET_ARGS": target_args,
            "MSPROF_TIMEOUT_SECONDS": timeout_seconds,
            "MSPROF_FLAGS": msprof_flags,
        }

        # Pass through workload env and msprof env from target.env/msprof mapping.
        passthrough = [k for k in env.keys() if k.startswith("VLLM_SMOKE_") or k.startswith("MSPROF_")]
        for k in passthrough:
            env_pairs[k] = env[k]

        cmd = ["docker", "exec"]
        for k, v in env_pairs.items():
            cmd.extend(["-e", f"{k}={v}"])
        cmd.extend([container, "/bin/sh", f"{remote_root}/run_msprof_target.sh"])

        completed = _run(cmd, check=False)
        rc = int(completed.returncode)

        _run(["docker", "cp", f"{container}:{remote_out}/.", f"{local_out}/"], check=False)

        if _env(env, "KEEP_REMOTE", "0") != "1":
            _run(["docker", "exec", container, "/bin/sh", "-c", f"rm -rf '{remote_root}'"], check=False)

        meta = {
            "target_runtime": "docker_exec",
            "target_command": target_command,
            "target_program": target_program,
            "target_script": target_script,
            "target_args": target_args,
            "container": container,
            "visible_devices": visible_devices,
            "workload_model": _env(env, "VLLM_SMOKE_MODEL"),
            "timeout_seconds": timeout_seconds,
        }
        for env_key in MSPROF_FLAG_ENV.keys():
            meta[env_key.lower()] = _env(env, env_key)
        _write_run_meta(local_out / "run_meta.env", meta)
        _write_index_files(local_out)

        print(f"[collect] runtime=docker_exec container={container}")
        print(f"[collect] run_id={run_id} rc={rc}")
        print(f"[collect] out_dir={local_out}")
        return rc
    finally:
        try:
            tmp_runner.unlink(missing_ok=True)
        except Exception:
            pass


def _local_collect(*, repo_root: Path, out_base: Path, run_id: str, env: Dict[str, str]) -> int:
    local_out = out_base / run_id
    _mkdir(local_out)

    timeout_seconds = _env(env, "MSPROF_TIMEOUT_SECONDS", "1800").strip() or "1800"
    target_command = _env(env, "TARGET_COMMAND")
    target_program = _env(env, "TARGET_PROGRAM", "python3")
    target_args = _env(env, "TARGET_ARGS")
    target_script = _env(env, "TARGET_SCRIPT").strip()

    if not target_command and not target_script:
        target_script = str((repo_root / "analyzer" / "workload" / "vllm_distributed_smoke.py").resolve())

    if target_script and not target_script.startswith("/"):
        script_candidate = (repo_root / target_script).resolve()
        if script_candidate.exists():
            target_script = str(script_candidate)

    msprof_flags = _build_msprof_flag_args(env)

    if target_command:
        workload_cmd = ["/bin/sh", "-lc", target_command]
    else:
        workload_cmd = [target_program, target_script, *_split_args(target_args)]

    cmd = [
        "timeout",
        f"{timeout_seconds}s",
        "msprof",
        f"--output={local_out}",
        *msprof_flags,
        *workload_cmd,
    ]

    run_env = dict(env)
    run_env.setdefault("WORKLOAD_OUTPUT_JSON", str(local_out / "workload_result.json"))
    run_env.setdefault("VLLM_PLUGINS", "ascend")

    with (local_out / "msprof.log").open("w", encoding="utf-8") as logf:
        completed = subprocess.run(
            cmd,
            check=False,
            env=run_env,
            stdout=logf,
            stderr=subprocess.STDOUT,
            text=True,
        )

    rc = int(completed.returncode)
    _write_text(local_out / "exit_code.txt", f"{rc}\n")

    meta = {
        "target_runtime": "local",
        "target_command": target_command,
        "target_program": target_program,
        "target_script": target_script,
        "target_args": target_args,
        "workload_model": _env(env, "VLLM_SMOKE_MODEL"),
        "timeout_seconds": timeout_seconds,
    }
    for env_key in MSPROF_FLAG_ENV.keys():
        meta[env_key.lower()] = _env(env, env_key)
    _write_run_meta(local_out / "run_meta.env", meta)
    _write_index_files(local_out)

    print("[collect] runtime=local")
    print(f"[collect] run_id={run_id} rc={rc}")
    print(f"[collect] out_dir={local_out}")
    return rc


def run_collect_target(*, env: Dict[str, str], repo_root: Path) -> int:
    out_base = Path(_env(env, "OUT_BASE").strip() or "analyzer/out").resolve()
    run_id = _env(env, "RUN_ID").strip() or time.strftime("%Y%m%d_%H%M%S")
    runtime = _env(env, "TARGET_RUNTIME", "docker_exec").strip().lower()

    _mkdir(out_base)

    if runtime == "docker_exec":
        return _docker_collect(repo_root=repo_root, out_base=out_base, run_id=run_id, env=env)
    if runtime == "local":
        return _local_collect(repo_root=repo_root, out_base=out_base, run_id=run_id, env=env)

    raise ValueError("TARGET_RUNTIME must be docker_exec or local")
