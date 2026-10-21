import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from src.wifi8 import lexical, store
from src.wifi8.chunks import build_chunks
from src.wifi8.importer import ImportConflict, Wifi8Importer, Wifi8Settings
from src.wifi8.package import PackageError, read_package


def make_package(path: Path, documents, segments, *, schema="km.wifi8-package.v1"):
    members = {
        "documents.jsonl": "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in documents).encode(),
        "segments.jsonl": "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in segments).encode(),
    }
    files = {n: {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for n, b in members.items()}
    content = hashlib.sha256(b"".join(files[n]["sha256"].encode() for n in sorted(files))).hexdigest()
    manifest = {"schema": schema, "package_id": f"wifi8-{content[:16]}", "content_sha256": content,
                "files": files, "counts": {"documents": len(documents)}, "source": {"repository_name": "fixture"}}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in members.items():
            archive.writestr(name, data)
    return manifest["package_id"]


def doc(rid, title, eligible=True, **extra):
    return {"revision_id": rid, "title": title, "analysis_eligible": eligible, "source_sha256": rid * 4,
            "text_status": "indexed", "wfa_document_id": "100", "document_role": "MRD", "publisher": "WFA",
            "topics": ["ELR"], "supersedes": [], **extra}


def seg(rid, n, text, loc=None):
    return {"segment_id": f"{rid}:{n}", "revision_id": rid, "ordinal": n, "kind": "text",
            "location": loc or {"type": "page", "page": n}, "text": text}


BASE_DOCS = [doc("new", "ELR Spec v2", supersedes=["old"]), doc("old", "ELR Spec v1", eligible=False)]
BASE_SEGS = [seg("new", 1, "Extended Long Range improves uplink."), seg("new", 2, "ELR uses a new preamble."),
             seg("old", 1, "Draft ELR text.")]


class FakeEncoder:
    def __init__(self, fail_after=None):
        self.calls = 0
        self.texts = 0
        self.fail_after = fail_after

    def __call__(self, texts):
        self.calls += 1
        if self.fail_after is not None and self.texts >= self.fail_after:
            raise RuntimeError("embedding service down")
        self.texts += sum(1 for t in texts if t != "dimension probe")  # count real chunks only
        return [[(hashlib.sha256(t.encode()).digest()[i] / 255.0) + 0.01 for i in range(8)] for t in texts]


@pytest.fixture
def env(tmp_path):
    client = QdrantClient(":memory:")
    settings = Wifi8Settings(root=tmp_path / "wifi8", collection="wifi8_test", embed_batch_size=2)
    return tmp_path, client, settings


def run(importer, job):
    for _ in range(100):
        job = importer.step(job["job_id"])
        if job["status"] in {"completed", "failed"}:
            return job
    raise AssertionError("import did not finish")


def test_package_verification_rejects_tampering(tmp_path):
    path = tmp_path / "p.zip"
    make_package(path, BASE_DOCS, BASE_SEGS)
    assert read_package(path, max_uncompressed_bytes=10**7).package_id.startswith("wifi8-")
    tampered = tmp_path / "t.zip"
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tampered, "w") as dst:
        for item in src.infolist():
            data = src.read(item)
            dst.writestr(item, data.replace(b"uplink", b"UPLINK") if item.filename == "segments.jsonl" else data)
    with pytest.raises(PackageError, match="checksum"):
        read_package(tampered, max_uncompressed_bytes=10**7)
    make_package(tmp_path / "s.zip", BASE_DOCS, BASE_SEGS, schema="other")
    with pytest.raises(PackageError, match="schema"):
        read_package(tmp_path / "s.zip", max_uncompressed_bytes=10**7)
    make_package(tmp_path / "u.zip", BASE_DOCS, BASE_SEGS + [seg("ghost", 1, "x")])
    with pytest.raises(PackageError, match="unknown revision_id"):
        read_package(tmp_path / "u.zip", max_uncompressed_bytes=10**7)
    with pytest.raises(PackageError, match="size limit"):
        read_package(path, max_uncompressed_bytes=10)


