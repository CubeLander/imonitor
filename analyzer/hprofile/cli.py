from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from . import __version__
from .config import HProfileConfig
from .config_loader import EXAMPLE_CONFIG, find_default_config, load_config
from .collect_target import run_collect_target
from .export.bundle import build_manifest, write_json
from .export.lineage import build_lineage
from .export.quality import build_quality_report
from .export.unified_json import build_unified_profile
from .io.discover import discover_msprof_dbs, inventory_raw_layout, resolve_run_id
from .io.sqlite_reader import build_alignment_summary, summarize_db_windows
from .web.renderer import render_web


HELP_TEXT = """hprofile

Usage:
  python -m analyzer.hprofile
  python -m analyzer.hprofile process [config_path]
  python -m analyzer.hprofile --help

Behavior:
  - No arguments: implicit start (collect + process).
    Reads config from ./hprofile.yaml (or ./hprofile.yml).
  - process: process-only entry from existing msprof raw data.
  - --help: show this help.

Notes:
  - Recommended v2 config sections: target / msprof / profiler.
  - Empty target.entry_script uses built-in collector.
  - collect.preset is still supported for transition compatibility.
  - Output layout is fixed: out/<run_tag>/msprof_raw + out/<run_tag>/hprofile_processed.

Example start config:
"""

DEFAULT_PROCESS_CONFIG_FILES = ("hprofile.process.yaml", "hprofile.process.yml")

