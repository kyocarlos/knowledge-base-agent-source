import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from src.wifi8.chunks import build_chunks, image_chunks
from src.wifi8.images import DescriberSettings, ImageTextCache, clean, describe_batch
from src.wifi8.importer import Wifi8Importer, Wifi8Settings
from src.wifi8.package import PackageError, read_package
from tests.test_wifi8_import import BASE_DOCS, BASE_SEGS, FakeEncoder, doc, run, seg

FIGURE = b"\x89PNG fake figure bytes"
LOGO = b"\x89PNG fake logo"
FIG_ID, LOGO_ID = hashlib.sha256(FIGURE).hexdigest(), hashlib.sha256(LOGO).hexdigest()
IMAGES = [
    {"image_id": FIG_ID, "revision_id": "new", "ordinal": 1, "location": {"type": "page", "page": 2},
     "caption": "Figure 3: ELR uplink", "extension": "png", "width": 400, "height": 300},
    {"image_id": LOGO_ID, "revision_id": "new", "ordinal": 2, "location": {"type": "page", "page": 1},
     "caption": "", "extension": "png", "width": 300, "height": 200},
    {"image_id": FIG_ID, "revision_id": "old", "ordinal": 1, "location": {"type": "image"},
     "caption": "", "extension": "png", "width": 400, "height": 300},
]
DESCRIPTIONS = {FIGURE: "【圖中文字】\nELR uplink 20 MHz\n【圖片說明】\n此圖說明 **ELR** 上行流程。", LOGO: "無內容。"}


def make_v2(path: Path, documents, segments, images, files, *, tamper=None, extra=None):
    members = {
        "documents.jsonl": "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in documents).encode(),
        "segments.jsonl": "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in segments).encode(),
        "images.jsonl": "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in images).encode(),
    }
    listed = {n: {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for n, b in members.items()}
    content = hashlib.sha256(b"".join(listed[n]["sha256"].encode() for n in sorted(listed))).hexdigest()
    manifest = {"schema": "km.wifi8-package.v2", "package_id": f"wifi8-{content[:16]}", "content_sha256": content,
                "files": listed, "counts": {"documents": len(documents), "images": len(images)}}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in members.items():
            archive.writestr(name, data)
        for data in files:
            name = f"images/{hashlib.sha256(data).hexdigest()}.png"
            archive.writestr(name, data + b"x" if name == tamper else data)
        if extra:
            archive.writestr(extra, b"x")
    return manifest["package_id"]


class FakeDescriber:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, data, extension):
        self.calls.append(data)
        if data in self.fail:
            raise TimeoutError("gateway timeout")
        return DESCRIPTIONS[data]


SETTINGS = DescriberSettings(provider="openai", model="vision-x", base_url="http://gw/v1", api_key_env="K",
                             batch_size=2, concurrency=2, retries=1, max_failed_ratio=0.0)


@pytest.fixture
def env(tmp_path):
    return tmp_path, QdrantClient(":memory:"), Wifi8Settings(root=tmp_path / "wifi8", collection="wifi8_test", embed_batch_size=4)


def importer_for(env, describer, settings=SETTINGS, encoder=None):
    tmp_path, client, wifi8 = env
    return Wifi8Importer(wifi8, qdrant=client, encoder=encoder or FakeEncoder(), embedding_model="fake",
                         describer_settings=settings, describer=describer)


def chunk_payloads(client):
    return [p.payload for p in client.scroll("wifi8_test", limit=200, with_payload=True)[0]]


