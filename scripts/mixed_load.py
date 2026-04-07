#!/usr/bin/env python3
"""Continuous mixed load generator for imonitor verification."""

from __future__ import annotations

import argparse
import math
import os
import random
import shutil
import signal
import tempfile
import threading
import time
from pathlib import Path


def _parse_gpus(value: str) -> list[int]:
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def _cpu_worker() -> None:
    x = 1.0
    while True:
        for i in range(40_000):
            x = math.sqrt((x + i * 1e-7) ** 2 + 1.0) + 0.01
            x %= 10_000_000.0
        if x > 9_000_000:
            x = 1.0


def _memory_worker(target_mb: int, stripe_mb: int = 64) -> None:
    if target_mb <= 0:
        return
    stripe = max(1, stripe_mb) * 1024 * 1024
    target = target_mb * 1024 * 1024
    chunks: list[bytearray] = []
    size = 0
    while size < target:
        chunks.append(bytearray(stripe))
        size += stripe

    idx = 0
    while True:
        arr = chunks[idx % len(chunks)]
        for j in range(0, len(arr), 4096):
            arr[j] = (arr[j] + 3) % 256
        idx += 1
        if idx > 1_000_000:
            idx = 0
            random.shuffle(chunks)


def _io_worker(chunk_mb: int = 16, max_mb: int = 256) -> None:
    chunk_mb = max(1, chunk_mb)
    max_mb = max(max_mb, chunk_mb)
    chunk = os.urandom(chunk_mb * 1024 * 1024)
    base = Path(tempfile.gettempdir()) / "imonitor_mixed_load_io"
    base.mkdir(parents=True, exist_ok=True)

    while True:
        fd, raw = tempfile.mkstemp(dir=base, prefix="imonitor-load-", suffix=".bin")
        raw_path = Path(raw)
        rot = base / f"{raw_path.name}.rot"
        try:
            written = 0
            with os.fdopen(fd, "wb", buffering=0) as f:
                while written < max_mb * 1024 * 1024:
                    f.write(chunk)
                    written += len(chunk)
            with open(raw, "rb") as f:
                _ = f.read(1024 * 1024)
            shutil.copy(raw, rot)
            os.replace(raw, str(rot) + ".done")
        finally:
            for path in (raw, str(raw) + ".done", str(rot), str(rot) + ".done"):
                try:
                    os.unlink(path)
                except OSError:
                    pass


def _gpu_worker(device: int, matrix: int = 2048) -> None:
    try:
        import torch
    except Exception as exc:
        print(f"[mixed_load] gpu:{device} skip (torch unavailable): {exc}")
        return

    if not torch.cuda.is_available():
        print(f"[mixed_load] gpu:{device} skip (CUDA unavailable)")
        return
    if device >= torch.cuda.device_count():
        print(f"[mixed_load] gpu:{device} skip (device {device} not present)")
        return

    torch.manual_seed(0)
    torch.cuda.set_device(device)
    a = torch.randn((matrix, matrix), device=f"cuda:{device}", dtype=torch.float32)
    b = torch.randn((matrix, matrix), device=f"cuda:{device}", dtype=torch.float32)

    while True:
        c = torch.matmul(a, b)
        a = torch.relu(c)
        if random.random() < 0.05:
            b = torch.randn((matrix, matrix), device=f"cuda:{device}", dtype=torch.float32)
        torch.cuda.synchronize(device)


def _start_worker(target, args=()) -> threading.Thread:
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    return t


def main() -> int:
    parser = argparse.ArgumentParser(description="Mixed load generator (CPU/Memory/IO/GPU)")
    parser.add_argument("--cpu-workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--memory-mb", type=int, default=1024)
    parser.add_argument("--io", action="store_true", help="Enable disk I/O worker")
    parser.add_argument("--io-chunk-mb", type=int, default=16)
    parser.add_argument("--io-max-mb", type=int, default=256)
    parser.add_argument("--gpu", action="store_true", help="Enable GPU workers")
    parser.add_argument("--gpu-devices", type=str, default="0,1", help="Comma list, e.g. 0,1")
    parser.add_argument("--gpu-matrix", type=int, default=2048)
    parser.add_argument("--print-interval", type=float, default=8.0)
    args = parser.parse_args()

    stop = threading.Event()

    def _stop(_sig, _frame):
        stop.set()
        print("[mixed_load] stopping...")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    threads: list[threading.Thread] = []
    for _ in range(max(1, args.cpu_workers)):
        threads.append(_start_worker(_cpu_worker))

    if args.memory_mb > 0:
        threads.append(_start_worker(_memory_worker, (args.memory_mb,)))

    if args.io:
        threads.append(_start_worker(_io_worker, (args.io_chunk_mb, args.io_max_mb)))

    gpu_devices = _parse_gpus(args.gpu_devices) if args.gpu else []
    for device in gpu_devices:
        threads.append(_start_worker(_gpu_worker, (device, args.gpu_matrix)))

    if args.gpu and not gpu_devices:
        print("[mixed_load] --gpu enabled but --gpu-devices empty")

    print(f"[mixed_load] started: cpu={args.cpu_workers}, mem={args.memory_mb}MB, io={args.io}, gpu={gpu_devices}")
    start = time.time()
    while not stop.is_set():
        print(f"[mixed_load] uptime={time.time() - start:.1f}s threads={len(threads)}")
        time.sleep(max(1.0, args.print_interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
