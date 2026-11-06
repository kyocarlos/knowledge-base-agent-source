"""Zone pages on real data: catalog, page JSON, weekly digest, questions (fakes only: no Qdrant, Redis or model)."""
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web_api import zone_routes
from src.zone_pages import views
from src.zone_pages.agent import ZoneAgent, grounding, split_followups
from src.zone_pages.catalog import ZoneCatalog, spread
from src.zone_pages.digest import DigestService

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def lib(fid, name, text, zone="認證知識專區", i=0, **extra):
    return ("km_csit_docs", {"document_file_id": fid, "source_type": "DocumentLibraryFile", "doc_name": name, "content": text, "chunk_index": i, "topic_zone": zone, "zone_id": "cert",
                             "zone_basis": "llm", "document_type": "SOP", "summary": f"{name} 的摘要", "keywords": ["認證", "NCC"], "indexed_at": "2026-11-05T01:00:00Z",
                             "classification": {"l1": None}, **extra})


def v2(entity, doc, version, name, text, zone="設備儀器專區", state="Active", i=0, **extra):
    return ("km_csit_docs", {"source_type": "VendorFile", "source_entity_id": entity, "document_id": doc, "document_version": version, "doc_name": name, "content": text,
                             "chunk_index": i, "topic_zone": zone, "zone_basis": "llm", "index_state": state, "document_type": "Manual", "indexed_at": "2026-11-04T01:00:00Z", **extra})


def report(doc, ver, name, text, zone="產品驗證專區", i=0, **extra):
    return ("knowledge_base", {"document_id": doc, "document_version": ver, "doc_name": name, "content": text, "chunk_index": i, "topic_zone": zone, "zone_basis": "source_type",
                               "document_type": "TestReport", "indexed_at": "2026-11-05T09:00:00Z", **extra})


def template(rec, name, text, i=0, **extra):
    return ("ai_km_knowledge_v1", {"source_system": "CSIT", "document_id": name, "document_version": "V10", "source_record_id": rec, "title": name, "chunk_text": text, "chunk_index": i,
                                   "topic_zone": "產品驗證專區", "source_sheet": "4.1 Xn Handover", "source_cell_range": "B8", "indexed_at": "2026-11-05T10:00:00Z", **extra})


def matches(cond, payload):
    if hasattr(cond, "must") or hasattr(cond, "must_not"):
        return flt_ok(cond, payload)
    value = payload.get(cond.key)
    m = cond.match
    return value in m.any if hasattr(m, "any") else value == m.value


def flt_ok(flt, payload):
    return all(matches(c, payload) for c in (flt.must or [])) and not any(matches(c, payload) for c in (flt.must_not or []))


class FakeQdrant:
    def __init__(self, rows):
        self.collections = {}
        for i, (collection, payload) in enumerate(rows):
            self.collections.setdefault(collection, []).append(SimpleNamespace(id=i, payload=payload, score=0.0))
        self.queries = []

    def scroll(self, collection, scroll_filter=None, limit=256, offset=None, with_payload=True, with_vectors=False):
        if collection not in self.collections:
            raise RuntimeError("Collection not found")
        rows = [p for p in self.collections[collection] if flt_ok(scroll_filter, p.payload)] if scroll_filter else self.collections[collection]
        start = offset or 0
        page = rows[start:start + limit]
        return page, (start + limit if start + limit < len(rows) else None)

    def query_points(self, collection, query, using, query_filter, limit, with_payload):
        self.queries.append((collection, using))
        if collection not in self.collections:
            raise RuntimeError("Collection not found")
        words = set(query_filter.__dict__.get("_q", ()))
        rows = [SimpleNamespace(id=p.id, payload=p.payload, score=self.score(p.payload)) for p in self.collections[collection] if flt_ok(query_filter, p.payload)]
        rows.sort(key=lambda p: p.score, reverse=True)
        return SimpleNamespace(points=rows[:limit])

    wanted = ""

    def score(self, payload):
        text = payload.get("content") or payload.get("chunk_text") or ""
        return float(sum(1 for w in self.wanted.split() if w in text))


