from __future__ import annotations

import ast
import re
from pathlib import Path

from src import ui_upload_tracking


ROOT = Path(__file__).resolve().parents[1]
DDL = re.compile(r"\b(?:CREATE\s+(?:TABLE|SCHEMA|INDEX)|ALTER\s+TABLE|DROP\s+(?:TABLE|SCHEMA|INDEX)|create_hypertable)\b", re.I)


class RecordingCursor:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def executemany(self, sql, params):
        self.statements.append((sql, params))


class RecordingConnection:
    def __init__(self):
        self.cursor_instance = RecordingCursor()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.cursor_instance


def _sql_strings(path):
    tree = ast.parse(path.read_text())
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_timescale_runtime_modules_have_no_schema_provisioning():
    for relative in ("src/ui_upload_tracking.py", "src/csit_integration_v1/writers.py"):
        sql_strings = _sql_strings(ROOT / relative)
        assert not any(DDL.search(value) for value in sql_strings), relative


def test_web_upload_and_ingest_report_use_dml_only(monkeypatch):
    connection = RecordingConnection()
    monkeypatch.setattr(ui_upload_tracking, "_connect", lambda: connection)
    ui_upload_tracking.record_upload(
        task_id="rotation-fixture",
        data_zone="da40",
        file_name="fixture.pdf",
        file_hash="a" * 64,
        extraction_mode="canonical",
        status="queued",
        report={
            "manifest": {"run_id": "run-fixture", "started_at": "2026-10-15T00:00:00Z"},
            "measurements": [{"case_id": "case-1", "metric": "throughput", "value": 1.0, "unit": "Mbps"}],
        },
    )
    statements = connection.cursor_instance.statements
    assert len(statements) == 2
    assert "INSERT INTO public.km_ui_uploads" in statements[0][0]
    assert "ON CONFLICT(task_id) DO UPDATE" in statements[0][0]
    assert "INSERT INTO public.km_ui_report_measurements" in statements[1][0]
    assert "ON CONFLICT(data_zone,run_id,case_id,metric,sample_index) DO UPDATE" in statements[1][0]
    assert not any(DDL.search(sql) for sql, _ in statements)


def test_upload_status_update_uses_dml_only(monkeypatch):
    connection = RecordingConnection()
    monkeypatch.setattr(ui_upload_tracking, "_connect", lambda: connection)
    ui_upload_tracking.update_upload_status({"ui_session_upload": True, "task_id": "rotation-fixture"}, "failed")
    assert len(connection.cursor_instance.statements) == 1
    assert "UPDATE public.km_ui_uploads" in connection.cursor_instance.statements[0][0]
    assert not DDL.search(connection.cursor_instance.statements[0][0])


def test_management_migration_is_idempotent_and_nondestructive():
    sql = (ROOT / "migrations/20261015_km_ui_upload_tracking.sql").read_text()
    assert sql.count("CREATE TABLE IF NOT EXISTS public.") == 2
    assert "BEGIN;" in sql and "COMMIT;" in sql
    assert not re.search(r"\b(?:DROP|TRUNCATE|ALTER|DELETE)\b", sql, re.I)
