import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.web_api import csit_assistant_routes, csit_assistants as assistants

CATALOGUE = {"assistants": [{
    "id": "report_query", "name": "報告查詢助手", "purpose": "查報告", "engine": "report_query", "examples": ["問題一"],
    "requires": [
        {"id": "numeric_store", "label": "數值資料庫", "type": "postgres_table", "dsn_env": "KM_TEST_NUMERIC_URL", "table": "km_test.test_run", "min_rows": 1},
        {"id": "query_engine", "label": "查詢引擎", "type": "engine_flag"}]}]}


def make_client(monkeypatch, tmp_path, *, authenticated=True, catalogue=CATALOGUE):
    file = tmp_path / "assistants.json"
    file.write_text(json.dumps(catalogue), encoding="utf-8")
    monkeypatch.setenv(assistants.REGISTRY_ENV, str(file))
    monkeypatch.delenv("KM_TEST_NUMERIC_URL", raising=False)
    assistants._cache.clear()
    app = FastAPI()
    if authenticated:
        @app.middleware("http")
        async def identity(request: Request, call_next):
            request.state.km_identity = {"sub": "u1", "instance_id": "test"}
            return await call_next(request)
    app.include_router(csit_assistant_routes.router)
    return TestClient(app)


def test_requires_a_km_login(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, authenticated=False)
    assert client.get("/api/csit-assistants").status_code == 401
    assert client.post("/api/csit-assistants/report_query/query", json={"question": "x"}).status_code == 401


def test_lists_the_assistant_as_pending_with_the_reason_for_each_requirement(monkeypatch, tmp_path):
    body = make_client(monkeypatch, tmp_path).get("/api/csit-assistants").json()
    item = body["assistants"][0]
    assert item["id"] == "report_query" and item["name"] == "報告查詢助手" and item["status"] == "pending_data"
    reasons = {r["id"]: r["reason"] for r in item["requirements"]}
    assert reasons == {"numeric_store": "not_configured", "query_engine": "not_implemented"}
    assert "KM_TEST_NUMERIC_URL" not in json.dumps(body)  # connection settings never reach the browser


def test_a_pending_assistant_names_what_is_missing_and_gives_no_numbers(monkeypatch, tmp_path):
    response = make_client(monkeypatch, tmp_path).post("/api/csit-assistants/report_query/query", json={"question": "5GHz 上行吞吐量？"})
    body = response.json()
    assert response.status_code == 200 and body["status"] == "pending_data"
    assert "尚未設定連線" in body["answer"] and "尚未實作" in body["answer"] and "問題一" in body["answer"]
    assert not any(ch.isdigit() for ch in body["answer"].split("可以這樣問")[0])  # no invented figures before the examples


def test_unknown_assistant_and_bad_input(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    assert client.post("/api/csit-assistants/nope/query", json={"question": "x"}).status_code == 404
    assert client.post("/api/csit-assistants/report_query/query", json={"question": ""}).status_code == 422
    assert client.post("/api/csit-assistants/report_query/query", json={"question": "x" * 2001}).status_code == 422


def test_a_broken_catalogue_means_no_assistants_not_an_error(monkeypatch, tmp_path):
    file = tmp_path / "broken.json"
    file.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(assistants.REGISTRY_ENV, str(file))
    assert assistants.load_registry() == []
    assert make_client(monkeypatch, tmp_path, catalogue={"assistants": [{"id": "Bad Id"}]}).get("/api/csit-assistants").json() == {"assistants": []}


def test_the_table_probe_reports_unreachable_no_rows_and_ok(monkeypatch):
    requirement = CATALOGUE["assistants"][0]["requires"][0]
    monkeypatch.setenv("KM_TEST_NUMERIC_URL", "postgresql://secret-user:secret-pass@db/x")

    def boom(dsn, table):
        raise RuntimeError("connection to secret-pass failed")
    monkeypatch.setattr(assistants, "_count_rows", boom)
    result = assistants.probe(requirement)
    assert result["reason"] == "unreachable" and "secret" not in json.dumps(result)  # only the class is logged, no detail returned
    monkeypatch.setattr(assistants, "_count_rows", lambda dsn, table: 0)
    assert assistants.probe(requirement)["reason"] == "no_rows"
    monkeypatch.setattr(assistants, "_count_rows", lambda dsn, table: 3)
    assert assistants.probe(requirement) == {"id": "numeric_store", "label": "數值資料庫", "ok": True, "reason": "ok"}


def test_a_table_name_that_is_not_an_identifier_is_refused_before_any_query(monkeypatch):
    monkeypatch.setenv("KM_TEST_NUMERIC_URL", "postgresql://x")
    monkeypatch.setattr(assistants, "_count_rows", lambda dsn, table: (_ for _ in ()).throw(AssertionError("must not query")))
    bad = {"id": "t", "label": "t", "type": "postgres_table", "dsn_env": "KM_TEST_NUMERIC_URL", "table": "km_test.test_run; DROP TABLE x"}
    assert assistants.probe(bad)["reason"] == "invalid_table"


def test_ready_needs_every_requirement_including_the_engine(monkeypatch):
    monkeypatch.setenv("KM_TEST_NUMERIC_URL", "postgresql://x")
    monkeypatch.setattr(assistants, "_count_rows", lambda dsn, table: 5)
    assistants._cache.clear()
    assistant = CATALOGUE["assistants"][0]
    assert assistants.readiness(assistant, use_cache=False)["status"] == "pending_data"  # data present, engine still missing
    monkeypatch.setattr(assistants, "ENGINES_IMPLEMENTED", frozenset({"report_query"}))
    assert assistants.readiness(assistant, use_cache=False)["status"] == "ready"


def test_the_shipped_catalogue_is_valid():
    items = assistants.load_registry(assistants.DEFAULT_REGISTRY)
    assert [item["id"] for item in items] == ["report_query"]
    assert all(r["type"] in {"postgres_table", "engine_flag"} for item in items for r in item["requires"])