_SMOKE_COMPAT_ENV_MAP = {
    "tp": "SMOKE_TP",
    "pp": "SMOKE_PP",
    "max_model_len": "SMOKE_MAX_MODEL_LEN",
    "max_tokens": "SMOKE_MAX_TOKENS",
    "batch_size": "SMOKE_BATCH_SIZE",
    "rounds": "SMOKE_ROUNDS",
    "trust_remote_code": "SMOKE_TRUST_REMOTE_CODE",
    "hf_overrides_json": "SMOKE_HF_OVERRIDES_JSON",
    "temperature": "SMOKE_TEMPERATURE",
    "prompt": "SMOKE_PROMPT",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_run_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_msprof_latest(repo_root: Path) -> Path | None:
    latest = repo_root / "msprof-docs-processed" / "ascend" / "out" / "msprof_smoke" / "latest"
    return latest.resolve() if latest.exists() else None


def _find_process_config(cwd: Path) -> Path | None:
    for name in DEFAULT_PROCESS_CONFIG_FILES:
        p = cwd / name
        if p.exists() and p.is_file():
            return p.resolve()
    return None


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _as_int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return default


def _switch(value: Any, default: str = "off") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "on" if value else "off"
    s = str(value).strip().lower()
    if s in {"true", "1", "yes", "on"}:
        return "on"
    if s in {"false", "0", "no", "off"}:
        return "off"
    return str(value)


def _resolve_path(value: Any, *, base: Path) -> Path:
    p = Path(_as_str(value))
    if not p.is_absolute():
        p = (base / p).resolve()
    return p


def _set_env(env: Dict[str, str], key: str, value: Any) -> None:
    s = _as_str(value).strip()
    if s != "":
        env[key] = s


def _set_env_default(env: Dict[str, str], key: str, value: Any) -> None:
    if key in env:
        return
    _set_env(env, key, value)


def _split_args(raw: Any) -> list[str]:
    s = _as_str(raw).strip()
    if not s:
        return []
    return shlex.split(s)


def _looks_like_v2(config: Dict[str, Any]) -> bool:
    return any(k in config for k in ("target", "msprof", "profiler"))


def _preset_compat_catalog(repo_root: Path) -> Dict[str, Dict[str, Any]]:
    return {
        "msprof_vllm_smoke": {
            "target_env": {},
            "msprof_defaults": {},
        },
        "msprof_vllm_2x2_stable": {
            "target_env": {
                "SMOKE_TP": "2",
                "SMOKE_PP": "2",
                "SMOKE_MAX_TOKENS": "128",
            },
            "msprof_defaults": {
                "aicpu": "off",
                "ai_core": "off",
                "model_execution": "off",
                "type": "db",
                "sys_hardware_mem": "off",
                "l2": "off",
                "task_memory": "off",
                "ge_api": "off",
            },
        },
        "msprof_vllm_8npu_smoke": {
            "target_env": {
                "SMOKE_TP": "8",
                "SMOKE_PP": "1",
            },
            "msprof_defaults": {},
        },
    }


def _resolve_collect_script_v2(
    config: Dict[str, Any], *, repo_root: Path, config_dir: Path
) -> tuple[Path | None, str, Dict[str, str], Dict[str, Any]]:
    target = _as_dict(config.get("target"))
    entry_script = _as_str(target.get("entry_script"))
    if entry_script:
        script = _resolve_path(entry_script, base=config_dir)
        return script, f"target.entry_script={script}", {}, {}

    collect = _as_dict(config.get("collect"))
    preset = _as_str(collect.get("preset"))
    preset_catalog = _preset_compat_catalog(repo_root)
    if preset:
        compat = preset_catalog.get(preset)
        if compat is None:
            supported = ", ".join(sorted(preset_catalog))
            raise ValueError(f"unsupported collect.preset={preset}; supported: {supported}")
        script_ref = _as_str(compat.get("entry_script"))
        script = Path(script_ref).resolve() if script_ref else None
        print(
            "[hprofile][warn] collect.preset is deprecated; "
            "compatible defaults are mapped to target/msprof/profiler generic fields"
        )
        return (
            script,
            f"collect.preset={preset}",
            dict(_as_dict(compat.get("target_env"))),
            dict(_as_dict(compat.get("msprof_defaults"))),
        )

    return (
        None,
        "builtin=analyzer.hprofile.collect_target",
        {},
        {},
    )


def _apply_env_map(env: Dict[str, str], extra_env: Any) -> None:
    obj = _as_dict(extra_env)
    for k, v in obj.items():
        key = _as_str(k).strip()
        if not key:
            continue
        env[key] = _as_str(v)


def _collect_target_compat(collect: Dict[str, Any]) -> Dict[str, str]:
    # Transitional aliases from old collect section to generic target fields.
    aliases = {
        "command": ("workload_command", "target_command"),
        "program": ("workload_program", "target_program"),
        "script": ("workload_script", "target_script"),
        "args": ("workload_args", "target_args"),
    }
    out: Dict[str, str] = {}
    for target_key, legacy_keys in aliases.items():
        for key in legacy_keys:
            value = _as_str(collect.get(key)).strip()
            if value:
                out[target_key] = value
                print(f"[hprofile][warn] collect.{key} is deprecated; migrate to target.{target_key}")
                break
    return out


def _collect_smoke_env_compat(collect: Dict[str, Any]) -> Dict[str, str]:
    smoke = _as_dict(collect.get("smoke"))
    if not smoke:
        return {}

    print("[hprofile][warn] collect.smoke is deprecated; migrate these values to target.env")
    out: Dict[str, str] = {}
    for key, env_key in _SMOKE_COMPAT_ENV_MAP.items():
        value = smoke.get(key)
        sval = _as_str(value).strip()
        if sval:
            out[env_key] = sval
    return out


def _apply_msprof_env(env: Dict[str, str], msprof: Dict[str, Any]) -> None:
    _set_env(env, "MSPROF_TIMEOUT_SECONDS", msprof.get("timeout_seconds"))
    _set_env(env, "MSPROF_ASCENDCL", _switch(msprof.get("ascendcl"), "on"))
    _set_env(env, "MSPROF_RUNTIME_API", _switch(msprof.get("runtime_api"), "on"))
    _set_env(env, "MSPROF_TASK_TIME", msprof.get("task_time") or "l1")
    _set_env(env, "MSPROF_HCCL", _switch(msprof.get("hccl"), "on"))
    _set_env(env, "MSPROF_AICPU", _switch(msprof.get("aicpu"), "off"))
    _set_env(env, "MSPROF_AI_CORE", _switch(msprof.get("ai_core"), "off"))
    _set_env(env, "MSPROF_MODEL_EXECUTION", _switch(msprof.get("model_execution"), "off"))
    _set_env(env, "MSPROF_AIC_MODE", msprof.get("aic_mode") or "sample-based")
    _set_env(env, "MSPROF_AIC_FREQ", msprof.get("aic_freq") or "50")
    _set_env(env, "MSPROF_AIC_METRICS", msprof.get("aic_metrics") or "PipeUtilization")
    _set_env(env, "MSPROF_TYPE", msprof.get("type") or "db")
    _set_env(env, "MSPROF_SYS_HARDWARE_MEM", _switch(msprof.get("sys_hardware_mem"), "off"))
    _set_env(env, "MSPROF_SYS_HARDWARE_MEM_FREQ", msprof.get("sys_hardware_mem_freq") or "20")
    _set_env(env, "MSPROF_L2", _switch(msprof.get("l2"), "off"))
    _set_env(env, "MSPROF_GE_API", msprof.get("ge_api") or "off")
    _set_env(env, "MSPROF_TASK_MEMORY", _switch(msprof.get("task_memory"), "off"))


def _run_legacy_analyzer(legacy_script: Path, run_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(legacy_script),
        "--run-dir",
        str(run_dir),
        "--out-dir",
        str(out_dir),
    ]
    print("[hprofile] run legacy analyzer:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_processed_layout(processed_dir: Path) -> Dict[str, Path]:
    derived_dir = processed_dir / "derived"
    web_dir = processed_dir / "web"
    assets_dir = web_dir / "assets"
    for p in (processed_dir, derived_dir, web_dir, assets_dir):
        p.mkdir(parents=True, exist_ok=True)
    return {
        "bundle_dir": processed_dir,
        "derived_dir": derived_dir,
        "web_dir": web_dir,
        "assets_dir": assets_dir,
    }


def _prepare_legacy_outputs(
    *,
    run_dir: Path,
    layout: Dict[str, Path],
    repo_root: Path,
    profiler_cfg: Dict[str, Any],
    config_dir: Path,
) -> Path:
    legacy_out_dir = layout["derived_dir"] / "legacy_stage"
    if legacy_out_dir.exists():
        shutil.rmtree(legacy_out_dir)

    reuse_legacy_out = _as_str(profiler_cfg.get("reuse_legacy_out"))
    if reuse_legacy_out:
        src = _resolve_path(reuse_legacy_out, base=config_dir)
        if not src.exists():
            raise FileNotFoundError(f"profiler.reuse_legacy_out not found: {src}")
        shutil.copytree(src, legacy_out_dir)
        return legacy_out_dir

    legacy_script = _as_str(profiler_cfg.get("legacy_script"))
    legacy_script_path = (
        _resolve_path(legacy_script, base=config_dir)
        if legacy_script
        else (repo_root / "analyzer" / "msprof_stage_analyzer.py").resolve()
    )
    if not legacy_script_path.exists():
        raise FileNotFoundError(f"legacy analyzer script not found: {legacy_script_path}")

    _run_legacy_analyzer(legacy_script=legacy_script_path, run_dir=run_dir, out_dir=legacy_out_dir)
    return legacy_out_dir


def _derive_run_id(raw_dir: Path) -> str:
    raw_dir = raw_dir.resolve()
    if raw_dir.name == "msprof_raw":
        return raw_dir.parent.name
    return resolve_run_id(raw_dir)


def _run_process_pipeline(
    *,
    raw_dir: Path,
    processed_dir: Path,
    profiler_cfg: Dict[str, Any],
    repo_root: Path,
    config_dir: Path,
) -> Path:
    raw_dir = raw_dir.resolve()
    processed_dir = processed_dir.resolve()
    layout = _ensure_processed_layout(processed_dir)

    legacy_out_dir = _prepare_legacy_outputs(
        run_dir=raw_dir,
        layout=layout,
        repo_root=repo_root,
        profiler_cfg=profiler_cfg,
        config_dir=config_dir,
    )

    cfg = HProfileConfig(
        run_dir=raw_dir,
        bundle_dir=processed_dir,
        legacy_out_dir=legacy_out_dir,
        raw_mode="none",
        topn_streams=_as_int(profiler_cfg.get("topn_streams"), 30),
        topn_edges=_as_int(profiler_cfg.get("topn_edges"), 50),
        topn_loops=_as_int(profiler_cfg.get("topn_loops"), 50),
        topn_kernels=_as_int(profiler_cfg.get("topn_kernels"), 30),
    )

    db_paths = discover_msprof_dbs(cfg.run_dir)
    windows = summarize_db_windows(db_paths)
    alignment = build_alignment_summary(windows)
    causality_meta = _load_json(cfg.legacy_out_dir / "stream_causality_meta.json")

    quality_report = build_quality_report(
        run_dir=cfg.run_dir,
        alignment=alignment,
        causality_meta=causality_meta,
        notes=[
            "web mode: static precompiled assets with embedded JSON (no runtime backend dependency)",
            "legacy_stage outputs are generated by analyzer/msprof_stage_analyzer.py",
            "layout: out/<run_tag>/msprof_raw + out/<run_tag>/hprofile_processed",
        ],
    )

    run_id = _derive_run_id(raw_dir)
    generated_at = _utc_now()
    unified = build_unified_profile(
        run_id=run_id,
        run_dir=cfg.run_dir,
        generated_at=generated_at,
        legacy_out_dir=cfg.legacy_out_dir,
        quality_report=quality_report,
        topn_streams=cfg.topn_streams,
        topn_edges=cfg.topn_edges,
        topn_loops=cfg.topn_loops,
        topn_kernels=cfg.topn_kernels,
    )
    lineage = build_lineage(run_id=run_id)

    write_json(layout["derived_dir"] / "unified_profile.json", unified)
    write_json(layout["derived_dir"] / "lineage.json", lineage)
    write_json(layout["derived_dir"] / "quality_report.json", quality_report)
    write_json(layout["derived_dir"] / "raw_inventory.json", inventory_raw_layout(cfg.run_dir))

    render_web(layout["web_dir"], unified_profile=unified, lineage=lineage)

    raw_meta = {
        "mode": "external",
        "source_run_dir": str(raw_dir),
        "target": str(raw_dir),
    }
    manifest = build_manifest(
        bundle_dir=cfg.bundle_dir,
        run_id=run_id,
        generated_at=generated_at,
        tool_version=__version__,
        raw=raw_meta,
    )
    write_json(cfg.bundle_dir / "manifest.json", manifest)

    print(f"[hprofile] run_id={run_id}")
    print(f"[hprofile] processed_dir={cfg.bundle_dir}")
    print("[hprofile] derived: unified_profile.json, lineage.json, quality_report.json")
    print("[hprofile] web: index.html + assets (static embedded data)")
    return cfg.bundle_dir


def _write_run_manifest(
    *,
    run_root: Path,
    run_tag: str,
    raw_dir: Path,
    processed_dir: Path,
    command: list[str],
    config_path: Path,
    config: Dict[str, Any],
) -> None:
    payload: Dict[str, Any] = {
        "schema_version": "v1",
        "generated_at": _utc_now(),
        "tool": {"name": "hprofile", "version": __version__},
        "run_tag": run_tag,
        "paths": {
            "run_root": str(run_root),
            "msprof_raw": str(raw_dir),
            "hprofile_processed": str(processed_dir),
        },
        "collect": {
            "command": command,
        },
        "config": {
            "path": str(config_path),
            "snapshot": config,
        },
    }
    write_json(run_root / "run_manifest.json", payload)


def _run_collect_v2(config: Dict[str, Any], *, repo_root: Path, config_dir: Path) -> Dict[str, Any]:
    target = _as_dict(config.get("target"))
    msprof = _as_dict(config.get("msprof"))
    profiler = _as_dict(config.get("profiler"))
    collect_compat = _as_dict(config.get("collect"))

    out_root_raw = profiler.get("out_root")
    if out_root_raw is None or _as_str(out_root_raw).strip() == "":
        compat_out_root = _as_str(collect_compat.get("out_root")).strip()
        if compat_out_root:
            print("[hprofile][warn] collect.out_root is deprecated; migrate to profiler.out_root")
            out_root_raw = compat_out_root
        else:
            out_root_raw = "analyzer/out"
    out_root = _resolve_path(out_root_raw, base=config_dir)
    run_tag_raw = _as_str(profiler.get("run_tag") or "")
    if run_tag_raw == "":
        compat_run_tag = _as_str(collect_compat.get("run_tag") or collect_compat.get("run_id")).strip()
        if compat_run_tag:
            print("[hprofile][warn] collect.run_tag/run_id is deprecated; migrate to profiler.run_tag")
            run_tag_raw = compat_run_tag
        else:
            run_tag_raw = "auto"
    run_tag = _default_run_tag() if run_tag_raw in {"", "auto"} else run_tag_raw

    run_root = (out_root / run_tag).resolve()
    raw_dir = (run_root / "msprof_raw").resolve()
    processed_dir = (run_root / "hprofile_processed").resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    script, collect_entry, preset_target_env, preset_msprof_defaults = _resolve_collect_script_v2(
        config, repo_root=repo_root, config_dir=config_dir
    )
    if script is not None and not script.exists():
        raise FileNotFoundError(f"collect script not found: {script}")

    env = dict(os.environ)
    runtime = _as_str(target.get("runtime") or "docker_exec").lower()
    if runtime not in {"docker_exec", "local"}:
        raise ValueError("target.runtime must be docker_exec or local")
    env["TARGET_RUNTIME"] = runtime

    if runtime == "docker_exec":
        _set_env(env, "CONTAINER_NAME", target.get("container"))

    _set_env(env, "TARGET_VISIBLE_DEVICES", target.get("visible_devices"))
    _set_env(env, "SMOKE_VISIBLE_DEVICES", target.get("visible_devices"))
    env["KEEP_REMOTE"] = "1" if _as_bool(target.get("keep_remote"), False) else "0"

    # Fixed output layout in v2.
    env["OUT_BASE"] = str(run_root)
    env["RUN_ID"] = "msprof_raw"

    # Target launch configuration.
    target_compat = _collect_target_compat(collect_compat)
    _set_env(env, "TARGET_COMMAND", target.get("command") or target_compat.get("command"))
    _set_env(env, "TARGET_PROGRAM", target.get("program") or target_compat.get("program"))
    _set_env(env, "TARGET_SCRIPT", target.get("script") or target_compat.get("script"))
    _set_env(env, "TARGET_ARGS", target.get("args") or target_compat.get("args"))
    _apply_env_map(env, target.get("env"))
    model_path_compat = _as_str(target.get("model_path")).strip()
    if model_path_compat and "VLLM_SMOKE_MODEL" not in env:
        print("[hprofile][warn] target.model_path is deprecated; migrate to target.env.VLLM_SMOKE_MODEL")
        env["VLLM_SMOKE_MODEL"] = model_path_compat
    for k, v in preset_target_env.items():
        _set_env_default(env, k, v)

    # Backward compatibility with legacy smoke fields when present.
    smoke_compat_env = _collect_smoke_env_compat(collect_compat)
    for k, v in smoke_compat_env.items():
        _set_env_default(env, k, v)

    effective_msprof: Dict[str, Any] = {}
    effective_msprof.update(preset_msprof_defaults)
    effective_msprof.update(msprof)
    _apply_msprof_env(env, effective_msprof)

    entry_args = _split_args(target.get("entry_args"))
    run_cwd_raw = _as_str(target.get("entry_cwd"))
    run_cwd = _resolve_path(run_cwd_raw, base=config_dir) if run_cwd_raw else repo_root

    cmd: list[str] = []
    print(f"[hprofile] collect {collect_entry}")
    if script is None:
        if entry_args:
            print("[hprofile][warn] target.entry_args is ignored by built-in collector")
        rc = run_collect_target(env=env, repo_root=repo_root)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, ["builtin_collect_target"])
        cmd = ["builtin_collect_target"]
    else:
        cmd = [str(script), *entry_args]
        print(f"[hprofile] collect cmd={' '.join(cmd)}")
        subprocess.run(cmd, cwd=str(run_cwd), env=env, check=True)

    if not raw_dir.exists() or not raw_dir.is_dir():
        fallback = _default_msprof_latest(repo_root)
        if fallback is None:
            raise RuntimeError(f"collect finished but expected raw dir missing: {raw_dir}")
        raw_dir = fallback

    print(f"[hprofile] collect raw_dir={raw_dir}")
    return {
        "run_tag": run_tag,
        "run_root": run_root,
        "raw_dir": raw_dir,
        "processed_dir": processed_dir,
        "collect_cmd": cmd,
    }


def _run_process_only_v2(config: Dict[str, Any], *, repo_root: Path, config_dir: Path) -> Path:
    profiler = _as_dict(config.get("profiler"))

    raw_input = _as_str(profiler.get("raw_input_dir"))
    if raw_input:
        raw_dir = _resolve_path(raw_input, base=config_dir)
    else:
        out_root = _resolve_path(profiler.get("out_root") or "analyzer/out", base=config_dir)
        run_tag = _as_str(profiler.get("run_tag"))
        if not run_tag or run_tag == "auto":
            raise ValueError("process mode requires profiler.raw_input_dir or concrete profiler.run_tag")
        raw_dir = (out_root / run_tag / "msprof_raw").resolve()

    process_out_raw = _as_str(profiler.get("process_out_dir"))
    if process_out_raw:
        processed_dir = _resolve_path(process_out_raw, base=config_dir)
    else:
        processed_dir = (raw_dir.parent / "hprofile_processed").resolve()

    return _run_process_pipeline(
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        profiler_cfg=profiler,
        repo_root=repo_root,
        config_dir=config_dir,
    )


def _print_help() -> None:
    print(HELP_TEXT)
    print(EXAMPLE_CONFIG.rstrip())
    print()
    print("Example process-only config:")
    print("  analyzer/hprofile/process.default.yaml")


def _run_legacy_main(config: Dict[str, Any], *, repo_root: Path, config_dir: Path) -> int:
    # Compatibility bridge for v1 configs.
    mode = _as_str(config.get("mode") or "bundle_only")

    if mode == "collect_and_bundle":
        collect_state = _run_collect_v2(
            {
                "target": _as_dict(config.get("target")),
                "msprof": _as_dict(config.get("collect", {}).get("msprof")),
                "profiler": {
                    "out_root": _as_dict(config.get("bundle")).get("out_root") or "analyzer/out",
                    "run_tag": "auto",
                    "process_after_collect": True,
                    "topn_streams": _as_dict(config.get("bundle")).get("topn_streams"),
                    "topn_edges": _as_dict(config.get("bundle")).get("topn_edges"),
                    "topn_loops": _as_dict(config.get("bundle")).get("topn_loops"),
                    "topn_kernels": _as_dict(config.get("bundle")).get("topn_kernels"),
                },
                "collect": _as_dict(config.get("collect")),
            },
            repo_root=repo_root,
            config_dir=config_dir,
        )
        _run_process_pipeline(
            raw_dir=collect_state["raw_dir"],
            processed_dir=collect_state["processed_dir"],
            profiler_cfg=_as_dict(config.get("bundle")),
            repo_root=repo_root,
            config_dir=config_dir,
        )
        return 0

    if mode == "bundle_only":
        run_dir_raw = _as_str(config.get("run_dir"))
        if run_dir_raw:
            run_dir = _resolve_path(run_dir_raw, base=config_dir)
        else:
            run_dir = _default_msprof_latest(repo_root)
            if run_dir is None:
                raise RuntimeError("bundle_only mode needs run_dir or existing msprof latest")

        out_root = _resolve_path(_as_dict(config.get("bundle")).get("out_root") or "analyzer/out", base=config_dir)
        run_tag = resolve_run_id(run_dir)
        processed_dir = (out_root / run_tag / "hprofile_processed").resolve()
        _run_process_pipeline(
            raw_dir=run_dir,
            processed_dir=processed_dir,
            profiler_cfg=_as_dict(config.get("bundle")),
            repo_root=repo_root,
            config_dir=config_dir,
        )
        return 0

    if mode == "collect_only":
        _run_collect_v2(
            {
                "target": _as_dict(config.get("target")),
                "msprof": _as_dict(config.get("collect", {}).get("msprof")),
                "profiler": {"out_root": "analyzer/out", "run_tag": "auto", "process_after_collect": False},
                "collect": _as_dict(config.get("collect")),
            },
            repo_root=repo_root,
            config_dir=config_dir,
        )
        return 0

    raise ValueError("unsupported mode; expected collect_and_bundle | bundle_only | collect_only")


def _load_config_or_raise(config_path: Path) -> Dict[str, Any]:
    try:
        return load_config(config_path)
    except Exception as exc:  # pragma: no cover - passthrough for CLI error reporting
        raise ValueError(f"failed to parse config: {config_path}: {exc}") from exc


def main() -> int:
    argv = sys.argv[1:]

    if argv == ["--help"]:
        _print_help()
        return 0

    cwd = Path.cwd()

    try:
        if argv and argv[0] == "process":
            if len(argv) > 2:
                print("[hprofile][error] usage: python -m analyzer.hprofile process [config_path]")
                return 2

            if len(argv) == 2:
                config_path = _resolve_path(argv[1], base=cwd)
            else:
                default_process = _find_process_config(cwd)
                if default_process is None:
                    print("[hprofile][error] process config not found (expected ./hprofile.process.yaml or ./hprofile.process.yml)")
                    return 2
                config_path = default_process

            config = _load_config_or_raise(config_path)
            repo_root = _repo_root()
            config_dir = config_path.parent.resolve()

            if _looks_like_v2(config):
                _run_process_only_v2(config, repo_root=repo_root, config_dir=config_dir)
                return 0

            # Legacy process fallback.
            run_dir_raw = _as_str(config.get("run_dir"))
            if not run_dir_raw:
                raise ValueError("legacy process config requires run_dir")
            run_dir = _resolve_path(run_dir_raw, base=config_dir)
            out_root = _resolve_path(_as_dict(config.get("bundle")).get("out_root") or "analyzer/out", base=config_dir)
            processed_dir = (out_root / resolve_run_id(run_dir) / "hprofile_processed").resolve()
            _run_process_pipeline(
                raw_dir=run_dir,
                processed_dir=processed_dir,
                profiler_cfg=_as_dict(config.get("bundle")),
                repo_root=repo_root,
                config_dir=config_dir,
            )
            return 0

        if argv:
            print(f"[hprofile][error] unsupported arguments: {' '.join(argv)}")
            print("[hprofile] Use --help for usage.")
            return 2

        config_path = find_default_config(cwd)
        if config_path is None:
            print("[hprofile][error] config file not found (expected ./hprofile.yaml or ./hprofile.yml)")
            print("[hprofile] Use --help to see config schema and example.")
            return 2

        config = _load_config_or_raise(config_path)
        repo_root = _repo_root()
        config_dir = config_path.parent.resolve()

        if _looks_like_v2(config):
            profiler = _as_dict(config.get("profiler"))
            collect_state = _run_collect_v2(config, repo_root=repo_root, config_dir=config_dir)
            if _as_bool(profiler.get("process_after_collect"), True):
                _run_process_pipeline(
                    raw_dir=collect_state["raw_dir"],
                    processed_dir=collect_state["processed_dir"],
                    profiler_cfg=profiler,
                    repo_root=repo_root,
                    config_dir=config_dir,
                )
            _write_run_manifest(
                run_root=collect_state["run_root"],
                run_tag=collect_state["run_tag"],
                raw_dir=collect_state["raw_dir"],
                processed_dir=collect_state["processed_dir"],
                command=collect_state["collect_cmd"],
                config_path=config_path,
                config=config,
            )
            return 0

        return _run_legacy_main(config, repo_root=repo_root, config_dir=config_dir)

    except subprocess.CalledProcessError as exc:
        print(f"[hprofile][error] subprocess failed with code={exc.returncode}")
        return int(exc.returncode) if isinstance(exc.returncode, int) else 1
    except Exception as exc:
        print(f"[hprofile][error] {exc}")
        print("[hprofile] Use --help to inspect expected config fields.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
