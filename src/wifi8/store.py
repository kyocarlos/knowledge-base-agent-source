"""SQLite store for one imported Wi-Fi8 package: metadata, segments, chunks and full-text.

The trigram FTS5 index matches English terms and CJK substrings alike, which the
CJK-oriented embedding model alone does not (see docs/wifi8-km-package-v1.md).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE documents (
    revision_id TEXT PRIMARY KEY, title TEXT NOT NULL, analysis_eligible INTEGER NOT NULL,
    wfa_document_id TEXT, document_role TEXT, publisher TEXT, primary_category_id TEXT,
    version_series_id TEXT, document_family_id TEXT, document_date TEXT, data TEXT NOT NULL);
CREATE TABLE segments (
    segment_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
    kind TEXT NOT NULL, location TEXT NOT NULL, text TEXT NOT NULL);
CREATE INDEX segments_revision ON segments(revision_id, ordinal);
CREATE TABLE chunks (
    point_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
    segment_ids TEXT NOT NULL, location TEXT NOT NULL, location_label TEXT NOT NULL,
    content_hash TEXT NOT NULL, text TEXT NOT NULL, embed_text TEXT NOT NULL,
    vector_state TEXT NOT NULL DEFAULT 'pending');
CREATE INDEX chunks_state ON chunks(vector_state);
CREATE VIRTUAL TABLE chunks_fts USING fts5(title, text, point_id UNINDEXED, tokenize='trigram');
"""

DOCUMENT_COLUMNS = ("wfa_document_id", "document_role", "publisher", "primary_category_id",
                    "version_series_id", "document_family_id", "document_date")


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def build_store(path: Path, manifest: dict[str, Any], documents: Iterable[dict[str, Any]],
                segments: Iterable[dict[str, Any]], chunks: list[dict[str, Any]]) -> None:
    """Write a complete store to ``path`` atomically (temp file, then rename)."""
    temp = path.with_suffix(".building")
    temp.unlink(missing_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    titles = {}
    with closing(connect(temp)) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO meta VALUES ('manifest', ?)", (json.dumps(manifest, ensure_ascii=False),))
        for doc in documents:
            titles[doc["revision_id"]] = doc["title"]
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                doc["revision_id"], doc["title"], int(bool(doc["analysis_eligible"])),
                *[None if doc.get(c) is None else str(doc.get(c)) for c in DOCUMENT_COLUMNS],
                json.dumps(doc, ensure_ascii=False)))
        db.executemany("INSERT INTO segments VALUES (?,?,?,?,?,?)", (
            (s["segment_id"], s["revision_id"], int(s["ordinal"]), s["kind"],
             json.dumps(s.get("location") or {}, ensure_ascii=False), s["text"]) for s in segments))
        for c in chunks:
            db.execute("INSERT INTO chunks (point_id, revision_id, ordinal, segment_ids, location, location_label,"
                       " content_hash, text, embed_text) VALUES (?,?,?,?,?,?,?,?,?)", (
                           c["point_id"], c["revision_id"], c["ordinal"], json.dumps(c["segment_ids"]),
                           json.dumps(c["location"], ensure_ascii=False), c["location_label"],
                           c["content_hash"], c["text"], c["embed_text"]))
            db.execute("INSERT INTO chunks_fts (title, text, point_id) VALUES (?,?,?)",
                       (titles.get(c["revision_id"], ""), c["text"], c["point_id"]))
        db.commit()
    temp.replace(path)


def manifest(path: Path) -> dict[str, Any]:
    with closing(connect(path, readonly=True)) as db:
        return json.loads(db.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])


def counts(path: Path) -> dict[str, int]:
    with closing(connect(path, readonly=True)) as db:
        states = dict(db.execute("SELECT vector_state, count(*) FROM chunks GROUP BY vector_state").fetchall())
        return {
            "documents": db.execute("SELECT count(*) FROM documents").fetchone()[0],
            "documents_analysis_eligible": db.execute("SELECT count(*) FROM documents WHERE analysis_eligible=1").fetchone()[0],
            "segments": db.execute("SELECT count(*) FROM segments").fetchone()[0],
            "chunks": sum(states.values()),
            "chunks_pending": states.get("pending", 0),
            "chunks_ready": states.get("ready", 0),
        }


def pending_chunks(path: Path, limit: int) -> list[dict[str, Any]]:
    with closing(connect(path, readonly=True)) as db:
        rows = db.execute("SELECT c.*, d.data AS document FROM chunks c JOIN documents d USING (revision_id)"
                          " WHERE c.vector_state='pending' ORDER BY c.revision_id, c.ordinal LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def mark_ready(path: Path, point_ids: list[str]) -> None:
    with closing(connect(path)) as db:
        db.executemany("UPDATE chunks SET vector_state='ready' WHERE point_id=?", ((p,) for p in point_ids))
        db.commit()


def all_point_ids(path: Path) -> set[str]:
    with closing(connect(path, readonly=True)) as db:
        return {row[0] for row in db.execute("SELECT point_id FROM chunks")}


def documents(path: Path) -> list[dict[str, Any]]:
    with closing(connect(path, readonly=True)) as db:
        return [json.loads(row[0]) for row in db.execute("SELECT data FROM documents ORDER BY revision_id")]
