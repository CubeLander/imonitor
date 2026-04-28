#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_run_spec(path: Path) -> Dict[str, Any]:
    txt = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(txt)

    out: Dict[str, Any] = {}
    section = ""
    for raw in txt.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.strip().endswith(":") and ":" not in raw.strip()[:-1]:
            section = raw.strip()[:-1].strip()
            out.setdefault(section, {})
            continue
        if ":" not in raw:
            continue
        k, v = raw.split(":", 1)
        key = k.strip()
        val = v.strip().strip("'\"")
        parsed: Any
        if val.lower() in {"true", "false"}:
            parsed = val.lower() == "true"
        else:
            try:
                parsed = float(val) if "." in val else int(val)
            except ValueError:
                parsed = val
        if section and isinstance(out.get(section), dict):
            out[section][key] = parsed
        else:
            out[key] = parsed
    return out


def _is_placeholder(path_str: str) -> bool:
    return "{run_dir}" in path_str or "{model_path}" in path_str or "/abs/path/" in path_str


def _resolve_path(path_str: str, *, base_dir: Path) -> Path:
    p = Path(path_str).expanduser()
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()


def _check_path(label: str, path_str: str, required: bool, checks: List[Dict[str, Any]], *, base_dir: Path) -> None:
    if not path_str:
        checks.append({"name": label, "ok": False, "level": "error" if required else "warn", "detail": "empty"})
        return
    if _is_placeholder(path_str):
        checks.append({"name": label, "ok": False, "level": "error" if required else "warn", "detail": f"placeholder:{path_str}"})
        return
    p = _resolve_path(path_str, base_dir=base_dir)
    checks.append({"name": label, "ok": p.exists(), "level": "error" if required else "warn", "detail": str(p)})