ROWS = [
    lib("f1", "ncc-process.txt", "NCC 認證需要準備申請書與送測樣品", i=0), lib("f1", "ncc-process.txt", "取得證書後才能銷售", i=1),
    lib("f2", "unplaced.txt", "待確認的內容", zone="待分類"),
    v2("e1", "d1", 1, "n9020b.txt", "頻譜分析儀每年校驗一次", state="Superseded", superseded_at="2026-11-05T02:00:00Z"),
    v2("e1", "d2", 2, "n9020b.txt", "頻譜分析儀每年校驗並登記資產編號"),
    report("r1", 1, "handover.xlsx", "換手成功率 100%，吞吐量 649 Mbps"),
    template("c9:v1", "SIT-SR-SC-NR-Handover-SCU2060-EV-V13.5a", "第 100 次：延遲 31→29 ms"),
    lib("f3", "wifi.txt", "Wi-Fi 7 的 MLO", zone="WiFi 知識專區"),
]


@pytest.fixture
def qdrant():
    return FakeQdrant(ROWS)


@pytest.fixture
def catalog(qdrant):
    return ZoneCatalog(qdrant, lambda texts: [[0.1] * 3 for _ in texts], ttl=0)


CERT = ["認證知識專區"]
EQUIP = ["設備儀器專區"]
VERIF = ["產品驗證專區", "待分類"]


# ---------- catalog ----------
def test_points_become_documents_of_their_zone(catalog):
    docs = catalog.documents(CERT)
    assert [d["title"] for d in docs] == ["ncc-process.txt"] and docs[0]["chunks"] == 2 and docs[0]["document_role"] == "作業程序" and docs[0]["document_date"] == "2026-11-05"
    assert catalog.documents(["WiFi 知識專區"])[0]["title"] == "wifi.txt"


def test_versions_of_one_source_are_one_family_and_the_old_one_is_history(catalog):
    docs = {d["revision_id"]: d for d in catalog.documents(EQUIP)}
    assert docs["d1:v1"]["analysis_eligible"] is False and docs["d2:v2"]["analysis_eligible"] is True and docs["d1:v1"]["family"] == docs["d2:v2"]["family"] == "e1"
    assert {d["revision_id"] for d in catalog.versions(EQUIP, docs["d2:v2"])} == {"d2:v2", "d1:v1"}


def test_the_verification_zone_holds_reports_of_both_paths_and_what_could_not_be_placed(catalog):
    docs = catalog.documents(VERIF)
    assert {d["revision_id"] for d in docs} == {"r1:v1", "c9:v1", "f2"}
    assert next(d for d in docs if d["revision_id"] == "f2")["document_role"] == "待分類（待確認）"
    assert next(d for d in docs if d["revision_id"] == "c9:v1")["version_label"] == "V10"
    assert catalog.documents(CERT)[0]["revision_id"] == "f1"


def test_a_missing_collection_only_means_nothing_delivered_there(qdrant):
    cat = ZoneCatalog(qdrant, lambda t: [[0.1]], sources=(("nothing", None, "content", ()), *__import__("src.zone_pages.catalog", fromlist=["SOURCES"]).SOURCES), ttl=0)
    assert [d["title"] for d in cat.documents(CERT)] == ["ncc-process.txt"]


def test_chunks_of_a_document_are_read_in_order(catalog):
    doc = catalog.document(CERT, "f1")
    rows, total = catalog.chunks(doc, 8)
    assert total == 2 and [r["content"] for r in rows] == ["NCC 認證需要準備申請書與送測樣品", "取得證書後才能銷售"] and rows[0]["location_label"] == "第 1 段"
    tmpl = catalog.document(VERIF, "c9:v1")
    assert catalog.chunks(tmpl)[0][0]["location_label"] == "4.1 Xn Handover・B8"


def test_search_stays_inside_the_zone_and_skips_superseded_versions_unless_asked(catalog, qdrant):
    qdrant.wanted = "校驗"
    hits = catalog.search("校驗", EQUIP, 5)
    assert [h["doc"]["revision_id"] for h in hits] == ["d2:v2"]
    assert {h["doc"]["revision_id"] for h in catalog.search("校驗", EQUIP, 5, include_history=True)} == {"d1:v1", "d2:v2"}
    assert {h["doc"]["topic_zone"] for h in catalog.search("校驗", CERT, 5)} == {"認證知識專區"}
    assert all(h["doc"]["topic_zone"] in EQUIP for h in hits)


