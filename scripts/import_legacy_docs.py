#!/usr/bin/env python3
"""Import legacy (NAS) documents into Qdrant + Neo4j, classified into the CSIT taxonomy / topic zones (KM v2.6).

The files are read from --root using the relative paths in --list (one per line), so the NAS folder structure stays visible to the
classifier. Re-runnable: identity is the file's SHA-256, so the same bytes never produce a second document.

Environment: KM_LLM_PRIMARY_MODEL / KM_LLM_PRIMARY_BASE_URL / KM_LLM_PRIMARY_API_KEY_ENV (the model gateway),
QDRANT_URL, NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD. Run inside a KM container (embedding model and BM25 tokenizer come from the KM source).

--dry-run classifies and reports without writing. --purge BATCH removes everything one batch wrote.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.legacy_import import analyze, stores, taxonomy, textio  # noqa: E402

MIN_CHARS = 50


def llm_complete():
    from src.web_api.openai_compatible_client import OpenAICompatibleClient
    env = os.environ.get
    client = OpenAICompatibleClient(model=env("KM_LLM_PRIMARY_MODEL"), base_url=env("KM_LLM_PRIMARY_BASE_URL"),
                                    timeout=float(env("KM_LLM_PRIMARY_TIMEOUT_SECONDS") or 180), max_tokens=2500,
                                    api_key_env=env("KM_LLM_PRIMARY_API_KEY_ENV") or "SUB2API_API_KEY")
    return lambda messages: client.chat(messages, temperature=0.1)


def read_files(root: Path, listing: list[str]) -> tuple[dict[str, dict], list[dict]]:
    """Group by content hash. Returns ({sha256: {paths, text, size}}, failures)."""
    unique: dict[str, dict] = {}
    failures = []
    for rel in listing:
        path = root / rel
        term = taxonomy.sensitive_path(rel)
        if term:                                    # HR / procurement / Time Report: not even read
            failures.append({"path": rel, "status": "sensitive_skipped", "reason": f"path contains '{term}'"})
            continue
        noise = taxonomy.noise_path(rel)
        if noise:                                   # drivers, binaries, codec source trees, package readmes: not read
            failures.append({"path": rel, "status": "noise_skipped", "reason": noise})
            continue
        try:
            digest = textio.sha256_file(path)
            if digest in unique:
                unique[digest]["paths"].append(rel)
                continue
            text = textio.extract_text(path)
            unique[digest] = {"paths": [rel], "text": text, "size": path.stat().st_size}
        except Exception as exc:  # unreadable file: record and go on
            failures.append({"path": rel, "status": "unreadable", "reason": f"{type(exc).__name__}: {str(exc)[:120]}"})
    return unique, failures


def analyse_all(unique: dict[str, dict], workers: int) -> dict[str, object]:
    complete = llm_complete()

    def one(item):
        digest, info = item
        for attempt in (1, 2):
            try:
                return digest, analyze.analyze(complete, info["paths"][0], info["text"])
            except Exception as exc:  # model output unusable / gateway error
                error = f"{type(exc).__name__}: {str(exc)[:120]}"
                time.sleep(2 * attempt)
        return digest, error

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, [(d, i) for d, i in unique.items() if len(i["text"]) >= MIN_CHARS]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path)
    ap.add_argument("--list", type=Path)
    ap.add_argument("--batch", required=True)
    ap.add_argument("--out", type=Path, default=Path("legacy-import-report"))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--purge", action="store_true", help="remove everything this batch wrote, then exit")
    a = ap.parse_args()

    qdrant = driver = None
    if not a.dry_run or a.purge:
        from neo4j import GraphDatabase
        from qdrant_client import QdrantClient
        qdrant = QdrantClient(url=os.environ["QDRANT_URL"], check_compatibility=False)
        driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    if a.purge:
        if qdrant.collection_exists("ai_km_knowledge_v1"):
            stores.LegacyQdrantWriter(qdrant, None, None, "").purge(a.batch)
        stores.LegacyNeo4jWriter(driver).purge(a.batch)
        print(json.dumps({"purged": a.batch}))
        return 0

    listing = [line.strip() for line in a.list.read_text(encoding="utf-8").splitlines() if line.strip()]
    started = time.time()
    unique, failures = read_files(a.root, listing)
    print(f"read {len(listing)} files -> {len(unique)} unique, {len(failures)} unreadable ({time.time() - started:.0f}s)", flush=True)
    results = analyse_all(unique, a.workers)
    print(f"analysed {len(results)} documents ({time.time() - started:.0f}s)", flush=True)

    records, report = [], list(failures)
    for digest, info in unique.items():
        if len(info["text"]) < MIN_CHARS:
            report.append({"path": info["paths"][0], "status": "no_text", "reason": f"{len(info['text'])} characters extracted (scanned image? OCR is off)"})
            continue
        result = results.get(digest)
        if isinstance(result, str) or result is None:
            report.append({"path": info["paths"][0], "status": "analysis_failed", "reason": result})
            continue
        if result.skip_reason:
            report.append({"path": info["paths"][0], "status": "sensitive_skipped", "reason": result.skip_reason})
            continue
        rec = stores.record(sha256=digest, paths=info["paths"], batch=a.batch, result=result, chars=len(info["text"]))
        rec["_text"] = info["text"]
        records.append(rec)

    written = {"documents": 0, "chunks": 0}
    if not a.dry_run and records:
        from src.report_numeric import vector
        vec_name, encode, _count = vector.load_encoder()
        qd =stores.LegacyQdrantWriter(qdrant, encode, vector.doc_sparse, vec_name)
        graph = stores.LegacyNeo4jWriter(driver)
        qd.ensure()
        graph.ensure()
        for rec in records:
            chunks = textio.chunk(rec["_text"])
            written["chunks"] += qd.write(rec, chunks)
            graph.write(rec)
            written["documents"] += 1
        print(f"written {written}", flush=True)

    a.out.mkdir(parents=True, exist_ok=True)
    columns = ["source_paths", "title", "document_type", "topic_zone", "l1", "l2", "l3", "l2_value", "l3_value", "classification_row", "classification_confidence",
               "needs_review", "suggested_row", "classification_evidence", "technology_tag", "modelNumbers", "vendorNames", "technologies", "document_date",
               "summary", "characters", "warnings", "sha256"]
    with open(a.out / "review.csv", "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for rec in sorted(records, key=lambda r: (r["needs_review"] is False, r["classification_confidence"])):
            writer.writerow([" | ".join(rec[c]) if isinstance(rec[c], list) else rec[c] for c in columns])
    (a.out / "skipped.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {"batch": a.batch, "dry_run": a.dry_run, "listed": len(listing), "unique": len(unique), "classified": len(records), "written": written,
               "skipped": Counter(r["status"] for r in report), "needs_review": sum(1 for r in records if r["needs_review"]),
               "by_zone": Counter(r["topic_zone"] for r in records), "by_row": Counter(f"{r['classification_row']} {r['l1']}/{r['l2']}/{r['l3']}" for r in records)}
    (a.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=dict), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=dict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
