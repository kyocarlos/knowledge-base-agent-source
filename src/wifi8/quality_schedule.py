"""Time of the zone's scheduled quality check (24-hour clock), chosen on the WiFi zone page.

Every day at this time the host runs the zone's quality check (retrieval and answer trust; on Sundays also the agent over every
question of the golden set) and reports the result to Telegram whatever it is. The host's watcher
(scripts/wifi8_quality_watch.py, via scripts/wifi8_quality_schedule.py) reads it through the zone's worker; without a file the
default time of quality-config.json applies, so a zone nobody touched keeps running as before.

Like the auto-check switch it is a file in the zone's wifi8 root (a persistent volume): ``quality-schedule.json`` =
``{"time": "HH:MM", "timezone", "changed_by", "changed_at"}``. Changing it needs the ``wifi8_quality_schedule`` capability that a
KM Control admin grants per account and zone (see ``src/km_control.py``): a check uses the language model and the host, so who may
move it is a decision. The page only mirrors that decision.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .autocheck import _now, _read, write_json

SETTINGS_NAME = "quality-schedule.json"
CAPABILITY = "wifi8_quality_schedule"
DEFAULT_TIME = "03:30"  # mirrors schedule.default_time of eval/wifi8/quality-config.json, which applies when there is no file
TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def default_timezone() -> str:
    """The clock the chosen time refers to; set per deployment (the host that runs the check reads the zone's value)."""
    return os.getenv("KM_WIFI8_QUALITY_TIMEZONE") or "Asia/Taipei"


def valid_time(value: Any) -> bool:
    return isinstance(value, str) and TIME_PATTERN.match(value) is not None


def read_settings(root: Path) -> dict[str, Any]:
    data = _read(Path(root) / SETTINGS_NAME)
    return {"time": data["time"] if valid_time(data.get("time")) else DEFAULT_TIME, "timezone": str(data.get("timezone") or default_timezone()),
            "changed_by": data.get("changed_by"), "changed_at": data.get("changed_at")}


def write_settings(root: Path, username: str, time: str) -> dict[str, Any]:
    if not valid_time(time):
        raise ValueError("time must be HH:MM on a 24-hour clock")
    record = {"time": time, "timezone": default_timezone(), "changed_by": str(username)[:100], "changed_at": _now().isoformat(timespec="seconds")}
    write_json(root, SETTINGS_NAME, record)
    return record
