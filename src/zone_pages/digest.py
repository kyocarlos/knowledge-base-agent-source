"""The weekly digest of a zone: what was delivered this week, in a few lines.

The items come straight from the week's documents (their own summaries). The highlights are one LLM call over those items, made at most once per
zone, ISO week and set of documents; until it finishes (or when no model is available) the highlights are the document titles, so the page never waits.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from . import views

logger = logging.getLogger("km.zones.digest")
NOTE = "週報由 KM 依本週新增文件的摘要整理，重點由語言模型產生。"
NOTE_PLAIN = "週報依本週新增文件的標題與摘要整理。"
MAX_ITEMS_IN_PROMPT = 15
PROMPT = ("你是企業知識庫的週報編輯。下面是「{zone}」本週新增的文件（標題與摘要）。請寫 2 到 4 個重點，每個重點一行、不超過 60 字，"
          "只根據下列內容，不得加入沒有出現的資訊。只輸出重點，每行開頭用「- 」。\n\n{items}")


def _signature(zone: str, week: str, items: list[dict]) -> str:
    raw = json.dumps([zone, week, [i["revision_id"] for i in items]], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _lines(reply: str) -> list[str]:
    out = []
    for line in (reply or "").splitlines():
        text = line.strip().lstrip("-•*· ").strip()
        if 4 <= len(text) <= 200:
            out.append(text)
    return out[:4]


class DigestService:
    def __init__(self, complete: Callable[[list[dict]], str] | None, cache: Any = None):
        self.complete = complete
        self.cache = cache if cache is not None else {}     # a dict, or anything with get/set(ex=): Redis in the web process
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def _get(self, key: str) -> list[str] | None:
        try:
            raw = self.cache.get(key)
        except Exception:  # noqa: BLE001
            return None
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw) if not isinstance(raw, list) else raw

    def _set(self, key: str, lines: list[str]) -> None:
        try:
            if hasattr(self.cache, "set") and not isinstance(self.cache, dict):
                self.cache.set(key, json.dumps(lines, ensure_ascii=False), ex=14 * 86400)
            else:
                self.cache[key] = lines
        except Exception:  # noqa: BLE001
            logger.warning("digest not cached", exc_info=True)

    def _generate(self, key: str, zone: str, items: list[dict]) -> None:
        try:
            listing = "\n".join(f"- {i['title']}：{(i['summary'] or '（沒有摘要）')[:200]}" for i in items[:MAX_ITEMS_IN_PROMPT])
            lines = _lines(self.complete([{"role": "user", "content": PROMPT.format(zone=zone, items=listing)}]))
            if lines:
                self._set(key, lines)
        except Exception:  # noqa: BLE001 - the plain highlights stay
            logger.warning("digest highlights not generated", exc_info=True)
        finally:
            with self._lock:
                self._running.discard(key)

    def build(self, zone_label: str, docs: list[dict], now: datetime | None = None, wait: bool = False) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        items = views.week_items(docs, now)
        plain = [i["title"] for i in items[:4]]
        if not items:
            return views.digest_shell(docs, [], NOTE_PLAIN, now)
        key = "zonepages:digest:" + _signature(zone_label, views._iso_week(now), items)
        lines = self._get(key)
        if lines is None and self.complete is not None:
            with self._lock:
                start = key not in self._running
                self._running.add(key)
            if start:
                worker = threading.Thread(target=self._generate, args=(key, zone_label, items), daemon=True)
                worker.start()
                if wait:
                    worker.join()
                    lines = self._get(key)
        return views.digest_shell(docs, lines or plain, NOTE if lines else NOTE_PLAIN, now)
