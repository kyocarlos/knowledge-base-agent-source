"""Read-only Neo4j access for the WiFi zone: fixed Cypher templates only (the model never writes or sees a query), bounded rows and time.

Used for related topics/documents and version history. Unavailable graph = no graph tools, the answer is unaffected.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("km.wifi8.graph")

RELATED_DOCS = """
MATCH (d:Wifi8Document {revision_id: $rid})-[:HAS_TOPIC]->(t:Wifi8Topic)<-[:HAS_TOPIC]-(o:Wifi8Document)
WHERE o.revision_id <> $rid AND coalesce(o.version_series_id, o.revision_id) <> coalesce(d.version_series_id, d.revision_id) AND o.lifecycle_status <> 'superseded'
RETURN o.revision_id AS revision_id, o.name AS title, o.document_role AS document_role, o.publisher AS publisher, o.lifecycle_status AS lifecycle,
       collect(DISTINCT t.name) AS shared_topics, count(DISTINCT t) AS shared
ORDER BY shared DESC, title LIMIT $limit"""
TOPIC_DOCS = """
MATCH (t:Wifi8Topic) WHERE toLower(t.name) = toLower($topic)
MATCH (t)<-[:HAS_TOPIC]-(o:Wifi8Document) WHERE o.lifecycle_status <> 'superseded'
RETURN t.name AS topic, o.revision_id AS revision_id, o.name AS title, o.document_role AS document_role, o.publisher AS publisher, o.lifecycle_status AS lifecycle
ORDER BY title LIMIT $limit"""
TOPIC_NEIGHBOURS = """
MATCH (t:Wifi8Topic) WHERE toLower(t.name) = toLower($topic)
MATCH (t)<-[:HAS_TOPIC]-(d:Wifi8Document)-[:HAS_TOPIC]->(o:Wifi8Topic) WHERE o <> t
RETURN o.name AS topic, count(DISTINCT d) AS documents ORDER BY documents DESC, topic LIMIT $limit"""
TIMELINE = """
MATCH (d:Wifi8Document {revision_id: $rid})
MATCH (x:Wifi8Document) WHERE x.version_series_id = d.version_series_id
RETURN x.revision_id AS revision_id, x.name AS title, x.lifecycle_status AS lifecycle, x.document_date AS document_date, x.wfa_revision AS wfa_revision,
       EXISTS { (x)-[:SUPERSEDES]->(:Wifi8Document) } AS replaces_older
ORDER BY coalesce(x.document_date, ''), title LIMIT $limit"""

CONCEPT_INDEX = """
MATCH (c:Wifi8Concept) RETURN c.concept_id AS concept_id, c.name AS name, c.type AS type, coalesce(c.aliases, []) AS aliases, coalesce(c.doc_count, 0) AS doc_count"""
# Relations of one concept in both directions; the relation type is a parameter filter (empty = all), never part of the query text.
CONCEPT_RELATIONS = """
MATCH (c:Wifi8Concept {concept_id: $cid})-[r]->(o:Wifi8Concept) WHERE $rel = '' OR type(r) = $rel
RETURN 'out' AS direction, type(r) AS relation, o.concept_id AS other_id, o.name AS other, o.type AS other_type, r.support_docs AS support_docs,
       r.support_windows AS support_windows, r.confidence AS confidence, coalesce(r.weak, false) AS weak, r.evidence AS evidence
