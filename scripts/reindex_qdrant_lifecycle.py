"""Rebuild Qdrant payload/lifecycle metadata without touching Neo4j.

This is intentionally an explicit, non-default operation.  It deduplicates
Markdown paths by document name, writes vectors with consistent top-level and
nested lifecycle fields, and never deletes the collection or its volume.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.chunker import chunk_document
from src.ingest import detect_extraction_mode
from src.storage_paths import infer_storage_category_from_path
from src.vector_store import VectorStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _metadata_for(path: Path) -> dict:
    metadata_path = path.with_name(f"{path.stem}.source.json")
    if not metadata_path.exists():
        return {}
    try:
        value = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid source metadata: {metadata_path}: {exc}") from exc
    return value if isinstance(value, dict) else {}


def discover_documents(roots: list[Path]) -> list[Path]:
    selected: dict[str, tuple[int, Path]] = {}
    for priority, root in enumerate(roots):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            if path.name.lower() == "index.md" or "wiki" in path.parts:
                continue
            selected.setdefault(path.stem, (priority, path))
    return [item[1] for item in sorted(selected.values(), key=lambda item: item[1].stem.lower())]


def prepare_chunks(path: Path) -> list[dict]:
    source_metadata = _metadata_for(path)
    mode = detect_extraction_mode(path.name)
    category = str(source_metadata.get("storage_category") or infer_storage_category_from_path(path))
    if category == "Report" or str(source_metadata.get("extraction_mode") or "").lower() == "report":
        mode = "report"
        category = "Report"
    chunks = chunk_document(str(path))
    for chunk in chunks:
        metadata = chunk.setdefault("metadata", {})
        metadata.setdefault("storage_category", category)
        metadata.setdefault("extraction_mode", mode)
        for key in (
            "run_id", "environment", "project_code", "dut_model", "band",
            "protocol", "direction", "verdict", "started_at", "schema_version",
            "publish_status", "is_current", "document_version",
        ):
            if source_metadata.get(key) not in (None, ""):
                metadata.setdefault(key, source_metadata[key])
    return chunks


def run(roots: list[Path], apply: bool) -> dict:
    documents = discover_documents(roots)
    summary = {"discovered": len(documents), "processed": 0, "failed": 0, "documents": []}
    if not apply:
        summary["documents"] = [str(path) for path in documents]
        return summary

    store = VectorStore()
    for index, path in enumerate(documents, start=1):
        doc_name = path.stem
        try:
            chunks = prepare_chunks(path)
            # Old points are removed only after the replacement chunks are
            # prepared; collection and unrelated document points remain intact.
            store.delete_by_doc(doc_name)
            store.add_documents(chunks, doc_name)
            summary["processed"] += 1
            logger.info("[%s/%s] reindexed %s", index, len(documents), doc_name)
        except Exception:
            summary["failed"] += 1
            logger.exception("failed to reindex %s", path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="write Qdrant points; default is dry-run")
    args = parser.parse_args()
    summary = run(args.root, apply=args.apply)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