def test_v2_package_is_verified_and_v1_still_accepted(tmp_path):
    path = tmp_path / "p.zip"
    make_v2(path, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE, LOGO])
    package = read_package(path, max_uncompressed_bytes=10**7)
    assert len(package.images) == 3 and package.image_bytes(FIG_ID, "png") == FIGURE
    for kwargs in ({"tamper": f"images/{FIG_ID}.png"}, {"extra": "images/" + "a" * 64 + ".png"}, {"extra": "images/../x.png"}):
        bad = tmp_path / "bad.zip"
        make_v2(bad, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE, LOGO], **kwargs)
        with pytest.raises(PackageError):
            read_package(bad, max_uncompressed_bytes=10**7)
    missing = tmp_path / "missing.zip"
    make_v2(missing, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE])  # LOGO listed but not shipped
    with pytest.raises(PackageError):
        read_package(missing, max_uncompressed_bytes=10**7)


def test_clean_drops_empty_marker_and_emphasis():
    assert clean("無內容。") == "" and clean("  ") == ""
    assert clean("【圖片說明】\n**ELR** 流程  \n") == "【圖片說明】\nELR 流程"


def test_describe_batch_caches_results_and_records_failures(tmp_path):
    cache = ImageTextCache(tmp_path)
    describer = FakeDescriber(fail={LOGO})
    images = [{"image_id": FIG_ID, "extension": "png"}, {"image_id": LOGO_ID, "extension": "png"}]
    counts = describe_batch(images, lambda i, e: {FIG_ID: FIGURE, LOGO_ID: LOGO}[i], cache, SETTINGS, describer, sleep=lambda s: None)
    assert counts == {"described": 1, "empty": 0, "failed": 1}
    assert describer.calls.count(LOGO) == 2  # one retry
    assert cache.usable(FIG_ID, SETTINGS.signature)["text"].endswith("此圖說明 ELR 上行流程。")
    assert cache.get(LOGO_ID)["status"] == "failed" and cache.usable(LOGO_ID, SETTINGS.signature) is None
    assert cache.find_image(FIG_ID).read_bytes() == FIGURE
    assert cache.usable(FIG_ID, "openai:other-model:low:p1") is None  # another model describes again


def test_image_chunks_keep_text_chunk_identities():
    text = build_chunks(BASE_DOCS, BASE_SEGS, max_chars=1200)
    figures = image_chunks(BASE_DOCS, IMAGES, {FIG_ID: "ELR uplink 20 MHz"}, {"new": 2, "old": 1})
    assert build_chunks(BASE_DOCS, BASE_SEGS, max_chars=1200) == text
    assert [(c["revision_id"], c["ordinal"], c["location_label"]) for c in figures] == [("new", 3, "第 2 頁・圖 1"), ("old", 2, "圖 1")]
    assert figures[0]["text"] == "【圖片】Figure 3: ELR uplink\nELR uplink 20 MHz" and figures[0]["image"]["id"] == FIG_ID
    assert figures[0]["embed_text"].startswith("ELR Spec v2\n第 2 頁・圖 1\n")
    assert figures[0]["point_id"] != figures[1]["point_id"] and figures[0]["point_id"] not in {c["point_id"] for c in text}


def test_import_describes_each_figure_once_and_reuses_the_cache(env):
    tmp_path, client, _ = env
    path = tmp_path / "p.zip"
    make_v2(path, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE, LOGO])
    describer, encoder = FakeDescriber(), FakeEncoder()
    importer = importer_for(env, describer, encoder=encoder)
    job = importer.submit(path, submitted_by="t")
    assert job["phase"] == "describe"
    job = run(importer, job)
    assert job["status"] == "completed", job.get("error")
    assert job["images"] == {"distinct": 2, "occurrences": 3, "described": 1, "empty": 1, "failed": 0, "pending": 0,
                             "signature": SETTINGS.signature}
    assert sorted(describer.calls) == sorted([FIGURE, LOGO])  # the figure used twice is described once
    figures = [p for p in chunk_payloads(client) if p.get("image")]
    assert sorted((p["revision_id"], p["location_label"]) for p in figures) == [("new", "第 2 頁・圖 1"), ("old", "圖 1")]
    assert all(p["image_id"] == FIG_ID and p["vector_state"] == "ready" for p in figures)
    assert importer.current()["image_text_signature"] == SETTINGS.signature
    assert importer.submit(path, submitted_by="t")["status"] == "completed"  # same package and setting: nothing to do

    # A new package with one more document: cached figures are not described again, text vectors are reused.
    embedded = encoder.texts
    docs = BASE_DOCS + [doc("extra", "DPS Overview")]
    make_v2(tmp_path / "p2.zip", docs, BASE_SEGS, IMAGES + [{**IMAGES[0], "revision_id": "extra"}], [FIGURE, LOGO])
    job = run(importer, importer.submit(tmp_path / "p2.zip", submitted_by="t"))
    assert job["status"] == "completed" and len(describer.calls) == 2
    assert encoder.texts == embedded + 1  # only the new document's figure chunk


