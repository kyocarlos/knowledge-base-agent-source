"""
Chunk 編輯與版本備份工具。

原則：
- 修改來源 markdown 檔，而不是只改 Qdrant payload
- 每次修改前保留一份完整備份，方便回復上一版
- 回復時以重新 ingest 的方式同步 Neo4j / Qdrant / Chunk Viewer
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHUNK_EDIT_ROOT = PROJECT_ROOT / "data" / "chunk_edits"


def _slugify_doc_name(doc_name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in (doc_name or "").strip())
    return safe or "document"


def _doc_version_dir(doc_name: str) -> Path:
    return CHUNK_EDIT_ROOT / _slugify_doc_name(doc_name)


def _version_manifest_path(doc_name: str, version_id: str) -> Path:
    return _doc_version_dir(doc_name) / f"{version_id}.json"


def _now_token() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_edit_root() -> Path:
    CHUNK_EDIT_ROOT.mkdir(parents=True, exist_ok=True)
    return CHUNK_EDIT_ROOT


def _resolve_original_excel_source(source_path: str) -> Path | None:
    """
    嘗試從來源 markdown 路徑反推出原始 xlsx。

    優先順序：
    1. converted/<name>.md -> original/<name>.xlsx
    2. data/uploads/**/original/<name>.xlsx
    3. data/raw/<name>.xlsx
    """
    source_file = Path(source_path)
    stem = source_file.stem

    if source_file.suffix.lower() == ".xlsx" and source_file.exists():
        return source_file

    if source_file.parent.name == "converted":
        candidate = source_file.parent.parent / "original" / f"{stem}.xlsx"
        if candidate.exists():
            return candidate

    uploads_root = PROJECT_ROOT / "data" / "uploads"
    if uploads_root.exists():
        for candidate in uploads_root.rglob(f"{stem}.xlsx"):
            if candidate.is_file() and candidate.parent.name == "original":
                return candidate

    raw_candidate = PROJECT_ROOT / "data" / "raw" / f"{stem}.xlsx"
    if raw_candidate.exists():
        return raw_candidate

    return None


def rebuild_source_excel_assets(source_path: str) -> List[str]:
    """
    重新建立來源 Excel 的原圖資產。

    會先嘗試從 converted md 推回原始 xlsx，再利用 converter 重新輸出 asset。
    """
    original_xlsx = _resolve_original_excel_source(source_path)
    if not original_xlsx:
        return []

    try:
        from .converter import rebuild_excel_assets

        return rebuild_excel_assets(str(original_xlsx))
    except Exception:
        return []


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def apply_chunk_edit_to_source(
    source_text: str,
    old_content: str,
    new_content: str,
    section_title: str | None = None,
) -> tuple[str, str]:
    """將 chunk 編輯回寫到來源 Markdown。

    回傳:
    - 更新後的 source text
    - 套用策略: exact / section / unchanged
    """
    old_content = (old_content or "").rstrip("\n")
    new_content = (new_content or "").rstrip("\n")

    if not old_content:
        return source_text, "unchanged"

    if old_content in source_text:
        return source_text.replace(old_content, new_content, 1), "exact"

    normalized_old = _normalize_whitespace(old_content)
    normalized_source = _normalize_whitespace(source_text)
    if normalized_old and normalized_old in normalized_source:
        # 仍以 section fallback 為主，避免做錯位替換
        pass

    section_title = (section_title or "").strip()
    if section_title and section_title in source_text:
        section_start = source_text.find(section_title)
        section_body_start = section_start + len(section_title)

        next_header_match = re.search(r"\n#{1,6}\s+", source_text[section_body_start:])
        section_end = section_body_start + next_header_match.start() if next_header_match else len(source_text)

        before = source_text[:section_start]
        after = source_text[section_end:]

        replacement = f"{section_title}\n{new_content}".rstrip() + "\n"
        updated_text = before + replacement + after.lstrip("\n")
        return updated_text, "section"

    return source_text, "unchanged"


def create_chunk_version_backup(
    *,
    doc_name: str,
    source_path: str,
    chunk_id: str,
    chunk_index: int,
    old_content: str,
    new_content: str,
    reason: str = "chunk_edit",
) -> Dict[str, Any]:
    """為修改前的來源檔建立完整備份。"""
    ensure_edit_root()
    source_file = Path(source_path)
    if not source_file.exists():
        raise FileNotFoundError(f"來源檔不存在: {source_path}")

    version_id = f"{_now_token()}_{uuid.uuid4().hex[:8]}"
    version_dir = _doc_version_dir(doc_name)
    version_dir.mkdir(parents=True, exist_ok=True)

    backup_ext = source_file.suffix or ".md"
    backup_path = version_dir / f"{version_id}{backup_ext}"
    shutil.copy2(source_file, backup_path)

    manifest = {
        "version_id": version_id,
        "created_at": datetime.now().isoformat(),
        "doc_name": doc_name,
        "source_path": str(source_file.resolve()),
        "backup_path": str(backup_path.resolve()),
        "chunk_id": chunk_id,
        "chunk_index": chunk_index,
        "reason": reason,
        "old_content_preview": (old_content or "")[:500],
        "new_content_preview": (new_content or "")[:500],
    }

    manifest_path = _version_manifest_path(doc_name, version_id)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def list_chunk_versions(doc_name: str) -> List[Dict[str, Any]]:
    """列出某份文件的歷史版本（新到舊）。"""
    version_dir = _doc_version_dir(doc_name)
    if not version_dir.is_dir():
        return []

    manifests: List[Dict[str, Any]] = []
    for manifest_path in version_dir.glob("*.json"):
        try:
            manifests.append(json.loads(manifest_path.read_text(encoding="utf-8")))
        except Exception:
            continue

    manifests.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return manifests


def get_chunk_version(doc_name: str, version_id: str) -> Dict[str, Any]:
    """取得指定版本的資訊。"""
    manifest_path = _version_manifest_path(doc_name, version_id)
    if not manifest_path.exists():
        raise FileNotFoundError(f"版本不存在: {version_id}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def restore_chunk_version(doc_name: str, version_id: str) -> Dict[str, Any]:
    """把文件回復到某個歷史版本。"""
    manifest = get_chunk_version(doc_name, version_id)
    source_path = Path(manifest["source_path"])
    backup_path = Path(manifest["backup_path"])

    if not backup_path.exists():
        raise FileNotFoundError(f"備份檔不存在: {backup_path}")

    source_path.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
    return manifest
