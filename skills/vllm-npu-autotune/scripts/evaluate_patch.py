#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List


def _mean(xs: List[float]) -> float:
    if not xs:
        return 0.0
    return sum(xs) / float(len(xs))


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / float(len(xs))
    return math.sqrt(var)


def _cv(xs: List[float]) -> float:
    m = _mean(xs)
    if m == 0.0:
        return 0.0
    return _std(xs) / m


def _load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_run_spec(path: Path) -> Dict:
    # Minimal YAML-like parser for simple key: value use, with a JSON fallback.
    txt = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(txt)

    out: Dict[str, Dict[str, float]] = {"gates": {}}
    section = ""
    for raw in txt.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":") and ":" not in line[:-1]:
            section = line[:-1].strip()
            out.setdefault(section, {})
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = k.strip()
        val = v.strip().strip("'\"")
        if val.lower() in {"true", "false"}:
            parsed = val.lower() == "true"
        else:
            try:
                parsed = float(val)
            except ValueError:
                parsed = val
        if section:
            if isinstance(out.get(section), dict):
                out[section][key] = parsed
        else:
            out[key] = parsed
    return out


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate whether a patch trial should be accepted.")
    p.add_argument("--baseline", type=Path, required=True, help="Baseline metrics JSON.")
    p.add_argument("--trial", type=Path, required=True, help="Trial metrics JSON.")
    p.add_argument("--run-spec", type=Path, required=True, help="Run spec YAML/JSON for gates.")
    p.add_argument("--out", type=Path, required=True, help="Decision JSON output path.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    baseline = _load_json(args.baseline)
    trial = _load_json(args.trial)
    spec = _load_run_spec(args.run_spec)
    gates = spec.get("gates", {}) if isinstance(spec.get("gates", {}), dict) else {}

    min_gain_pct = float(gates.get("min_gain_pct", 2.0))
    significance_z = float(gates.get("significance_z", 1.5))
    max_p95_multiplier = float(gates.get("max_p95_multiplier", 1.02))
    max_error_rate = float(gates.get("max_error_rate", 0.001))

    b_thr = [float(x) for x in baseline.get("throughput_tok_s", [])]
    t_thr = [float(x) for x in trial.get("throughput_tok_s", [])]
    if not b_thr or not t_thr:
        raise SystemExit("baseline/trial throughput_tok_s arrays are required")

    b_thr_mean = _mean(b_thr)
    t_thr_mean = _mean(t_thr)
    delta_tok_s = t_thr_mean - b_thr_mean
    delta_pct = 100.0 * delta_tok_s / b_thr_mean if b_thr_mean > 0 else 0.0

    b_thr_std = _std(b_thr)
    b_cv = _cv(b_thr)
    t_cv = _cv(t_thr)

    b_p95 = _mean([float(x) for x in baseline.get("p95_latency_ms", [])]) if baseline.get("p95_latency_ms") else 0.0
    t_p95 = _mean([float(x) for x in trial.get("p95_latency_ms", [])]) if trial.get("p95_latency_ms") else 0.0
    b_err = _mean([float(x) for x in baseline.get("error_rate", [])]) if baseline.get("error_rate") else 0.0
    t_err = _mean([float(x) for x in trial.get("error_rate", [])]) if trial.get("error_rate") else 0.0

    checks = {
        "gain_pct": delta_pct >= min_gain_pct,
        "above_noise_floor": delta_tok_s > (significance_z * b_thr_std),
        "p95_constraint": (t_p95 <= b_p95 * max_p95_multiplier) if (b_p95 > 0 and t_p95 > 0) else True,
        "error_constraint": t_err <= max_error_rate,
    }
    accept = all(checks.values())

    reason = []
    for k, ok in checks.items():
        if not ok:
            reason.append(k)
    reason_txt = "accept" if accept else "reject:" + ",".join(reason)

    out = {
        "accept": accept,
        "reason": reason_txt,
        "stats": {
            "baseline_mean_tok_s": b_thr_mean,
            "trial_mean_tok_s": t_thr_mean,
            "delta_tok_s": delta_tok_s,
            "delta_pct": delta_pct,
            "baseline_std_tok_s": b_thr_std,
            "baseline_cv": b_cv,
            "trial_cv": t_cv,
            "baseline_p95_ms": b_p95,
            "trial_p95_ms": t_p95,
            "baseline_error_rate": b_err,
            "trial_error_rate": t_err,
        },
        "gates": {
            "min_gain_pct": min_gain_pct,
            "significance_z": significance_z,
            "max_p95_multiplier": max_p95_multiplier,
            "max_error_rate": max_error_rate,
        },
        "checks": checks,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
