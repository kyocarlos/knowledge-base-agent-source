#!/usr/bin/env python3
"""Concept graph extraction (pilot). Reads WiFi zone chunks from Qdrant (read-only), calls the LLM one window at a time (never in parallel: the gateway
times out under load), validates in code and appends one JSON line per window; re-running skips windows already done.

  extract   --roles "MRD Feature Contribution" --per-doc 1 --out DIR     (needs QDRANT_URL and the KM LLM settings)
  report    --out DIR                                                    (statistics + aggregated rows -> DIR/graph-rows.json)
  load      --out DIR [--wipe-run RUN]                                   (needs NEO4J_URI/USER/PASSWORD; writes Wifi8Concept nodes)

Round 3 additions (all rules live in concept_rules.json):
  relevance --out DIR --roles ROLES                                      (Wi-Fi vocabulary density per document -> DIR/relevance.json)
  combine   --out DIR --src DIR1 --src DIR2 ... [--relevance FILE] [--merges FILE]   (aggregate every run once -> DIR/graph-rows.json)
  merge-candidates --out DIR [--vectors]                                 (candidate duplicate concepts -> DIR/merge-candidates.json)
  merge-judge      --out DIR                                             (LLM judges each candidate, one by one, resumable -> DIR/merge-decisions.jsonl)
  merge-apply      --out DIR                                             (approved decisions -> DIR/merges.json, read by combine/load_rules)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.wifi8 import concepts as cx  # noqa: E402

LOG = "windows.jsonl"


def read_done(out: Path) -> dict[str, dict]:
    path = out / LOG
    return {r["window_id"]: r for r in (json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip())} if path.exists() else {}


def load_windows(roles: list[str], per_doc: int, max_chars: int, only: set[str], pick_frac: float = -1.0) -> tuple[list[dict], list[str], dict[str, str]]:
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchAny
    client = QdrantClient(url=os.environ["QDRANT_URL"], check_compatibility=False)
    flt = Filter(must=[FieldCondition(key="document_role", match=MatchAny(any=roles)), FieldCondition(key="analysis_eligible", match=__import__("qdrant_client.models", fromlist=["MatchValue"]).MatchValue(value=True))])
    by_doc: dict[str, list[dict]] = {}
    topics: Counter = Counter()
    off = None
    while True:
        points, off = client.scroll("wifi8_chunks", scroll_filter=flt, limit=256, offset=off, with_payload=["revision_id", "chunk_index", "content", "source_name", "doc_name", "topics", "document_role"], with_vectors=False)
        for p in points:
            by_doc.setdefault(p.payload["revision_id"], []).append(p.payload)
            topics.update(p.payload.get("topics") or [])
        if off is None:
            break
    windows = []
    titles = {}
    rules = cx.load_rules()
    skipped = Counter()
    for rid, chunks in sorted(by_doc.items()):
        if only and rid not in only:
            continue
        titles[rid] = chunks[0].get("source_name") or chunks[0].get("doc_name") or rid
        doc_windows = cx.build_windows(chunks, max_chars)
        if cx.relevance_applies(chunks[0].get("document_role"), rules):  # e.g. Research Paper: only Wi-Fi related documents and windows
            if not cx.document_relevance(titles[rid], " ".join(c.get("content") or "" for c in chunks), rules)["relevant"]:
                skipped["documents_not_relevant"] += 1
                continue
            kept = [w for w in doc_windows if cx.window_relevant(w["text"], rules)]
            skipped["windows_not_relevant"] += len(doc_windows) - len(kept)
            doc_windows = kept
            if not doc_windows:
                continue
        if pick_frac >= 0:  # one window from a chosen position of the document (skips cover/agenda pages at the start)
            doc_windows = [doc_windows[min(len(doc_windows) - 1, int(len(doc_windows) * pick_frac))]]
        windows += doc_windows[:per_doc if per_doc > 0 else None]
    if skipped:
        print(f"relevance filter skipped {dict(skipped)}", flush=True)
    return windows, [t for t, _ in topics.most_common(40)], titles


def llm_client():
    from src.main import load_config
    from src.web_api.ollama_client import _build_primary_client
    client, label = _build_primary_client(load_config())
    if client is None:
        raise SystemExit("primary LLM not configured")
    return client, label


def ask(client, prompt: str, attempts: int = 4) -> str:
    for n in range(attempts):
        try:
            return client.chat.completions.create(messages=[{"role": "user", "content": prompt}], temperature=0, max_tokens=4096).choices[0].message.content or ""
        except Exception:  # gateway 5xx / timeout
            if n == attempts - 1:
                raise
            time.sleep(10 * (n + 1))
    return ""


def cmd_extract(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    done = read_done(out)
    windows, known, _ = load_windows([r.strip() for r in a.roles.split(",") if r.strip()], a.per_doc, a.max_chars, set(a.only.split(",")) if a.only else set(), a.pick_frac)
    if a.sample and len(windows) > a.sample:  # evenly spaced, deterministic
        step = len(windows) / a.sample
        windows = [windows[int(i * step)] for i in range(a.sample)]
    if a.limit:
        windows = windows[:a.limit]
    client, label = llm_client()
    rules = cx.load_rules()
    scope = (rules.relevance.get("scope_instruction") or "") if any(cx.relevance_applies(r.strip(), rules) for r in a.roles.split(",")) else ""
    (out / "run.json").write_text(json.dumps({"model": label, "roles": a.roles, "per_doc": a.per_doc, "max_chars": a.max_chars, "windows": len(windows), "known": known, "scope": bool(scope)}, ensure_ascii=False), "utf-8")
    todo = [w for w in windows if w["window_id"] not in done]
    print(f"{len(windows)} windows, {len(done)} done, {len(todo)} to do, model {label}", flush=True)
    with (out / LOG).open("a", encoding="utf-8") as log:
        for i, w in enumerate(todo, 1):
            t0 = time.monotonic()
            raw = ask(client, cx.build_prompt(w["title"], w["text"], known, scope))
            data = cx.parse_json(raw)
            if data is None:  # one retry for malformed JSON
                raw = ask(client, cx.build_prompt(w["title"], w["text"], known, scope))
                data = cx.parse_json(raw)
            v = cx.validate(data, w["text"], rules)
            log.write(json.dumps({"window_id": w["window_id"], "revision_id": w["revision_id"], "title": w["title"], "chunk_indexes": w["chunk_indexes"], "chars": len(w["text"]),
                                  "concepts": v.concepts, "relations": v.relations, "dropped": dict(v.dropped), "raw_concepts": len((data or {}).get("concepts") or []),
                                  "raw_relations": len((data or {}).get("relations") or []), "raw": raw[:30000], "ms": round((time.monotonic() - t0) * 1000)}, ensure_ascii=False) + "\n")
            log.flush()
            print(f"[{i}/{len(todo)}] {w['window_id'][:60]} concepts={len(v.concepts)} relations={len(v.relations)} dropped={dict(v.dropped)} {round((time.monotonic() - t0))}s", flush=True)
    return 0


def cmd_revalidate(a) -> int:
    """Re-run the code checks on the stored raw model answers (no LLM calls): used after the rules change. The old log is kept."""
    out = Path(a.out)
    rules = cx.load_rules()
    windows, _, _ = load_windows([r.strip() for r in a.roles.split(",") if r.strip()], 0, a.max_chars, set())
    text = {w["window_id"]: w["text"] for w in windows}
    old = read_done(out)
    (out / LOG).rename(out / "windows.before-revalidate.jsonl")
    with (out / LOG).open("w", encoding="utf-8") as log:
        for r in old.values():
            v = cx.validate(cx.parse_json(r.get("raw", "")), text[r["window_id"]], rules)
            r.update(concepts=v.concepts, relations=v.relations, dropped=dict(v.dropped))
            log.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"revalidated {len(old)} windows")
    return 0


def cmd_relevance(a) -> int:
    """Wi-Fi vocabulary density of every document of the given roles (read-only on Qdrant); combine uses it to drop earlier records of irrelevant documents."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchAny
    rules = cx.load_rules()
    client = QdrantClient(url=os.environ["QDRANT_URL"], check_compatibility=False)
    flt = Filter(must=[FieldCondition(key="document_role", match=MatchAny(any=[r.strip() for r in a.roles.split(",") if r.strip()]))])
    texts: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    off = None
    while True:
        points, off = client.scroll("wifi8_chunks", scroll_filter=flt, limit=256, offset=off, with_payload=["revision_id", "content", "source_name"], with_vectors=False)
        for p in points:
            texts.setdefault(p.payload["revision_id"], []).append(p.payload.get("content") or "")
            titles[p.payload["revision_id"]] = p.payload.get("source_name") or ""
        if off is None:
            break
    rows = {rid: {"title": titles[rid], **cx.document_relevance(titles[rid], " ".join(t), rules)} for rid, t in texts.items()}
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "relevance.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({"documents": len(rows), "relevant": sum(1 for r in rows.values() if r["relevant"])}))
    return 0