# ---------- page JSON ----------
def test_overview_counts_types_and_flags_unplaced_documents(catalog):
    o = views.overview(catalog.documents(VERIF), "產品驗證專區")
    assert o["counts"]["documents"] == 3 and o["counts"]["chunks"] == 3 and o["attention"][0]["title"] == "1 份文件待分類"
    assert {r["label"] for r in o["by_category"]["rows"]} == {"測試報告", "待分類（待確認）"}
    e = views.overview(catalog.documents(EQUIP), "設備儀器專區")
    assert e["counts"]["documents"] == 2 and e["counts"]["superseded_documents"] == 1 and e["qna_documents"] == 1


def test_document_list_filters_pages_and_hides_history(catalog):
    docs = catalog.documents(EQUIP)
    cur = views.list_documents(docs)
    assert cur["total"] == 1 and cur["documents"][0]["title"] == "n9020b.txt" and cur["facets"]["publishers"] == [["廠商檔案", 1]]
    assert views.list_documents(docs, history=True)["total"] == 2
    assert views.list_documents(docs, query="不存在")["total"] == 0
    assert views.list_documents(docs, publisher="設備附件")["total"] == 0


def test_the_weekly_digest_lists_the_weeks_documents_and_uses_titles_without_a_model(catalog):
    docs = catalog.documents(VERIF)
    d = DigestService(None).build("產品驗證專區", docs, NOW)
    assert d["week"] == "2026-W45" and {i["title"] for i in d["items"]} >= {"handover.xlsx"} and d["highlights"] and "標題" in d["note"]
    assert DigestService(None).build("x", [], NOW)["items"] == []


def test_the_digest_highlights_come_from_the_model_once_and_are_then_cached(catalog):
    docs = catalog.documents(VERIF)
    calls = []

    def complete(messages):
        calls.append(messages)
        return "- 本週新增 2 份測試報告\n- 換手成功率皆為 100%"
    svc = DigestService(complete)
    first = svc.build("產品驗證專區", docs, NOW, wait=True)
    again = svc.build("產品驗證專區", docs, NOW, wait=True)
    assert first["highlights"] == ["本週新增 2 份測試報告", "換手成功率皆為 100%"] and again["highlights"] == first["highlights"] and len(calls) == 1 and "語言模型" in again["note"]


def test_feed_has_events_and_recent(catalog):
    f = views.feed(catalog.documents(EQUIP), {"week": "x"})
    types = {e["type"] for e in f["updates"]["events"]}
    assert types == {"new_document", "superseded"} and f["updates"]["recent"][0]["title"] == "n9020b.txt"


# ---------- questions ----------
def complete_ok(messages):
    return "校驗每年一次 [S1]，並要登記資產編號 [S1]。年限 12 個月。\n追問：誰負責校驗？｜校驗證書放哪裡？"


def run_agent(catalog, qdrant, complete, question="頻譜分析儀多久校驗", names=EQUIP, files=None):
    qdrant.wanted = "校驗"
    events = []
    result = ZoneAgent(catalog, complete).answer(task_id="t1", zone_label="設備儀器專區", zone_names=names, question=question, history=[], owner={"user_id": "u"},
                                                 file_records=files or {}, emit=events.append)
    return result, events


def test_the_answer_cites_the_passages_it_used_and_checks_its_numbers(catalog, qdrant):
    r, events = run_agent(catalog, qdrant, complete_ok)
    assert r["status"] == "completed" and r["citations"][0]["ref"] == "S1" and r["citations"][0]["source"] == "n9020b.txt" and "追問" not in r["answer_main"]
    assert r["extension"]["followups"] == ["誰負責校驗？", "校驗證書放哪裡？"] and r["extension"]["related"].startswith("相關文件")
    g = r["grounding"]["summary"]
    assert g["claims_cited"] >= 1 and g["values_not_found"] == 1 and r["grounding"]["flagged"] == [{"kind": "value_not_found", "value": "12"}]  # "12" is not in the cited passage
    assert [e["type"] for e in events][:3] == ["tool", "tool", "tool"] and "".join(e["text"] for e in events if e["type"] == "delta") == r["answer_main"]


def test_no_passages_means_no_model_call(catalog, qdrant):
    def forbidden(messages):
        raise AssertionError("the model must not be called without evidence")
    r, _ = run_agent(catalog, qdrant, forbidden, question="完全無關的問題 xyz", names=["實驗室管理專區"])
    assert r["answer_main"].startswith("在這個專區的資料裡找不到") and r["citations"] == []


