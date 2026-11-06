"""The CSIT names of a report's project, case and task travel with it into the numeric store."""
from src.csit_integration_v1.report_adapter import ReportAdapter
from src.report_numeric import timescale
from tests.csit_v1.test_handover_template import NAME, build

JOB = {"file_name": NAME, "request_payload": {"documentId": "d-1", "version": 1, "project": {"id": "p-id", "number": "PRJ-001", "name": "模擬專案"},
                                               "case": {"id": "c-id", "number": "CASE-001", "name": "模擬測試案例"}, "task": {"id": "t-id", "number": "TASK-001", "name": "模擬測試任務"}}}


def test_the_names_reach_the_test_run(tmp_path):
    f = tmp_path / "upload.xlsx"
    build(f)
    run = ReportAdapter(None, None, None).parse(f, JOB)["test_run"]
    assert (run["project_id"], run["project_name"]) == ("PRJ-001", "模擬專案")
    assert (run["case_code"], run["case_name"]) == ("CASE-001", "模擬測試案例")
    assert (run["task_code"], run["task_name"]) == ("TASK-001", "模擬測試任務")


def test_a_notification_without_names_still_parses(tmp_path):
    f = tmp_path / "upload.xlsx"
    build(f)
    job = {"file_name": NAME, "request_payload": {"documentId": "d-1", "version": 1, "project": {"number": "PRJ-001"}}}
    run = ReportAdapter(None, None, None).parse(f, job)["test_run"]
    assert run["project_id"] == "PRJ-001" and run["project_name"] is None and run["case_name"] is None


def test_the_store_creates_and_fills_the_columns():
    ddl = timescale.ddl()
    assert "ADD COLUMN IF NOT EXISTS project_name text" in ddl and "task_name text" in ddl and ddl.index("CREATE TABLE IF NOT EXISTS km_test.test_run") < ddl.index("ADD COLUMN IF NOT EXISTS project_name")
    import inspect
    source = inspect.getsource(timescale.write_package)
    for column in ("project_name", "case_code", "case_name", "task_code", "task_name"):
        assert f"%({column})s" in source