def read_run(src: Path) -> list[dict]:
    recs = []
    for r in read_done(src).values():
        r["run"] = src.name
        recs.append(r)
    return recs


def cmd_combine(a) -> int:
    """Aggregate every run once: support counts and evidence are accumulated across runs, not overwritten by the last load."""
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    excluded: set[str] = set()
    if a.relevance:
        excluded = {rid for rid, r in json.loads(Path(a.relevance).read_text("utf-8")).items() if not r["relevant"]}
    recs, sources = [], []
    for src in map(Path, a.src):
        got = [r for r in read_run(src) if r["revision_id"] not in excluded]
        recs += got
        meta = json.loads((src / "run.json").read_text("utf-8")) if (src / "run.json").exists() else {}
        sources.append({"run": src.name, "windows": len(got), "dropped_irrelevant": len(read_done(src)) - len(got), "model": meta.get("model"), "roles": meta.get("roles")})
    rules = cx.load_rules(merges=a.merges or None)
    agg = cx.aggregate(recs, rules)
    (out / "graph-rows.json").write_text(json.dumps(agg, ensure_ascii=False), "utf-8")
    models = sorted({s["model"] for s in sources if s["model"]})
    (out / "run.json").write_text(json.dumps({"model": ",".join(models), "sources": sources, "merges": bool(a.merges), "windows": len(recs)}, ensure_ascii=False), "utf-8")
    (out / LOG).write_text("".join(json.dumps({"window_id": r["window_id"], "revision_id": r["revision_id"], "title": r["title"]}, ensure_ascii=False) + "\n" for r in recs), "utf-8")
    print(json.dumps({"sources": sources, "concepts": len(agg["concepts"]), "relations": len(agg["relations"]),
                      "cross_run_concepts": sum(1 for c in agg["concepts"] if len(c["runs"]) > 1), "cross_doc_concepts": sum(1 for c in agg["concepts"] if c["doc_count"] > 1)}, ensure_ascii=False, indent=1))
    return 0