def test_chunks_keep_all_text_and_title():
    segments = [seg("new", i, f"短句{i}", {"type": "paragraph", "paragraph": i}) for i in range(1, 30)]
    segments.append(seg("new", 30, "x" * 3000, {"type": "page", "page": 9}))
    chunks = build_chunks(BASE_DOCS, segments, max_chars=50)
    joined = "\n".join(c["text"] for c in chunks)
    for s in segments:
        assert s["text"] in joined  # nothing dropped, including the oversized segment
    assert len(chunks) < len(segments)  # short segments were merged
    assert all(c["embed_text"].startswith("ELR Spec v2\n") for c in chunks)
    again = build_chunks(BASE_DOCS, segments, max_chars=50)
    assert [c["point_id"] for c in chunks] == [c["point_id"] for c in again]
    dup = build_chunks(BASE_DOCS, [seg("new", 1, "same", {"type": "page", "page": 1}),
                                   seg("new", 2, "same", {"type": "page", "page": 2})], max_chars=50)
    assert len({c["point_id"] for c in dup}) == 2


def test_full_import_and_incremental_reuse(env):
    tmp_path, client, settings = env
    encoder = FakeEncoder()
    importer = Wifi8Importer(settings, qdrant=client, encoder=encoder, embedding_model="fake")
    first = tmp_path / "first.zip"
    first_id = make_package(first, BASE_DOCS, BASE_SEGS)
    job = run(importer, importer.submit(first, submitted_by="tester"))
    assert job["status"] == "completed", job
    assert importer.current()["package_id"] == first_id
    assert client.count("wifi8_test", exact=True).count == job["progress"]["chunks"] > 0
    point = client.scroll("wifi8_test", limit=1, with_payload=True)[0][0].payload
    assert point["storage_category"] == "WiFi" and point["source_system"] == "WIFI8"
    assert point["packages"] == [first_id] and "location_label" in point
    assert not (settings.root / "import.lock").exists()

    # Same package again: no new work.
    again = importer.submit(first, submitted_by="tester")
    assert again["status"] == "completed"

    # The same package over a pre-Qdrant current.json (SQLite era) is imported again, not skipped.
    current = importer.current()
    (settings.root / "current.json").write_text(json.dumps({k: v for k, v in current.items() if k != "documents_collection"}))
    assert importer.current_store() is None
    assert run(importer, importer.submit(first, submitted_by="tester"))["status"] == "completed"
    assert importer.current_store() is not None and importer.current_store().counts()["documents"] == 2

    # Changed package: one document removed, one new; unchanged vectors are reused.
    texts_before = encoder.texts
    second = tmp_path / "second.zip"
    second_docs = [BASE_DOCS[0], doc("extra", "Co-SR Brief")]
    second_segs = [s for s in BASE_SEGS if s["revision_id"] == "new"] + [seg("extra", 1, "Coordinated spatial reuse.")]
    second_id = make_package(second, second_docs, second_segs)
    job2 = importer.submit(second, submitted_by="tester")
    job2 = importer.step(job2["job_id"])  # stage only
    assert importer.current()["package_id"] == first_id  # old package keeps serving mid-import
    job2 = run(importer, job2)
    assert job2["status"] == "completed"
    assert importer.current()["package_id"] == second_id
    assert importer.current()["previous_package_id"] == first_id
    assert encoder.texts - texts_before == 1  # only the new document's chunk was embedded
    assert job2["progress"]["vectors_reused"] >= 1
    ids = {p.payload["revision_id"] for p in client.scroll("wifi8_test", limit=100, with_payload=True)[0]}
    assert ids == {"new", "extra"}
    assert all(second_id in p.payload["packages"] for p in client.scroll("wifi8_test", limit=100, with_payload=True)[0])
    assert importer.current_store().counts()["documents"] == 2
    # Documents of the previous package are gone; only the serving package record remains.
    kinds = [p.payload["package_id"] for p in client.scroll("wifi8_documents", limit=100, with_payload=True)[0]]
    assert set(kinds) == {second_id}


