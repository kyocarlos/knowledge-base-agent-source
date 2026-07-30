"""
舊資料重攝入工具。

用途：
- 先清空 Neo4j / QDrant 內既有文件索引
- 再依目前 `detect_extraction_mode()` 規則重攝入所有可用 Markdown 文件

這個工具的目標是消除舊規則留下的殘留分類結果，
讓資料庫內容與目前的 `SIT-SR-SC / SIT-TR-WL` 規則一致。
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from .ingest import detect_extraction_mode, ingest_document, load_config
from .graphrag.neo4j_schema import clear_all_data, setup_neo4j_schema
from .storage_paths import resolve_storage_category
from .runtime_config import resolve_qdrant_url
from .vector_store import VectorStore


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_ROOTS = (
    PROJECT_ROOT / "data" / "processed",
    PROJECT_ROOT / "data" / "uploads",
    PROJECT_ROOT / "data" / "raw",
)


@dataclass
class ReingestEntry:
    md_path: Path
    source_name: str = ""
    original_path: str = ""
    converted_path: str = ""
    source_hash: str = ""
    storage_category: str = ""
    detected_mode: str = ""
    metadata_path: Path | None = None
    metadata: dict | None = None
    tags: set[str] = field(default_factory=set)

    @property
    def doc_name(self) -> str:
        return self.md_path.stem

    @property
    def mode_source(self) -> str:
        if self.source_name:
            return self.source_name
        if self.original_path:
            return Path(self.original_path).name
        if self.converted_path:
            return Path(self.converted_path).name
        return self.md_path.name


def _load_json(path: Path) -> dict | None:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("讀取中繼資料失敗: %s (%s)", path, exc)
        return None


def _find_md_from_metadata(meta_path: Path, meta: dict) -> Path | None:
    converted_path = str(meta.get("converted_path") or "").strip()
    if converted_path:
        candidate = Path(converted_path)
        if candidate.exists() and candidate.suffix.lower() == ".md":
            return candidate

    original_path = str(meta.get("original_path") or "").strip()
    if original_path:
        original = Path(original_path)
        if original.exists() and original.suffix.lower() == ".md":
            return original

    source_name = str(meta.get("source_name") or "").strip()
    if source_name:
        sibling = meta_path.with_name(f"{Path(source_name).stem}.md")
        if sibling.exists():
            return sibling

    fallback = meta_path.with_name(meta_path.name.replace(".source.json", ".md"))
    if fallback.exists():
        return fallback

    return None


def _iter_candidate_markdown_files(source_roots: Iterable[Path]) -> Iterator[ReingestEntry]:
    entries: dict[str, ReingestEntry] = {}

    def register(md_path: Path, meta: dict | None = None, meta_path: Path | None = None) -> None:
        resolved = str(md_path.resolve())
        entry = entries.get(resolved)
        if entry is None:
            entry = ReingestEntry(md_path=md_path)
            entries[resolved] = entry
        elif meta is None and entry.detected_mode:
            # 這個檔案已經由 metadata 或較高優先序規則決定過類別，
            # 後續純 md 掃描不要再用 filename 規則覆蓋掉它。
            return
        if meta_path and entry.metadata_path is None:
            entry.metadata_path = meta_path
        if meta:
            entry.metadata = meta
            entry.source_name = entry.source_name or str(meta.get("source_name") or "").strip()
            entry.original_path = entry.original_path or str(meta.get("original_path") or "").strip()
            entry.converted_path = entry.converted_path or str(meta.get("converted_path") or "").strip()
            entry.source_hash = entry.source_hash or str(meta.get("source_hash") or "").strip()
            entry.storage_category = entry.storage_category or str(meta.get("storage_category") or "").strip()
            entry.tags.add("metadata")

        metadata_storage = str((meta or {}).get("storage_category") or "").strip()
        metadata_mode = str((meta or {}).get("extraction_mode") or "").strip().lower()
        if metadata_storage == "Report" or metadata_mode == "report":
            entry.detected_mode = "report"
            entry.storage_category = "Report"
        else:
            mode = detect_extraction_mode(Path(entry.mode_source).name)
            entry.detected_mode = mode
            if not entry.storage_category:
                entry.storage_category = resolve_storage_category(mode, entry.md_path.name)

    for root in source_roots:
        if not root.exists():
            continue

        for meta_path in root.rglob("*.source.json"):
            meta = _load_json(meta_path)
            if not meta:
                continue
            md_path = _find_md_from_metadata(meta_path, meta)
            if md_path:
                register(md_path, meta=meta, meta_path=meta_path)

        for md_path in root.rglob("*.md"):
            if md_path.name.lower() == "index.md":
                continue
            if "wiki" in md_path.parts:
                continue
            register(md_path)

    yield from sorted(entries.values(), key=lambda item: str(item.md_path))


def _purge_all_data() -> None:
    config = load_config()
    neo4j = config.get("neo4j", {})
    qdrant = config.get("qdrant", {})
    neo4j_uri = neo4j.get("uri", "bolt://neo4j:7687")
    neo4j_user = neo4j.get("user", "neo4j")
    neo4j_password = neo4j.get("password", "#*cda40da40")
    qdrant_url = resolve_qdrant_url(qdrant.get("url", "http://host.docker.internal:6333"))

    logger.info("清除 Neo4j 全部資料...")
    clear_all_data(neo4j_uri, neo4j_user, neo4j_password)

    logger.info("清除 QDrant collection...")
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=qdrant_url, timeout=30)
        try:
            client.delete_collection(collection_name=VectorStore.COLLECTION_NAME)
            logger.info("已刪除 QDrant collection")
        except Exception as exc:
            if "doesn't exist" not in str(exc) and "Not found: Collection" not in str(exc):
                raise
            logger.info("QDrant collection 不存在，略過刪除")
    except Exception as exc:
        logger.warning("清除 QDrant collection 失敗: %s", exc)


def rebuild_knowledge_base(
    source_roots: Iterable[Path] = DEFAULT_SOURCE_ROOTS,
    purge: bool = True,
    preserve_assets: bool = True,
    enable_vector: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    重新建立知識庫索引。

    Args:
        source_roots: 掃描 Markdown 與 metadata 的根目錄。
        purge: 是否先清空 Neo4j / QDrant。
        preserve_assets: 是否保留原始 asset 檔。
        enable_vector: 是否寫入向量資料庫。
        dry_run: 只列出計畫，不實際執行。
    """
    entries = list(_iter_candidate_markdown_files(source_roots))
    summary = {
        "purge": purge,
        "dry_run": dry_run,
        "discovered": len(entries),
        "ingested": 0,
        "failed": 0,
        "documents": [],
    }

    if dry_run:
        for entry in entries:
            summary["documents"].append({
                "doc_name": entry.doc_name,
                "md_path": str(entry.md_path),
                "detected_mode": entry.detected_mode,
                "storage_category": entry.storage_category,
                "source_name": entry.source_name,
            })
        return summary

    if purge:
        _purge_all_data()

    config = load_config()
    neo4j = config.get("neo4j", {})
    setup_neo4j_schema(
        neo4j.get("uri", "bolt://neo4j:7687"),
        neo4j.get("user", "neo4j"),
        neo4j.get("password", "#*cda40da40"),
    )

    for index, entry in enumerate(entries, start=1):
        if not entry.md_path.exists():
            logger.warning("略過不存在的 Markdown: %s", entry.md_path)
            summary["failed"] += 1
            continue

        logger.info(
            "[%s/%s] 重攝入 %s (mode=%s, storage=%s)",
            index,
            len(entries),
            entry.md_path.name,
            entry.detected_mode,
            entry.storage_category,
        )
        try:
            ok = ingest_document(
                str(entry.md_path),
                enable_vector=enable_vector,
                extraction_mode=entry.detected_mode,
                preserve_assets=preserve_assets,
            )
            if ok:
                summary["ingested"] += 1
            else:
                summary["failed"] += 1
        except Exception as exc:
            logger.exception("重攝入失敗: %s", entry.md_path)
            summary["failed"] += 1
            summary["documents"].append({
                "doc_name": entry.doc_name,
                "md_path": str(entry.md_path),
                "detected_mode": entry.detected_mode,
                "storage_category": entry.storage_category,
                "error": str(exc),
            })
            continue

        summary["documents"].append({
            "doc_name": entry.doc_name,
            "md_path": str(entry.md_path),
            "detected_mode": entry.detected_mode,
            "storage_category": entry.storage_category,
            "source_name": entry.source_name,
        })

    try:
        from .index_generator import generate_index_md
        generate_index_md()
    except Exception as exc:
        logger.warning("更新 index.md 失敗: %s", exc)

    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="重攝入舊資料，清除舊規則留下的分類結果")
    parser.add_argument(
        "--no-purge",
        action="store_true",
        help="不要先清空 Neo4j / QDrant，僅重新攝入掃描到的文件",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出將重攝入的文件，不實際執行",
    )
    parser.add_argument(
        "--no-vector",
        action="store_true",
        help="不寫入 QDrant，只重建 Neo4j",
    )
    parser.add_argument(
        "--no-assets",
        action="store_true",
        help="重攝入時刪除並重建原始資產",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    summary = rebuild_knowledge_base(
        purge=not args.no_purge,
        preserve_assets=not args.no_assets,
        enable_vector=not args.no_vector,
        dry_run=args.dry_run,
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
