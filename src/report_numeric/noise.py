"""Noise-aware thresholds for report comparison.

compare.py and findings.py call a difference "notable" when it passes a fixed placeholder (5 %). A metric that normally wanders by 8 % between repeated
runs then raises a false alarm on every comparison. Given the published history of the same product and report type, the natural spread of each value is
estimated with the median and the median absolute deviation (robust to the odd real change in the history), and the threshold becomes the larger of the
fixed rule and K times that spread. The fixed rule is a floor: history can only make a comparison more careful, never more sensitive. With fewer than
MIN_HISTORY values nothing is estimated and the fixed rule stays, and the pack says so.
"""
from __future__ import annotations

import statistics

MIN_HISTORY = 5      # fewer values than this give no usable spread
K = 3.0              # a difference must exceed K robust standard deviations of the normal spread
MAD_SCALE = 1.4826   # makes the MAD comparable to a standard deviation for roughly normal data


def robust_sigma(values) -> float | None:
    v = [float(x) for x in values if x is not None]
    if len(v) < MIN_HISTORY:
        return None
    med = statistics.median(v)
    return MAD_SCALE * statistics.median(abs(x - med) for x in v)


def relative_pct(values) -> float | None:
    """Spread as a percentage of the median (None: too little history, or a median of 0 so a percentage means nothing)."""
    v = [float(x) for x in values if x is not None]
    sigma = robust_sigma(v)
    if sigma is None:
        return None
    med = statistics.median(v)
    return None if med == 0 else sigma / abs(med) * 100


def effective(fixed: float, noise: float | None, k: float = K) -> float:
    """The threshold in use: the fixed rule, raised to k times the natural spread when that is larger."""
    return fixed if noise is None else max(fixed, k * noise)
