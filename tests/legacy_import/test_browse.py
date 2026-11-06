"""Zone search / Q&A / catalogue for imported legacy documents (fakes, no stores, no model)."""
import re
from types import SimpleNamespace

from src.legacy_import import browse


def point(pid, doc, index, text, **extra):
    payload = {"document_id": doc, "title": f"T-{doc}", "source_paths": [f"NAS/{doc}.pdf"], "topic_zone": "WiFi 知識專區", "l1": "A", "l2": "B", "l3": "C",
               "chunk_index": index, "chunk_text": text, "document_type": "Manual", "needs_review": False, **extra}
    return SimpleNamespace(id=pid, payload=payload)


class FakeClient:
    def __init__(self, dense, sparse):
        self.dense, self.sparse, self.calls = dense, sparse, []

    def query_points(self, collection, query, using, query_filter, limit, with_payload):
        self.calls.append((using, query_filter))
        return SimpleNamespace(points=self.dense if using == browse.DENSE else self.sparse)


def conditions(flt):
    return {c.key: c.match.value for c in flt.must}


def test_search_filters_by_origin_and_zone_and_fuses_both_rankings():
    a, b, c = point(1, "d1", 0, "alpha"), point(2, "d2", 0, "beta"), point(3, "d1", 1, "gamma")
    client = FakeClient([a, b], [b, c])
    hits = browse.ZoneSearch(client, lambda t: [[0.1, 0.2]], lambda q: ([1], [1.0])).search("q", zone="WiFi 知識專區", l1="A")
    assert [h["document_id"] for h in hits] == ["d2", "d1"]                # d2 is ranked by both retrievers
    assert hits[1]["passages"][0]["text"] == "alpha" and len(hits[1]["passages"]) == 2
    for _, flt in client.calls:
        assert conditions(flt) == {"origin": "legacy_nas", "topic_zone": "WiFi 知識專區", "l1": "A"}


def test_search_without_keyword_terms_uses_dense_only():
    client = FakeClient([point(1, "d1", 0, "x")], [])
    browse.ZoneSearch(client, lambda t: [[0.1]], lambda q: ([], [])).search("q", zone="z")
    assert [using for using, _ in client.calls] == [browse.DENSE]


def test_answer_cites_sources_and_skips_the_model_without_evidence():
    hits = [{"document_id": "d1", "title": "T1", "source_paths": ["NAS/d1.pdf"], "topic_zone": "Z", "l1": "A", "l2": "B", "l3": "",
             "passages": [{"chunk_index": 0, "text": "內容甲"}, {"chunk_index": 1, "text": "內容乙"}, {"chunk_index": 2, "text": "內容丙"}]}]
    seen = {}

    def complete(messages):
        seen["prompt"] = messages[-1]["content"]
        return " 答案 [S1] "

    out = browse.answer(complete, "問題?", hits)
    assert out["answer"] == "答案 [S1]" and out["grounded"] and [c["ref"] for c in out["citations"]] == ["S1", "S2"]
    assert "[S1] T1" in seen["prompt"] and "內容丙" not in seen["prompt"]   # at most two passages per document
    assert out["citations"][0]["category"] == "A / B"

    def forbidden(messages):
        raise AssertionError("model must not be called without evidence")

    empty = browse.answer(forbidden, "問題?", [])
    assert empty["grounded"] is False and empty["citations"] == []


class FakeDriver:
    def __init__(self):
        self.runs = []

    def session(self, **kw):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.runs.append((query, params))
        return [SimpleNamespace(data=lambda: {"n": 3, "doc": {"title": "t"}, "l1": "A", "l2": None, "l3": None, "entities": [{"kind": "Model", "name": "X1"}, {"kind": None, "name": None}]})]


def test_catalogue_binds_every_parameter_and_only_reads_legacy_labels():
    driver = FakeDriver()
    catalogue = browse.ZoneCatalogue(driver)
    catalogue.zones()
    catalogue.categories("Z")
    catalogue.documents("Z", l1="A", l3="C", text="abc", skip=5, limit=500)
    catalogue.document("id1")
    for query, params in driver.runs:
        assert set(re.findall(r"\$(\w+)", query)) <= set(params), query[:70]
        assert not re.search(r"\b(CREATE|MERGE|DELETE|SET)\b", query), query[:70]
        assert all(label.startswith("Legacy") for label in re.findall(r"\(\w*:(\w+)", query))
    listing = [p for q, p in driver.runs if "SKIP" in q][0]
    assert listing["limit"] == 200 and listing["skip"] == 5 and listing["l1"] == "A"