def test_attached_files_are_searched_and_cited(catalog, qdrant):
    files = {"abc": {"name": "mine.txt", "chunks": [{"index": 0, "label": "第 1 段", "text": "校驗報告摘要：12 個月內有效"}]}}
    seen = {}

    def complete(messages):
        seen["prompt"] = messages[-1]["content"]
        return "你的檔案提到有效期 12 個月 [S2]。"
    r, events = run_agent(catalog, qdrant, complete, files=files)
    assert "mine.txt" in seen["prompt"] and r["citations"][0]["publisher"] == "使用者上傳" and r["grounding"]["flagged"] == [] and any(e.get("label") == "讀取你上傳的檔案" for e in events)


def test_followups_and_grounding_helpers():
    assert split_followups("答案。\n追問：甲｜乙｜丙｜丁") == ("答案。", ["甲", "乙", "丙"])
    assert split_followups("只有答案") == ("只有答案", [])
    assert grounding("數值 649 Mbps [S1]", "吞吐量 649 Mbps", 1, 1)["summary"]["values_verified"] == 1


# ---------- HTTP ----------
class FakeRedis:
    def __init__(self):
        self.kv, self.lists = {}, {}

    def set(self, k, v, ex=None):
        self.kv[k] = v

    def get(self, k):
        return self.kv.get(k)

    def rpush(self, k, v):
        self.lists.setdefault(k, []).append(v)

    def lrange(self, k, a, b):
        return self.lists.get(k, [])[a:b + 1]

    def expire(self, *a):
        pass

    def exists(self, k):
        return k in self.kv


@pytest.fixture
def client(monkeypatch, catalog, qdrant):
    redis = FakeRedis()
    qdrant.wanted = "校驗"
    monkeypatch.setattr(zone_routes, "_catalog", lambda: catalog)
    monkeypatch.setattr(zone_routes, "_redis", lambda: redis)
    monkeypatch.setattr(zone_routes, "_complete", lambda: complete_ok)
    monkeypatch.setattr(zone_routes, "_digest", lambda: DigestService(None))
    monkeypatch.setattr(zone_routes, "_feedback_enabled", lambda: True)
    zone_routes._pool = SimpleNamespace(submit=lambda fn, *a: fn(*a))          # run the answer inline
    app = FastAPI()
    user = {"sub": "u1", "instance_id": "da40"}

    @app.middleware("http")
    async def ident(request, call_next):
        if request.headers.get("x-user") != "none":
            request.state.km_identity = {"sub": request.headers.get("x-user", "u1"), "instance_id": "da40"}
        return await call_next(request)
    app.include_router(zone_routes.router)
    return TestClient(app)


def test_the_page_endpoints_answer_in_the_wifi_pages_shapes(client):
    o = client.get("/api/zones/equipment/overview").json()
    assert o["counts"]["current_documents"] == 1 and "by_category" in o and "processing" in o
    d = client.get("/api/zones/equipment/documents").json()
    assert d["total"] == 1 and d["facets"]["document_roles"] == [["手冊", 1]]
    rid = d["documents"][0]["revision_id"]
    detail = client.get(f"/api/zones/equipment/documents/{rid}").json()
    assert detail["document"]["title"] == "n9020b.txt" and len(detail["versions"]) == 2
    assert client.get(f"/api/zones/equipment/documents/{rid}/chunks").json()["total"] == 1
    assert client.get("/api/zones/equipment/documents/nope/chunks").status_code == 404
    s = client.post("/api/zones/equipment/search", json={"query": "校驗"}).json()
    assert s["results"][0]["source"] == "n9020b.txt" and "content" in s["results"][0]
    f = client.get("/api/zones/csit/feed").json()
    assert "digest" in f and "updates" in f and f["digest"]["items"]


def test_zone_ids_and_login_are_enforced(client):
    assert client.get("/api/zones/wifi/overview").status_code == 404 and client.get("/api/zones/nowhere/overview").status_code == 404
    assert client.get("/api/zones/equipment/overview", headers={"x-user": "none"}).status_code == 401
    assert client.get("/api/zones/csit/overview").json()["attention"][0]["title"] == "1 份文件待分類"        # the page 'csit' is 產品驗證專區 and lists what is unplaced


