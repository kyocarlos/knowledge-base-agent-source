"""Write a Knowledge Package into the km_test schema (one transaction per report; re-running the same report changes nothing)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
NAMESPACE = uuid.UUID("6f1b6f2e-5a0e-4a52-9a43-1b7f3b2f6a10")
DIMS = ("direction", "band", "bandwidth_mhz", "channel", "attenuation_db", "angle_deg", "traffic_mode", "protocol", "statistic", "sample_index", "value_basis")
POLICY = {"source_system": "ManualUpload", "approval_status": "approved", "approval_basis": "assumed_manual", "publish_status": "published",
          "visibility": "internal", "owner_department": "CSIT", "access_roles": ["CSIT_ENGINEER", "CSIT_MANAGER"], "access_departments": ["CSIT"]}
# The access and approval values are assumptions (WiFi report data carries none): replace with CSIT values when they exist.


class ConflictError(RuntimeError):
    pass


def ddl() -> str:
    return (HERE / "schema.sql").read_text(encoding="utf-8")


def load_dictionary() -> list[dict]:
    return json.loads((HERE / "metric_dictionary.json").read_text(encoding="utf-8"))["metrics"]


def _uid(*parts: Any) -> str:
    return str(uuid.uuid5(NAMESPACE, "|".join("" if p is None else str(p) for p in parts)))


def validate(pkg: dict, allowed_metrics: set[tuple[str, str]]) -> list[str]:
    errors = []
    for key in ("document_id", "document_version", "report_type"):
        if not pkg["document"].get(key):
            errors.append(f"document.{key} missing")
    for key in ("test_run_id", "product_id", "dut_model"):
        if not pkg["test_run"].get(key):
            errors.append(f"test_run.{key} missing")
    for m in pkg["measurements"]:
        if (m["metric_name"], m["unit"]) not in allowed_metrics:
            errors.append(f"metric not in dictionary or unit mismatch: {m['metric_name']} {m['unit']} ({m['source_sheet']}!{m['source_cell_range']})")
            break
    return errors


def write_package(conn, pkg: dict, *, accept_source_errors: bool, replace: bool = False, policy: dict | None = None) -> dict:
    """Returns counts; raises ConflictError when the same document and version already exist with other content."""
    doc, run = pkg["document"], pkg["test_run"]
    policy = policy or pkg.get("policy") or POLICY
    errors = pkg["quality"]["formula_errors"]
    if errors and not accept_source_errors:
        raise ConflictError(f"{len(errors)} formula error cells; fix the report or accept source errors explicitly")
    content_hash = pkg["source"]["checksum"]
    with conn.transaction():
        conn.execute(ddl())
        for m in load_dictionary():
            conn.execute("""INSERT INTO km_test.metric_dictionary (metric_name, unit, kind, description) VALUES (%s,%s,%s,%s)
                            ON CONFLICT (metric_name) DO UPDATE SET unit = EXCLUDED.unit, kind = EXCLUDED.kind, description = EXCLUDED.description""",
                         (m["metric_name"], m["unit"], m["kind"], m.get("description")))
        allowed = {(r[0], r[1]) for r in conn.execute("SELECT metric_name, unit FROM km_test.metric_dictionary").fetchall()}
        problems = validate(pkg, allowed)
        if problems:
            raise ConflictError("; ".join(problems))
        existing = conn.execute("SELECT content_hash, csit_id FROM km_test.test_run WHERE document_id = %s AND document_version = %s",
                                (doc["document_id"], doc["document_version"])).fetchone()
        if existing and existing[0] == content_hash:
            return {"status": "unchanged"}
        # A newer upload of the same CSIT document supersedes it; any other content under the same number and version is a conflict.
        if existing and run.get("csit_id") and existing[1] == run["csit_id"]:
            replace = True
        if existing and not replace:
            raise ConflictError("same document and version with different content; raise the report version or pass replace")
        if existing:
            conn.execute("DELETE FROM km_test.test_run WHERE document_id = %s AND document_version = %s", (doc["document_id"], doc["document_version"]))
        conn.execute("""INSERT INTO km_test.test_run (test_run_id, id_basis, report_id, document_id, document_version, report_revision, report_type, technology,
            product_id, product_id_basis, dut_model, npi_stage, firmware_id, firmware_version, hardware_version, chipset_vendor, ethernet_type, test_date,
            overall_result, source_system, approval_status, approval_basis, publish_status, visibility, owner_department, access_roles, access_departments,
            quality_status, formula_error_count, package_id, schema_version, content_hash, csit_id, source_record_id, project_id)
            VALUES (%(test_run_id)s,%(id_basis)s,%(document_id)s,%(document_id)s,%(document_version)s,%(report_revision)s,%(report_type)s,%(technology)s,
            %(product_id)s,%(product_id_basis)s,%(dut_model)s,%(npi_stage)s,%(firmware_id)s,%(firmware_version)s,%(hardware_version)s,%(chipset_vendor)s,%(ethernet_type)s,%(test_date)s,
            %(overall_result)s,%(source_system)s,%(approval_status)s,%(approval_basis)s,%(publish_status)s,%(visibility)s,%(owner_department)s,%(access_roles)s,%(access_departments)s,
            %(quality_status)s,%(formula_error_count)s,%(package_id)s,%(schema_version)s,%(content_hash)s,%(csit_id)s,%(source_record_id)s,%(project_id)s)""",
                     {"csit_id": None, "source_record_id": None, "project_id": None, **run, **doc, **policy, "quality_status": "source_errors_accepted" if errors else "clean",
                      "formula_error_count": len(errors), "package_id": pkg["package_id"], "schema_version": pkg["schema_version"], "content_hash": content_hash})
        rid = run["test_run_id"]
        with conn.cursor() as cur:
            cur.executemany("""INSERT INTO km_test.test_measurement (measurement_id, test_run_id, test_case_id, test_case_name, metric_name, value, unit, value_basis, band,
                bandwidth_mhz, channel, center_freq_mhz, direction, direction_source_label, attenuation_db, angle_deg, traffic_mode, protocol, statistic, sample_index,
                time_slot, wireless_mode, source_sheet, source_cell_range)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            [(_uid(rid, m["test_case_id"], m["metric_name"], *[m.get(d) for d in DIMS]), rid, m["test_case_id"], m.get("test_case_name"), m["metric_name"], m["value"], m["unit"],
                              m["value_basis"], m.get("band"), m.get("bandwidth_mhz"), m.get("channel"), m.get("center_freq_mhz"), m.get("direction"), m.get("direction_source_label"),
                              m.get("attenuation_db"), m.get("angle_deg"), m.get("traffic_mode"), m.get("protocol"), m.get("statistic"), m.get("sample_index"), m.get("time_slot"),
                              m.get("wireless_mode"), m["source_sheet"], m["source_cell_range"]) for m in pkg["measurements"]])
            cur.executemany("""INSERT INTO km_test.test_item_result (result_id, test_run_id, test_case_id, item_label, band, bandwidth_mhz, channel, criteria_value, criteria_unit,
                criteria_basis, result, result_basis, source_sheet, source_cell_range) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (test_run_id, test_case_id, item_label) DO NOTHING""",
                            [(_uid(rid, r["test_case_id"], r["item_label"]), rid, r["test_case_id"], r["item_label"], r.get("band"), r.get("bandwidth_mhz"), r.get("channel"),
                              r.get("criteria_value"), r.get("criteria_unit"), r.get("criteria_basis"), r["result"], r["result_basis"], r["source_sheet"], r["source_cell_range"])
                             for r in pkg["results"]])
            cur.executemany("""INSERT INTO km_test.criteria_reference (criteria_id, test_run_id, band, bandwidth_mhz, spatial_stream, wireless_mode, attenuation_range,
                reference_rate_mbps, criteria_value, criteria_unit, criteria_basis, source_sheet, source_cell_range) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            [(_uid(rid, c["source_cell_range"], c.get("attenuation_range")), rid, c.get("band"), c.get("bandwidth_mhz"), c.get("spatial_stream"), c.get("wireless_mode"),
                              c.get("attenuation_range"), c.get("reference_rate_mbps"), c.get("criteria_value"), c.get("criteria_unit"), c.get("criteria_basis"), c["source_sheet"],
                              c["source_cell_range"]) for c in pkg["criteria"]])
            cur.executemany("""INSERT INTO km_test.test_condition (condition_id, test_run_id, name, value, text_value, unit, band, bandwidth_mhz, source_sheet, source_cell_range)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            [(_uid(rid, c["name"], c.get("band"), c.get("bandwidth_mhz")), rid, c["name"], c.get("value"), c.get("text"), c.get("unit"), c.get("band"),
                              c.get("bandwidth_mhz"), c["source_sheet"], c["source_cell_range"]) for c in pkg["conditions"]])
        conn.execute("DELETE FROM km_test.report_package WHERE document_id = %s AND document_version = %s", (doc["document_id"], doc["document_version"]))
        conn.execute("INSERT INTO km_test.report_package (package_id, document_id, document_version, test_run_id, content_hash, quality) VALUES (%s,%s,%s,%s,%s,%s)",
                     (pkg["package_id"], doc["document_id"], doc["document_version"], rid, content_hash, json.dumps(pkg["quality"], ensure_ascii=False)))
    return {"status": "written", "measurements": len(pkg["measurements"]), "results": len(pkg["results"]), "criteria": len(pkg["criteria"]), "conditions": len(pkg["conditions"])}
