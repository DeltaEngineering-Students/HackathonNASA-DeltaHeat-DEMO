"""Half-up rounding on the decimal representation (7.55 → 7.6), the same rule as science's ``stats.rnd`` and the
Ukrainian texts (R3-9). Python's ``round`` works on the binary value (round(7.55, 1) == 7.5), so displayed numbers
computed in the backend go through this instead."""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal


def rnd(v, nd: int = 1) -> float | None:
    if v is None:
        return None
    v = float(v)
    if not math.isfinite(v):
        return None
    return float(Decimal(repr(v)).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP))