def test_asking_returns_a_task_with_events_and_a_result_only_the_asker_can_read(client):
    r = client.post("/api/zones/equipment/agent", json={"question": "頻譜分析儀多久校驗"})
    assert r.status_code == 202 and r.json()["stream"] is True and r.json()["feedback"] is True
    tid = r.json()["task_id"]
    ev = client.get(f"/api/zones/equipment/agent/{tid}/events").json()
    assert ev["done"] is True and ev["events"][-1]["type"] == "done" and ev["events"][-1]["status"] == "completed"
    res = client.get(f"/api/zones/equipment/agent/{tid}").json()
    assert res["status"] == "completed" and res["citations"] and "owner" not in res
    assert client.get(f"/api/zones/equipment/agent/{tid}", headers={"x-user": "other"}).status_code == 404
    assert client.get(f"/api/zones/equipment/agent/{tid}/events", headers={"x-user": "other"}).status_code == 404
    assert client.get("/api/zones/equipment/agent/unknown-id").status_code == 404


def test_a_failed_answer_is_reported_not_lost(client, monkeypatch):
    def boom(messages):
        raise RuntimeError("model down")
    monkeypatch.setattr(zone_routes, "_complete", lambda: boom)
    tid = client.post("/api/zones/equipment/agent", json={"question": "頻譜分析儀多久校驗"}).json()["task_id"]
    assert client.get(f"/api/zones/equipment/agent/{tid}").json()["status"] == "failed"
    assert client.get(f"/api/zones/equipment/agent/{tid}/events").json()["done"] is True


def test_feedback_is_kept_for_the_asker_only(client, tmp_path, monkeypatch):
    from src.web_api import wifi8_routes
    monkeypatch.setattr(wifi8_routes, "_wifi8_root", lambda: tmp_path)
    tid = client.post("/api/zones/equipment/agent", json={"question": "頻譜分析儀多久校驗"}).json()["task_id"]
    assert client.get("/api/zones/equipment/agent-feedback/options").json()["reasons"]
    ok = client.post(f"/api/zones/equipment/agent/{tid}/feedback", json={"rating": "up"})
    assert ok.status_code == 200 and list((tmp_path / "zones" / "equipment" / "feedback").glob("*.json"))
    assert client.post(f"/api/zones/equipment/agent/{tid}/feedback", json={"rating": "up"}, headers={"x-user": "other"}).status_code == 404


def test_attached_file_config_is_enabled(client):
    c = client.get("/api/zones/equipment/files/config").json()
    assert c["enabled"] is True and "max_bytes" in c


def test_a_reference_after_the_full_stop_counts_for_its_sentence():
    g = grounding("校驗每年一次。[S1]\n\n並要登記資產編號。[S1]", "校驗每年一次，登記資產編號", 1, 1)["summary"]
    assert g["claims"] == 2 and g["claims_cited"] == 2


def test_an_answer_that_found_nothing_cites_nothing(catalog, qdrant):
    r, _ = run_agent(catalog, qdrant, lambda m: "在這個專區的資料裡找不到相關內容。資料中只有校驗的內容。[S1]")
    assert r["citations"] == [] and r["extension"]["related"] == ""


def test_the_not_found_sentence_may_name_the_topic(catalog, qdrant):
    r, _ = run_agent(catalog, qdrant, lambda m: "在這個專區的資料裡找不到「火星」相關內容。資料只有校驗的內容。[S1]")
    assert r["citations"] == []


def _hit(score, text):
    return {"score": score, "doc": {}, "chunk": {"content": text}}


def test_a_question_naming_two_things_reaches_both_even_when_one_matches_every_word_better():
    ng = [_hit(0.9 - i / 100, f"NG Handover 第 {i} 次 SCU2050") for i in range(10)]
    xn = [_hit(0.5 - i / 100, f"Xn Handover 第 {i} 次 SCU2050") for i in range(5)]
    hits = ng + xn
    plain = hits[:8]
    assert not any("Xn" in h["chunk"]["content"] for h in plain)
    chosen = spread(hits, "NG 和 Xn 換手的結果有什麼差別?", 8)
    assert len(chosen) == 8
    assert sum("Xn" in h["chunk"]["content"] for h in chosen) == 3
    assert sum("NG" in h["chunk"]["content"] for h in chosen) == 5
    assert [h["score"] for h in chosen] == sorted((h["score"] for h in chosen), reverse=True)


def test_one_name_or_a_name_no_passage_mentions_changes_nothing():
    hits = [_hit(0.9 - i / 100, f"NG Handover {i}") for i in range(12)]
    assert spread(hits, "NG 結果", 8) == hits[:8]
    assert spread(hits, "NG 和 Zeta 的差別", 8) == hits[:8]