def test_too_many_failures_keep_the_current_package(env, monkeypatch):
    tmp_path, client, _ = env
    path = tmp_path / "p.zip"
    make_v2(path, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE, LOGO])
    importer = importer_for(env, FakeDescriber(fail={FIGURE}))
    monkeypatch.setattr("src.wifi8.images.time.sleep", lambda s: None)
    job = run(importer, importer.submit(path, submitted_by="t"))
    assert job["status"] == "failed" and "圖片轉文字失敗 1/2" in job["error"]
    assert importer.current() is None and importer.active_job() is None
    # The next job tries the failed figure again (the described one comes from the cache).
    retry = importer_for(env, FakeDescriber())
    job = run(retry, retry.submit(path, submitted_by="t"))
    assert job["status"] == "completed" and retry._describer.calls == [FIGURE]


def test_describer_off_imports_text_only_and_says_so(env):
    tmp_path, client, _ = env
    path = tmp_path / "p.zip"
    make_v2(path, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE, LOGO])
    importer = importer_for(env, None, settings=DescriberSettings(provider="off"))
    job = importer.submit(path, submitted_by="t")
    assert job["phase"] == "stage" and "KM_WIFI8_IMAGE_DESCRIBER=off" in job["message"]
    assert run(importer, job)["status"] == "completed"
    assert not any(p.get("image") for p in chunk_payloads(client))
    assert importer.current()["image_text_signature"] is None
    # Turning the describer on imports the same package again, now with its figures.
    enabled = importer_for(env, FakeDescriber())
    job = enabled.submit(path, submitted_by="t")
    assert job["status"] == "queued" and run(enabled, job)["status"] == "completed"
    assert any(p.get("image") for p in chunk_payloads(client))


@pytest.fixture
def image_api(env, monkeypatch):
    from src.web_api import wifi8_routes
    tmp_path, client, settings = env
    path = tmp_path / "p.zip"
    make_v2(path, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE, LOGO])
    importer = importer_for(env, FakeDescriber())
    assert run(importer, importer.submit(path, submitted_by="t"))["status"] == "completed"
    monkeypatch.setattr(wifi8_routes, "_importer", lambda: importer)
    app = FastAPI()
    state = {"identity": {"sub": "u1"}}

    @app.middleware("http")
    async def identity(request: Request, call_next):
        if state["identity"]:
            request.state.km_identity = state["identity"]
        return await call_next(request)

    app.include_router(wifi8_routes.router)
    return TestClient(app), state, importer


def test_image_route_serves_only_figures_of_the_current_package(image_api):
    client, state, importer = image_api
    response = client.get(f"/api/wifi8/images/{FIG_ID}")
    assert response.status_code == 200 and response.content == FIGURE
    assert response.headers["content-type"] == "image/png" and response.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/wifi8/images/{LOGO_ID}").status_code == 404  # cached, but no chunk (nothing to show)
    for bad in ("../../etc/passwd", "A" * 64, "0" * 63):
        assert client.get(f"/api/wifi8/images/{bad}").status_code == 404
    chunks = client.get("/api/wifi8/documents/new/chunks", params={"start": 1, "count": 20}).json()["chunks"]
    assert [c["image"]["id"] for c in chunks if c.get("image")] == [FIG_ID]
    figures = client.get("/api/wifi8/documents/new/chunks", params={"figures": "true", "count": 1}).json()
    assert figures["total"] == 1 and [c["location_label"] for c in figures["chunks"]] == ["第 2 頁・圖 1"]
    assert client.get("/api/wifi8/documents/new/chunks", params={"figures": "true"}).json()["chunks"][0]["image"]["id"] == FIG_ID
    state["identity"] = None
    assert client.get(f"/api/wifi8/images/{FIG_ID}").status_code == 401


