"""When each zone's scheduled quality check runs: the time chosen on the zone's WiFi page (24-hour clock).

The WiFi zone page stores per zone ``quality-schedule.json`` = ``{"time": "HH:MM", "timezone": "Asia/Taipei", ...}``
(src/wifi8/quality_schedule.py); no file means the default time of quality-config.json. scripts/wifi8_quality_watch.py (cron, every
few minutes) asks ``due_zones``: a zone is due once its local time has reached the chosen time, not later than ``catchup_minutes``
after it (a host that was down must not run yesterday's check at night), and nothing ran for that local date. A due zone gets the
daily levels, or on the weekly weekday all levels (including the one that asks the agent every question of the golden set).

Everything here is plain code over dates and settings; the check itself is scripts/wifi8_quality_check.py, which reports every
scheduled run to Telegram whatever its status. This replaces the fixed 03:30 / Sunday 04:00 cron entries.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DEFAULTS = {"default_time": "03:30", "default_timezone": "Asia/Taipei", "catchup_minutes": 180, "weekly_weekday": 6,
            "daily_levels": "retrieval,trust", "weekly_levels": "retrieval,agent,trust", "max_attempts": 3}


def settings(config: dict) -> dict:
    return {**DEFAULTS, **(config.get("schedule") or {})}


def local_now(now_utc: datetime, tz_name: str, fallback: str) -> tuple[datetime, str]:
    for name in (tz_name, fallback):
        try:
            return now_utc.astimezone(ZoneInfo(name)), name
        except Exception:  # noqa: BLE001 - an unknown zone name in the zone's file falls back to the default
            continue
    return now_utc, "UTC"


def due(now_local: datetime, hhmm: str, last_run_date: str | None, catchup_minutes: int) -> bool:
    match = TIME_PATTERN.match(hhmm or "")
    if not match:
        return False
    target = now_local.replace(hour=int(match[1]), minute=int(match[2]), second=0, microsecond=0)
    return target <= now_local < target + timedelta(minutes=catchup_minutes) and last_run_date != now_local.date().isoformat()


def levels_for(now_local: datetime, cfg: dict) -> str:
    return cfg["weekly_levels"] if now_local.weekday() == int(cfg["weekly_weekday"]) else cfg["daily_levels"]


def due_zones(config: dict, read_setting: Callable[[str], dict | None], now_utc: datetime, state: dict) -> list[dict]:
    """[{zone, levels, date, time}] for every zone whose check is due now. One zone's unreadable setting never hides the others."""
    cfg = settings(config)
    found = []
    for zone in config["zones"]:
        try:
            setting = read_setting(zone) or {}
            now_local, _ = local_now(now_utc, str(setting.get("timezone") or cfg["default_timezone"]), cfg["default_timezone"])
            hhmm = setting.get("time") if TIME_PATTERN.match(str(setting.get("time") or "")) else cfg["default_time"]
            entry = state.get(zone) or {}
            if entry.get("gave_up_date") == now_local.date().isoformat():
                continue
            if due(now_local, hhmm, entry.get("last_run_date"), int(cfg["catchup_minutes"])):
                found.append({"zone": zone, "levels": levels_for(now_local, cfg), "date": now_local.date().isoformat(), "time": hhmm})
        except Exception:  # noqa: BLE001
            continue
    return found


def load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def record_run(state: dict, item: dict, now_utc: datetime) -> None:
    """The check ran and reported (PASS, WARN or FAIL): this date is done for the zone."""
    state[item["zone"]] = {"last_run_date": item["date"], "ran_at": now_utc.isoformat(timespec="seconds"), "time": item["time"],
                           "levels": item["levels"], "attempts": 0}


def record_failure(state: dict, item: dict, max_attempts: int) -> int:
    """The check could not run (crash, timeout). Returns the attempts so far; after ``max_attempts`` the date is given up on
    (the next date starts fresh) so a broken check does not retry for hours."""
    entry = {**(state.get(item["zone"]) or {})}
    entry["attempts"] = int(entry.get("attempts", 0)) + 1 if entry.get("attempt_date") == item["date"] else 1
    entry["attempt_date"] = item["date"]
    if entry["attempts"] >= max_attempts:
        entry["gave_up_date"] = item["date"]
    state[item["zone"]] = entry
    return entry["attempts"]
