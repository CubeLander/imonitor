from __future__ import annotations

import math

from imonitor.signals.schema import Signal


def normalize_signal(signal: Signal) -> Signal | None:
    if not math.isfinite(signal.value):
        return None
    return signal