def test_first_finished_description_wins_and_failures_are_replaced(tmp_path):
    cache = ImageTextCache(tmp_path)
    sig = SETTINGS.signature
    cache.put(FIG_ID, {"signature": sig, "status": "failed", "text": "", "error": "TimeoutError"})
    assert cache.put(FIG_ID, {"signature": sig, "status": "described", "text": "first"})["text"] == "first"
    assert cache.put(FIG_ID, {"signature": sig, "status": "described", "text": "second"})["text"] == "first"
    assert cache.put(FIG_ID, {"signature": sig, "status": "failed", "text": ""})["status"] == "described"
    assert cache.put(FIG_ID, {"signature": "openai:other:low:p1", "status": "described", "text": "new model"})["text"] == "new model"
    assert not list(tmp_path.rglob("*.tmp"))


def _zone(tmp_path, name, describer, shared=None):
    settings = Wifi8Settings(root=tmp_path / name, collection="wifi8_test", embed_batch_size=4, image_cache_root=shared)
    return Wifi8Importer(settings, qdrant=QdrantClient(":memory:"), encoder=FakeEncoder(), embedding_model="fake",
                         describer_settings=SETTINGS, describer=describer)


def _figure_texts(importer):
    return sorted(p.payload["content"] for p in importer.qdrant.scroll("wifi8_test", limit=200, with_payload=True)[0]
                  if p.payload.get("image"))


def test_zones_sharing_the_cache_serve_identical_figure_texts(tmp_path):
    path = tmp_path / "p.zip"
    make_v2(path, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE, LOGO])
    shared = tmp_path / "shared-cache"
    test_zone = _zone(tmp_path, "test", FakeDescriber(), shared)
    assert run(test_zone, test_zone.submit(path, submitted_by="t"))["status"] == "completed"

    class OtherWording(FakeDescriber):  # the same model answers a little differently on another call
        def __call__(self, data, extension):
            self.calls.append(data)
            return "另一種說法"
    da40 = _zone(tmp_path, "da40", OtherWording(), shared)
    assert run(da40, da40.submit(path, submitted_by="t"))["status"] == "completed"
    assert da40._describer.calls == []  # nothing described again
    assert _figure_texts(da40) == _figure_texts(test_zone) and len(_figure_texts(da40)) == 2


def test_served_texts_that_differ_from_the_cache_are_imported_again(tmp_path):
    path = tmp_path / "p.zip"
    make_v2(path, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE, LOGO])

    class OwnWording(FakeDescriber):
        def __call__(self, data, extension):
            self.calls.append(data)
            return "DA40 自己的說法" if data == FIGURE else "無內容"
    alone = _zone(tmp_path, "da40", OwnWording())  # imported before the zones shared a cache
    assert run(alone, alone.submit(path, submitted_by="t"))["status"] == "completed"
    reference = _zone(tmp_path, "test", FakeDescriber(), tmp_path / "shared-cache")
    assert run(reference, reference.submit(path, submitted_by="t"))["status"] == "completed"

    joined = Wifi8Importer(Wifi8Settings(root=tmp_path / "da40", collection="wifi8_test", embed_batch_size=4,
                                         image_cache_root=tmp_path / "shared-cache"),
                           qdrant=alone.qdrant, encoder=alone.encoder, embedding_model="fake",
                           describer_settings=SETTINGS, describer=FakeDescriber())
    job = joined.submit(path, submitted_by="t")
    assert job["status"] == "queued"  # same package and setting, but different served figure texts
    assert run(joined, job)["status"] == "completed" and joined._describer.calls == []
    assert _figure_texts(joined) == _figure_texts(reference)
    assert joined.submit(path, submitted_by="t")["status"] == "completed"  # now nothing to do