def test_no_local_database_is_written(env):
    tmp_path, client, settings = env
    importer = Wifi8Importer(settings, qdrant=client, encoder=FakeEncoder(), embedding_model="fake")
    path = tmp_path / "p.zip"
    make_package(path, BASE_DOCS, BASE_SEGS)
    assert run(importer, importer.submit(path, submitted_by="t"))["status"] == "completed"
    written = [p for p in settings.root.rglob("*") if p.is_file()]
    assert not [p for p in written if p.suffix in {".sqlite", ".db", ".sqlite3"}]
    assert {p.parent.name for p in written} <= {"wifi8", "jobs"}  # only current.json and job records
    package = importer.current_store()
    assert package.manifest()["package_id"] == importer.current()["package_id"]
    assert package.counts() == {"documents": 2, "documents_analysis_eligible": 1, "segments": 3,
                                "chunks": client.count("wifi8_test", exact=True).count, "chunks_pending": 0,
                                "chunks_ready": client.count("wifi8_test", exact=True).count}
    total, page = package.chunk_page("new", 1, 10)
    assert total == len(page) and [p["chunk_index"] for _, p in page] == sorted(p["chunk_index"] for _, p in page)


def test_vectors_are_reused_from_the_previous_collection(env):
    from qdrant_client.models import Distance, PointStruct, VectorParams
    tmp_path, client, settings = env
    chunks = build_chunks(BASE_DOCS, BASE_SEGS, max_chars=settings.chunk_max_chars)
    client.create_collection("wifi8_kb", vectors_config=VectorParams(size=8, distance=Distance.COSINE))
    client.upsert("wifi8_kb", points=[PointStruct(id=c["point_id"], vector=[0.5] * 8, payload={"embedding_model": "fake"})
                                      for c in chunks[:-1]])
    encoder = FakeEncoder()
    importer = Wifi8Importer(settings, qdrant=client, encoder=encoder, embedding_model="fake")
    path = tmp_path / "p.zip"
    make_package(path, BASE_DOCS, BASE_SEGS)
    job = run(importer, importer.submit(path, submitted_by="t"))
    assert job["status"] == "completed" and job["progress"]["vectors_reused"] == len(chunks) - 1
    assert encoder.texts == 1  # only the chunk missing from the old collection was embedded
    other = Wifi8Importer(settings, qdrant=QdrantClient(":memory:"), encoder=FakeEncoder(), embedding_model="fake")
    assert other._reusable_vectors([chunks[0]["point_id"]]) == {}  # no old collection: nothing reused


def test_bm25_tokens_cover_cjk_and_technical_terms():
    assert lexical.query_terms("漫遊門檻是什麼？") == ["漫遊", "遊門", "門檻", "檻是"]
    assert {"wi-fi", "wi", "fi", "wifi"} <= set(lexical.tokens("Wi-Fi 8"))
    assert "802.11bn" in lexical.tokens("IEEE 802.11bn.")
    i1, v1 = lexical.document_vector("ELR ELR uplink", avg_tokens=256)
    i2, v2 = lexical.document_vector("ELR ELR uplink", avg_tokens=256)
    assert (i1, v1) == (i2, v2) and len(i1) == 2  # deterministic, independent of the package


def test_failed_import_keeps_current_package(env):
    tmp_path, client, settings = env
    ok = Wifi8Importer(settings, qdrant=client, encoder=FakeEncoder(), embedding_model="fake")
    first = tmp_path / "first.zip"
    first_id = make_package(first, BASE_DOCS, BASE_SEGS)
    run(ok, ok.submit(first, submitted_by="tester"))
    count = client.count("wifi8_test", exact=True).count

    broken = Wifi8Importer(settings, qdrant=client, encoder=FakeEncoder(fail_after=0), embedding_model="fake")
    second = tmp_path / "second.zip"
    make_package(second, [doc("other", "Other")], [seg("other", 1, "brand new text")])
    job = run(broken, broken.submit(second, submitted_by="tester"))
    assert job["status"] == "failed" and "embedding service down" in job["error"]
    assert broken.current()["package_id"] == first_id
    assert client.count("wifi8_test", exact=True,).count == count
    assert broken.active_job() is None  # lock released so the next upload can proceed


def test_embedding_model_change_is_refused(env):
    tmp_path, client, settings = env
    first = Wifi8Importer(settings, qdrant=client, encoder=FakeEncoder(), embedding_model="model-a")
    path = tmp_path / "p.zip"
    make_package(path, BASE_DOCS, BASE_SEGS)
    run(first, first.submit(path, submitted_by="tester"))
    assert first.current()["embedding_model"] == "model-a"
    other = tmp_path / "o.zip"
    make_package(other, [doc("x", "X")], [seg("x", 1, "x text")])
    second = Wifi8Importer(settings, qdrant=client, encoder=FakeEncoder(), embedding_model="model-b")
    job = run(second, second.submit(other, submitted_by="tester"))
    assert job["status"] == "failed" and "model-a" in job["error"]
    small = Wifi8Importer(settings, qdrant=client, encoder=lambda texts: [[0.1] * 4 for _ in texts], embedding_model="model-a")
    job = run(small, small.submit(other, submitted_by="tester"))
    assert job["status"] == "failed" and "8-dim" in job["error"]


