"""Short-lived storage of generated files, readable only by the account that asked for them."""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

FILE_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class ExportSettings:
    directory: Path
    ttl_seconds: int = 3600
    max_files_per_owner: int = 20
    max_bytes: int = 25 * 1024 * 1024
    plans_per_hour: int = 12
    builds_per_hour: int = 40

    @classmethod
    def from_environment(cls) -> "ExportSettings":
        env = os.environ.get
        return cls(directory=Path(env("KM_EXPORT_DIR") or Path(tempfile.gettempdir()) / "km-export"),
                   ttl_seconds=int(env("KM_EXPORT_TTL_SECONDS", "3600")),
                   max_files_per_owner=int(env("KM_EXPORT_MAX_FILES", "20")),
                   plans_per_hour=int(env("KM_EXPORT_PLANS_PER_HOUR", "12")),
                   builds_per_hour=int(env("KM_EXPORT_BUILDS_PER_HOUR", "40")))

    def public(self) -> dict:
        return {"ttl_seconds": self.ttl_seconds}


class ExportStore:
    def __init__(self, settings: ExportSettings, clock=time.time) -> None:
        self.settings, self.clock = settings, clock
        settings.directory.mkdir(parents=True, exist_ok=True)

    def _paths(self, file_id: str) -> tuple[Path, Path]:
        return self.settings.directory / f"{file_id}.bin", self.settings.directory / f"{file_id}.json"

    def purge(self) -> None:
        now = self.clock()
        for meta in self.settings.directory.glob("*.json"):
            try:
                expired = json.loads(meta.read_text("utf-8"))["expires"] <= now
            except (OSError, ValueError, KeyError):
                expired = True
            if expired:
                meta.with_suffix(".bin").unlink(missing_ok=True)
                meta.unlink(missing_ok=True)

    def _owned(self, owner: str) -> list[tuple[float, str]]:
        found = []
        for meta in self.settings.directory.glob("*.json"):
            try:
                data = json.loads(meta.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("owner") == owner:
                found.append((data.get("created", 0), meta.stem))
        return sorted(found)

    def save(self, owner: str, data: bytes, media_type: str, name: str) -> dict:
        if len(data) > self.settings.max_bytes:
            raise ValueError("file too large")
        self.purge()
        owned = self._owned(owner)
        for _, old in owned[:max(0, len(owned) - self.settings.max_files_per_owner + 1)]:  # the oldest go first, so a user is never locked out
            for path in self._paths(old):
                path.unlink(missing_ok=True)
        file_id, now = uuid.uuid4().hex, self.clock()
        blob, meta = self._paths(file_id)
        blob.write_bytes(data)
        meta.write_text(json.dumps({"owner": owner, "media_type": media_type, "name": name, "created": now, "expires": now + self.settings.ttl_seconds, "bytes": len(data)}), "utf-8")
        return {"file_id": file_id, "name": name, "bytes": len(data), "expires_in": self.settings.ttl_seconds}

    def open(self, owner: str, file_id: str) -> tuple[Path, dict] | None:
        if not FILE_ID.match(file_id):
            return None
        blob, meta = self._paths(file_id)
        try:
            data = json.loads(meta.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        if data.get("owner") != owner or data.get("expires", 0) <= self.clock() or not blob.exists():
            return None
        return blob, data


class RateLimiter:
    """Per-account sliding hour. Kept in this process, so the service runs a single worker."""

    def __init__(self, clock=time.time) -> None:
        self.clock, self._hits = clock, defaultdict(deque)

    def allow(self, key: str, limit: int) -> bool:
        now, hits = self.clock(), self._hits[key]
        while hits and hits[0] <= now - 3600:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True
