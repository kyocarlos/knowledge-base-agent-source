"""Stage, embed and publish a Wi-Fi8 package into the KM WiFi zone.

Each ``step`` call does a bounded amount of work so a Celery task can re-enqueue
itself: stage -> embed (repeated) -> publish. The current package keeps serving
until a new one has fully finished; only then is ``current.json`` switched.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import store
from .chunks import build_chunks
from .package import PackageError, read_package

SOURCE_SYSTEM = "WIFI8"
STORAGE_CATEGORY = "WiFi"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Wifi8Settings:
    root: Path
    collection: str = "wifi8_kb"
    chunk_max_chars: int = 1200
    embed_batch_size: int = 256
    max_package_bytes: int = 200 * 1024 * 1024
    max_uncompressed_bytes: int = 1024 * 1024 * 1024
    keep_stores: int = 2

    @classmethod
    def from_environment(cls) -> "Wifi8Settings":
        mb = 1024 * 1024
        return cls(
            root=Path(os.getenv("KM_WIFI8_ROOT", "/app/data/wifi8")),
            collection=os.getenv("KM_WIFI8_COLLECTION", "wifi8_kb"),
            chunk_max_chars=int(os.getenv("KM_WIFI8_CHUNK_MAX_CHARS", "1200")),
            embed_batch_size=int(os.getenv("KM_WIFI8_EMBED_BATCH_SIZE", "256")),
            max_package_bytes=int(os.getenv("KM_WIFI8_MAX_PACKAGE_MB", "200")) * mb,
            max_uncompressed_bytes=int(os.getenv("KM_WIFI8_MAX_UNCOMPRESSED_MB", "1024")) * mb,
            keep_stores=int(os.getenv("KM_WIFI8_KEEP_STORES", "2")),
        )


class ImportConflict(RuntimeError):
    """Another import is still running."""


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


class Wifi8Importer:
    def __init__(self, settings: Wifi8Settings, *, qdrant=None, encoder: Callable[[list[str]], list[list[float]]] | None = None,
                 embedding_model: str = "", neo4j_driver=None):
        self.settings = settings
        self.qdrant = qdrant
        self.encoder = encoder
        self.embedding_model = embedding_model
        self.neo4j = neo4j_driver

    # ---- paths and state -------------------------------------------------
    @property
    def root(self) -> Path:
        return self.settings.root

    def _job_path(self, job_id: str) -> Path:
        return self.root / "jobs" / f"{job_id}.json"

    def _store_path(self, package_id: str) -> Path:
        return self.root / "stores" / f"{package_id}.sqlite"

    def current(self) -> dict[str, Any] | None:
        return _read_json(self.root / "current.json")

    def current_store(self) -> Path | None:
        current = self.current()
        if not current:
            return None
        path = self._store_path(current["package_id"])
        return path if path.is_file() else None

    def job(self, job_id: str) -> dict[str, Any] | None:
        return _read_json(self._job_path(job_id))

    def _save(self, job: dict[str, Any]) -> dict[str, Any]:
        job["updated_at"] = _now()
        _write_json(self._job_path(job["job_id"]), job)
        return job

    def active_job(self) -> dict[str, Any] | None:
        lock = _read_json(self.root / "import.lock")
        if not lock:
            return None
        job = self.job(lock["job_id"])
        return job if job and job["status"] in {"queued", "staging", "embedding", "publishing"} else None

    # ---- submission ------------------------------------------------------
    def submit(self, upload_path: Path, *, submitted_by: str) -> dict[str, Any]:
        """Verify an uploaded file and register an import job (no heavy work here)."""
        if self.active_job():
            raise ImportConflict("another Wi-Fi8 import is still running")
        if upload_path.stat().st_size > self.settings.max_package_bytes:
            raise PackageError("package exceeds the configured upload limit")
        package = read_package(upload_path, max_uncompressed_bytes=self.settings.max_uncompressed_bytes)
        current = self.current() or {}
        job_id = f"wifi8-import-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
        incoming = self.root / "incoming" / f"{package.package_id}.zip"
        incoming.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upload_path, incoming)
        same = current.get("package_id") == package.package_id
        job = {
            "job_id": job_id, "package_id": package.package_id, "status": "completed" if same else "queued",
            "phase": "done" if same else "stage", "submitted_by": submitted_by, "created_at": _now(),
            "manifest_counts": package.manifest.get("counts", {}), "progress": {},
            "message": "同一份匯出包已是目前版本，不重複匯入" if same else "",
        }
        self._save(job)
        if not same:
            _write_json(self.root / "import.lock", {"job_id": job_id, "created_at": job["created_at"]})
        return job

    # ---- steps -----------------------------------------------------------
    def step(self, job_id: str) -> dict[str, Any]:
        job = self.job(job_id)
        if not job or job["status"] in {"completed", "failed"}:
            return job or {}
        try:
            if job["phase"] == "stage":
                return self._stage(job)
            if job["phase"] == "embed":
                return self._embed(job)
            if job["phase"] == "publish":
                return self._publish(job)
            raise RuntimeError(f"unknown phase {job['phase']}")
        except Exception as exc:  # The old package keeps serving; the job records why.
            job.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:500])
            (self.root / "import.lock").unlink(missing_ok=True)
            return self._save(job)

    def _stage(self, job: dict[str, Any]) -> dict[str, Any]:
        job["status"] = "staging"
        self._save(job)
        package = read_package(self.root / "incoming" / f"{job['package_id']}.zip",
                               max_uncompressed_bytes=self.settings.max_uncompressed_bytes)
        chunks = build_chunks(package.documents, package.segments, max_chars=self.settings.chunk_max_chars)
        path = self._store_path(package.package_id)
        store.build_store(path, package.manifest, package.documents, package.segments, chunks)
        self._ensure_collection()
        job.update(phase="embed", status="embedding", progress=store.counts(path))
        return self._save(job)

    def _ensure_collection(self) -> None:
        from qdrant_client.models import Distance, PayloadSchemaType, VectorParams
        names = {c.name for c in self.qdrant.get_collections().collections}
        dim = len(self.encoder(["dimension probe"])[0])
        if self.settings.collection not in names:
            self.qdrant.create_collection(self.settings.collection, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
        else:
            existing = self.qdrant.get_collection(self.settings.collection).config.params.vectors.size
            if existing != dim:
                raise RuntimeError(f"collection {self.settings.collection} has {existing}-dim vectors, "
                                   f"embedding model {self.embedding_model} produces {dim}")
        current = self.current() or {}
        if current.get("embedding_model") and current["embedding_model"] != self.embedding_model:
            # Reused vectors would silently mix two models; a model change needs a fresh collection.
            raise RuntimeError(f"current package was embedded with {current['embedding_model']}, not {self.embedding_model}")
        for field, schema in (("packages", PayloadSchemaType.KEYWORD), ("revision_id", PayloadSchemaType.KEYWORD),
                              ("analysis_eligible", PayloadSchemaType.BOOL), ("document_role", PayloadSchemaType.KEYWORD),
                              ("publisher", PayloadSchemaType.KEYWORD), ("wfa_document_id", PayloadSchemaType.KEYWORD)):
            self.qdrant.create_payload_index(self.settings.collection, field_name=field, field_schema=schema)

    def _payload(self, chunk: dict[str, Any], packages: list[str]) -> dict[str, Any]:
        doc = json.loads(chunk["document"])
        eligible = bool(doc.get("analysis_eligible"))
        return {
            "doc_name": doc.get("title"), "source_name": doc.get("display_filename") or doc.get("title"),
            "content": chunk["text"], "storage_category": STORAGE_CATEGORY, "source_system": SOURCE_SYSTEM,
            "revision_id": chunk["revision_id"], "chunk_index": chunk["ordinal"],
            "segment_ids": json.loads(chunk["segment_ids"]), "location": json.loads(chunk["location"]),
            "location_label": chunk["location_label"], "content_hash": chunk["content_hash"],
            "wfa_document_id": doc.get("wfa_document_id"), "wfa_revision": doc.get("wfa_revision"),
            "document_role": doc.get("document_role"), "publisher": doc.get("publisher"),
            "primary_category_id": doc.get("primary_category_id"), "topics": doc.get("topics") or [],
            "document_date": doc.get("document_date"), "version_series_id": doc.get("version_series_id"),
            "lifecycle_status": doc.get("lifecycle_status"), "analysis_eligible": eligible,
            "publish_status": "published", "is_current": eligible, "packages": packages,
            "embedding_model": self.embedding_model,
        }

    @staticmethod
    def _progress(job: dict[str, Any], path: Path, reused: int = 0) -> dict[str, Any]:
        progress = store.counts(path)
        progress["vectors_reused"] = job.get("progress", {}).get("vectors_reused", 0) + reused
        return progress

    def _embed(self, job: dict[str, Any]) -> dict[str, Any]:
        from qdrant_client.models import PointStruct
        path = self._store_path(job["package_id"])
        batch = store.pending_chunks(path, self.settings.embed_batch_size)
        if not batch:
            job.update(phase="publish", status="publishing", progress=self._progress(job, path))
            return self._save(job)
        collection = self.settings.collection
        existing = {p.id: (p.payload or {}) for p in self.qdrant.retrieve(collection, ids=[c["point_id"] for c in batch], with_payload=["packages"])}
        fresh = [c for c in batch if c["point_id"] not in existing]
        for chunk in batch:
            if chunk["point_id"] in existing:
                packages = sorted(set(existing[chunk["point_id"]].get("packages") or []) | {job["package_id"]})
                self.qdrant.set_payload(collection, payload=self._payload(chunk, packages), points=[chunk["point_id"]])
        if fresh:
            vectors = self.encoder([c["embed_text"] for c in fresh])
            self.qdrant.upsert(collection, points=[
                PointStruct(id=c["point_id"], vector=list(v), payload=self._payload(c, [job["package_id"]]))
                for c, v in zip(fresh, vectors)], wait=True)
        store.mark_ready(path, [c["point_id"] for c in batch])
        job["progress"] = self._progress(job, path, len(batch) - len(fresh))
        return self._save(job)

    def _publish(self, job: dict[str, Any]) -> dict[str, Any]:
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue
        package_id = job["package_id"]
        path = self._store_path(package_id)
        if store.counts(path)["chunks_pending"]:
            raise RuntimeError("publish requested before all chunks were embedded")
        if self.neo4j is not None:
            self._sync_graph(package_id, store.documents(path))
        previous = (self.current() or {}).get("package_id")
        _write_json(self.root / "current.json", {"package_id": package_id, "switched_at": _now(),
                                                 "previous_package_id": previous, "job_id": job["job_id"],
                                                 "collection": self.settings.collection,
                                                 "embedding_model": self.embedding_model})
        # Only after the switch: drop vectors that the new package no longer uses.
        self.qdrant.delete(self.settings.collection, points_selector=FilterSelector(filter=Filter(
            must_not=[FieldCondition(key="packages", match=MatchValue(value=package_id))])), wait=True)
        self._prune_stores(package_id)
        (self.root / "incoming" / f"{package_id}.zip").unlink(missing_ok=True)
        (self.root / "import.lock").unlink(missing_ok=True)
        job.update(phase="done", status="completed", progress=self._progress(job, path), previous_package_id=previous,
                   completed_at=_now())
        return self._save(job)

    def _prune_stores(self, package_id: str) -> None:
        stores = sorted((p for p in (self.root / "stores").glob("wifi8-*.sqlite")), key=lambda p: p.stat().st_mtime, reverse=True)
        keep = {self._store_path(package_id)} | set(stores[: self.settings.keep_stores])
        for path in stores:
            if path not in keep:
                path.unlink(missing_ok=True)

    def _sync_graph(self, package_id: str, documents: list[dict[str, Any]]) -> None:
        rows = [{
            "revision_id": d["revision_id"], "name": d.get("title"), "wfa_document_id": d.get("wfa_document_id"),
            "wfa_revision": d.get("wfa_revision"), "document_role": d.get("document_role"),
            "publisher": d.get("publisher"), "document_date": d.get("document_date"),
            "analysis_eligible": bool(d.get("analysis_eligible")), "lifecycle_status": d.get("lifecycle_status"),
            "version_series_id": d.get("version_series_id"), "topics": [t for t in d.get("topics") or [] if t],
            "supersedes": [s for s in d.get("supersedes") or [] if s],
        } for d in documents]
        with self.neo4j.session() as session:
            session.run("CREATE CONSTRAINT wifi8_document_revision IF NOT EXISTS FOR (d:Wifi8Document) REQUIRE d.revision_id IS UNIQUE")
            session.run("""
                UNWIND $rows AS row
                MERGE (d:Wifi8Document {revision_id: row.revision_id})
                SET d.name = row.name, d.wfa_document_id = row.wfa_document_id, d.wfa_revision = row.wfa_revision,
                    d.document_role = row.document_role, d.publisher = row.publisher, d.document_date = row.document_date,
                    d.analysis_eligible = row.analysis_eligible, d.lifecycle_status = row.lifecycle_status,
                    d.version_series_id = row.version_series_id, d.source_system = 'WIFI8',
                    d.storage_category = 'WiFi', d.package_id = $package_id
            """, rows=rows, package_id=package_id)
            session.run("MATCH (d:Wifi8Document) WHERE d.package_id <> $package_id DETACH DELETE d", package_id=package_id)
            session.run("MATCH (:Wifi8Document)-[r:SUPERSEDES|HAS_TOPIC|PUBLISHED_BY]->() DELETE r")
            session.run("""
                UNWIND $rows AS row
                MATCH (newer:Wifi8Document {revision_id: row.revision_id})
                UNWIND row.supersedes AS older_id
                MATCH (older:Wifi8Document {revision_id: older_id})
                MERGE (newer)-[:SUPERSEDES]->(older)
            """, rows=rows)
            session.run("""
                UNWIND $rows AS row
                MATCH (d:Wifi8Document {revision_id: row.revision_id})
                FOREACH (topic IN row.topics | MERGE (t:Wifi8Topic {name: topic}) MERGE (d)-[:HAS_TOPIC]->(t))
                FOREACH (p IN CASE WHEN row.publisher IS NULL OR row.publisher = '' THEN [] ELSE [row.publisher] END |
                    MERGE (o:Wifi8Publisher {name: p}) MERGE (d)-[:PUBLISHED_BY]->(o))
            """, rows=rows)
            session.run("MATCH (t:Wifi8Topic) WHERE NOT (t)<-[:HAS_TOPIC]-() DELETE t")
            session.run("MATCH (o:Wifi8Publisher) WHERE NOT (o)<-[:PUBLISHED_BY]-() DELETE o")
