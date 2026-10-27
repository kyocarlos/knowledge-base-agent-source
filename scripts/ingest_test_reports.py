#!/usr/bin/env python3
"""Ingest test-report workbooks into km_test (TimescaleDB), Neo4j and Qdrant (KM v2.6). Re-runnable: unchanged reports are skipped.

Environment: KM_TEST_NUMERIC_URL (PostgreSQL DSN), NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD, QDRANT_URL. Run inside a KM container (the embedding model and the
BM25 tokenizer are loaded from the KM source). Reports with formula-error cells are refused unless --accept-source-errors is given.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.report_numeric import chunks as chunk_mod, graph, timescale, vector  # noqa: E402
from src.report_numeric.parser import parse_report  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="xlsx files or directories")
    ap.add_argument("--accept-source-errors", action="store_true", help="ingest reports whose source has formula-error cells (the cells are not stored as numbers)")
    ap.add_argument("--replace", action="store_true", help="replace a report whose document and version already exist with other content")
    ap.add_argument("--skip-vectors", action="store_true")
    ap.add_argument("--skip-graph", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="parse and report only")
    a = ap.parse_args()
    files = sorted({f for p in a.paths for f in (glob.glob(os.path.join(p, "*.xlsx")) if os.path.isdir(p) else [p]) if not os.path.basename(f).startswith(("~", "."))})
    seen: dict[str, str] = {}
    packages = []
    for f in files:
        pkg = parse_report(f)
        digest = pkg["source"]["checksum"]
        if digest in seen:
            print(f"skip duplicate file {os.path.basename(f)} (same content as {seen[digest]})")
            continue
        seen[digest] = os.path.basename(f)
        packages.append(pkg)
    for pkg in packages:
        print(f"{pkg['document']['document_id']}: measurements={len(pkg['measurements'])} results={len(pkg['results'])} criteria={len(pkg['criteria'])} formula_errors={len(pkg['quality']['formula_errors'])}")
    if a.dry_run:
        return 0
    import psycopg
    conn = psycopg.connect(os.environ["KM_TEST_NUMERIC_URL"], autocommit=True)
    driver = client = None
    if not a.skip_graph:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    if not a.skip_vectors:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=os.environ["QDRANT_URL"], check_compatibility=False)
        model_name, encode, count = vector.load_encoder()
        sparse = vector.doc_sparse
    report = []
    for pkg in packages:
        row = {"document_id": pkg["document"]["document_id"]}
        try:
            row["numeric"] = timescale.write_package(conn, pkg, accept_source_errors=a.accept_source_errors, replace=a.replace)
        except timescale.ConflictError as exc:
            row["numeric"] = {"status": "refused", "reason": str(exc)}
            report.append(row)
            continue
        if driver is not None:
            with driver.session() as session:
                row["graph"] = graph.write_graph(session, pkg)
        if client is not None:
            chunks = chunk_mod.build_chunks(pkg, count)
            row["vectors"] = vector.write_chunks(client, pkg, chunks, encode, sparse, model_name, "v1")
        report.append(row)
        print(json.dumps(row, ensure_ascii=False))
    print(json.dumps({"reports": len(report), "refused": sum(1 for r in report if r["numeric"]["status"] == "refused")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
