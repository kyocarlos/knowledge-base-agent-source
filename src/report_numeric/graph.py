"""Neo4j projection of a Knowledge Package using only the KM v2.6 Phase 1 ontology: Product, Firmware, TestCase, TestRun, TestResult, Report,
Document. MERGE keyed by formal ids, every relationship carries its source and evidence. Numbers stay in km_test (``numeric_ref``)."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

CONSTRAINTS = (
    "CREATE CONSTRAINT product_id IF NOT EXISTS FOR (n:Product) REQUIRE n.product_id IS UNIQUE",
    "CREATE CONSTRAINT firmware_id IF NOT EXISTS FOR (n:Firmware) REQUIRE n.firmware_id IS UNIQUE",
    "CREATE CONSTRAINT test_case_id IF NOT EXISTS FOR (n:TestCase) REQUIRE n.test_case_id IS UNIQUE",
    "CREATE CONSTRAINT test_run_id IF NOT EXISTS FOR (n:TestRun) REQUIRE n.test_run_id IS UNIQUE",
    "CREATE CONSTRAINT result_id IF NOT EXISTS FOR (n:TestResult) REQUIRE n.result_id IS UNIQUE",
    "CREATE CONSTRAINT report_id IF NOT EXISTS FOR (n:Report) REQUIRE n.report_id IS UNIQUE",
    "CREATE CONSTRAINT document_key IF NOT EXISTS FOR (n:Document) REQUIRE (n.document_id, n.document_version) IS UNIQUE",
)


def _case_meta(case_id: str) -> dict:
    kind, _, rest = case_id.partition(":")
    parts = rest.split(":")
    return {"category": kind, "band": parts[0] if parts else None, "name": case_id}


def _evidence(doc: dict, sheet: str, kind: str) -> dict:
    return {"source_type": "document", "source_document_id": doc["document_id"], "source_document_version": doc["document_version"], "source_section_id": sheet,
            "evidence_type": kind, "confidence": None, "review_status": "approved"}


def write_graph(session, pkg: dict) -> dict:
    for stmt in CONSTRAINTS:
        session.run(stmt)
    doc, run = pkg["document"], pkg["test_run"]
    rid, pid, fid = run["test_run_id"], run["product_id"], run.get("firmware_id")
    ref = f"km_test.test_run/{rid}"
    pol = pkg.get("policy") or {}
    ss, ab, idb = pol.get("source_system", "ManualUpload"), pol.get("approval_basis", "assumed_manual"), run.get("id_basis", "derived")
    src = {"source_system": ss, "created_from_package_id": pkg["package_id"], "schema_version": pkg["schema_version"]}
    cases = sorted({m["test_case_id"] for m in pkg["measurements"]} | {r["test_case_id"] for r in pkg["results"]})
    tally: dict[str, Counter] = defaultdict(Counter)
    for r in pkg["results"]:
        tally[r["test_case_id"]][r["result"]] += 1
    results = []
    for cid in cases:
        t = tally.get(cid)
        if t:
            verdict = "mixed" if t["fail"] and t["pass"] else "fail" if t["fail"] else "pass" if t["pass"] else "n/a"
            results.append({"result_id": f"{rid}::{cid}", "test_case_id": cid, "result": verdict, "pass_items": t["pass"], "fail_items": t["fail"], "na_items": t["n/a"]})
    sheet = pkg["measurements"][0]["source_sheet"] if pkg["measurements"] else "Cover"
    session.run("""
        MERGE (p:Product {product_id: $pid}) SET p.name = $model, p.product_type = $ptype, p.source_system = $ss, p.created_from_package_id = $pkg
        MERGE (d:Document {document_id: $did, document_version: $ver})
          SET d.title = $title, d.document_type = 'test_report', d.source_system = $ss, d.source_record_id = $did, d.publish_status = 'published', d.is_current = true,
              d.source_sha256 = $sha, d.created_from_package_id = $pkg, d.schema_version = $sv
        MERGE (rep:Report {report_id: $did}) SET rep.version = $ver, rep.approval_status = 'approved', rep.approval_basis = $ab, rep.source_system = $ss
        MERGE (tr:TestRun {test_run_id: $rid}) SET tr.id_basis = $idb, tr.test_date = $date, tr.overall_result = $overall, tr.source_system = $ss, tr.numeric_ref = $ref,
              tr.report_type = $rtype, tr.created_from_package_id = $pkg
        MERGE (tr)-[x:DOCUMENTED_IN]->(rep) SET x += $ev
        MERGE (rep)-[y:SOURCE_FROM]->(d) SET y += $ev
        """, pid=pid, model=run["dut_model"], ptype="Small Cell" if doc["technology"] == "NR" else "WiFi AP", ss=ss, ab=ab, idb=idb, pkg=pkg["package_id"], did=doc["document_id"],
                ver=doc["document_version"], title=doc["title"], sha=pkg["source"]["checksum"], sv=pkg["schema_version"], rid=rid, date=run.get("test_date"),
                overall=run.get("overall_result"), ref=ref, rtype=doc["report_type"], ev=_evidence(doc, "Cover", "explicit"))
    if fid:
        session.run("""MATCH (p:Product {product_id: $pid}), (tr:TestRun {test_run_id: $rid})
            MERGE (f:Firmware {firmware_id: $fid}) SET f.version = $ver, f.product_id = $pid, f.source_system = $ss
            MERGE (p)-[a:HAS_FIRMWARE]->(f) SET a += $ev
            MERGE (f)-[b:USED_IN]->(tr) SET b += $ev""", pid=pid, rid=rid, fid=fid, ver=run["firmware_version"], ss=ss, ev=_evidence(doc, "2. Introduction", "explicit"))
    session.run("""UNWIND $cases AS c
        MATCH (p:Product {product_id: $pid}), (tr:TestRun {test_run_id: $rid})
        MERGE (tc:TestCase {test_case_id: c.id}) SET tc.name = c.name, tc.category = c.category, tc.technology = $tech, tc.source_system = $ss
        MERGE (p)-[a:HAS_TEST_CASE]->(tc) SET a += $ev
        MERGE (tc)-[b:EXECUTED_IN]->(tr) SET b += $ev""", cases=[{"id": c, "name": c, "category": _case_meta(c)["category"]} for c in cases], pid=pid, rid=rid,
                tech=doc["technology"], ss=ss, ev=_evidence(doc, sheet, "derived"))
    if results:
        session.run("""UNWIND $rows AS r MATCH (tr:TestRun {test_run_id: $rid})
            MERGE (x:TestResult {result_id: r.result_id}) SET x.test_case_id = r.test_case_id, x.result = r.result, x.pass_items = r.pass_items, x.fail_items = r.fail_items,
                x.na_items = r.na_items, x.numeric_ref = $ref, x.source_system = $ss
            MERGE (tr)-[h:HAS_RESULT]->(x) SET h += $ev""", rows=results, rid=rid, ref=ref, ss=ss, ev=_evidence(doc, "3. Test Result Summary", "explicit"))
    return {"product": pid, "firmware": fid, "test_cases": len(cases), "test_results": len(results)}
