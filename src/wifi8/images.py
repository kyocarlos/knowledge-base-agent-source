"""Turn the figures of a Wi-Fi8 package into searchable text with a vision-capable chat model.

Results are cached per image content hash under ``<root>/image-text`` and the
image files under ``<root>/images``, so a figure is described once per zone and
a later package only pays for new figures. The cache key also carries the model
and prompt version: changing either describes the figures again.
"""
from __future__ import annotations

import base64
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .package import IMAGE_TYPES

PROMPT_VERSION = 1
EMPTY_MARKER = "無內容"
PROMPT = (
    "這是一份 Wi-Fi 技術文件中的圖片。請輸出兩段：\n"
    "【圖中文字】逐字抄錄圖中可辨識的文字（保留原文語言、數值、單位與欄位名稱；表格用「欄 | 欄」一列一行）。\n"
    "【圖片說明】用繁體中文 2～5 句說明這張圖在表達什麼（圖的類型、主要元素、流程或比較關係、重要數值）；技術名詞保留英文。\n"
    f"沒有內容可描述（純裝飾、標誌、照片背景）時只輸出：{EMPTY_MARKER}。不要猜測圖中沒有的資訊。"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class DescriberSettings:
    # One import step describes one batch; batch/concurrency x (timeout x (retries+1)) must stay below the
    # Celery soft time limit (600 s), e.g. 2 rounds x 2 x 120 s.
    provider: str = "off"  # "openai" (OpenAI-compatible gateway such as Sub2API) or "off"
    model: str = ""
    base_url: str = ""
    api_key_env: str = ""
    reasoning_effort: str = "low"
    timeout_seconds: float = 120.0
    max_tokens: int = 4000
    concurrency: int = 4
    batch_size: int = 8
    retries: int = 1
    max_failed_ratio: float = 0.05

    @classmethod
    def from_environment(cls) -> "DescriberSettings":
        env = os.getenv
        return cls(
            provider=env("KM_WIFI8_IMAGE_DESCRIBER", "off").strip().lower(),
            model=env("KM_WIFI8_IMAGE_MODEL") or env("KM_LLM_PRIMARY_MODEL", ""),
            base_url=env("KM_WIFI8_IMAGE_BASE_URL") or env("KM_LLM_PRIMARY_BASE_URL", ""),
            api_key_env=env("KM_WIFI8_IMAGE_API_KEY_ENV") or env("KM_LLM_PRIMARY_API_KEY_ENV", ""),
            reasoning_effort=env("KM_WIFI8_IMAGE_REASONING_EFFORT", "low"),
            timeout_seconds=float(env("KM_WIFI8_IMAGE_TIMEOUT_SECONDS", "120")),
            max_tokens=int(env("KM_WIFI8_IMAGE_MAX_TOKENS", "4000")),
            concurrency=int(env("KM_WIFI8_IMAGE_CONCURRENCY", "4")),
            batch_size=int(env("KM_WIFI8_IMAGE_BATCH_SIZE", "8")),
            retries=int(env("KM_WIFI8_IMAGE_RETRIES", "1")),
            max_failed_ratio=float(env("KM_WIFI8_IMAGE_MAX_FAILED_RATIO", "0.05")),
        )

    @property
    def enabled(self) -> bool:
        return self.provider != "off"

    @property
    def signature(self) -> str:
        """What a cached description must have been made with to be reused."""
        return f"{self.provider}:{self.model}:{self.reasoning_effort}:p{PROMPT_VERSION}"


def openai_describer(settings: DescriberSettings) -> Callable[[bytes, str], str]:
    from ..web_api.openai_compatible_client import OpenAICompatibleClient
    if settings.provider != "openai" or not settings.model or not settings.base_url or not settings.api_key_env:
        raise RuntimeError("圖片轉文字設定不完整：需要 KM_WIFI8_IMAGE_DESCRIBER=openai 與模型、端點、金鑰變數名稱")
    client = OpenAICompatibleClient(settings.model, settings.base_url, timeout=settings.timeout_seconds,
                                    max_tokens=settings.max_tokens, api_key_env=settings.api_key_env)
    extra = {"reasoning_effort": settings.reasoning_effort} if settings.reasoning_effort else {}

    def describe(data: bytes, extension: str) -> str:
        url = f"data:{IMAGE_TYPES[extension]};base64,{base64.b64encode(data).decode('ascii')}"
        response = client.chat.completions.create(messages=[{"role": "user", "content": [
            {"type": "text", "text": PROMPT}, {"type": "image_url", "image_url": {"url": url}}]}], temperature=0, **extra)
        return response.choices[0].message.content or ""
    return describe


def clean(text: str) -> str:
    """Model output as stored: trimmed, Markdown emphasis removed, "nothing to describe" as empty."""
    lines = [line.rstrip().replace("**", "") for line in str(text or "").strip().splitlines()]
    value = "\n".join(lines).strip()
    return "" if not value or value.strip("。. ") == EMPTY_MARKER else value


class ImageTextCache:
    def __init__(self, root: Path):
        self.root = root

    def image_path(self, image_id: str, extension: str) -> Path:
        return self.root / "images" / image_id[:2] / f"{image_id}.{extension}"

    def find_image(self, image_id: str) -> Path | None:
        for extension in IMAGE_TYPES:
            path = self.image_path(image_id, extension)
            if path.is_file():
                return path
        return None

    def _text_path(self, image_id: str) -> Path:
        return self.root / "image-text" / image_id[:2] / f"{image_id}.json"

    def get(self, image_id: str) -> dict[str, Any] | None:
        try:
            return json.loads(self._text_path(image_id).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def put(self, image_id: str, record: dict[str, Any]) -> None:
        path = self._text_path(image_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps({"image_id": image_id, **record, "updated_at": _now()}, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)

    def store_image(self, image_id: str, extension: str, data: bytes) -> None:
        path = self.image_path(image_id, extension)
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_bytes(data)
            temp.replace(path)

    def usable(self, image_id: str, signature: str) -> dict[str, Any] | None:
        """A finished description made with ``signature``; failed attempts are tried again."""
        record = self.get(image_id)
        return record if record and record.get("signature") == signature and record.get("status") in ("described", "empty") else None


def describe_batch(images: list[dict[str, Any]], read: Callable[[str, str], bytes], cache: ImageTextCache,
                   settings: DescriberSettings, describe: Callable[[bytes, str], str], *,
                   sleep: Callable[[float], None] | None = None) -> dict[str, int]:
    """Describe ``images`` (distinct image_id/extension rows) concurrently; every result, failed or not, is cached."""
    sleep = sleep or time.sleep
    def one(image: dict[str, Any]) -> str:
        image_id, extension = image["image_id"], image["extension"]
        data = read(image_id, extension)
        cache.store_image(image_id, extension, data)
        error = ""
        for attempt in range(settings.retries + 1):
            try:
                text = clean(describe(data, extension))
                cache.put(image_id, {"signature": settings.signature, "status": "described" if text else "empty", "text": text})
                return "described" if text else "empty"
            except Exception as exc:  # noqa: BLE001 - recorded per image; the batch goes on
                error = type(exc).__name__
                if attempt < settings.retries:
                    sleep(5 * (attempt + 1))
        cache.put(image_id, {"signature": settings.signature, "status": "failed", "text": "", "error": error})
        return "failed"

    counts = {"described": 0, "empty": 0, "failed": 0}
    with ThreadPoolExecutor(max_workers=max(1, settings.concurrency)) as pool:
        for status in pool.map(one, images):
            counts[status] += 1
    return counts