def evidence_by_concept(out: Path, agg: dict) -> dict[str, str]:
    by_id = {c["concept_id"]: c for c in agg["concepts"]}
    ev: dict[str, str] = {}
    for r in agg["relations"]:
        for side in (r["source"], r["target"]):
            if side not in ev and r["evidence"]:
                ev[side] = f"{r['evidence'][0]['revision_id']}: {r['evidence'][0]['quote']}"
    return {cid: ev.get(cid, "（無關係證據）") for cid in by_id}


def cmd_merge_candidates(a) -> int:
    from src.wifi8 import concept_merge as cm
    out = Path(a.out)
    agg = json.loads((out / "graph-rows.json").read_text("utf-8"))
    encode = None
    if a.vectors:
        from src.vector_store import VectorStore
        store = VectorStore()
        encode = store.encode
    rules = cx.load_rules()
    cands = cm.candidates(agg["concepts"], rules, encode)
    (out / "merge-candidates.json").write_text(json.dumps(cands, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({"concepts": len(agg["concepts"]), "candidates": len(cands), "by_signal": dict(Counter(s for c in cands for s in set(c["signals"])))}))
    return 0


def cmd_merge_judge(a) -> int:
    from src.wifi8 import concept_merge as cm
    out = Path(a.out)
    agg = json.loads((out / "graph-rows.json").read_text("utf-8"))
    by_id = {c["concept_id"]: c for c in agg["concepts"]}
    ev = evidence_by_concept(out, agg)
    cands = json.loads((out / "merge-candidates.json").read_text("utf-8"))
    path = out / "merge-decisions.jsonl"
    done = {(d["a"], d["b"]) for d in (json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip())} if path.exists() else set()
    client, label = llm_client()
    todo = [c for c in cands if (c["a"], c["b"]) not in done]
    print(f"{len(cands)} candidates, {len(done)} done, {len(todo)} to do, model {label}", flush=True)
    with path.open("a", encoding="utf-8") as log:
        for i, c in enumerate(todo, 1):
            raw = ask(client, cm.judge_prompt(by_id[c["a"]], by_id[c["b"]], ev))
            dec = cm.parse_decision(raw)
            log.write(json.dumps({"a": c["a"], "b": c["b"], "a_name": by_id[c["a"]]["name"], "b_name": by_id[c["b"]]["name"], "signals": c["signals"], "score": round(c["score"], 3),
                                  "same": dec["same"] if dec else False, "canonical": dec["canonical"] if dec else "", "reason": dec["reason"] if dec else "unparseable", "model": label}, ensure_ascii=False) + "\n")
            log.flush()
            print(f"[{i}/{len(todo)}] {by_id[c['a']]['name']} | {by_id[c['b']]['name']} -> {dec['same'] if dec else 'unparseable'}", flush=True)
    return 0


def cmd_merge_apply(a) -> int:
    from src.wifi8 import concept_merge as cm
    out = Path(a.out)
    agg = json.loads((out / "graph-rows.json").read_text("utf-8"))
    by_id = {c["concept_id"]: c for c in agg["concepts"]}
    decisions = [json.loads(l) for l in (out / "merge-decisions.jsonl").read_text("utf-8").splitlines() if l.strip()]
    merges = cm.merges_file(decisions, by_id)
    (out / "merges.json").write_text(json.dumps(merges, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({"decisions": len(decisions), "approved": sum(1 for d in decisions if d["same"]), "merge_groups": len(merges)}))
    return 0


def cmd_report(a) -> int:
    out = Path(a.out)
    recs = list(read_done(out).values())
    agg = cx.aggregate(recs, cx.load_rules())
    dropped: Counter = Counter()
    for r in recs:
        dropped.update(r["dropped"])
    raw_c, raw_r = sum(r["raw_concepts"] for r in recs), sum(r["raw_relations"] for r in recs)
    kept_c, kept_r = sum(len(r["concepts"]) for r in recs), sum(len(r["relations"]) for r in recs)
    print(json.dumps({"windows": len(recs), "docs": len({r["revision_id"] for r in recs}), "raw_concepts": raw_c, "kept_concepts": kept_c, "raw_relations": raw_r, "kept_relations": kept_r,
                      "relation_keep_rate": round(kept_r / raw_r, 3) if raw_r else None, "dropped": dict(dropped), "graph_concepts": len(agg["concepts"]), "graph_relations": len(agg["relations"]),
                      "median_ms": sorted(r["ms"] for r in recs)[len(recs) // 2] if recs else None,
                      "relations_by_type": dict(Counter(r["type"] for r in agg["relations"])), "concepts_by_type": dict(Counter(c["type"] for c in agg["concepts"]))}, ensure_ascii=False, indent=1))
    (out / "graph-rows.json").write_text(json.dumps(agg, ensure_ascii=False), "utf-8")
    return 0


def cmd_load(a) -> int:
    from neo4j import GraphDatabase
    from src.wifi8 import concept_graph as cg
    out = Path(a.out)
    rows = json.loads((out / "graph-rows.json").read_text("utf-8"))
    meta = json.loads((out / "run.json").read_text("utf-8"))
    titles = {r["revision_id"]: r["title"] for r in read_done(out).values()}
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    run = {"run_id": a.run_id or time.strftime("pilot-%Y%m%dT%H%M%SZ", time.gmtime()), "model": meta["model"], "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with driver.session() as session:
        if a.wipe_run:
            session.run("MATCH (c:Wifi8Concept {run_id: $r}) DETACH DELETE c", r=a.wipe_run).consume()
        cg.init_constraints(session)
        clash = cg.foreign_overlap(session, rows, run["run_id"])
        if clash and not a.allow_overwrite:
            raise SystemExit(f"{clash} concepts already exist from another run; a second load would overwrite their support counts and evidence. Use combine to aggregate all runs, or --allow-overwrite.")
        print(json.dumps({"run": run["run_id"], **cg.write(session, rows, run, titles)}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--roles", required=True)
    e.add_argument("--per-doc", type=int, default=0, help="windows per document (0 = all)")
    e.add_argument("--max-chars", type=int, default=6000)
    e.add_argument("--limit", type=int, default=0)
    e.add_argument("--only", default="", help="comma-separated revision_ids")
    e.add_argument("--sample", type=int, default=0, help="keep N evenly spaced windows")
    e.add_argument("--pick-frac", type=float, default=-1.0, help="per document, take the window at this relative position (0-1) instead of the first ones")
    for name in ("extract", "report", "load"):
        pass
    rv = sub.add_parser("revalidate")
    rv.add_argument("--roles", required=True)
    rv.add_argument("--max-chars", type=int, default=6000)
    for p in (e, rv, sub.add_parser("report"), sub.add_parser("load")):
        p.add_argument("--out", required=True)
    l = sub.choices["load"]
    l.add_argument("--wipe-run", default="")
    l.add_argument("--run-id", default="")
    l.add_argument("--allow-overwrite", action="store_true")
    rl = sub.add_parser("relevance")
    rl.add_argument("--roles", required=True)
    rl.add_argument("--out", required=True)
    cb = sub.add_parser("combine")
    cb.add_argument("--out", required=True)
    cb.add_argument("--src", action="append", required=True)
    cb.add_argument("--relevance", default="")
    cb.add_argument("--merges", default="")
    for name in ("merge-candidates", "merge-judge", "merge-apply"):
        mp = sub.add_parser(name)
        mp.add_argument("--out", required=True)
        if name == "merge-candidates":
            mp.add_argument("--vectors", action="store_true")
    a = ap.parse_args()
    return {"extract": cmd_extract, "report": cmd_report, "load": cmd_load, "revalidate": cmd_revalidate, "relevance": cmd_relevance, "combine": cmd_combine,
            "merge-candidates": cmd_merge_candidates, "merge-judge": cmd_merge_judge, "merge-apply": cmd_merge_apply}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
