"""Findings: what the model is shown instead of hundreds of aligned rows.

A Throughput report is one number per (band, bandwidth, channel, direction); an RvR report is a curve of throughput against attenuation for every
(channel, angle). Comparing them point by point (compare.py's `diffs`) buries the picture, and a model asked to explain 40 unrelated points wanders.
This module reduces each report type to a few scopes an engineer would actually read, all computed by code:

  wifi_throughput  scope = band + bandwidth + direction      median / min / max over the channels, how many channels moved the same way
  wifi_rvr         scope = band + bandwidth + direction      per curve: peak, cliff (first attenuation below CLIFF_RATIO of the peak), mean; then the median over curves

Every scope gets an evidence id (P#, kind "pattern") so the model can cite it and the checker can verify the numbers it quotes. A focus (metric, band,
bandwidth, direction) narrows the scopes before the model sees anything. Nothing here says better or worse: that needs higher_is_better.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

CLIFF_RATIO = 0.5       # a curve has "fallen off" where it first drops below this share of its own peak
MAX_SCOPES = 8          # what the model is shown; the rest is only counted
FOCUS_KEYS = ("band", "bandwidth_mhz", "direction")
SUPPORTED = ("wifi_throughput", "wifi_rvr")


@dataclass(frozen=True)
class FindingThresholds:
    pct: float = 5.0        # median / peak / mean moved by at least this share of the baseline
    cliff_db: float = 3.0   # the cliff moved by at least this many dB (placeholder until CSIT defines it)


def supported(report_type: str) -> bool:
    return report_type in SUPPORTED


def _med(values: list[float]) -> float:
    return statistics.median(values)


def _pct(base: float | None, value: float | None) -> float | None:
    return None if base in (None, 0) or value is None else (value - base) / abs(base) * 100


def _round(x: float | None, n: int = 2) -> float | None:
    return None if x is None else round(x, n)


def _fkey(m: dict) -> tuple:
    return (m.get("band"), m.get("bandwidth_mhz"), m.get("direction"))


def _scope_label(key: tuple) -> str:
    band, bw, direction = key
    return " ".join(str(p) for p in (band, f"{bw}MHz" if bw else None, {"dl": "下行", "ul": "上行"}.get(direction, direction)) if p)


def _wanted(key: tuple, focus: dict) -> bool:
    return all(focus.get(k) in (None, "", v) for k, v in zip(FOCUS_KEYS, key))


def available_focus(runs: list[dict]) -> dict:
    """The focus choices every selected report can answer, so the page offers only comparisons that exist in all of them."""
    per_run = []
    for r in runs:
        per_run.append({_fkey(m) for m in r["measurements"] if m["metric_name"] == "throughput" and m.get("value_basis") == "measured" and m.get("direction") in ("dl", "ul")})
    common = set.intersection(*per_run) if per_run else set()
    some = set.union(*per_run) if per_run else set()
    def opts(keys):
        return [{"band": b, "bandwidth_mhz": w, "direction": d, "label": _scope_label((b, w, d)), "in_all": (b, w, d) in common}
                for b, w, d in sorted(keys, key=lambda t: tuple("" if x is None else str(x) for x in t))]
    return {"scopes": opts(some), "common": len(common), "total": len(some)}


# ---------------------------------------------------------------- Throughput
def _throughput_per_run(run: dict) -> dict[tuple, dict]:
    groups: dict[tuple, dict] = {}
    for m in run["measurements"]:
        if m.get("value_basis") != "measured" or m.get("direction") not in ("dl", "ul"):
            continue
        g = groups.setdefault(_fkey(m), {"tp": {}, "rssi": []})
        if m["metric_name"] == "throughput":
            g["tp"][(m.get("channel"), m.get("protocol"), m.get("traffic_mode"), m.get("wireless_mode"))] = m["value"]
        elif m["metric_name"] == "rssi":
            g["rssi"].append(m["value"])
    out = {}
    for k, g in groups.items():
        if g["tp"]:
            v = list(g["tp"].values())
            out[k] = {"n": len(v), "median": _med(v), "min": min(v), "max": max(v), "points": g["tp"], "unit": "Mbps"}
    return out


def _channel_agreement(base_points: dict, other_points: dict, th: FindingThresholds) -> dict | None:
    """Of the channels both reports measured, how many moved by at least the threshold, and in which direction."""
    common = base_points.keys() & other_points.keys()
    if not common:
        return None
    up = down = same = 0
    for k in common:
        pct = _pct(base_points[k], other_points[k])
        if pct is None or abs(pct) < th.pct:
            same += 1
        elif pct > 0:
            up += 1
        else:
            down += 1
    return {"common_points": len(common), "higher": up, "lower": down, "within_threshold": same}


def _throughput_scopes(runs: list[dict], focus: dict, th: FindingThresholds) -> list[dict]:
    per_run = [_throughput_per_run(r) for r in runs]
    scopes = []
    for key in sorted({k for t in per_run for k in t}, key=lambda t: tuple("" if x is None else str(x) for x in t)):
        if not _wanted(key, focus):
            continue
        cells = [t.get(key) for t in per_run]
        base = cells[0]
        rows = []
        for i, c in enumerate(cells):
            if c is None:
                rows.append({"run": i, "present": False}); continue
            row = {"run": i, "present": True, "channels": c["n"], "median": _round(c["median"]), "min": _round(c["min"]), "max": _round(c["max"])}
            if i and base:
                row["median_delta_pct"] = _round(_pct(base["median"], c["median"]), 1)
                row["agreement"] = _channel_agreement(base["points"], c["points"], th)
            rows.append(row)
        movers = [r["median_delta_pct"] for r in rows if r.get("median_delta_pct") is not None]
        magnitude = max((abs(x) for x in movers), default=0.0)
        scopes.append({"scope": _scope_label(key), "key": dict(zip(FOCUS_KEYS, key)), "unit": "Mbps", "metric": "throughput", "per_run": rows,
                       "complete": all(c is not None for c in cells), "magnitude": magnitude,
                       "notable": any(abs(x) >= th.pct for x in movers)})
    return scopes


# ------------------------------------------------------------------- RvR
def _curve_features(points: list[tuple[float, float]]) -> dict | None:
    pts = sorted(points)
    if len(pts) < 3:
        return None
    peak = max(v for _, v in pts)
    if peak <= 0:
        return None
    peak_at = next(a for a, v in pts if v == peak)
    cliff = next((a for a, v in pts if a > peak_at and v < peak * CLIFF_RATIO), None)
    return {"peak": peak, "peak_at": peak_at, "cliff": cliff, "mean": statistics.fmean(v for _, v in pts), "last_att": pts[-1][0]}


def _rvr_per_run(run: dict) -> dict[tuple, dict]:
    curves: dict[tuple, dict[tuple, list]] = {}
    for m in run["measurements"]:
        if m["metric_name"] != "throughput" or m.get("value_basis") != "measured" or m.get("direction") not in ("dl", "ul") or m.get("attenuation_db") is None:
            continue
        curves.setdefault(_fkey(m), {}).setdefault((m.get("channel"), m.get("angle_deg")), []).append((m["attenuation_db"], m["value"]))
    out = {}
    for key, per_curve in curves.items():
        feats = [f for f in (_curve_features(p) for p in per_curve.values()) if f]
        if not feats:
            continue
        cliffs = [f["cliff"] for f in feats if f["cliff"] is not None]
        out[key] = {"curves": len(feats), "peak_median": _med([f["peak"] for f in feats]), "mean_median": _med([f["mean"] for f in feats]),
                    "cliff_median": _med(cliffs) if cliffs else None, "cliff_earliest": min(cliffs) if cliffs else None, "curves_with_cliff": len(cliffs),
                    "max_attenuation": max(f["last_att"] for f in feats)}
    return out


def _rvr_scopes(runs: list[dict], focus: dict, th: FindingThresholds) -> list[dict]:
    per_run = [_rvr_per_run(r) for r in runs]
    scopes = []
    for key in sorted({k for t in per_run for k in t}, key=lambda t: tuple("" if x is None else str(x) for x in t)):
        if not _wanted(key, focus):
            continue
        cells = [t.get(key) for t in per_run]
        base = cells[0]
        rows, magnitude, notable = [], 0.0, False
        for i, c in enumerate(cells):
            if c is None:
                rows.append({"run": i, "present": False}); continue
            row = {"run": i, "present": True, "curves": c["curves"], "peak_median": _round(c["peak_median"]), "mean_median": _round(c["mean_median"]),
                   "cliff_median_db": c["cliff_median"], "cliff_earliest_db": c["cliff_earliest"], "curves_with_cliff": c["curves_with_cliff"],
                   "max_attenuation_db": c["max_attenuation"]}
            if i and base:
                row["peak_delta_pct"] = _round(_pct(base["peak_median"], c["peak_median"]), 1)
                row["mean_delta_pct"] = _round(_pct(base["mean_median"], c["mean_median"]), 1)
                if base["cliff_median"] is not None and c["cliff_median"] is not None:
                    row["cliff_delta_db"] = _round(c["cliff_median"] - base["cliff_median"], 1)
                elif (base["cliff_median"] is None) != (c["cliff_median"] is None):
                    row["cliff_note"] = "只有其中一份報告的曲線掉到峰值一半以下"
                for name, val, limit in (("peak", row["peak_delta_pct"], th.pct), ("mean", row["mean_delta_pct"], th.pct), ("cliff", row.get("cliff_delta_db"), th.cliff_db)):
                    if val is not None and abs(val) >= limit:
                        notable = True; magnitude = max(magnitude, abs(val) if name != "cliff" else abs(val) / th.cliff_db * th.pct)
                if row.get("cliff_note"):
                    notable = True; magnitude = max(magnitude, 50.0)
            rows.append(row)
        scopes.append({"scope": _scope_label(key), "key": dict(zip(FOCUS_KEYS, key)), "unit": "Mbps", "metric": "throughput", "per_run": rows,
                       "complete": all(c is not None for c in cells), "magnitude": magnitude, "notable": notable})
    return scopes


# ---------------------------------------------------------------- entry
def build(runs: list[dict], report_type: str, focus: dict | None = None, thresholds: FindingThresholds | None = None) -> dict | None:
    """None when this report type has no reduction yet (the page then falls back to the plain difference table)."""
    if not supported(report_type):
        return None
    focus = {k: v for k, v in (focus or {}).items() if k in FOCUS_KEYS and v not in (None, "")}
    th = thresholds or FindingThresholds()
    scopes = (_rvr_scopes if report_type == "wifi_rvr" else _throughput_scopes)(runs, focus, th)
    shown = sorted([s for s in scopes if s["complete"] and s["notable"]], key=lambda s: -s["magnitude"])[:MAX_SCOPES]
    return {"report_type": report_type, "focus": focus, "available": available_focus(runs),
            "method": ("曲線特徵：峰值＝曲線最高的吞吐量；斷崖＝峰值之後第一個低於峰值 50% 的衰減值（dB）；數值取各曲線的中位數。" if report_type == "wifi_rvr"
                       else "每個範圍取各通道吞吐量的中位數、最小、最大；agreement 為兩份報告都測到的通道中，變動達門檻的筆數。"),
            "thresholds": {"pct": th.pct, "cliff_db": th.cliff_db, "cliff_ratio": CLIFF_RATIO},
            "scopes_total": len(scopes), "scopes_complete": sum(1 for s in scopes if s["complete"]),
            "scopes_notable": sum(1 for s in scopes if s["complete"] and s["notable"]), "scopes_unchanged": sum(1 for s in scopes if s["complete"] and not s["notable"]),
            "scopes_partial": [s["scope"] for s in scopes if not s["complete"]], "scopes": shown}