def test_only_one_import_at_a_time(env):
    tmp_path, client, settings = env
    importer = Wifi8Importer(settings, qdrant=client, encoder=FakeEncoder(), embedding_model="fake")
    path = tmp_path / "p.zip"
    make_package(path, BASE_DOCS, BASE_SEGS)
    importer.submit(path, submitted_by="tester")
    other = tmp_path / "o.zip"
    make_package(other, [doc("x", "X")], [seg("x", 1, "x text")])
    with pytest.raises(ImportConflict):
        importer.submit(other, submitted_by="tester")


@pytest.fixture
def api(tmp_path, monkeypatch):
    from src.web_api import wifi8_routes

    monkeypatch.setenv("KM_WIFI8_ROOT", str(tmp_path / "wifi8"))
    monkeypatch.setattr(wifi8_routes, "_qdrant", lambda: None)  # upload and job status need no Qdrant
    app = FastAPI()
    state = {"identity": {"sub": "u1", "instance_id": "test", "role": "user", "epoch": 1}}

    @app.middleware("http")
    async def identity(request: Request, call_next):
        if state["identity"]:
            request.state.km_identity = state["identity"]
        return await call_next(request)

    class User:
        username = "km-clude1"

    class Registry:
        def get_user(self, user_id):
            return User() if user_id == "u1" else None

    monkeypatch.setattr("src.km_control.ControlRegistry.from_environment", classmethod(lambda cls: Registry()))
    enqueued = []
    monkeypatch.setattr(wifi8_routes, "_enqueue", lambda job_id: enqueued.append([job_id]))
    app.include_router(wifi8_routes.router)
    return TestClient(app), state, enqueued, tmp_path


def test_upload_permissions_and_status(api, monkeypatch):
    client, state, enqueued, tmp_path = api
    path = tmp_path / "p.zip"
    make_package(path, BASE_DOCS, BASE_SEGS)
    files = {"file": ("wifi8.zip", path.read_bytes(), "application/zip")}
    headers = {"x-km-wifi8-import": "1"}

    monkeypatch.delenv("KM_WIFI8_IMPORT_USERS", raising=False)
    assert client.post("/api/wifi8/packages", files=files, headers=headers).status_code == 403  # disabled by default
    monkeypatch.setenv("KM_WIFI8_IMPORT_USERS", "someone-else")
    assert client.post("/api/wifi8/packages", files=files, headers=headers).status_code == 403
    monkeypatch.setenv("KM_WIFI8_IMPORT_USERS", "*")  # every logged-in account
    assert client.post("/api/wifi8/packages", files=files).status_code == 403  # missing same-origin header
    bad = {"file": ("wifi8.zip", b"not a zip", "application/zip")}
    assert client.post("/api/wifi8/packages", files=bad, headers=headers).status_code == 422

    response = client.post("/api/wifi8/packages", files=files, headers=headers)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["status"] == "queued" and job["submitted_by"] == "km-clude1"
    assert enqueued == [[job["job_id"]]]
    assert client.get(f"/api/wifi8/jobs/{job['job_id']}").json()["package_id"] == job["package_id"]
    assert client.get("/api/wifi8/jobs/../../etc").status_code == 404
    status = client.get("/api/wifi8/status").json()
    assert status["active_job"]["job_id"] == job["job_id"] and status["upload_enabled"] is True

    state["identity"] = None
    assert client.get("/api/wifi8/status").status_code == 401


def _table_seg(rid, n, row, text, table=1, kind="table_row", loc_type="table"):
    return {"segment_id": f"{rid}:{n}", "revision_id": rid, "ordinal": n, "kind": kind,
            "location": {"type": loc_type, "table": table, "row": row}, "text": text}