def test_figure_chunks_are_weighted_in_the_fused_ranking(env):
    from src.wifi8.search import SearchOptions, Wifi8Search
    tmp_path, client, _ = env
    path = tmp_path / "p.zip"
    make_v2(path, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE, LOGO])
    importer = importer_for(env, FakeDescriber())
    assert run(importer, importer.submit(path, submitted_by="t"))["status"] == "completed"

    def ranking(weight):
        search = Wifi8Search(importer.current_store(), encoder=importer.encoder, image_weight=weight)
        return [bool(r.get("image")) for r in search.search("ELR uplink 20 MHz 流程", SearchOptions(top_k=5, include_history=True))["results"]]
    assert ranking(1.0)[0] is True
    assert ranking(0.01)[0] is False and True in ranking(0.01)  # still found, just after the text


def test_dense_retrieval_is_exact_unless_configured(env, monkeypatch):
    from src.wifi8.search import Wifi8Search
    tmp_path, client, _ = env
    path = tmp_path / "p.zip"
    make_v2(path, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE, LOGO])
    importer = importer_for(env, FakeDescriber())
    assert run(importer, importer.submit(path, submitted_by="t"))["status"] == "completed"
    monkeypatch.delenv("KM_WIFI8_VECTOR_EXACT", raising=False)
    monkeypatch.delenv("KM_WIFI8_IMAGE_SCORE_WEIGHT", raising=False)
    search = Wifi8Search.for_current(importer, encoder=importer.encoder, reranker=None)
    assert (search.exact, search.image_weight) == (True, 0.7)
    calls = []
    original = client.query_points
    monkeypatch.setattr(client, "query_points", lambda *a, **k: calls.append(k["search_params"].exact) or original(*a, **k))
    assert search.vector("ELR uplink", search._resolve("ELR uplink", __import__("src.wifi8.search", fromlist=["SearchOptions"]).SearchOptions(), search._documents()))
    assert calls == [True]
    monkeypatch.setenv("KM_WIFI8_VECTOR_EXACT", "false")
    monkeypatch.setenv("KM_WIFI8_IMAGE_SCORE_WEIGHT", "1")
    search = Wifi8Search.for_current(importer, encoder=importer.encoder, reranker=None)
    assert (search.exact, search.image_weight) == (False, 1.0)


def test_equal_scores_are_ordered_by_id():
    from types import SimpleNamespace
    from src.wifi8.search import _ranked
    points = [SimpleNamespace(id="b", score=1.0), SimpleNamespace(id="c", score=2.0), SimpleNamespace(id="a", score=1.0)]
    assert _ranked(points) == ["c", "a", "b"] == _ranked(list(reversed(points)))
    noisy = [SimpleNamespace(id="b", score=24.407490), SimpleNamespace(id="a", score=24.407488), SimpleNamespace(id="c", score=30.0)]
    assert _ranked(noisy, 2) == ["c", "a"]  # float noise between servers does not decide the order or the cut-off


def test_import_keeps_qdrant_vacuuming_deleted_points(env, monkeypatch):
    tmp_path, client, _ = env
    path = tmp_path / "p.zip"
    make_v2(path, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE, LOGO])
    importer = importer_for(env, FakeDescriber())
    updates = []
    original = client.update_collection
    monkeypatch.setattr(client, "update_collection", lambda name, **k: updates.append((name, k["optimizers_config"])) or original(name, **k))
    assert run(importer, importer.submit(path, submitted_by="t"))["status"] == "completed"
    assert {name for name, _ in updates} == {"wifi8_test", "wifi8_documents"}
    assert all((c.deleted_threshold, c.vacuum_min_vector_number) == (0.001, 100) for _, c in updates)
    if not str(type(client._client)).endswith("QdrantLocal'>"):  # real server: the setting is stored
        config = client.get_collection("wifi8_test").config.optimizer_config
        assert (config.deleted_threshold, config.vacuum_min_vector_number) == (0.001, 100)


