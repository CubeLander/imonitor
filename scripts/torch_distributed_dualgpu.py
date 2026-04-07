#!/usr/bin/env python3
"""Dual-GPU distributed Torch workload sample for imonitor verification.

This script starts 2 ranks with torch.distributed (NCCL), binds each rank to
one GPU, and continuously runs compute + cross-GPU collective communication.
"""

from __future__ import annotations

import argparse
import socket
import time

import torch
import torch.distributed as dist
import torch.multiprocessing as mp


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _worker(rank: int, args: argparse.Namespace) -> None:
    world_size = int(args.world_size)
    device = rank
    torch.cuda.set_device(device)
    torch.manual_seed(int(args.seed) + rank)
    torch.backends.cuda.matmul.allow_tf32 = True

    dist.init_process_group(
        backend="nccl",
        init_method=f"tcp://{args.master_addr}:{args.master_port}",
        rank=rank,
        world_size=world_size,
    )

    mat = int(args.matrix)
    x = torch.randn((mat, mat), device=f"cuda:{device}", dtype=torch.float32)
    w = torch.randn((mat, mat), device=f"cuda:{device}", dtype=torch.float32)
    comm_vec = torch.randn((8192,), device=f"cuda:{device}", dtype=torch.float32)
    gathered = [torch.empty_like(comm_vec) for _ in range(world_size)]

    warmup = max(0, int(args.warmup_iters))
    for _ in range(warmup):
        y = torch.relu(x @ w)
        dist.all_reduce(comm_vec, op=dist.ReduceOp.SUM)
        x = y
    torch.cuda.synchronize(device)
    dist.barrier()

    start = time.time()
    deadline = start + float(args.duration)
    last_log = start
    steps = 0

    while time.time() < deadline:
        y = torch.relu(x @ w)
        comm_vec.copy_(y.flatten()[: comm_vec.numel()])
        dist.all_reduce(comm_vec, op=dist.ReduceOp.SUM)
        dist.all_gather(gathered, comm_vec)
        x = y
        steps += 1

        if steps % 12 == 0:
            w = torch.randn_like(w)

        now = time.time()
        if rank == 0 and now - last_log >= float(args.print_interval):
            elapsed = now - start
            print(
                f"[dist-load] elapsed={elapsed:.1f}s steps={steps} "
                f"step_rate={steps / max(elapsed, 1e-9):.2f}/s",
                flush=True,
            )
            last_log = now

    torch.cuda.synchronize(device)
    step_t = torch.tensor([float(steps)], device=f"cuda:{device}")
    dist.all_reduce(step_t, op=dist.ReduceOp.SUM)
    if rank == 0:
        total_steps = float(step_t.item())
        elapsed = max(time.time() - start, 1e-9)
        print(
            f"[dist-load] done world={world_size} elapsed={elapsed:.1f}s "
            f"total_rank_steps={total_steps:.0f}",
            flush=True,
        )

    dist.destroy_process_group()


def main() -> int:
    parser = argparse.ArgumentParser(description="Dual-GPU torch.distributed workload")
    parser.add_argument("--duration", type=float, default=120.0, help="Run duration in seconds")
    parser.add_argument("--matrix", type=int, default=4096, help="Square matmul size")
    parser.add_argument("--warmup-iters", type=int, default=8, help="Warmup iterations per rank")
    parser.add_argument("--print-interval", type=float, default=3.0, help="Rank0 log interval seconds")
    parser.add_argument("--world-size", type=int, default=2, help="Distributed world size (<= GPU count)")
    parser.add_argument("--master-addr", type=str, default="127.0.0.1", help="Master address")
    parser.add_argument("--master-port", type=int, default=0, help="Master port, 0 means auto-pick")
    parser.add_argument("--seed", type=int, default=1337)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable")
    gpu_count = int(torch.cuda.device_count())
    if gpu_count < 2:
        raise SystemExit(f"Need at least 2 GPUs, got {gpu_count}")
    if args.world_size < 2:
        raise SystemExit("world-size must be >= 2")
    if args.world_size > gpu_count:
        raise SystemExit(f"world-size {args.world_size} exceeds GPU count {gpu_count}")
    if args.master_port <= 0:
        args.master_port = _pick_free_port()

    print(
        f"[dist-load] start world={args.world_size} gpus={gpu_count} "
        f"addr={args.master_addr}:{args.master_port} matrix={args.matrix}",
        flush=True,
    )
    mp.spawn(_worker, args=(args,), nprocs=int(args.world_size), join=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
