#!/usr/bin/env python3
"""Run the equipment synthesis on a fixture or on stored KM DEV job results (read-only) and print the result as JSON.

  --fixture FILE                 a JSON file with {"manifest": {...}, "metadata": [...]} (see tests/fixtures/equipment_three_documents.json)
  --from-jobs KM-ING-000021,...  build a KM-made TEST manifest from Completed rows of km_csit_v2_jobs (read-only; needs KM_CSIT_DB_URL).
                                 The manifest is labelled as a test: KM does not decide which documents belong to a CSIT equipment item.

Nothing is written to any database, to CSIT, to Qdrant or to Neo4j.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.csit_integration_v1 import equipment_synthesis as es  # noqa: E402


def from_fixture(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    metadata = [es.DocumentMetadata(m["documentId"], m["version"], m["sha256"], m["sourceType"], m["sourceEntityId"], m["kmJobId"], m["result"]) for m in data["metadata"]]
    source = es.JobRowsSource([])
    source._by_key = {(m.documentId, m.version): m for m in metadata}
    return es.EquipmentManifest.model_validate(data["manifest"]), source


def from_jobs(job_ids, equipment_id):
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(os.environ["KM_CSIT_DB_URL"], row_factory=dict_row) as conn:
        conn.read_only = True
        rows = conn.execute("SELECT * FROM km_csit_v2_jobs WHERE km_job_id = ANY(%s) ORDER BY km_job_id", (job_ids,)).fetchall()
    if len(rows) != len(job_ids):
        sys.exit("unknown job ids: " + ", ".join(sorted(set(job_ids) - {r["km_job_id"] for r in rows})))
    documents = [{"documentId": str(r["document_id"]), "version": r["version"], "sha256": r["expected_sha256"], "sourceType": r["source_type"],
                  "sourceEntityId": str(r["source_entity_id"]), "fileName": r["original_file_name"]} for r in rows]
    manifest = es.EquipmentManifest.model_validate({"schemaVersion": "1.0", "equipmentId": equipment_id, "manifestHash": "km-test-manifest-" + "-".join(job_ids)[:60],
                                                    "manifestRevision": 1, "generatedAt": datetime.now(timezone.utc).isoformat(), "documents": documents})
    return manifest, es.JobRowsSource(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture")
    ap.add_argument("--from-jobs")
    ap.add_argument("--equipment-id", default="KM-TEST-EQUIPMENT")
    args = ap.parse_args()
    if bool(args.fixture) == bool(args.from_jobs):
        ap.error("give exactly one of --fixture / --from-jobs")
    manifest, source = from_fixture(args.fixture) if args.fixture else from_jobs(args.from_jobs.split(","), args.equipment_id)
    outcome = es.EquipmentSynthesizer(source, es.EquipmentSynthesisStore()).analyze(manifest)
    print(json.dumps(outcome.result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
