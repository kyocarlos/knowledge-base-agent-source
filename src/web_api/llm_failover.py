"""Backup LLM tier: when the primary OpenAI-compatible gateway fails, the same request goes to a second OpenAI-compatible endpoint.

The backup is the SAM compute centre's ModaOne ModelSpace (https://modaone-llm-api.dginfra.gov.tw/api/v1, OpenAI-style /chat/completions, key as Bearer or
X-API-KEY). It is configured with KM_LLM_BACKUP_* and is off unless KM_LLM_BACKUP_PROVIDER is set. Order of use for every call site that goes through
``_build_primary_client``: primary gateway -> this backup -> local Ollama (the existing last resort).

 * The backup is only called after the primary failed (HTTP error, 429 quota, timeout, bad reply), so it spends compute points only when needed.
 * After a failure the primary is skipped for KM_LLM_FAILOVER_COOLDOWN_SECONDS (default 30) so a down gateway does not add its timeout to every request;
   if the backup then fails too, the primary is tried once more.
 * A streamed answer that broke after text had been delivered is never retried on the backup (the caller already showed part of it).
 * The model name a caller passes belongs to the primary; the backup always uses its own model.
 * ModaOne's models are reasoning models: reasoning tokens count against max_tokens, so the backup client has a floor for max_tokens and can
   send reasoning_effort (KM_LLM_BACKUP_REASONING_EFFORT).
 * Platform rules to respect (SAM notice, 2026-09): only the registered fixed IPs may call it; use stays inside the approved project scope; models from
   Chinese vendors (DeepSeek, Kimi, ...) must not be used; one compute point is 100,000 input or output tokens.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable

from .openai_compatible_client import OpenAICompatibleClient, StreamInterrupted

logger = logging.getLogger(__name__)
_OFF = {"", "0", "off", "false", "none"}


class _Completions:
    def __init__(self, owner: "FailoverClient") -> None:
        self._owner = owner

    def create(self, *, model: str | None = None, messages: list[dict[str, Any]], temperature: float = 0.3, **kwargs: Any) -> Any:
        return self._owner._run(lambda client, is_backup: client.chat.completions.create(
            **({} if is_backup or model is None else {"model": model}), messages=messages, temperature=temperature, **kwargs))


class _Chat:
    def __init__(self, owner: "FailoverClient") -> None:
        self._owner = owner
        self.completions = _Completions(owner)

    def __call__(self, messages: list[dict[str, Any]], temperature: float = 0.3) -> str:
        return self._owner._run(lambda client, is_backup: client.chat(messages, temperature=temperature))


class FailoverClient:
    """Same surface as OpenAICompatibleClient (chat(...), chat.completions.create(...), generate(...))."""

    def __init__(self, primary, backup, *, primary_label: str = "primary", backup_label: str = "backup", cooldown_seconds: float = 30.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.primary, self.backup = primary, backup
        self.primary_label, self.backup_label = primary_label, backup_label
        self.cooldown, self._clock = float(cooldown_seconds), clock
        self._down_until = 0.0
        self._lock = threading.Lock()
        self.stats = {"primary_failures": 0, "backup_calls": 0, "backup_failures": 0}
        self.chat = _Chat(self)

    def __getattr__(self, name: str):          # model, base_url, max_tokens ... of the primary
        if name in ("primary", "backup"):
            raise AttributeError(name)
        return getattr(self.primary, name)

    def generate(self, prompt: str, temperature: float = 0.3) -> str:
        return self.chat([{"role": "user", "content": prompt}], temperature=temperature)

    def _run(self, call: Callable[[Any, bool], Any]) -> Any:
        primary_first = self._clock() >= self._down_until
        order = [(self.primary, False), (self.backup, True)] if primary_first else [(self.backup, True), (self.primary, False)]
        last: Exception | None = None
        for client, is_backup in order:
            try:
                result = call(client, is_backup)
            except StreamInterrupted:
                raise
            except Exception as exc:  # noqa: BLE001 - any failure of one tier moves on to the next
                last = exc
                with self._lock:
                    self.stats["backup_failures" if is_backup else "primary_failures"] += 1
                    if not is_backup:
                        self._down_until = self._clock() + self.cooldown
                logger.warning("LLM %s failed (%s)%s", self.backup_label if is_backup else self.primary_label, type(exc).__name__,
                               "" if is_backup else "; using the backup LLM " + self.backup_label)
                continue
            if is_backup:
                with self._lock:
                    self.stats["backup_calls"] += 1
                logger.info("LLM answered by the backup %s", self.backup_label)
            return result
        raise RuntimeError("primary and backup LLM both failed") from last


def backup_settings(env=os.environ) -> dict | None:
    """The KM_LLM_BACKUP_* settings, or None when the backup tier is off or incomplete (incomplete is logged, never silent)."""
    provider = (env.get("KM_LLM_BACKUP_PROVIDER") or "").strip().lower()
    if provider in _OFF:
        return None
    model, base_url = (env.get("KM_LLM_BACKUP_MODEL") or "").strip(), (env.get("KM_LLM_BACKUP_BASE_URL") or "").strip()
    if not model or not base_url:
        logger.error("backup LLM %s needs KM_LLM_BACKUP_MODEL and KM_LLM_BACKUP_BASE_URL; running without a backup", provider)
        return None
    return {"provider": provider, "model": model, "base_url": base_url, "api_key_env": env.get("KM_LLM_BACKUP_API_KEY_ENV") or "MODAONE_API_KEY",
            "timeout": float(env.get("KM_LLM_BACKUP_TIMEOUT_SECONDS") or 120), "max_tokens": int(env.get("KM_LLM_BACKUP_MAX_TOKENS") or 8192),
            "max_tokens_floor": int(env.get("KM_LLM_BACKUP_MAX_TOKENS_FLOOR") or 2048),
            "reasoning_effort": (env.get("KM_LLM_BACKUP_REASONING_EFFORT") or "low").strip(),
            "cooldown": float(env.get("KM_LLM_FAILOVER_COOLDOWN_SECONDS") or 30)}


def build_backup_client(env=os.environ):
    settings = backup_settings(env)
    if settings is None:
        return None, ""
    extra = {"reasoning_effort": settings["reasoning_effort"]} if settings["reasoning_effort"] not in _OFF else None
    try:
        client = OpenAICompatibleClient(model=settings["model"], base_url=settings["base_url"], timeout=settings["timeout"], max_tokens=settings["max_tokens"],
                                        api_key_env=settings["api_key_env"], max_tokens_floor=settings["max_tokens_floor"], extra_payload=extra)
    except Exception as exc:  # noqa: BLE001 - e.g. the key variable is missing
        logger.error("backup LLM %s could not be created, running without it: %s", settings["provider"], exc)
        return None, ""
    return client, f"{settings['provider']}:{settings['model']}"


def with_backup(primary, primary_label: str = "primary", env=os.environ):
    """The primary client wrapped with the backup tier when one is configured; the primary itself otherwise."""
    if primary is None:
        return None
    backup, label = build_backup_client(env)
    if backup is None:
        return primary
    cooldown = (backup_settings(env) or {}).get("cooldown", 30.0)
    logger.info("LLM chain: %s -> %s (backup)", primary_label, label)
    return FailoverClient(primary, backup, primary_label=primary_label, backup_label=label, cooldown_seconds=cooldown)