def _run_cmd(cmd: List[str], *, timeout_seconds: int = 20) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
        )
        return int(completed.returncode), (completed.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001
        return 255, str(exc)


def _check_python_import(
    python_bin: str,
    module: str,
    extra_pythonpath: str,
    required: bool,
    checks: List[Dict[str, Any]],
) -> None:
    env = os.environ.copy()
    if extra_pythonpath:
        env["PYTHONPATH"] = extra_pythonpath + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [
        python_bin,
        "-c",
        (
            "import importlib.util,sys;"
            f"print('1' if importlib.util.find_spec('{module}') else '0')"
        ),
    ]
    try:
        out = subprocess.check_output(cmd, env=env, text=True, stderr=subprocess.STDOUT, timeout=20).strip()
        ok = out.endswith("1")
        checks.append({"name": f"import:{module}", "ok": ok, "level": "error" if required else "warn", "detail": f"python={python_bin}"})
    except Exception as exc:  # noqa: BLE001
        checks.append(
            {
                "name": f"import:{module}",
                "ok": False,
                "level": "error" if required else "warn",
                "detail": f"{python_bin} failed: {exc}",
            }
        )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Preflight checks for vLLM NPU autotune run.")
    p.add_argument("--run-spec", type=Path, required=True, help="Path to run_spec.yaml/json")
    p.add_argument("--out", type=Path, required=True, help="Output env manifest json")
    p.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Repository root for resolving relative paths")
    p.add_argument("--python-bin", default=sys.executable, help="Python executable used for runtime checks")
    p.add_argument("--strict", action="store_true", help="Fail on warnings too")
    return p.parse_args()


def _check_docker_container(container: str, checks: List[Dict[str, Any]]) -> bool:
    if not container:
        checks.append({"name": "docker:container", "ok": False, "level": "error", "detail": "empty"})
        return False

    rc, out = _run_cmd(["docker", "ps", "--format", "{{.Names}}"], timeout_seconds=20)
    if rc != 0:
        checks.append({"name": "docker:daemon_access", "ok": False, "level": "error", "detail": out})
        return False

    names = {line.strip() for line in out.splitlines() if line.strip()}
    ok = container in names
    checks.append({"name": "docker:container", "ok": ok, "level": "error", "detail": container})
    return ok


def _check_docker_module(container: str, module: str, checks: List[Dict[str, Any]]) -> None:
    cmd = [
        "docker",
        "exec",
        container,
        "python3",
        "-c",
        f"import importlib.util as u;print('1' if u.find_spec('{module}') else '0')",
    ]
    rc, out = _run_cmd(cmd, timeout_seconds=20)
    ok = (rc == 0) and out.endswith("1")
    detail = out if out else f"container={container}"
    checks.append({"name": f"docker_import:{module}", "ok": ok, "level": "error", "detail": detail})


def _check_command_entry(label: str, command: str, checks: List[Dict[str, Any]], *, base_dir: Path) -> None:
    if not command:
        checks.append({"name": label, "ok": False, "level": "warn", "detail": "empty"})
        return

    try:
        head = shlex.split(command)[0]
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": label, "ok": False, "level": "warn", "detail": f"parse_error:{exc}"})
        return

    if "/" in head:
        p = _resolve_path(head, base_dir=base_dir)
        checks.append({"name": label, "ok": p.exists(), "level": "warn", "detail": str(p)})
    else:
        checks.append({"name": label, "ok": shutil.which(head) is not None, "level": "warn", "detail": head})


def main() -> int:
    args = _parse_args()
    repo_root = args.repo_root.expanduser().resolve()
    spec = _load_run_spec(args.run_spec)
    repos = spec.get("repos", {}) if isinstance(spec.get("repos"), dict) else {}
    model = spec.get("model", {}) if isinstance(spec.get("model"), dict) else {}
    workload = spec.get("workload", {}) if isinstance(spec.get("workload"), dict) else {}
    hardware = spec.get("hardware", {}) if isinstance(spec.get("hardware"), dict) else {}
    commands = spec.get("commands", {}) if isinstance(spec.get("commands"), dict) else {}
    profiler_runtime = spec.get("profiler_runtime", {}) if isinstance(spec.get("profiler_runtime"), dict) else {}

    checks: List[Dict[str, Any]] = []

    vllm_repo = str(repos.get("vllm_repo", "")).strip()
    vllm_ascend_repo = str(repos.get("vllm_ascend_repo", "")).strip()
    model_path = str(model.get("model_path", "")).strip()
    dataset_path = str(workload.get("dataset_path", "")).strip()
    visible_devices = str(hardware.get("visible_devices", "")).strip()
    benchmark_cmd = str(commands.get("benchmark_command", "")).strip()
    smoke_cmd = str(commands.get("smoke_command", "")).strip()
    profiler_smoke_cmd = str(commands.get("profiler_smoke_command", "")).strip()

    profiler_mode = str(profiler_runtime.get("mode", "local")).strip().lower()
    profiler_container = str(profiler_runtime.get("container", "")).strip()
    profiler_cfg = str(profiler_runtime.get("hprofile_config", "")).strip()

    _check_path("repo:vllm_repo", vllm_repo, required=True, checks=checks, base_dir=repo_root)
    _check_path("repo:vllm_ascend_repo", vllm_ascend_repo, required=False, checks=checks, base_dir=repo_root)
    _check_path("model:model_path", model_path, required=True, checks=checks, base_dir=repo_root)
    _check_path("workload:dataset_path", dataset_path, required=False, checks=checks, base_dir=repo_root)
    _check_path(
        "profiler:hprofile_config",
        profiler_cfg,
        required=(profiler_mode == "docker_exec"),
        checks=checks,
        base_dir=repo_root,
    )

    if benchmark_cmd.startswith("vllm "):
        has_vllm_cmd = shutil.which("vllm") is not None
        checks.append(
            {
                "name": "cmd:vllm",
                "ok": has_vllm_cmd,
                "level": "warn",
                "detail": benchmark_cmd,
            }
        )
    if smoke_cmd:
        checks.append(
            {
                "name": "cmd:smoke_placeholders",
                "ok": ("{run_dir}" not in smoke_cmd and "{model_path}" not in smoke_cmd),
                "level": "warn",
                "detail": smoke_cmd,
            }
        )
    if benchmark_cmd:
        checks.append(
            {
                "name": "cmd:benchmark_placeholders",
                "ok": ("{run_dir}" not in benchmark_cmd and "{model_path}" not in benchmark_cmd),
                "level": "warn",
                "detail": benchmark_cmd,
            }
        )
    _check_command_entry("cmd:profiler_smoke_entry", profiler_smoke_cmd, checks, base_dir=repo_root)

    if visible_devices:
        checks.append({"name": "hardware:visible_devices", "ok": True, "level": "info", "detail": visible_devices})

    extra_pythonpath = ""
    if vllm_repo and not _is_placeholder(vllm_repo):
        extra_pythonpath = str(_resolve_path(vllm_repo, base_dir=repo_root))

    if profiler_mode not in {"local", "docker_exec"}:
        checks.append(
            {
                "name": "profiler_runtime:mode",
                "ok": False,
                "level": "error",
                "detail": profiler_mode,
            }
        )
    else:
        checks.append({"name": "profiler_runtime:mode", "ok": True, "level": "info", "detail": profiler_mode})

    if profiler_mode == "docker_exec":
        has_docker = shutil.which("docker") is not None
        checks.append({"name": "cmd:docker", "ok": has_docker, "level": "error", "detail": "docker"})
        if has_docker and _check_docker_container(profiler_container, checks):
            _check_docker_module(profiler_container, "torch", checks)
            _check_docker_module(profiler_container, "vllm", checks)
    else:
        _check_python_import(args.python_bin, "torch", extra_pythonpath, required=True, checks=checks)
        _check_python_import(args.python_bin, "vllm", extra_pythonpath, required=True, checks=checks)

    errors = [c for c in checks if (not c["ok"]) and c["level"] == "error"]
    warns = [c for c in checks if (not c["ok"]) and c["level"] == "warn"]
    ok = not errors and (not warns if args.strict else True)

    manifest = {
        "ok": ok,
        "strict": args.strict,
        "repo_root": str(repo_root),
        "python_bin": args.python_bin,
        "profiler_mode": profiler_mode,
        "profiler_container": profiler_container,
        "checks": checks,
        "error_count": len(errors),
        "warn_count": len(warns),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
