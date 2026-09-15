"""Run deterministic smoke contracts against isolated CI databases."""

from __future__ import annotations

import sys
import time
import uuid


def main() -> int:
    from neo4j import GraphDatabase
    import psycopg
    from qdrant_client import QdrantClient, models

    collection = "km_ci_contract"
    point_id = str(uuid.uuid4())
    qdrant = QdrantClient("http://127.0.0.1:16333")
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                qdrant.recreate_collection(
                    collection_name=collection,
                    vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE),
                )
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(2)
        qdrant.upsert(collection, points=[models.PointStruct(
            id=point_id, vector=[0.1, 0.2, 0.3], payload={"acl": "km-ci"}
        )])
        hits = qdrant.search(collection, query_vector=[0.1, 0.2, 0.3], query_filter=models.Filter(
            must=[models.FieldCondition(key="acl", match=models.MatchValue(value="km-ci"))]
        ))
        if not hits or hits[0].id != point_id:
            raise RuntimeError("qdrant query contract failed")
        qdrant.delete(collection, points_selector=models.PointIdsList(points=[point_id]))
        if qdrant.retrieve(collection, ids=[point_id]):
            raise RuntimeError("qdrant cleanup left residual data")
    finally:
        try:
            qdrant.delete_collection(collection)
        except Exception:
            pass

    driver = GraphDatabase.driver("bolt://127.0.0.1:17688", auth=("neo4j", "ci-neo4j-password"))
    try:
        with driver.session() as session:
            for _ in range(2):
                session.run("MERGE (n:KMCI {id: $id}) SET n.provenance = $provenance",
                            id=point_id, provenance="ci").consume()
            count = session.run("MATCH (n:KMCI {id: $id}) RETURN count(n) AS count",
                                id=point_id).single()["count"]
            if count != 1:
                raise RuntimeError("neo4j MERGE contract failed")
            session.run("MATCH (n:KMCI {id: $id}) DELETE n", id=point_id).consume()
    finally:
        driver.close()

    with psycopg.connect("postgresql://km_ci:ci-timescale-password@127.0.0.1:15433/km_ci") as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE km_ci_contract (id text)")
            cur.execute("SELECT 1")
            if cur.fetchone()[0] != 1:
                raise RuntimeError("timescaledb readiness contract failed")

    print("KM_DB_SMOKE_PASS qdrant=PASS neo4j=PASS timescaledb=READINESS_PASS cleanup=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Driver errors may contain DSNs; keep CI output free of credentials.
        print(f"KM_DB_SMOKE_FAIL {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