UNION ALL
MATCH (o:Wifi8Concept)-[r]->(c:Wifi8Concept {concept_id: $cid}) WHERE $rel = '' OR type(r) = $rel
RETURN 'in' AS direction, type(r) AS relation, o.concept_id AS other_id, o.name AS other, o.type AS other_type, r.support_docs AS support_docs,
       r.support_windows AS support_windows, r.confidence AS confidence, coalesce(r.weak, false) AS weak, r.evidence AS evidence"""
CONCEPT_DOCS = """
MATCH (c:Wifi8Concept {concept_id: $cid})-[:MENTIONED_IN]->(d:Wifi8Document)
RETURN d.revision_id AS revision_id, d.name AS title, d.document_role AS document_role, d.publisher AS publisher, d.lifecycle_status AS lifecycle
ORDER BY title LIMIT $limit"""
CONCEPT_SHARED_DOCS = """
MATCH (a:Wifi8Concept {concept_id: $a})-[:MENTIONED_IN]->(d:Wifi8Document)<-[:MENTIONED_IN]-(b:Wifi8Concept {concept_id: $b})
RETURN d.revision_id AS revision_id, d.name AS title, d.document_role AS document_role, d.publisher AS publisher, d.lifecycle_status AS lifecycle
ORDER BY title LIMIT $limit"""
CONCEPT_COMMON = """
MATCH (a:Wifi8Concept {concept_id: $a})-[r1]-(x:Wifi8Concept)-[r2]-(b:Wifi8Concept {concept_id: $b}) WHERE x <> a AND x <> b
RETURN x.name AS name, x.type AS type, collect(DISTINCT type(r1)) AS with_a, collect(DISTINCT type(r2)) AS with_b, coalesce(x.doc_count, 0) AS doc_count
ORDER BY doc_count DESC, name LIMIT $limit"""


class Wifi8Graph:
    def __init__(self, driver: Any, database: str | None = None, timeout: float = 5.0, max_rows: int = 12) -> None:
        self.driver, self.database, self.timeout, self.max_rows = driver, database, timeout, max_rows

    @classmethod
    def from_environment(cls) -> "Wifi8Graph | None":
        uri = os.getenv("NEO4J_URI")
        if not uri or os.getenv("KM_WIFI8_GRAPH", "1").strip().lower() in {"0", "false", "no", "off"}:
            return None
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(uri, auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]), connection_timeout=3)
            return cls(driver, os.getenv("NEO4J_DATABASE") or None, float(os.getenv("KM_WIFI8_GRAPH_TIMEOUT_SECONDS", "5")), int(os.getenv("KM_WIFI8_GRAPH_MAX_ROWS", "12")))
        except Exception as exc:  # noqa: BLE001 - the graph is optional
            logger.warning("WiFi graph unavailable: %s", type(exc).__name__)
            return None

    def _read(self, query: str, **params: Any) -> list[dict[str, Any]]:
        from neo4j import Query
        cap = int(params.pop("cap", self.max_rows))
        limit = max(1, min(int(params.pop("limit", self.max_rows)), cap))
        with self.driver.session(database=self.database, default_access_mode="READ") as session:
            return [dict(r) for r in session.run(Query(query, timeout=self.timeout), limit=limit, **params)]

    def related_documents(self, revision_id: str, limit: int = 8) -> list[dict[str, Any]]:
        return self._read(RELATED_DOCS, rid=str(revision_id), limit=limit)

    def topic_documents(self, topic: str, limit: int = 8) -> list[dict[str, Any]]:
        return self._read(TOPIC_DOCS, topic=str(topic).strip(), limit=limit)

    def topic_neighbours(self, topic: str, limit: int = 8) -> list[dict[str, Any]]:
        return self._read(TOPIC_NEIGHBOURS, topic=str(topic).strip(), limit=limit)

    def timeline(self, revision_id: str, limit: int = 12) -> list[dict[str, Any]]:
        return self._read(TIMELINE, rid=str(revision_id), limit=limit)

    # ---- concept graph (LLM-extracted, partial coverage) ----------------
    def concept_index(self, ttl: float = 600.0) -> list[dict[str, Any]]:
        """Every concept (name, aliases, type, documents), cached for ``ttl`` seconds: name resolution happens in code, not in Cypher."""
        import time
        cached = getattr(self, "_concepts", None)
        if cached and time.monotonic() - cached[0] < ttl:
            return cached[1]
        with self.driver.session(database=self.database, default_access_mode="READ") as session:
            from neo4j import Query
            rows = [dict(r) for r in session.run(Query(CONCEPT_INDEX, timeout=max(self.timeout, 15.0)))]
        self._concepts = (time.monotonic(), rows)
        return rows

    def concept_relations(self, concept_id: str, relation: str = "", limit: int = 40) -> list[dict[str, Any]]:
        return self._read(CONCEPT_RELATIONS, cid=str(concept_id), rel=str(relation), limit=limit, cap=60)

    def concept_documents(self, concept_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self._read(CONCEPT_DOCS, cid=str(concept_id), limit=limit, cap=60)

    def concept_shared_documents(self, a: str, b: str, limit: int = 20) -> list[dict[str, Any]]:
        return self._read(CONCEPT_SHARED_DOCS, a=str(a), b=str(b), limit=limit, cap=60)

    def concept_common(self, a: str, b: str, limit: int = 12) -> list[dict[str, Any]]:
        return self._read(CONCEPT_COMMON, a=str(a), b=str(b), limit=limit, cap=60)
