"""Switch for the scheduled quality-check summary notification of a zone.

When on, every scheduled quality check (``scripts/wifi8_quality_check.py --trigger schedule``) sends a short status message for
this zone even when everything passes, so the people watching know the schedule is alive. Off (the default) keeps the old
behaviour: only WARN/FAIL and data updates are notified.

Like the auto-check switch it is a file in the zone's wifi8 root (a persistent volume) that the host script reads through the
zone's worker. Unlike it, changing it needs the ``wifi8_summary_notify`` capability that a KM Control admin grants per account
and zone (see ``src/km_control.py``); the page only mirrors that decision.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .autocheck import _now, _read, write_json

SETTINGS_NAME = "summary-notify.json"
CAPABILITY = "wifi8_summary_notify"


def read_settings(root: Path) -> dict[str, Any]:
    data = _read(Path(root) / SETTINGS_NAME)
    return {"enabled": data.get("enabled") is True, "changed_by": data.get("changed_by"), "changed_at": data.get("changed_at")}


def write_settings(root: Path, enabled: bool, username: str) -> dict[str, Any]:
    record = {"enabled": bool(enabled), "changed_by": str(username)[:100], "changed_at": _now().isoformat(timespec="seconds")}
    write_json(root, SETTINGS_NAME, record)
    return record
