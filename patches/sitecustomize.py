#!/usr/bin/env python3
"""imonitor monkeypatches loaded via PYTHONPATH/sitecustomize.

Child-process NVTX profile window patch for vLLM async/multiprocess runs.
"""

from __future__ import annotations

import os
import time


def _env_true(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default)).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _enabled() -> bool:
    return _env_true("IMONITOR_CHILD_NVTX", "0")


def _debug_enabled() -> bool:
    return _env_true("IMONITOR_CHILD_NVTX_DEBUG", "0") or bool(
        str(os.getenv("IMONITOR_CHILD_NVTX_DEBUG_LOG", "")).strip()
    )


def _debug(msg: str) -> None:
    if not _debug_enabled():
        return
    line = (
        f"{time.time():.6f} pid={os.getpid()} ppid={os.getppid()} "
        f"msg={msg}\n"
    )
    path = str(
        os.getenv("IMONITOR_CHILD_NVTX_DEBUG_LOG", "/tmp/imonitor_child_nvtx.log")
    ).strip()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _patch_enginecore_nvtx() -> None:
    if not _enabled():
        return

    _debug("sitecustomize_imported")
    try:
        import torch
        from vllm.v1.engine.core import (
            EngineCore,
            EngineCoreProc,
            EngineCoreRequestType,
        )
    except BaseException as e:
        _debug(f"import_failed type={type(e).__name__} err={e!r}")
        return

    if getattr(EngineCoreProc, "_imonitor_nvtx_patch_applied", False):
        _debug("patch_already_applied")
        return

    profile_prefix = str(os.getenv("IMONITOR_PROFILE_REQ_PREFIX", "profile-"))
    nvtx_name = str(os.getenv("IMONITOR_PROFILE_NVTX_NAME", "IMONITOR_PROFILE_PHASE"))
    _debug(
        f"patch_start prefix={profile_prefix!r} nvtx_name={nvtx_name!r} "
        f"cuda={int(torch.cuda.is_available())}"
    )

    orig_proc_handle = EngineCoreProc._handle_client_request
    orig_core_add = EngineCore.add_request
    orig_core_step = EngineCore.step
    orig_core_step_bq = getattr(EngineCore, "step_with_batch_queue", None)
    orig_core_shutdown = EngineCore.shutdown

    def _ensure_state(self) -> None:
        if not hasattr(self, "_imonitor_nvtx_active"):
            self._imonitor_nvtx_active = False
        if not hasattr(self, "_imonitor_nvtx_seen"):
            self._imonitor_nvtx_seen = 0
        if not hasattr(self, "_imonitor_profile_open_reqs"):
            self._imonitor_profile_open_reqs = set()
        if not hasattr(self, "_imonitor_debug_add_seen"):
            self._imonitor_debug_add_seen = 0

    def _push_if_needed(self, rid: str, reason: str) -> None:
        _ensure_state(self)
        if not profile_prefix or not rid.startswith(profile_prefix):
            return
        self._imonitor_profile_open_reqs.add(rid)
        if self._imonitor_nvtx_active:
            return
        try:
            if torch.cuda.is_available():
                torch.cuda.nvtx.range_push(nvtx_name)
                self._imonitor_nvtx_active = True
                self._imonitor_nvtx_seen += 1
                _debug(
                    f"nvtx_push rid={rid} reason={reason} "
                    f"open={len(self._imonitor_profile_open_reqs)} seen={self._imonitor_nvtx_seen}"
                )
        except Exception as e:
            _debug(f"nvtx_push_failed rid={rid} reason={reason} err={e!r}")

    def _pop_if_needed(self, reason: str) -> None:
        _ensure_state(self)
        if not self._imonitor_nvtx_active:
            return
        if self._imonitor_profile_open_reqs:
            return
        try:
            torch.cuda.nvtx.range_pop()
            self._imonitor_nvtx_active = False
            _debug(f"nvtx_pop reason={reason}")
        except Exception as e:
            _debug(f"nvtx_pop_failed reason={reason} err={e!r}")

    def _drop_finished(self, outputs, reason: str) -> None:
        _ensure_state(self)
        if not outputs:
            return
        removed = 0
        for eco in outputs.values():
            finished = getattr(eco, "finished_requests", None)
            if not finished:
                continue
            for rid in finished:
                rid_s = str(rid)
                if rid_s in self._imonitor_profile_open_reqs:
                    self._imonitor_profile_open_reqs.discard(rid_s)
                    removed += 1
        if removed > 0:
            _debug(
                f"profile_finished reason={reason} removed={removed} "
                f"open={len(self._imonitor_profile_open_reqs)}"
            )
            _pop_if_needed(self, reason=f"{reason}_all_done")

    def _patched_proc_handle(self, request_type, request):
        try:
            if request_type == EngineCoreRequestType.ADD:
                req, _request_wave = request
                rid = str(getattr(req, "request_id", ""))
                _ensure_state(self)
                if self._imonitor_debug_add_seen < 20:
                    self._imonitor_debug_add_seen += 1
                    _debug(
                        f"proc_add rid={rid!r} "
                        f"prefix_hit={int(bool(profile_prefix and rid.startswith(profile_prefix)))}"
                    )
                _push_if_needed(self, rid=rid, reason="proc_handle_add")
            elif request_type == EngineCoreRequestType.ABORT:
                _ensure_state(self)
                req_ids = [str(x) for x in (request or [])]
                hit = False
                for rid in req_ids:
                    if rid in self._imonitor_profile_open_reqs:
                        self._imonitor_profile_open_reqs.discard(rid)
                        hit = True
                if hit:
                    _debug(
                        f"profile_abort removed=1+ open={len(self._imonitor_profile_open_reqs)}"
                    )
                    _pop_if_needed(self, reason="abort")
        except Exception as e:
            _debug(f"proc_handle_hook_failed err={e!r}")
        return orig_proc_handle(self, request_type, request)

    def _patched_core_add(self, request, request_wave=0):
        try:
            rid = str(getattr(request, "request_id", ""))
            _ensure_state(self)
            if self._imonitor_debug_add_seen < 20:
                self._imonitor_debug_add_seen += 1
                _debug(
                    f"core_add rid={rid!r} "
                    f"prefix_hit={int(bool(profile_prefix and rid.startswith(profile_prefix)))}"
                )
            _push_if_needed(self, rid=rid, reason="core_add_fallback")
        except Exception as e:
            _debug(f"core_add_hook_failed err={e!r}")
        return orig_core_add(self, request, request_wave)

    def _patched_core_step(self):
        outputs, model_executed = orig_core_step(self)
        try:
            _drop_finished(self, outputs, reason="core_step")
        except Exception as e:
            _debug(f"core_step_hook_failed err={e!r}")
        return outputs, model_executed

    def _patched_core_step_bq(self):
        outputs, model_executed = orig_core_step_bq(self)
        try:
            _drop_finished(self, outputs, reason="core_step_bq")
        except Exception as e:
            _debug(f"core_step_bq_hook_failed err={e!r}")
        return outputs, model_executed

    def _patched_core_shutdown(self):
        try:
            _ensure_state(self)
            self._imonitor_profile_open_reqs.clear()
            _pop_if_needed(self, reason="shutdown")
        finally:
            return orig_core_shutdown(self)

    EngineCoreProc._handle_client_request = _patched_proc_handle
    EngineCore.add_request = _patched_core_add
    EngineCore.step = _patched_core_step
    if orig_core_step_bq is not None:
        EngineCore.step_with_batch_queue = _patched_core_step_bq
    EngineCore.shutdown = _patched_core_shutdown
    EngineCoreProc._imonitor_nvtx_patch_applied = True
    _debug("patch_done")


_patch_enginecore_nvtx()
