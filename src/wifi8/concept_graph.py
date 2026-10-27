"""Neo4j side of the concept graph: nodes Wifi8Concept, typed relations between them, MENTIONED_IN to the existing Wifi8Document nodes.

Rows come from concepts.aggregate. Writes are MERGE (re-runnable); a run is tagged so it can be inspected or removed as a whole. Fixed Cypher only.
"""
from __future__ import annotations

from typing import Any

from .concepts import RELATION_TYPES

CONSTRAINT = "CREATE CONSTRAINT wifi8_concept_id IF NOT EXISTS FOR (n:Wifi8Concept) REQUIRE n.concept_id IS UNIQUE"


def init_constraints(session) -> None:
    session.run(CONSTRAINT).consume()


def foreign_overlap(session, rows: dict[str, Any], run_id: str) -> int:
    """Concepts of this load that already exist from another run: a second load would overwrite their support counts and evidence."""
    ids = [c["concept_id"] for c in rows["concepts"]]
    return session.run("MATCH (c:Wifi8Concept) WHERE c.concept_id IN $ids AND c.run_id <> $run RETURN count(c) AS n", ids=ids, run=run_id).single()["n"]


def write(session, rows: dict[str, Any], run: dict[str, Any], documents: dict[str, str], batch: int = 200) -> dict[str, int]:
    """run: {"run_id","model","extracted_at"}; documents: revision_id -> title (used only when a document node does not exist yet)."""
    concepts = rows["concepts"]
    for i in range(0, len(concepts), batch):
        session.run("""UNWIND $rows AS r
            MERGE (c:Wifi8Concept {concept_id: r.concept_id})
            SET c.name = r.name, c.type = r.type, c.aliases = r.aliases, c.doc_count = r.doc_count, c.window_count = r.window_count,
                c.source = 'llm', c.run_id = $run, c.model = $model, c.extracted_at = $at, c.source_runs = r.runs""",
                    rows=[{k: v for k, v in c.items() if k not in ("mentions", "key")} for c in concepts[i:i + batch]], run=run["run_id"], model=run["model"], at=run["extracted_at"]).consume()
    mentions = [{"concept_id": c["concept_id"], "revision_id": d, "chunks": ix, "title": documents.get(d)} for c in concepts for d, ix in c["mentions"].items()]
    for i in range(0, len(mentions), batch):
        session.run("""UNWIND $rows AS r
            MATCH (c:Wifi8Concept {concept_id: r.concept_id})
            MERGE (d:Wifi8Document {revision_id: r.revision_id}) ON CREATE SET d.name = r.title
            MERGE (c)-[m:MENTIONED_IN]->(d) SET m.chunk_indexes = r.chunks, m.source = 'llm', m.run_id = $run""", rows=mentions[i:i + batch], run=run["run_id"]).consume()
    written = 0
    for kind in RELATION_TYPES:  # relationship types cannot be parameters: one fixed statement per allowed type
        subset = [r for r in rows["relations"] if r["type"] == kind]
        for i in range(0, len(subset), batch):
            flat = [{**r, "evidence": [f"{e['revision_id']}: {e['quote']}" for e in r["evidence"]]} for r in subset[i:i + batch]]
            session.run(f"""UNWIND $rows AS r
                MATCH (a:Wifi8Concept {{concept_id: r.source}}), (b:Wifi8Concept {{concept_id: r.target}})
                MERGE (a)-[x:{kind}]->(b)
                SET x.support_windows = r.support_windows, x.support_docs = r.support_docs, x.confidence = r.confidence, x.evidence = r.evidence,
                    x.weak = coalesce(r.weak, false), x.source_runs = r.runs, x.source = 'llm', x.run_id = $run, x.model = $model, x.extracted_at = $at""", rows=flat, run=run["run_id"], model=run["model"], at=run["extracted_at"]).consume()
            written += len(flat)
    return {"concepts": len(concepts), "mentions": len(mentions), "relations": written}
