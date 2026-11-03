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
