"""Selectable LLM profiles for the assistants (phase 1: backend only).

A profile is a named, server-side choice of model. The browser sends only a profile id (never a model name, URL or key); the server checks it against the
registry (config/llm_profiles.json, or KM_LLM_PROFILES_FILE) and the policy of the zone being asked, then builds the client itself.

 * ``auto`` (always present) is today's behaviour: the primary model, with the backup tier (llm_failover) when one is configured. A request without a
   profile, or with ``auto``, goes through the caller's own default path unchanged.
 * An explicit profile is used as chosen and never falls over to another provider silently: if it fails the asker gets the error and can pick another
   model. That keeps the data-egress policy of the zone meaningful.
 * Policy per profile: ``external`` (the request leaves the company network), ``blocked_zones`` / ``allowed_zones`` (zone ids; ``hub`` is the home page
   keeper), ``purposes`` the profile is verified for, ``expires_at`` (a profile stops being offered after that date, e.g. the end of the SAM compute grant),
   ``rate_per_hour`` per account.
 * Profile ids and zone ids are logged for audit; questions, answers and keys never are.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..csit_integration_v1.zones import PAGE_KEY, ZONE_BY_ID

logger = logging.getLogger("km.llm_profiles")

PURPOSES = ("zone_answer", "keeper", "wifi_agent")
AUTO = "auto"
DEFAULT_FILE = Path(__file__).resolve().parents[2] / "config" / "llm_profiles.json"
_PAGE_TO_ZONE = {page: zone for zone, page in PAGE_KEY.items()}     # the page key "csit" is the zone "verification"
KNOWN_ZONES = set(ZONE_BY_ID) | {"hub"}


_FULLWIDTH_CITE = re.compile(r"[【［\[]\s*(S\d+)\s*[】］\]]")


def normalise_citations(text: str) -> str:
    """Some models write the evidence marker as 【S1】 (full-width brackets); the zone answer reads and checks [S1]. Only the bracket style changes."""
    return _FULLWIDTH_CITE.sub(lambda m: "[" + m.group(1) + "]", text) if isinstance(text, str) else text


class ProfileError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class Profile:
    id: str
    label: str
    description: str = ""
    source: str = "custom"                    # auto | primary (KM_LLM_PRIMARY_*) | backup (KM_LLM_BACKUP_*) | custom (the fields below)
    provider: str = ""
    model: str = ""
    base_url: str = ""
    api_key_env: str = ""
    timeout: float = 120.0
    max_tokens: int = 4096
    max_tokens_floor: int = 0
    reasoning_effort: str = ""
    tool_calling: bool = False
    external: bool = True
    experimental: bool = False
    purposes: tuple[str, ...] = ("zone_answer", "keeper")
    blocked_zones: tuple[str, ...] = ()
    allowed_zones: tuple[str, ...] | None = None
    expires_at: date | None = None
    rate_per_hour: int = 0                    # 0 = no limit
    extra: dict = field(default_factory=dict, compare=False)


AUTO_PROFILE = Profile(id=AUTO, label="自動（預設）", description="使用主要模型；主要模型失敗時自動改用備援模型。", source="auto", tool_calling=True,
                       purposes=PURPOSES)


def zone_key(zone: str) -> str:
    """A zone id from either a zone id or the page key of the front end (csit -> verification); "hub" is the home page."""
    zone = (zone or "").strip().lower()
    return _PAGE_TO_ZONE.get(zone, zone)


def _parse(raw: dict) -> Profile:
    pid = str(raw["id"]).strip()
    if not pid or not all(c.isalnum() or c in "-_." for c in pid) or len(pid) > 64:
        raise ValueError("profile id must be 1-64 letters, digits, - _ .")
    purposes = tuple(raw.get("purposes") or ("zone_answer", "keeper"))
    bad = [p for p in purposes if p not in PURPOSES]
    zones = [z for key in ("blocked_zones", "allowed_zones") for z in (raw.get(key) or [])]
    unknown = [z for z in zones if z not in KNOWN_ZONES]
    if bad or unknown:
        raise ValueError(f"profile {pid}: unknown purposes {bad} / zones {unknown}")
    source = str(raw.get("source") or "custom")
    if source not in ("auto", "primary", "backup", "custom"):
        raise ValueError(f"profile {pid}: unknown source {source}")
    if source == "custom" and not (raw.get("model") and raw.get("base_url") and raw.get("api_key_env")):
        raise ValueError(f"profile {pid}: custom needs model, base_url and api_key_env")
    expires = date.fromisoformat(raw["expires_at"]) if raw.get("expires_at") else None
    return Profile(id=pid, label=str(raw.get("label") or pid)[:80], description=str(raw.get("description") or "")[:300], source=source,
                   provider=str(raw.get("provider") or ""), model=str(raw.get("model") or ""), base_url=str(raw.get("base_url") or ""),
                   api_key_env=str(raw.get("api_key_env") or ""), timeout=float(raw.get("timeout") or 120), max_tokens=int(raw.get("max_tokens") or 4096),
                   max_tokens_floor=int(raw.get("max_tokens_floor") or 0), reasoning_effort=str(raw.get("reasoning_effort") or ""),
                   tool_calling=bool(raw.get("tool_calling", False)), external=bool(raw.get("external", True)), experimental=bool(raw.get("experimental", False)),
                   purposes=purposes, blocked_zones=tuple(raw.get("blocked_zones") or ()),
                   allowed_zones=tuple(raw["allowed_zones"]) if raw.get("allowed_zones") else None, expires_at=expires,
                   rate_per_hour=int(raw.get("rate_per_hour") or 0))


class Registry:
    def __init__(self, profiles: list[Profile], default: str = AUTO, env=os.environ, clock: Callable[[], float] = time.monotonic,
                 today: Callable[[], date] = lambda: datetime.now(timezone.utc).date()):
        by_id = {AUTO: AUTO_PROFILE}
        for p in profiles:
            if p.id == AUTO:
                continue            # auto is built in and cannot be redefined
            by_id[p.id] = p
        self.profiles, self.env, self._clock, self._today = by_id, env, clock, today
        self.default = default if default in by_id else AUTO
        self._clients: dict[str, Any] = {}
        self._recent: dict[tuple[str, str], deque] = defaultdict(deque)
        self._lock = threading.Lock()

    # ---- loading
    @classmethod
    def load(cls, path: str | os.PathLike | None = None, env=os.environ, **kw) -> "Registry":
        file = Path(path or env.get("KM_LLM_PROFILES_FILE") or DEFAULT_FILE)
        if not file.is_file():
            return cls([], env=env, **kw)
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            return cls([_parse(raw) for raw in data.get("profiles", [])], default=str(data.get("default") or AUTO), env=env, **kw)
        except Exception as exc:  # noqa: BLE001 - a bad file must not take the assistants down: only auto stays
            logger.error("LLM profile file %s is invalid (%s); only the automatic profile is offered", file, exc)
            return cls([], env=env, **kw)

    # ---- availability
    def _resolved(self, p: Profile) -> tuple[str, str, str]:
        """(model, base_url, api_key_env) of a profile after resolving its source."""
        e = self.env
        if p.source == "primary":
            return e.get("KM_LLM_PRIMARY_MODEL", ""), e.get("KM_LLM_PRIMARY_BASE_URL", ""), e.get("KM_LLM_PRIMARY_API_KEY_ENV") or "SUB2API_API_KEY"
        if p.source == "backup":
            return e.get("KM_LLM_BACKUP_MODEL", ""), e.get("KM_LLM_BACKUP_BASE_URL", ""), e.get("KM_LLM_BACKUP_API_KEY_ENV") or "MODAONE_API_KEY"
        return p.model, p.base_url, p.api_key_env

    def why_not(self, p: Profile, zone: str, purpose: str) -> tuple[int, str, str] | None:
        """None when the profile may be used for this zone and purpose; otherwise (http status, code, message for the asker)."""
        zone = zone_key(zone)
        if purpose not in PURPOSES:
            return 422, "bad_purpose", "unknown purpose"
        if purpose not in p.purposes:
            return 422, "not_supported", "這個模型目前不支援這個助理"
        if p.expires_at and self._today() > p.expires_at:
            return 403, "expired", f"這個模型的使用期限已於 {p.expires_at.isoformat()} 結束"
        if zone in p.blocked_zones or (p.allowed_zones is not None and zone not in p.allowed_zones):
            return 403, "zone_blocked", "這個專區的資料不允許使用這個模型"
        if p.source != "auto":
            model, base_url, key_env = self._resolved(p)
            if not model or not base_url or not self.env.get(key_env, ""):
                return 503, "unavailable", "這個模型目前沒有設定完成"
        return None

    def check(self, profile_id: str | None, zone: str, purpose: str) -> Profile:
        pid = (profile_id or "").strip() or self.default
        p = self.profiles.get(pid)
        if p is None:
            raise ProfileError(422, "unknown_profile", "沒有這個模型選項")
        problem = self.why_not(p, zone, purpose)
        if problem:
            raise ProfileError(*problem)
        return p

    def listing(self, zone: str, purpose: str) -> dict:
        items = []
        for p in self.profiles.values():
            problem = self.why_not(p, zone, purpose)
            items.append({"id": p.id, "label": p.label, "description": p.description, "external": p.external, "experimental": p.experimental,
                          "default": p.id == self.default, "available": problem is None, "reason": problem[2] if problem else None})
        return {"zone": zone_key(zone), "purpose": purpose, "default": self.default, "profiles": items}

    # ---- use
    def _allow(self, owner: str, p: Profile) -> bool:
        if not p.rate_per_hour:
            return True
        now = self._clock()
        with self._lock:
            q = self._recent[(owner, p.id)]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= p.rate_per_hour:
                return False
            q.append(now)
            return True

    def client(self, p: Profile):
        with self._lock:
            if p.id not in self._clients:
                from .openai_compatible_client import OpenAICompatibleClient
                model, base_url, key_env = self._resolved(p)
                extra = {"reasoning_effort": p.reasoning_effort} if p.reasoning_effort else None
                self._clients[p.id] = OpenAICompatibleClient(model=model, base_url=base_url, timeout=p.timeout, max_tokens=p.max_tokens, api_key_env=key_env,
                                                             max_tokens_floor=p.max_tokens_floor, extra_payload=extra)
            return self._clients[p.id]

    def complete_for(self, profile_id: str | None, zone: str, purpose: str, owner: str = "anonymous", temperature: float = 0.1):
        """(complete(messages) -> str, profile). complete is None for ``auto``: the caller keeps its own default path."""
        p = self.check(profile_id, zone, purpose)
        if p.source == "auto":
            return None, p
        if not self._allow(owner, p):
            raise ProfileError(429, "rate_limited", "這個模型的使用次數已達每小時上限，請稍後再試或改用其他模型")
        logger.info("llm_profile zone=%s purpose=%s profile=%s external=%s user=%s", zone_key(zone), purpose, p.id, p.external, owner)
        client = self.client(p)
        return (lambda messages: normalise_citations(client.chat(messages, temperature=temperature))), p


_registry: Registry | None = None
_registry_key: tuple | None = None


def get_registry() -> Registry:
    """The registry for the current file (reloaded when the file changes)."""
    global _registry, _registry_key
    file = Path(os.environ.get("KM_LLM_PROFILES_FILE") or DEFAULT_FILE)
    key = (str(file), file.stat().st_mtime if file.is_file() else None)
    if _registry is None or key != _registry_key:
        _registry, _registry_key = Registry.load(file), key
    return _registry


def http_error(exc: ProfileError):
    from fastapi import HTTPException
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})
