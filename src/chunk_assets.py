"""
Chunk 原圖/資產管理工具。

將文件攝入後的圖片或頁面快照存成可回溯檔案，
並提供一致的 asset 根目錄與安全路徑處理。
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve_assets_root() -> Path:
    """Resolve the runtime asset root.

    Prefer an explicit environment override, then the mounted host data path,
    then the project-local path, then the image-local /app path fallback.
    """
    candidates: list[Path] = []

    env_root = os.getenv("KB_ASSETS_ROOT")
    if env_root:
        candidates.append(Path(env_root))

    candidates.extend(
        [
            Path("/home/da40_ai_gb10/knowledge-base/data/assets"),
            PROJECT_ROOT / "data" / "assets",
            Path("/app/data/assets"),
        ]
    )

    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_dir():
                return candidate.resolve()
        except Exception:
            continue

    return (PROJECT_ROOT / "data" / "assets").resolve()


ASSETS_ROOT = resolve_assets_root()


def sanitize_name(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "document"
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    return text[:180]


def get_document_asset_dir(doc_name: str) -> Path:
    return ASSETS_ROOT / sanitize_name(doc_name)


def get_document_asset_path(doc_name: str, *parts: str) -> Path:
    base = get_document_asset_dir(doc_name)
    current = base
    for part in parts:
        current = current / sanitize_name(part)
    return current


def relative_asset_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ASSETS_ROOT))
    except Exception:
        return str(path)


def cleanup_document_assets(doc_name: str) -> bool:
    target = get_document_asset_dir(doc_name)
    if not target.exists():
        return False
    shutil.rmtree(target, ignore_errors=True)
    return True
