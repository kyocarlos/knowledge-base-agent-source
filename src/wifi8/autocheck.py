"""Switch and status of the automatic quality check that follows a data update.

``scripts/wifi8_quality_watch.py`` runs on the host every few minutes (cron) and starts the quality check when the zone serves
a new package. Accounts that a KM Control admin authorised (capability ``wifi8_auto_check``) can switch it off and on from the
WiFi zone page; everybody else sees the state but not the switch. The page cannot touch the host's crontab, so the
switch is a file in the zone's data directory that the watcher reads on every run (the cron entry itself stays, and a
switched-off run costs nothing). The watcher also writes a status file, so the page shows that it is alive and what it did last.

Both files live in the zone's wifi8 root (a persistent volume): they survive container replacement. No file means "on".
The scheduled daily and weekly checks are not affected by the switch.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SETTINGS_NAME = "auto-check.json"
CAPABILITY = "wifi8_auto_check"  # granted per account and zone on the KM Control admin page (config/km_capabilities.json)
STATUS_NAME = "auto-check-status.json"
DEFAULT_INTERVAL_MINUTES = 5
OVERDUE_FACTOR = 3  # a watcher that has not reported for this many intervals is not running


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_settings(root: Path) -> dict[str, Any]:
    data = _read(Path(root) / SETTINGS_NAME)
    return {"enabled": data.get("enabled") is not False, "changed_by": data.get("changed_by"), "changed_at": data.get("changed_at")}


def write_json(root: Path, name: str, record: dict[str, Any]) -> None:
    """Replace ``root/name`` atomically (the host's watcher or quality check may read it at any moment)."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=root, delete=False) as tmp:
        json.dump(record, tmp, ensure_ascii=False)
    os.replace(tmp.name, root / name)


def write_settings(root: Path, enabled: bool, username: str) -> dict[str, Any]:
    record = {"enabled": bool(enabled), "changed_by": str(username)[:100], "changed_at": _now().isoformat(timespec="seconds")}
    write_json(root, SETTINGS_NAME, record)
    return record


def view(root: Path, now: datetime | None = None) -> dict[str, Any]:
    """What the page shows: the switch, and what the watcher last reported (None when it never did)."""
    now = now or _now()
    status = _read(Path(root) / STATUS_NAME)
    interval = int(status.get("interval_minutes") or DEFAULT_INTERVAL_MINUTES)
    polled = status.get("last_poll_at")
    overdue = True
    if polled:
        try:
            overdue = (now - datetime.fromisoformat(polled)).total_seconds() > interval * 60 * OVERDUE_FACTOR
        except ValueError:
            overdue = True
    return {**read_settings(root), "interval_minutes": interval, "last_poll_at": polled, "watcher_overdue": overdue,
            "watching": status.get("watching"), "last_check": status.get("last_check")}
