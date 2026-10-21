import json
from pathlib import Path

from qdrant_client.models import Filter, FieldCondition, MatchValue

from src.wifi8 import acceptance, store as store_module
from src.wifi8.search import SearchOptions
from tests.test_wifi8_search import engine  # noqa: F401

SPEC = json.loads((Path(__file__).resolve().parent.parent / "eval/wifi8/acceptance-spec.json").read_text(encoding="utf-8"))
CASES = [
    {"id": "c1", "question": "漫遊門檻是多少？", "gold": ["mesh"], "facts": []},
    {"id": "c2", "question": "ELR preamble", "gold": ["elr2"], "facts": []},
    {"id": "c3", "question": "Broadcom BCM43840 support", "gold": ["bcm"], "facts": []},
]


def by_id(rows):
    return {r["id"]: r for r in rows}


def with_policy(search, excluded=0):
    """The test package has no exclusion policy; real exports always record one."""
    record = search.store.record()
    manifest = record.setdefault("manifest", {})
    manifest["policy"] = {"excluded_confidentiality": ["internal"], "never_includes": ["mail body"]}
    manifest.setdefault("counts", {})["excluded"] = {"confidentiality:internal": excluded}


def run(search):
    return by_id(acceptance.run(CASES, SPEC, search)["rows"])


def test_a_healthy_package_passes_and_rerank_is_reported_as_not_enabled(engine):  # noqa: F811
    search, *_ = engine
    with_policy(search)
    rows = run(search)
    assert {k: v["status"] for k, v in rows.items() if k != "4.4"} == {k: "PASS" for k in rows if k != "4.4"}, rows
    assert rows["4.4"]["status"] == acceptance.NOT_ENABLED and rows["4.4"]["evidence"] == {"enabled": False}
    assert {"1.1", "1.5", "1.9", "4.1", "4.2", "4.3"} <= set(rows)


def first_point(search, **match):
    flt = search.store.chunk_filter(*[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in match.items()])
    return search.qdrant.scroll(search.collection, scroll_filter=flt, limit=1)[0][0]


def test_chunk_faults_are_caught(engine):  # noqa: F811
    search, *_ = engine
    point = first_point(search, revision_id="mesh")
    search.qdrant.set_payload(search.collection, {"content": "  ", "location": {}, "location_label": "", "vector_state": "pending"}, points=[point.id])
    row = run(search)["1.3"]
    assert row["status"] == acceptance.FAIL and row["evidence"]["problems"]["empty"] == 1 and row["evidence"]["problems"]["not_ready"] == 1


def test_missing_chunks_break_coverage_and_continuity(engine):  # noqa: F811
    search, *_ = engine
    big = first_point(search, revision_id="big", chunk_index=2)
    search.qdrant.delete(search.collection, points_selector=[big.id])
    rows = run(search)
    assert rows["1.4"]["status"] == acceptance.FAIL and rows["1.4"]["evidence"]["gaps"] == ["big"]
    assert rows["1.5"]["status"] == acceptance.FAIL


def test_metadata_drift_between_chunk_and_document_is_caught(engine):  # noqa: F811
    search, *_ = engine
    point = first_point(search, revision_id="elr2")
    search.qdrant.set_payload(search.collection, {"wfa_document_id": "WRONG"}, points=[point.id])
    row = run(search)["1.7"]
    assert row["status"] == acceptance.FAIL and row["evidence"]["differing"] == {"payload_wfa_document_id_differs": 1}


def test_a_replaced_document_that_is_still_current_fails_the_version_check(engine):  # noqa: F811
    search, *_ = engine
    documents = search.store.documents()
    elr1 = next(d for d in documents if d["revision_id"] == "elr1")
    elr1["analysis_eligible"] = True  # the replaced version slips back in
    search.store._documents = documents
    row = run(search)["1.9"]
    assert row["status"] == acceptance.FAIL and row["evidence"]["still_current"] == ["elr1"]


def test_excluded_confidentiality_must_not_stay_in_the_store(engine):  # noqa: F811
    search, *_ = engine
    with_policy(search, excluded=1)
    documents = search.store.documents()
    documents[0]["confidentiality"] = "internal"
    search.store._documents = documents
    row = run(search)["1.1"]
    assert row["status"] == acceptance.FAIL and row["evidence"]["leaked"] == [documents[0]["revision_id"]]


def test_a_package_without_an_exclusion_policy_is_not_accepted(engine):  # noqa: F811
    search, *_ = engine
    assert run(search)["1.1"]["status"] == acceptance.FAIL


def found(dense, lexical, hybrid):
    return {name: {"cases": 10, "hit_at_10": hit, "mrr": 0.5, "missed": []} for name, hit in (("dense", dense), ("lexical", lexical), ("hybrid", hybrid))}


def test_hybrid_check_compares_with_each_single_path(engine, monkeypatch):  # noqa: F811
    search, *_ = engine
    options = lambda: SearchOptions(top_k=10)  # noqa: E731
    for dense, lexical, hybrid, status in ((0.94, 0.91, 0.96, "PASS"), (0.97, 0.91, 0.94, "FAIL"), (0.80, 0.78, 0.85, "FAIL"), (0.94, 0.91, 0.93, "PASS")):
        monkeypatch.setattr(acceptance, "ablation", lambda *a, _f=found(dense, lexical, hybrid): _f)
        assert acceptance.check_hybrid(search, CASES, SPEC, options)[0]["status"] == status, (dense, lexical, hybrid)


def test_ablation_runs_each_path_alone_and_restores_the_search(engine):  # noqa: F811
    search, *_ = engine
    original = (search.vector, search.lexical)
    result = acceptance.ablation(search, CASES, lambda: SearchOptions(top_k=10))
    assert set(result) == {"dense", "lexical", "hybrid"} and all(v["cases"] == 3 for v in result.values())
    assert (search.vector, search.lexical) == original
    assert result["hybrid"]["hit_at_10"] >= max(result["dense"]["hit_at_10"], result["lexical"]["hit_at_10"]) - 0.34


def test_ablation_leaves_follow_up_questions_out_of_the_count(engine):  # noqa: F811
    search, *_ = engine
    follow_up = {"id": "h1", "question": "那它的門檻呢？", "gold": ["mesh"], "facts": [],
                 "history": [{"role": "user", "content": "漫遊是什麼？"}, {"role": "assistant", "content": "…"}]}
    result = acceptance.ablation(search, CASES + [follow_up], lambda: SearchOptions(top_k=10))
    assert all(v["cases"] == 3 and "h1" not in v["missed"] for v in result.values())


def test_citation_check_needs_a_place_on_every_result(engine, monkeypatch):  # noqa: F811
    search, *_ = engine
    real = search.search

    def without_location(query, options=None):
        result = real(query, options)
        for hit in result["results"]:
            hit["location_label"] = ""
        return result

    monkeypatch.setattr(search, "search", without_location)
    row = by_id(acceptance.check_citation_samples(search, CASES, SPEC, lambda: SearchOptions(top_k=3)))["4.3"]
    assert row["status"] == acceptance.FAIL and row["evidence"]["bad"]
