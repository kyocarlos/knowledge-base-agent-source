"""
知識庫檔案存放路徑工具。

將攝入模式與磁碟目錄對齊，讓原始檔與轉出的 Markdown
都能依照相同的類型分到固定資料夾。
"""

from __future__ import annotations

from pathlib import Path


STORAGE_CATEGORY_MAP = {
    "4g5g": "4G_5G",
    "wifi": "WiFi",
    "lab": "Lab",
    "project": "Project",
    "automation": "Automation",
    "report": "Report",
    "simple": "Simple",
}

STORAGE_CATEGORY_ALIASES = {
    "4g5g": "4G_5G",
    "4g_5g": "4G_5G",
    "4g/5g": "4G_5G",
    "4g5g電信設備": "4G_5G",
    "4g_5g電信設備": "4G_5G",
    "wifi": "WiFi",
    "wifi設備": "WiFi",
    "lab": "Lab",
    "實驗室管理": "Lab",
    "project": "Project",
    "專案管理": "Project",
    "automation": "Automation",
    "自動化管理": "Automation",
    "report": "Report",
    "sit-tr-sc": "Report",
    "report測試報告": "Report",
    "simple": "Simple",
    "簡化文件": "Simple",
}


def normalize_storage_category(value: str | None, fallback: str = "4g5g") -> str:
    """
    將 mode / 類別名稱 / 資料夾名稱統一轉成實際資料夾名稱。
    """
    key = (value or fallback or "4g5g").strip().lower()
    key = key.replace("-", "_")
    key = key.replace(" ", "")
    return STORAGE_CATEGORY_ALIASES.get(key, STORAGE_CATEGORY_MAP.get(key, "4G_5G"))


def infer_storage_category_from_filename(filename: str, fallback: str = "4g5g") -> str:
    """
    根據檔名推測存放類型。
    """
    from .ingest import detect_extraction_mode

    stem = Path(filename).stem if filename else ""
    mode = detect_extraction_mode(stem) if stem else fallback
    return normalize_storage_category(mode, fallback=fallback)


def infer_storage_category_from_path(path: str | Path, fallback: str = "4g5g") -> str:
    """
    根據路徑或檔名推測存放類型。

    優先看路徑各層資料夾名稱，若已存在明確類別則直接採用；
    否則回退到檔名判斷。
    """
    candidate = Path(path) if path else Path()
    parts = [part for part in candidate.parts if part]
    normalized_parts = [part.lower().replace("-", "_").replace(" ", "") for part in parts]
    for part in normalized_parts:
        if part in STORAGE_CATEGORY_ALIASES or part in STORAGE_CATEGORY_MAP:
            return normalize_storage_category(part, fallback=fallback)
    if candidate.name:
        return infer_storage_category_from_filename(candidate.name, fallback=fallback)
    return normalize_storage_category(None, fallback=fallback)


def resolve_storage_category(mode: str | None, filename: str | None = None) -> str:
    """
    依 mode 決定儲存資料夾；若 mode 不明則回退到檔名推測。
    """
    if filename:
        inferred = infer_storage_category_from_filename(filename)
        if inferred != "4G_5G":
            return inferred
    if mode:
        return normalize_storage_category(mode)
    if filename:
        return infer_storage_category_from_filename(filename)
    return normalize_storage_category(None)


def build_category_file_path(base_dir: Path, category: str, filename: str) -> Path:
    """
    建立 category 目錄下的檔案路徑。
    """
    return Path(base_dir) / normalize_storage_category(category) / filename
