"""Switch and time of the daily quality-check summary message of a zone.

When on, a short status message for this zone is sent every day at the time chosen here (24-hour clock), built from the latest
quality checks and flagging checks that did not run on schedule, so the people watching know the schedule is alive even when
everything passes. Off (the default) keeps the old behaviour: only WARN/FAIL and data updates are notified.

Like the auto-check switch it is a file in the zone's wifi8 root (a persistent volume): ``summary-notify.json`` =
``{"enabled", "time": "HH:MM", "timezone", "changed_by", "changed_at"}``. The host's watcher (scripts/wifi8_quality_watch.py, via
scripts/wifi8_quality_summary.py) reads it through the zone's worker. Changing it needs the ``wifi8_summary_notify`` capability
that a KM Control admin grants per account and zone (see ``src/km_control.py``); the page only mirrors that decision.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .autocheck import _now, _read, write_json

SETTINGS_NAME = "summary-notify.json"
CAPABILITY = "wifi8_summary_notify"
DEFAULT_TIME = "09:00"
TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def default_timezone() -> str:
    """The clock the chosen time refers to; set per deployment (the host that sends the message reads the zone's value)."""
    return os.getenv("KM_WIFI8_SUMMARY_TIMEZONE") or "Asia/Taipei"


def valid_time(value: Any) -> bool:
    return isinstance(value, str) and TIME_PATTERN.match(value) is not None


def read_settings(root: Path) -> dict[str, Any]:
    data = _read(Path(root) / SETTINGS_NAME)
    return {"enabled": data.get("enabled") is True, "time": data["time"] if valid_time(data.get("time")) else DEFAULT_TIME,
            "timezone": str(data.get("timezone") or default_timezone()), "changed_by": data.get("changed_by"), "changed_at": data.get("changed_at")}


def write_settings(root: Path, enabled: bool, username: str, time: str | None = None) -> dict[str, Any]:
    """``time`` omitted keeps the stored (or default) time; a malformed one is refused."""
    if time is not None and not valid_time(time):
        raise ValueError("time must be HH:MM on a 24-hour clock")
    record = {"enabled": bool(enabled), "time": time or read_settings(root)["time"], "timezone": default_timezone(),
              "changed_by": str(username)[:100], "changed_at": _now().isoformat(timespec="seconds")}
    write_json(root, SETTINGS_NAME, record)
    return record