def test_table_chunks_get_markdown_display_without_changing_identity():
    docs = [doc("tbl", "Co-BF vs Co-SR")]
    segs = [seg("tbl", 1, "Intro paragraph.", {"type": "paragraph", "paragraph": 1})]
    segs += [_table_seg("tbl", 1 + r, r, "Feature | Co-BF | Co-SR" if r == 1 else f"Row {r} | a{r} | b{r}") for r in range(1, 41)]
    chunks = build_chunks(docs, segs, max_chars=300)
    tables = [c for c in chunks if c["display_text"]]
    assert len(tables) >= 2 and all(c["display_text"] for c in chunks if c["location"].get("type") == "table")
    first, later = tables[0]["display_text"].split("\n"), tables[1]["display_text"].split("\n")
    assert first[0] == "| Feature | Co-BF | Co-SR |" and first[1] == "|---|---|---|" and first[2] == "| Row 2 | a2 | b2 |"
    assert later[0] == "（續上表）" and later[1] == "| Feature | Co-BF | Co-SR |"  # the header is repeated
    assert not [c for c in chunks if c["location"].get("type") == "paragraph"][0]["display_text"]
    # Identity, BM25 and embedding input do not depend on the display text.
    stripped = build_chunks(docs, segs, max_chars=300)
    assert [(c["point_id"], c["text"], c["embed_text"]) for c in chunks] == [(c["point_id"], c["text"], c["embed_text"]) for c in stripped]
    assert "Feature | Co-BF | Co-SR" in tables[0]["text"]  # the plain rows stay searchable


def test_markdown_table_pads_ragged_rows_and_escapes_pipes():
    from src.wifi8.chunks import markdown_table
    text = markdown_table("A | B", ["1", "2 | 3 | 4", "x|y | z"])
    assert text.split("\n") == ["| A | B |  |", "|---|---|---|", "| 1 |  |  |", "| 2 | 3 | 4 |", "| x／y | z |  |"]


def test_same_package_is_reimported_for_a_newer_display_version(env):
    tmp_path, client, settings = env
    encoder = FakeEncoder()
    importer = Wifi8Importer(settings, qdrant=client, encoder=encoder, embedding_model="fake")
    path = tmp_path / "t.zip"
    segs = [_table_seg("new", r, r, "H1 | H2" if r == 1 else f"v{r} | w{r}") for r in range(1, 4)] + BASE_SEGS[2:]
    make_package(path, BASE_DOCS, segs)
    assert run(importer, importer.submit(path, submitted_by="t"))["status"] == "completed"
    assert importer.current()["display_version"] >= 1
    assert importer.submit(path, submitted_by="t")["status"] == "completed"  # nothing to do

    # Simulate a package imported before display texts existed.
    points = client.scroll("wifi8_test", limit=100, with_payload=True)[0]
    client.delete_payload("wifi8_test", keys=["display_text"], points=[p.id for p in points])
    current = importer.current()
    (settings.root / "current.json").write_text(json.dumps({k: v for k, v in current.items() if k != "display_version"}))
    embedded = encoder.texts
    job = importer.submit(path, submitted_by="t")
    assert job["status"] == "queued"
    assert run(importer, job)["status"] == "completed"
    assert encoder.texts == embedded  # identities unchanged: nothing re-embedded
    table = [p.payload for p in client.scroll("wifi8_test", limit=100, with_payload=True)[0] if p.payload["revision_id"] == "new"]
    assert table and table[0]["display_text"].startswith("| H1 | H2 |")
    assert importer.current()["display_version"] >= 1


def test_rejected_upload_stays_visible_in_the_job_list(api, monkeypatch):
    client, state, enqueued, tmp_path = api
    monkeypatch.setenv("KM_WIFI8_IMPORT_USERS", "*")
    bad = {"file": ("broken.zip", b"not a zip", "application/zip")}
    response = client.post("/api/wifi8/packages", files=bad, headers={"x-km-wifi8-import": "1"})
    assert response.status_code == 422 and "匯出包驗證失敗" in response.json()["detail"]
    jobs = client.get("/api/wifi8/jobs").json()
    assert [j["status"] for j in jobs["jobs"]] == ["failed"] and jobs["active_job"] is None
    failed = jobs["jobs"][0]
    assert failed["phase"] == "validate" and failed["submitted_by"] == "km-clude1" and "broken.zip" in failed["message"]
    assert "匯出包驗證失敗" in failed["error"] and not enqueued  # no work was queued, nothing is locked
    assert not (tmp_path / "wifi8" / "import.lock").exists()