def test_agent_citations_of_figure_chunks_carry_the_image(env):
    from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools
    from src.wifi8.search import Wifi8Search
    tmp_path, client, _ = env
    path = tmp_path / "p.zip"
    make_v2(path, BASE_DOCS, BASE_SEGS, IMAGES, [FIGURE, LOGO])
    importer = importer_for(env, FakeDescriber())
    assert run(importer, importer.submit(path, submitted_by="t"))["status"] == "completed"
    citations = CitationRegistry()
    tools = WifiTools(Wifi8Search(importer.current_store(), encoder=importer.encoder), AgentSettings(), citations)
    tools.search_wifi("ELR uplink 20 MHz 流程", include_history=True)
    tools.read_document("new", start=1, count=8)
    figures = [c for c in citations.items.values() if c.get("image")]
    assert figures and all(c["image"]["id"] == FIG_ID and c["location_label"].endswith("圖 1") for c in figures)
    assert all("image" not in c for c in citations.items.values() if "圖" not in (c["location_label"] or ""))


def test_figure_intent_terms():
    from src.wifi8.search import figure_intent
    assert figure_intent("DSO 和 Preamble Puncturing 比較表中 Purpose 各是什麼？")
    assert figure_intent("Show the Wi-Fi 8 timeline") and figure_intent("Sensing 架構圖")
    assert not figure_intent("這代表什麼意思？誰發表的？") and not figure_intent("NPCA 是什麼？")


def test_figure_questions_raise_figure_chunks_and_citations_are_numbered(env):
    from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools
    from src.wifi8.search import SearchOptions, Wifi8Search
    tmp_path, client, _ = env
    path = tmp_path / "p.zip"
    segs = [seg("new", 1, "ELR uplink overview " + "x" * 1300, {"type": "page", "page": 2}),
            seg("new", 2, "ELR uplink details on the same page.", {"type": "page", "page": 2})] + BASE_SEGS[1:]
    make_v2(path, BASE_DOCS, segs, IMAGES, [FIGURE, LOGO])
    importer = importer_for(env, FakeDescriber())
    assert run(importer, importer.submit(path, submitted_by="t"))["status"] == "completed"
    search = Wifi8Search(importer.current_store(), encoder=importer.encoder, image_weight=0.01, figure_weight=100.0)

    def first_is_figure(query, **options):
        return bool(search.search(query, SearchOptions(top_k=5, include_history=True, **options))["results"][0].get("image"))
    assert not first_is_figure("ELR uplink 20 MHz 流程")
    assert first_is_figure("ELR uplink 20 MHz 流程圖")  # the query itself asks for a figure
    assert first_is_figure("ELR uplink 20 MHz 流程", figure_focus=True)

    tools = WifiTools(search, AgentSettings(), CitationRegistry())
    tools.question = "ELR uplink 的流程圖畫了什麼？"  # set by run_agent; the model's own query may drop 流程圖
    hits = tools.search_wifi("ELR uplink 20 MHz", include_history=True)["hits"]
    assert hits[0].get("figure") is True
    tools.read_document("new", start=1, count=8)  # cite every chunk of the document
    page_two = sorted((c["part"]["index"], c["part"]["total"]) for c in tools.citations.items.values() if c["location_label"] == "第 2 頁")
    assert page_two == [(1, 2), (2, 2)]
    assert all(c.get("part") is None for c in tools.citations.items.values() if c["location_label"] != "第 2 頁")