# ---------- documents delivered by CSIT, in the zone KM decided for them ----------
class CsitClient(FakeClient):
    def __init__(self, dense, sparse, csit):
        super().__init__(dense, sparse)
        self.csit, self.csit_calls = csit, []

    def query_points(self, collection, query, using, query_filter, limit, with_payload):
        is_csit = collection in self.csit and (collection != browse.COLLECTION or any(c.key == "source_system" for c in query_filter.must))  # the shared collection serves both
        if is_csit:
            self.csit_calls.append((collection, using, query_filter))
            out = self.csit[collection]
            if isinstance(out, Exception):
                raise out
            return SimpleNamespace(points=out)
        return super().query_points(collection, query, using, query_filter, limit, with_payload)


def csit_point(pid, doc, text, zone="認證知識專區", **extra):
    return SimpleNamespace(id=pid, payload={"document_file_id": doc, "doc_name": f"{doc}.pdf", "content": text, "topic_zone": zone, "classification": {"l1": None, "l2": None, "l3": None},
                                            "source_type": "DocumentLibraryFile", "chunk_index": 0, **extra})


def test_csit_documents_are_searched_in_their_zone_and_merged_by_rank():
    legacy = point(1, "legacy1", 0, "舊資料", topic_zone="認證與法規知識專區")
    client = CsitClient([legacy], [legacy], {"km_csit_docs": [csit_point(10, "c1", "CSIT 文件內容")], "knowledge_base": [], "ai_km_knowledge_v1": [csit_point(11, "r1", "x")]})
    search = browse.ZoneSearch(client, lambda t: [[0.1]], lambda q: ([1], [1.0]))
    hits = search.search("q", zone="認證與法規知識專區", csit_zones=["認證知識專區", "認證與法規知識專區"])
    assert {h["document_id"] for h in hits} == {"legacy1", "c1", "r1"}
    assert next(h for h in hits if h["document_id"] == "c1")["passages"][0]["text"] == "CSIT 文件內容" and next(h for h in hits if h["document_id"] == "c1")["origin"] == "csit"
    by_collection = {c: flt for c, _, flt in client.csit_calls}
    zone_condition = next(c for c in by_collection["km_csit_docs"].must if c.key == "topic_zone")
    assert set(zone_condition.match.any) == {"認證知識專區", "認證與法規知識專區"}
    assert [c.key for c in by_collection["km_csit_docs"].must_not] == ["index_state"]                      # a superseded version is not an answer
    assert {c.key for c in by_collection["ai_km_knowledge_v1"].must} == {"topic_zone", "source_system"}   # legacy points in the shared collection are not taken twice


def test_nothing_from_csit_is_read_unless_the_caller_names_the_zone_values():
    client = CsitClient([point(1, "d1", 0, "x")], [], {"km_csit_docs": [csit_point(10, "c1", "x")]})
    hits = browse.ZoneSearch(client, lambda t: [[0.1]], lambda q: ([], [])).search("q", zone="WiFi 知識專區")
    assert [h["document_id"] for h in hits] == ["d1"] and client.csit_calls == []


def test_a_missing_csit_collection_only_means_no_csit_hits():
    client = CsitClient([point(1, "d1", 0, "x")], [], {"km_csit_docs": RuntimeError("Collection not found"), "knowledge_base": [csit_point(12, "r2", "報告內容", zone="產品驗證專區")],
                                                       "ai_km_knowledge_v1": RuntimeError("not found")})
    hits = browse.ZoneSearch(client, lambda t: [[0.1]], lambda q: ([], [])).search("q", zone="WiFi 知識專區", csit_zones=["產品驗證專區"])
    assert {h["document_id"] for h in hits} == {"d1", "r2"}


def test_the_legacy_category_filters_leave_csit_documents_out():
    client = CsitClient([point(1, "d1", 0, "x")], [], {"km_csit_docs": [csit_point(10, "c1", "x")]})
    hits = browse.ZoneSearch(client, lambda t: [[0.1]], lambda q: ([], [])).search("q", zone="WiFi 知識專區", l1="A", csit_zones=["認證知識專區"])
    assert [h["document_id"] for h in hits] == ["d1"] and client.csit_calls == []


def test_the_route_maps_a_page_key_or_a_name_to_the_zone_values():
    from src.web_api import legacy_routes
    assert legacy_routes._csit_zones("mobile")[0] == "行動通訊知識專區" and "4G/5G 知識專區" in legacy_routes._csit_zones("mobile")
    assert legacy_routes._csit_zones("csit")[0] == "產品驗證專區"                       # the page "csit" is 產品驗證專區
    assert legacy_routes._csit_zones("認證與法規知識專區")[0] == "認證知識專區"
    assert legacy_routes._csit_zones("nowhere") is None
