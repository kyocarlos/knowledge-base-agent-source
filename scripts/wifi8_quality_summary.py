"""Daily summary message of a zone's quality checks, sent at the time the zone's page asks for.

The WiFi zone page (switch "排程摘要通知", src/wifi8/summary_notify.py) stores per zone ``summary-notify.json``:
``{"enabled": true, "time": "HH:MM", "timezone": "Asia/Taipei"}``. scripts/wifi8_quality_watch.py (cron, every few minutes) calls
``send_due`` here: once the zone's local time has reached ``time`` (and not later than ``catchup_minutes`` after it, so a host that
was down does not send yesterday's news at night) and nothing was sent for that local date, one message is sent for that zone.

The message is built from what the checks already recorded (history.jsonl): per level the latest status, its key numbers and when
it ran. A level whose latest record is older than its ``stale_hours`` is flagged: the scheduled checks may not be running, which is
what the summary is for. Nothing here runs a check or calls a model. Only statuses, numbers and report paths are sent.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
LEVEL_NAMES = {"retrieval": "①檢索", "agent": "②Agent", "trust": "③可信度"}
DEFAULTS = {"default_time": "09:00", "default_timezone": "Asia/Taipei", "catchup_minutes": 180,
            "stale_hours": {"retrieval": 36, "trust": 36, "agent": 192}}


def settings(config: dict) -> dict:
    return {**DEFAULTS, **((config.get("notify") or {}).get("summary") or {})}


def local_now(now_utc: datetime, tz_name: str, fallback: str) -> tuple[datetime, str]:
    for name in (tz_name, fallback):
        try:
            return now_utc.astimezone(ZoneInfo(name)), name
        except Exception:  # noqa: BLE001 - an unknown zone name in the zone's file falls back to the default
            continue
    return now_utc, "UTC"


def due(now_local: datetime, hhmm: str, last_sent_date: str | None, catchup_minutes: int) -> bool:
    match = TIME_PATTERN.match(hhmm or "")
    if not match:
        return False
    target = now_local.replace(hour=int(match[1]), minute=int(match[2]), second=0, microsecond=0)
    return target <= now_local < target + timedelta(minutes=catchup_minutes) and last_sent_date != now_local.date().isoformat()


def latest_rows(history: Path, zone: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    try:
        lines = history.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("zone") == zone and row.get("level") in LEVEL_NAMES:
            rows[row["level"]] = row  # appended in time order: the last one wins
    return rows


def _pct(value: Any) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, (int, float)) else "—"


def _numbers(level: str, metrics: dict) -> str:
    if level == "retrieval":
        return f"命中@10 {_pct(metrics.get('hit_at_10'))}、MRR {metrics.get('mrr', '—')}"
    if level == "agent":
        return f"答案通過 {_pct(metrics.get('answer_pass'))}"
    return f"最近 24 小時 {metrics.get('answers', 0)} 則回答"


def build_summary(zone: str, rows: dict[str, dict], now_local: datetime, tz: str, stale_hours: dict, root: Path) -> str:
    lines = [f"[KM WiFi 品質驗證] 每日摘要・{zone.upper()}", f"{now_local:%Y-%m-%d %H:%M}（{tz}）"]
    stale = []
    for level, name in LEVEL_NAMES.items():
        row = rows.get(level)
        if not row:
            lines.append(f"{name}：尚無檢查紀錄")
            stale.append(name)
            continue
        ran = datetime.fromisoformat(row["ts"]).astimezone(now_local.tzinfo)
        age_hours = (now_local - ran).total_seconds() / 3600
        flag = "（超時未更新）" if age_hours > float(stale_hours.get(level, 36)) else ""
        if flag:
            stale.append(name)
        lines.append(f"{name}：{row['status']}（{_numbers(level, row.get('metrics') or {})}）・{ran:%m/%d %H:%M}{flag}")
    package = next((r["package_id"] for r in (rows.get("retrieval"), rows.get("agent")) if r and r.get("package_id")), None)
    if package:
        lines.append(f"資料版本 {package}")
    if stale:
        lines.append("⚠ " + "、".join(stale) + " 超過預期時間沒有新的檢查，排程可能沒有執行")
    newest = max(rows.values(), key=lambda r: r["ts"], default=None)
    if newest and newest.get("run"):
        lines.append(f"報告：{root / newest['run'] / 'report.md'}")
    return "\n".join(lines)


def send_due(config: dict, read_setting: Callable[[str], dict | None], now_utc: datetime, history: Path, state_path: Path,
             root: Path, send: Callable[[str], Any]) -> list[str]:
    """Send the summary of every zone that is due; returns the zones sent. Never raises for one zone's problem."""
    cfg = settings(config)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state = state if isinstance(state, dict) else {}
    except (OSError, json.JSONDecodeError):
        state = {}
    sent = []
    for zone in config["zones"]:
        try:
            setting = read_setting(zone) or {}
            if setting.get("enabled") is not True:
                continue
            now_local, tz = local_now(now_utc, str(setting.get("timezone") or cfg["default_timezone"]), cfg["default_timezone"])
            hhmm = setting.get("time") if TIME_PATTERN.match(str(setting.get("time") or "")) else cfg["default_time"]
            if not due(now_local, hhmm, (state.get(zone) or {}).get("last_sent_date"), int(cfg["catchup_minutes"])):
                continue
            send(build_summary(zone, latest_rows(history, zone), now_local, tz, cfg["stale_hours"], root))
            state[zone] = {"last_sent_date": now_local.date().isoformat(), "sent_at": now_utc.isoformat(timespec="seconds"), "time": hhmm}
            sent.append(zone)
        except Exception:  # noqa: BLE001 - a failed send is retried at the next poll while the catch-up window lasts
            continue
    if sent:
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(state_path)
    return sent
