"""Writers for legacy documents: Qdrant (shared collection, origin-tagged) and Neo4j (Legacy-prefixed labels).

Legacy data is kept apart from CSIT-defined data: every Qdrant point carries origin = legacy_nas and an import batch id, every graph
label starts with "Legacy". Purging one batch removes exactly what that batch wrote.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Callable

from src.report_numeric import vector as rv

NAMESPACE = uuid.UUID("5d0f4c1e-8a3b-4f7e-9c2a-6b1d3e7f9a10")
ORIGIN = "legacy_nas"
SOURCE_SYSTEM = "LEGACY_NAS"
EXTRA_KEYWORD_INDEXES = ("topic_zone", "origin", "import_batch", "l1", "document_type", "technologies", "classification_row", "sha256")

ENTITY_KINDS = (("productNames", "Product"), ("modelNumbers", "Model"), ("vendorNames", "Vendor"), ("technologies", "Technology"),
                ("standards", "Standard"), ("softwareVersions", "SoftwareVersion"), ("hardwareVersions", "HardwareVersion"),
                ("projectNames", "Project"), ("testItems", "TestItem"), ("issueKeys", "IssueKey"))
CONSTRAINTS = (
    "CREATE CONSTRAINT legacy_document_id IF NOT EXISTS FOR (n:LegacyDocument) REQUIRE n.document_id IS UNIQUE",
    "CREATE CONSTRAINT legacy_topic_zone IF NOT EXISTS FOR (n:LegacyTopicZone) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT legacy_category_key IF NOT EXISTS FOR (n:LegacyCategory) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT legacy_entity_key IF NOT EXISTS FOR (n:LegacyEntity) REQUIRE n.key IS UNIQUE",
)


def document_id(sha256: str) -> str:
    """Content-based identity: the same bytes always map to the same document, wherever they were found."""
    return str(uuid.uuid5(NAMESPACE, "legacy-nas:" + sha256))


def record(*, sha256: str, paths: list[str], batch: str, result, chars: int) -> dict:
    """The flat document record both writers (and the review report) use."""
    row = result.row
    doc = dict(result.document)
    return {
        "document_id": document_id(sha256), "sha256": sha256, "source_paths": paths, "import_batch": batch, "characters": chars,
        "origin": ORIGIN, "source_system": SOURCE_SYSTEM,
        "title": doc.get("title") or paths[0].rsplit("/", 1)[-1], "document_type": doc.get("documentType", "Other"),
        "summary": doc.get("summary"), "language": doc.get("language"), "document_date": doc.get("documentDate"),
        "authors": doc.get("authors", []), "department": doc.get("department"), "version_label": doc.get("documentVersionLabel"),
        "keywords": doc.get("keywords", []), "tags": doc.get("tags", []),
        **{name: result.technical.get(name, []) for name, _ in ENTITY_KINDS}, "errorCodes": result.technical.get("errorCodes", []),
        "l1": row.l1, "l2": row.l2, "l3": row.l3, "l2_value": result.l2_value, "l3_value": result.l3_value,
        "classification_row": row.id, "classification_basis": "llm_mapped", "classification_confidence": result.confidence,
        "classification_evidence": result.evidence, "suggested_row": result.suggested_row, "needs_review": result.needs_review,
        "technology_tag": result.technology, "topic_zone": row.topic, "warnings": result.warnings,
    }


class LegacyQdrantWriter:
    def __init__(self, client, encode: Callable, sparse: Callable, model_name: str, model_version: str = "v1"):
        self.client, self.encode, self.sparse, self.model, self.version = client, encode, sparse, model_name, model_version

    def ensure(self) -> None:
        from qdrant_client.models import PayloadSchemaType
        rv.ensure_collection(self.client)
        for field in EXTRA_KEYWORD_INDEXES:
            self.client.create_payload_index(rv.COLLECTION, field, field_schema=PayloadSchemaType.KEYWORD)

    def payload(self, rec: dict, index: int, text: str) -> dict:
        return {
            "schema_version": "legacy-1.0", "document_id": rec["document_id"], "document_version": "1", "chunk_id": f"{rec['document_id']}:{index:04d}",
            "chunk_index": index, "chunk_hash": hashlib.sha1(text.encode("utf-8")).hexdigest(), "chunk_text": text, "content_type": "document_chunk",
            "source_system": rec["source_system"], "origin": rec["origin"], "import_batch": rec["import_batch"], "source_record_id": rec["source_paths"][0],
            "source_paths": rec["source_paths"], "sha256": rec["sha256"], "title": rec["title"], "document_type": rec["document_type"],
            "summary": rec["summary"], "language": rec["language"], "document_date": rec["document_date"], "keywords": rec["keywords"], "tags": rec["tags"],
            "product_names": rec["productNames"], "model_numbers": rec["modelNumbers"], "vendor_names": rec["vendorNames"], "technologies": rec["technologies"],
            "standards": rec["standards"], "l1": rec["l1"], "l2": rec["l2"], "l3": rec["l3"], "l2_value": rec["l2_value"], "l3_value": rec["l3_value"],
            "classification_row": rec["classification_row"], "classification_basis": rec["classification_basis"],
            "classification_confidence": rec["classification_confidence"], "needs_review": rec["needs_review"], "topic_zone": rec["topic_zone"],
            "technology_tag": rec["technology_tag"], "publish_status": "published", "approval_status": "not_applicable", "is_current": True,
            "visibility": "open", "access_roles": [], "access_departments": [], "embedding_model": self.model, "embedding_model_version": self.version,
        }

    def write(self, rec: dict, chunks: list[str], batch: int = 32) -> int:
        from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct, SparseVector
        self.client.delete(rv.COLLECTION, points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=rec["document_id"]))]), wait=True)
        total = 0
        for start in range(0, len(chunks), batch):
            part = chunks[start:start + batch]
            vectors = self.encode(part)
            points = []
            for offset, (text, vector) in enumerate(zip(part, vectors)):
                index = start + offset
                idx, vals = self.sparse(text)
                points.append(PointStruct(id=rv.point_id(rec["document_id"], "1", f"{index:04d}"),
                                          vector={rv.DENSE: list(map(float, vector)), rv.SPARSE: SparseVector(indices=idx, values=vals)},
                                          payload=self.payload(rec, index, text)))
            self.client.upsert(rv.COLLECTION, points=points, wait=True)
            total += len(points)
        return total

    def purge(self, batch_id: str) -> None:
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        self.client.delete(rv.COLLECTION, points_selector=Filter(must=[FieldCondition(key="import_batch", match=MatchValue(value=batch_id))]), wait=True)


class LegacyNeo4jWriter:
    def __init__(self, driver, database: str | None = None):
        self.driver, self.database = driver, database

    def _session(self):
        return self.driver.session(database=self.database) if self.database else self.driver.session()

    def ensure(self) -> None:
        with self._session() as session:
            for statement in CONSTRAINTS:
                session.run(statement).consume()

    def write(self, rec: dict) -> dict:
        entities = [{"key": f"{kind}|{name}", "kind": kind, "name": name} for field, kind in ENTITY_KINDS for name in rec[field]]
        category_key = " / ".join([rec["l1"], rec["l2"], rec["l3"]])
        with self._session() as session:
            session.run("""
                MERGE (d:LegacyDocument {document_id: $id})
                  SET d.title = $title, d.document_type = $dtype, d.summary = $summary, d.language = $lang, d.document_date = $date,
                      d.sha256 = $sha, d.source_paths = $paths, d.import_batch = $batch, d.origin = $origin, d.source_system = $ss,
                      d.topic_zone = $zone, d.needs_review = $review, d.classification_confidence = $conf, d.keywords = $keywords
                MERGE (z:LegacyTopicZone {name: $zone})
                MERGE (d)-[:IN_TOPIC]->(z)
                MERGE (c:LegacyCategory {key: $ckey}) SET c.l1 = $l1, c.l2 = $l2, c.l3 = $l3
                MERGE (d)-[r:CLASSIFIED_AS]->(c) SET r.basis = $basis, r.confidence = $conf, r.row = $row
                """, id=rec["document_id"], title=rec["title"], dtype=rec["document_type"], summary=rec["summary"], lang=rec["language"],
                        date=rec["document_date"], sha=rec["sha256"], paths=rec["source_paths"], batch=rec["import_batch"], origin=rec["origin"],
                        ss=rec["source_system"], zone=rec["topic_zone"], review=rec["needs_review"], conf=rec["classification_confidence"],
                        keywords=rec["keywords"], ckey=category_key, l1=rec["l1"], l2=rec["l2"], l3=rec["l3"], basis=rec["classification_basis"],
                        row=rec["classification_row"]).consume()
            if entities:
                session.run("""
                    MATCH (d:LegacyDocument {document_id: $id})
                    UNWIND $entities AS e
                    MERGE (n:LegacyEntity {key: e.key}) SET n.kind = e.kind, n.name = e.name
                    MERGE (d)-[:MENTIONS]->(n)
                    """, id=rec["document_id"], entities=entities).consume()
        return {"entities": len(entities)}

    def purge(self, batch_id: str) -> None:
        with self._session() as session:
            session.run("MATCH (d:LegacyDocument {import_batch: $b}) DETACH DELETE d", b=batch_id).consume()
            for label in ("LegacyEntity", "LegacyCategory", "LegacyTopicZone"):
                session.run(f"MATCH (n:{label}) WHERE NOT (n)--() DELETE n").consume()
