from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.web_api import wifi8_routes
from tests.test_wifi8_search import engine  # noqa: F401


def make_client(monkeypatch, engine, *, authenticated=True):  # noqa: F811
    search, importer, _ = engine
    monkeypatch.setattr(wifi8_routes, "_importer", lambda: importer)
    monkeypatch.setattr(wifi8_routes, "_search_engine", lambda importer=None: search)
    app = FastAPI()

    if authenticated:
        @app.middleware("http")
        async def identity(request: Request, call_next):
            request.state.km_identity = {"sub": "u1", "instance_id": "test"}
            return await call_next(request)

    app.include_router(wifi8_routes.router)
    return TestClient(app)


def test_overview_uses_real_import_counts(monkeypatch, engine):  # noqa: F811
    response = make_client(monkeypatch, engine).get("/api/wifi8/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["documents"] == 5
    assert body["counts"]["current_documents"] == 4
    assert body["counts"]["superseded_documents"] == 1
    assert sum(count for _, count in body["by_publisher"]) == 4
    assert sum(count for _, count in body["by_document_role"]) == 4


def test_documents_filter_history_and_pagination(monkeypatch, engine):  # noqa: F811
    client = make_client(monkeypatch, engine)
    current = client.get("/api/wifi8/documents", params={"query": "104438", "page_size": 1}).json()
    assert current["total"] == 1 and current["documents"][0]["title"] == "ELR MRD v2"
    history = client.get("/api/wifi8/documents", params={"query": "10443", "include_history": True}).json()
    assert {doc["title"] for doc in history["documents"]} == {"ELR MRD v1", "ELR MRD v2"}
    publisher = client.get("/api/wifi8/documents", params={"publisher": "Broadcom"}).json()
    assert publisher["total"] == 1
    assert publisher["documents"][0]["title"] == "BCM43840 Product Brief"
    assert client.get("/api/wifi8/documents", params={"page_size": 101}).status_code == 422


def test_document_detail_chunks_and_version_relationship(monkeypatch, engine):  # noqa: F811
    client = make_client(monkeypatch, engine)
    detail = client.get("/api/wifi8/documents/elr2")
    assert detail.status_code == 200
    assert {version["revision_id"] for version in detail.json()["versions"]} == {"elr1", "elr2"}
    chunks = client.get("/api/wifi8/documents/elr2/chunks", params={"count": 1}).json()
    assert chunks["total"] == 2 and len(chunks["chunks"]) == 1
    assert chunks["chunks"][0]["location_label"]
    assert client.get("/api/wifi8/documents/../secret").status_code == 404


def test_search_supports_short_cjk_wfa_id_and_history(monkeypatch, engine):  # noqa: F811
    client = make_client(monkeypatch, engine)
    short = client.post("/api/wifi8/search", json={"query": "漫遊", "top_k": 3}).json()
    assert short["results"][0]["source"] == "Mesh Network Design Guide"
    wfa = client.post("/api/wifi8/search", json={"query": "104438 preamble"}).json()
    assert {hit["source"] for hit in wfa["results"]} == {"ELR MRD v2"}
    current = client.post("/api/wifi8/search", json={"query": "ELR preamble"}).json()
    assert "ELR MRD v1" not in {hit["source"] for hit in current["results"]}
    history = client.post("/api/wifi8/search", json={"query": "ELR preamble", "include_history": True}).json()
    assert "ELR MRD v1" in {hit["source"] for hit in history["results"]}


def test_jobs_and_authentication(monkeypatch, engine):  # noqa: F811
    client = make_client(monkeypatch, engine)
    jobs = client.get("/api/wifi8/jobs").json()["jobs"]
    assert jobs and jobs[0]["status"] == "completed"
    anonymous = make_client(monkeypatch, engine, authenticated=False)
    assert anonymous.get("/api/wifi8/overview").status_code == 401
    assert anonymous.get("/api/wifi8/documents").status_code == 401
    assert anonymous.post("/api/wifi8/search", json={"query": "ELR"}).status_code == 401
