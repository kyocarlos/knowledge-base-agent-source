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

from . import lexical, store
from .chunks import DISPLAY_VERSION, build_chunks
from .package import PackageError, read_package

SOURCE_SYSTEM = "WIFI8"
STORAGE_CATEGORY = "WiFi"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Wifi8Settings:
    root: Path
    collection: str = "wifi8_chunks"
    documents_collection: str = "wifi8_documents"
    reuse_collection: str = "wifi8_kb"
    chunk_max_chars: int = 1200
    embed_batch_size: int = 256
    stage_batch_size: int = 1000
    bm25_avg_tokens: float = 256.0
    max_package_bytes: int = 200 * 1024 * 1024
    max_uncompressed_bytes: int = 1024 * 1024 * 1024

    @classmethod
    def from_environment(cls) -> "Wifi8Settings":
        mb = 1024 * 1024
        return cls(
            root=Path(os.getenv("KM_WIFI8_ROOT", "/app/data/wifi8")),
            collection=os.getenv("KM_WIFI8_COLLECTION", "wifi8_chunks"),
            documents_collection=os.getenv("KM_WIFI8_DOCUMENTS_COLLECTION", "wifi8_documents"),
            # Vectors of an earlier collection are reused by content-addressed point id (empty disables).
            reuse_collection=os.getenv("KM_WIFI8_REUSE_COLLECTION", "wifi8_kb"),
            chunk_max_chars=int(os.getenv("KM_WIFI8_CHUNK_MAX_CHARS", "1200")),
            embed_batch_size=int(os.getenv("KM_WIFI8_EMBED_BATCH_SIZE", "256")),
            stage_batch_size=int(os.getenv("KM_WIFI8_STAGE_BATCH_SIZE", "1000")),
            bm25_avg_tokens=float(os.getenv("KM_WIFI8_BM25_AVG_TOKENS", "256")),
            max_package_bytes=int(os.getenv("KM_WIFI8_MAX_PACKAGE_MB", "200")) * mb,
            max_uncompressed_bytes=int(os.getenv("KM_WIFI8_MAX_UNCOMPRESSED_MB", "1024")) * mb,
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

    def current(self) -> dict[str, Any] | None:
        return _read_json(self.root / "current.json")

    def package_store(self, package_id: str) -> store.Wifi8Store:
        return store.Wifi8Store(self.qdrant, package_id=package_id, chunks_collection=self.settings.collection,
                                documents_collection=self.settings.documents_collection)

    def current_store(self, qdrant=None) -> store.Wifi8Store | None:
        """Store of the serving package; None before the first Qdrant-backed import."""
        current = self.current()
        if not current or not current.get("documents_collection"):
            return None
        return store.Wifi8Store(qdrant or self.qdrant, package_id=current["package_id"],
                                chunks_collection=current.get("collection") or self.settings.collection,
                                documents_collection=current["documents_collection"])

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
        # The same package is imported again when the current one predates the Qdrant store (no documents
        # collection) or an older display format (e.g. no table display text): vectors are reused, nothing re-embedded.
        same = (current.get("package_id") == package.package_id and bool(current.get("documents_collection"))
                and int(current.get("display_version") or 0) >= DISPLAY_VERSION)
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
            self._discard_staged(job["package_id"])
            (self.root / "import.lock").unlink(missing_ok=True)
            return self._save(job)

    def _package(self, package_id: str):
        return read_package(self.root / "incoming" / f"{package_id}.zip",
                            max_uncompressed_bytes=self.settings.max_uncompressed_bytes)

    def _stage(self, job: dict[str, Any]) -> dict[str, Any]:
        """Write documents and chunk points (BM25 sparse vector, payload) in bounded batches."""
        job["status"] = "staging"
        self._save(job)
        package = self._package(job["package_id"])
        documents = {d["revision_id"]: d for d in package.documents}
        chunks = build_chunks(package.documents, package.segments, max_chars=self.settings.chunk_max_chars)
        offset = int(job.get("stage_offset") or 0)
        if offset == 0:
            self._ensure_collections()
            self._write_documents(package, len(package.segments), len(chunks))
        batch = chunks[offset: offset + self.settings.stage_batch_size]
        reused = self._stage_chunks(job["package_id"], batch, documents)
        job["stage_offset"] = offset + len(batch)
        job["progress"] = self._progress(job, reused)
        if job["stage_offset"] >= len(chunks):
            job.update(phase="embed", status="embedding")
        return self._save(job)

    def _ensure_collections(self) -> None:
        from qdrant_client.models import (Distance, Modifier, PayloadSchemaType, SparseVectorParams, VectorParams)
        names = {c.name for c in self.qdrant.get_collections().collections}
        dim = len(self.encoder(["dimension probe"])[0])
        sparse = {store.SPARSE: SparseVectorParams(modifier=Modifier.IDF)}
        if self.settings.collection not in names:
            self.qdrant.create_collection(self.settings.collection, vectors_config={store.DENSE: VectorParams(size=dim, distance=Distance.COSINE)},
                                          sparse_vectors_config=sparse)
        else:
            vectors = self.qdrant.get_collection(self.settings.collection).config.params.vectors
            existing = vectors[store.DENSE].size if isinstance(vectors, dict) and store.DENSE in vectors else None
            if existing != dim:
                raise RuntimeError(f"collection {self.settings.collection} has {existing}-dim vectors, "
                                   f"embedding model {self.embedding_model} produces {dim}")
        if self.settings.documents_collection not in names:
            self.qdrant.create_collection(self.settings.documents_collection, vectors_config={}, sparse_vectors_config=sparse)
        current = self.current() or {}
        if current.get("embedding_model") and current["embedding_model"] != self.embedding_model:
            # Reused vectors would silently mix two models; a model change needs a fresh collection.
            raise RuntimeError(f"current package was embedded with {current['embedding_model']}, not {self.embedding_model}")
        for field, schema in (("packages", PayloadSchemaType.KEYWORD), ("revision_id", PayloadSchemaType.KEYWORD),
                              ("analysis_eligible", PayloadSchemaType.BOOL), ("document_role", PayloadSchemaType.KEYWORD),
                              ("publisher", PayloadSchemaType.KEYWORD), ("wfa_document_id", PayloadSchemaType.KEYWORD),
                              ("vector_state", PayloadSchemaType.KEYWORD), ("chunk_index", PayloadSchemaType.INTEGER)):
            self.qdrant.create_payload_index(self.settings.collection, field_name=field, field_schema=schema)
        for field in ("package_id", "kind"):
            self.qdrant.create_payload_index(self.settings.documents_collection, field_name=field, field_schema=PayloadSchemaType.KEYWORD)

    def _write_documents(self, package, segments: int, chunks: int) -> None:
        from qdrant_client.models import PointStruct
        package_id = package.package_id
        points = [PointStruct(id=store.package_point_id(package_id), vector={}, payload={
            "kind": "package", "package_id": package_id, "manifest": package.manifest,
            "segments": segments, "chunks": chunks, "embedding_model": self.embedding_model, "created_at": _now()})]
        points += [PointStruct(id=store.document_point_id(package_id, d["revision_id"]), vector={}, payload={
            "kind": "document", "package_id": package_id, "revision_id": d["revision_id"], "document": d})
            for d in package.documents]
        for i in range(0, len(points), 256):
            self.qdrant.upsert(self.settings.documents_collection, points=points[i:i + 256], wait=True)

    def _document_payload(self, doc: dict[str, Any]) -> dict[str, Any]:
        eligible = bool(doc.get("analysis_eligible"))
        return {
            "doc_name": doc.get("title"), "source_name": doc.get("display_filename") or doc.get("title"),
            "storage_category": STORAGE_CATEGORY, "source_system": SOURCE_SYSTEM,
            "wfa_document_id": doc.get("wfa_document_id"), "wfa_revision": doc.get("wfa_revision"),
            "document_role": doc.get("document_role"), "publisher": doc.get("publisher"),
            "primary_category_id": doc.get("primary_category_id"), "topics": doc.get("topics") or [],
            "document_date": doc.get("document_date"), "version_series_id": doc.get("version_series_id"),
            "lifecycle_status": doc.get("lifecycle_status"), "analysis_eligible": eligible,
            "publish_status": "published", "is_current": eligible,
        }

    def _reusable_vectors(self, point_ids: list[str]) -> dict[str, list[float]]:
        name = self.settings.reuse_collection
        if not name or name == self.settings.collection or not self.qdrant.collection_exists(name):
            return {}
        found = {}
        for point in self.qdrant.retrieve(name, ids=point_ids, with_payload=["embedding_model"], with_vectors=True):
            vector = point.vector.get(store.DENSE) if isinstance(point.vector, dict) else point.vector
            if vector and (point.payload or {}).get("embedding_model") == self.embedding_model:
                found[str(point.id)] = list(vector)
        return found

    def _stage_chunks(self, package_id: str, batch: list[dict[str, Any]], documents: dict[str, dict[str, Any]]) -> int:
        from qdrant_client.models import PointStruct, SparseVector
        if not batch:
            return 0
        collection = self.settings.collection
        ids = [c["point_id"] for c in batch]
        existing = {str(p.id): (p.payload or {}).get("packages") or []
                    for p in self.qdrant.retrieve(collection, ids=ids, with_payload=["packages"])}
        groups: dict[tuple[str, ...], list[str]] = {}
        for point_id, packages in existing.items():
            groups.setdefault(tuple(sorted(set(packages) | {package_id})), []).append(point_id)
        for packages, point_ids in groups.items():
            self.qdrant.set_payload(collection, payload={"packages": list(packages)}, points=point_ids, wait=True)
        self._refresh_display(collection, [c for c in batch if c["point_id"] in existing])
        fresh = [c for c in batch if c["point_id"] not in existing]
        reusable = self._reusable_vectors([c["point_id"] for c in fresh]) if fresh else {}
        points = []
        for chunk in fresh:
            doc = documents[chunk["revision_id"]]
            indices, values = lexical.document_vector(chunk["text"], doc.get("title") or "", avg_tokens=self.settings.bm25_avg_tokens)
            vector: dict[str, Any] = {store.SPARSE: SparseVector(indices=indices, values=values)}
            if chunk["point_id"] in reusable:
                vector[store.DENSE] = reusable[chunk["point_id"]]
            points.append(PointStruct(id=chunk["point_id"], vector=vector, payload={
                **self._document_payload(doc),
                "content": chunk["text"], "revision_id": chunk["revision_id"], "chunk_index": chunk["ordinal"],
                "segment_ids": chunk["segment_ids"], "location": chunk["location"], "location_label": chunk["location_label"],
                "content_hash": chunk["content_hash"], "embed_text": chunk["embed_text"], "packages": [package_id],
                **({"display_text": chunk["display_text"]} if chunk.get("display_text") else {}),
                "embedding_model": self.embedding_model,
                "vector_state": "ready" if chunk["point_id"] in reusable else "pending",
            }))
        for i in range(0, len(points), 256):
            self.qdrant.upsert(collection, points=points[i:i + 256], wait=True)
        return len(existing) + len(reusable)

    def _refresh_display(self, collection: str, chunks: list[dict[str, Any]]) -> None:
        """Existing chunks get the current display text; their identity and vectors stay as they are."""
        from qdrant_client.models import SetPayload, SetPayloadOperation
        operations = [SetPayloadOperation(set_payload=SetPayload(payload={"display_text": c["display_text"]}, points=[c["point_id"]]))
                      for c in chunks if c.get("display_text")]
        for i in range(0, len(operations), 256):
            self.qdrant.batch_update_points(collection, update_operations=operations[i:i + 256], wait=True)

    def _progress(self, job: dict[str, Any], reused: int = 0) -> dict[str, Any]:
        progress = self.package_store(job["package_id"]).counts()
        progress["vectors_reused"] = job.get("progress", {}).get("vectors_reused", 0) + reused
        return progress

    def _embed(self, job: dict[str, Any]) -> dict[str, Any]:
        from qdrant_client.models import PointVectors
        package = self.package_store(job["package_id"])
        collection = self.settings.collection
        batch, _ = self.qdrant.scroll(collection, scroll_filter=package.chunk_filter(store.match("vector_state", "pending")),
                                      limit=self.settings.embed_batch_size, with_payload=["embed_text"], with_vectors=False)
        if not batch:
            job.update(phase="publish", status="publishing", progress=self._progress(job))
            return self._save(job)
        vectors = self.encoder([p.payload["embed_text"] for p in batch])
        self.qdrant.update_vectors(collection, points=[PointVectors(id=p.id, vector={store.DENSE: list(v)})
                                                       for p, v in zip(batch, vectors)], wait=True)
        self.qdrant.set_payload(collection, payload={"vector_state": "ready"}, points=[p.id for p in batch], wait=True)
        job["progress"] = self._progress(job)
        return self._save(job)

    def _publish(self, job: dict[str, Any]) -> dict[str, Any]:
        from qdrant_client.models import Filter, FilterSelector
        package_id = job["package_id"]
        package = self.package_store(package_id)
        if package.counts()["chunks_pending"]:
            raise RuntimeError("publish requested before all chunks were embedded")
        documents = package.documents()
        if self.neo4j is not None:
            self._sync_graph(package_id, documents)
        previous = (self.current() or {}).get("package_id")
        _write_json(self.root / "current.json", {"package_id": package_id, "switched_at": _now(),
                                                 "previous_package_id": previous, "job_id": job["job_id"],
                                                 "store": "qdrant", "collection": self.settings.collection,
                                                 "documents_collection": self.settings.documents_collection,
                                                 "embedding_model": self.embedding_model, "display_version": DISPLAY_VERSION})
        collection = self.settings.collection
        # Only after the switch: chunks shared with the previous package take this package's document metadata,
        # then everything the new package no longer uses is removed.
        for doc in documents:
            self.qdrant.set_payload(collection, payload=self._document_payload(doc), wait=True,
                                    points=FilterSelector(filter=package.chunk_filter(store.match("revision_id", doc["revision_id"]))))
        self.qdrant.delete(collection, points_selector=FilterSelector(filter=Filter(
            must_not=[store.match("packages", package_id)])), wait=True)
        self.qdrant.set_payload(collection, payload={"packages": [package_id]}, points=FilterSelector(filter=package.chunk_filter()), wait=True)
        self.qdrant.delete(self.settings.documents_collection, points_selector=FilterSelector(filter=Filter(
            must_not=[store.match("package_id", package_id)])), wait=True)
        (self.root / "incoming" / f"{package_id}.zip").unlink(missing_ok=True)
        (self.root / "import.lock").unlink(missing_ok=True)
        job.update(phase="done", status="completed", progress=self._progress(job), previous_package_id=previous,
                   completed_at=_now())
        return self._save(job)

    def _discard_staged(self, package_id: str) -> None:
        """Remove what a failed import wrote, without touching the serving package."""
        from qdrant_client.models import Filter, FilterSelector
        if self.qdrant is None or (self.current() or {}).get("package_id") == package_id:
            return
        try:
            names = {c.name for c in self.qdrant.get_collections().collections}
            if self.settings.collection in names:
                serving = (self.current() or {}).get("package_id")
                self.qdrant.delete(self.settings.collection, wait=True, points_selector=FilterSelector(filter=Filter(
                    must=[store.match("packages", package_id)],
                    must_not=[store.match("packages", serving)] if serving else [])))
            if self.settings.documents_collection in names:
                self.qdrant.delete(self.settings.documents_collection, wait=True, points_selector=FilterSelector(
                    filter=Filter(must=[store.match("package_id", package_id)])))
        except Exception:  # cleanup is best effort; the next publish removes leftovers too
            pass

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
