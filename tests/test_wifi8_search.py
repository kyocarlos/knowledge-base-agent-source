import pytest
from qdrant_client import QdrantClient

from src.wifi8.importer import Wifi8Importer, Wifi8Settings
from src.wifi8.search import SearchOptions, SearchUnavailable, Wifi8Search, query_terms
from tests.test_wifi8_import import FakeEncoder, doc, make_package, run, seg

DOCS = [
    doc("mesh", "Mesh Network Design Guide", publisher="Askey"),
    doc("big", "3GPP TS 38.300 NR Overall Description", publisher="3GPP", wfa_document_id=""),
    doc("elr2", "ELR MRD v2", supersedes=["elr1"], publisher="WFA", wfa_document_id="104438"),
    doc("elr1", "ELR MRD v1", eligible=False, publisher="WFA", wfa_document_id="104437"),
    doc("bcm", "BCM43840 Product Brief", publisher="Broadcom", wfa_document_id=""),
]
SEGS = (
    [seg("mesh", 1, "節點擺放：主節點放中心位置，子節點間距 10-15 公尺，漫遊門檻 -70 dBm。")]
    + [seg("big", i, f"NR RAN architecture overview paragraph {i} about network design and gNB.", {"type": "page", "page": i}) for i in range(1, 60)]
    + [seg("elr2", 1, "Extended Long Range (ELR) improves uplink range for low-rate clients."),
       seg("elr2", 2, "ELR uses a new preamble and repetition.", {"type": "page", "page": 2}),
       seg("elr1", 1, "Draft ELR text with old preamble design.")]
    + [seg("bcm", 1, "BCM43840 supports ELR, NPCA and DSO for Wi-Fi 8 access points.")]
)


@pytest.fixture
def engine(tmp_path):
    client = QdrantClient(":memory:")
    settings = Wifi8Settings(root=tmp_path / "wifi8", collection="wifi8_test", embed_batch_size=50, chunk_max_chars=80)
    encoder = FakeEncoder()
    importer = Wifi8Importer(settings, qdrant=client, encoder=encoder, embedding_model="fake")
    path = tmp_path / "p.zip"
    make_package(path, DOCS, SEGS)
    assert run(importer, importer.submit(path, submitted_by="t"))["status"] == "completed"
    return Wifi8Search.for_current(importer, qdrant=client, encoder=encoder, embedding_model="fake"), importer, client


def titles(result):
    return [r["source"] for r in result["results"]]


def test_small_document_is_not_crowded_out(engine):
    search, *_ = engine
    result = search.search("Mesh network design", SearchOptions(top_k=5, per_document=2))
    assert "Mesh Network Design Guide" in titles(result)
    assert titles(result).count("3GPP TS 38.300 NR Overall Description") <= 2


def test_two_char_cjk_term_matches(engine):
    search, *_ = engine
    assert query_terms("漫遊") == ["漫遊"]  # below the trigram minimum: literal match path
    assert titles(search.search("漫遊", SearchOptions(top_k=3)))[0] == "Mesh Network Design Guide"
    assert titles(search.search("漫遊門檻是多少？", SearchOptions(top_k=3)))[0] == "Mesh Network Design Guide"


def test_superseded_versions_excluded_unless_history(engine):
    search, *_ = engine
    assert "ELR MRD v1" not in titles(search.search("ELR preamble", SearchOptions(top_k=10)))
    assert "ELR MRD v1" in titles(search.search("ELR preamble", SearchOptions(top_k=10, include_history=True)))


def test_publisher_and_wfa_id_become_filters(engine):
    search, *_ = engine
    result = search.search("Broadcom ELR support", SearchOptions(top_k=10))
    assert result["filters"]["publishers"] == ["Broadcom"]
    assert set(titles(result)) == {"BCM43840 Product Brief"}
    result = search.search("104438 preamble", SearchOptions(top_k=10))
    assert set(titles(result)) == {"ELR MRD v2"}


def test_results_carry_citation_fields(engine):
    search, *_ = engine
    hit = search.search("ELR uplink range", SearchOptions(top_k=1))["results"][0]
    assert hit["source"] == "ELR MRD v2" and hit["wfa_document_id"] == "104438"
    assert hit["location_label"] and hit["matched_by"]
    assert hit["storage_category"] == "WiFi"


def test_unavailable_without_import_or_on_model_mismatch(tmp_path, engine):
    empty = Wifi8Importer(Wifi8Settings(root=tmp_path / "none"))
    with pytest.raises(SearchUnavailable):
        Wifi8Search.for_current(empty)
    _, importer, client = engine
    with pytest.raises(SearchUnavailable, match="mismatch"):
        Wifi8Search.for_current(importer, qdrant=client, encoder=FakeEncoder(), embedding_model="other")


def test_reranker_reorders_fused_candidates_and_keeps_per_document_limit(engine):
    from src.wifi8.rerank import Reranker, RerankSettings
    search, importer, client = engine
    baseline = search.search("ELR uplink range", SearchOptions(top_k=5))["results"]
    seen = []

    def score(query, passages):
        seen.append((query, passages))
        # Prefer the Broadcom brief over everything else, otherwise keep the fused order.
        return [10.0 if "BCM43840" in p else -float(i) for i, p in enumerate(passages)]

    reranked = Wifi8Search(search.store, encoder=search.encoder,
                           reranker=Reranker(RerankSettings(model="fake", candidates=50, chars=200), score))
    results = reranked.search("ELR uplink range", SearchOptions(top_k=5))["results"]
    assert seen and seen[0][0] == "ELR uplink range" and all(len(p) <= 200 + 80 for p in seen[0][1])
    assert all("rerank_score" in r for r in results)
    scores = [r["rerank_score"] for r in results]
    assert scores == sorted(scores, reverse=True)  # results follow the reranker, not the fused order
    assert len(results) == len(baseline)
    per_doc = {}
    for r in results:
        per_doc[r["revision_id"]] = per_doc.get(r["revision_id"], 0) + 1
    assert max(per_doc.values()) <= SearchOptions().per_document


def test_reranker_only_scores_the_configured_number_of_candidates(engine):
    from src.wifi8.rerank import Reranker, RerankSettings
    search, *_ = engine
    sizes = []
    reranked = Wifi8Search(search.store, encoder=search.encoder,
                           reranker=Reranker(RerankSettings(model="fake", candidates=3), lambda q, p: sizes.append(len(p)) or [0.0] * len(p)))
    results = reranked.search("NR RAN architecture", SearchOptions(top_k=8))["results"]
    assert sizes == [3]
    assert sum("rerank_score" in r for r in results) <= 3


def test_reranker_is_off_without_configuration(engine, monkeypatch):
    from src.wifi8 import rerank
    monkeypatch.delenv("KM_WIFI8_RERANK_MODEL", raising=False)
    assert rerank.from_environment() is None
    search, *_ = engine
    assert search.reranker is None
    assert all("rerank_score" not in r for r in search.search("ELR", SearchOptions())["results"])


SIBLINGS = [doc("pf1", "WFA - Wi-Fi 8 PF1 Report", publisher="WFA"), doc("ee1", "WFA - Wi-Fi 8 EE1 Report", publisher="WFA"),
            doc("v2a", "Vendor Note v2", publisher="Askey"), doc("v2b", "Other Note v2", publisher="Askey")]
SIBLING_SEGS = [seg("pf1", 1, "Results APUT table UHR-4.5.2 values 25 30 30"),
                seg("ee1", 1, "Results APUT table UHR-4.5.2 values 6 9 9"),
                seg("v2a", 1, "Results APUT table UHR-4.5.2 values 1 1 1"), seg("v2b", 1, "Results APUT table notes")]


@pytest.fixture
def siblings(tmp_path):
    client = QdrantClient(":memory:")
    settings = Wifi8Settings(root=tmp_path / "wifi8", collection="wifi8_siblings", embed_batch_size=50, chunk_max_chars=200)
    encoder = FakeEncoder()
    importer = Wifi8Importer(settings, qdrant=client, encoder=encoder, embedding_model="fake")
    path = tmp_path / "s.zip"
    make_package(path, SIBLINGS, SIBLING_SEGS)
    assert run(importer, importer.submit(path, submitted_by="t"))["status"] == "completed"
    return Wifi8Search.for_current(importer, qdrant=client, encoder=encoder, embedding_model="fake")


def test_named_documents_are_found_by_short_name_in_the_title(siblings):
    docs = siblings._documents()
    assert {docs[r]["title"] for r in siblings.named_documents("Wi-Fi 8 PF1 Report 的 APUT 結果", docs)} == {"WFA - Wi-Fi 8 PF1 Report"}
    assert {docs[r]["title"] for r in siblings.named_documents("ee1 results", docs)} == {"WFA - Wi-Fi 8 EE1 Report"}
    assert siblings.named_documents("what is v2 about", docs) == {}  # version labels are not document names
    assert siblings.named_documents("APUT results of all reports", docs) == {}


def test_title_weight_puts_the_named_sibling_first_and_leaves_other_questions_alone(siblings):
    question = "PF1 Report 的 APUT UHR-4.5.2 結果表"
    siblings.title_weight = 1.0
    plain = [r["source"] for r in siblings.search(question, SearchOptions(top_k=4))["results"]]
    siblings.title_weight = 1.5
    weighted = [r["source"] for r in siblings.search(question, SearchOptions(top_k=4))["results"]]
    assert weighted[0] == "WFA - Wi-Fi 8 PF1 Report"
    assert set(weighted) == set(plain)  # a weight reorders, it never drops results
    generic = "APUT UHR-4.5.2 結果表"
    siblings.title_weight = 1.0
    before = siblings.search(generic, SearchOptions(top_k=4))["results"]
    siblings.title_weight = 1.5
    assert [(r["point_id"], r["score"]) for r in siblings.search(generic, SearchOptions(top_k=4))["results"]] == [(r["point_id"], r["score"]) for r in before]


def test_document_name_in_the_question_counts_when_the_agent_rewrites_the_query(siblings):
    siblings.title_weight = 1.5
    rewritten = "APUT UHR-4.5.2 results"
    plain = siblings.search(rewritten, SearchOptions(top_k=4))["results"]
    asked = siblings.search(rewritten, SearchOptions(top_k=4, context="PF1 Report 的 APUT 結果表中，UHR-4.5.2 的數值各是多少？"))["results"]
    assert asked[0]["source"] == "WFA - Wi-Fi 8 PF1 Report"
    score = lambda results, title: next(r["score"] for r in results if r["source"] == title)  # noqa: E731
    assert score(asked, "WFA - Wi-Fi 8 PF1 Report") == pytest.approx(score(plain, "WFA - Wi-Fi 8 PF1 Report") * 1.5, rel=1e-3)
    assert score(asked, "WFA - Wi-Fi 8 EE1 Report") == score(plain, "WFA - Wi-Fi 8 EE1 Report")


def test_agent_search_is_limited_to_the_document_the_question_names(siblings):
    from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools
    tools = WifiTools(siblings, AgentSettings(), CitationRegistry())
    tools.question = "PF1 Report 的 APUT 結果表中，UHR-4.5.2 的數值各是多少？"
    scoped = tools.search_wifi("APUT UHR-4.5.2 results")
    assert {h["title"] for h in scoped["hits"]} == {"WFA - Wi-Fi 8 PF1 Report"}
    assert scoped["scope"]["documents"] == ["WFA - Wi-Fi 8 PF1 Report"]
    everything = tools.search_wifi("APUT UHR-4.5.2 results", all_documents=True)
    assert {"WFA - Wi-Fi 8 PF1 Report", "WFA - Wi-Fi 8 EE1 Report"} <= {h["title"] for h in everything["hits"]} and "scope" not in everything
    tools.question = "APUT 結果表的數值各是多少？"  # no document named: nothing is narrowed
    assert "scope" not in tools.search_wifi("APUT UHR-4.5.2 results")


def test_agent_search_falls_back_when_the_named_document_has_no_match(siblings):
    from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools
    tools = WifiTools(siblings, AgentSettings(), CitationRegistry())
    tools.question = "EE1 Report 的 notes 是什麼？"
    result = tools.search_wifi("zzzunmatchedterm qqqq", top_k=3)
    assert "scope" not in result or result["scope"]["documents"] == ["WFA - Wi-Fi 8 EE1 Report"]


def test_scoped_agent_search_does_not_downweight_figure_chunks(siblings):
    from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools
    seen = []
    real = siblings.search
    siblings.search = lambda query, options=None: (seen.append(options), real(query, options))[1]
    tools = WifiTools(siblings, AgentSettings(), CitationRegistry())
    tools.question = "PF1 Report 的 APUT 結果"
    tools.search_wifi("APUT results")
    assert seen[0].figure_focus is True and seen[0].revision_ids
    tools.question = "APUT 結果"
    tools.search_wifi("APUT results")
    assert seen[-1].figure_focus is None and not seen[-1].revision_ids


def test_unknown_filter_values_are_ignored_instead_of_returning_nothing(siblings):
    from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools
    tools = WifiTools(siblings, AgentSettings(), CitationRegistry())
    tools.question = "PF1 Report 的 APUT 結果"
    result = tools.search_wifi("APUT results", document_role="PF1 Report", publisher="No Such Vendor")
    assert result["ignored_filters"] == {"document_role": "PF1 Report", "publisher": "No Such Vendor"} and result["count"] > 0
    known = tools.search_wifi("APUT results", publisher="WFA")
    assert "ignored_filters" not in known and known["count"] > 0


def test_results_say_whether_they_are_the_document_the_question_names_when_the_search_is_not_scoped(siblings):
    from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools
    tools = WifiTools(siblings, AgentSettings(), CitationRegistry())
    tools.question = "PF1 Report 的 APUT 結果"
    wide = tools.search_wifi("APUT UHR-4.5.2 results", all_documents=True)
    flags = {h["title"]: h["is_named_document"] for h in wide["hits"]}
    assert flags["WFA - Wi-Fi 8 PF1 Report"] is True and flags["WFA - Wi-Fi 8 EE1 Report"] is False
    assert wide["named_documents_in_question"] == ["WFA - Wi-Fi 8 PF1 Report"]
    scoped = tools.search_wifi("APUT UHR-4.5.2 results")
    assert "is_named_document" not in scoped["hits"][0]  # everything in scope is the named document


def test_documents_counts_every_candidate_chunk_of_a_document(engine):
    search, *_ = engine
    per_chunk = search.search("NR RAN architecture overview gNB", SearchOptions(top_k=12))
    assert sum(1 for r in per_chunk["results"] if r["source"].startswith("3GPP")) <= 3  # the per-document cap of search()
    found = search.documents("NR RAN architecture overview gNB")
    top = found["results"][0]
    assert top["best"]["source"].startswith("3GPP") and top["matching_chunks"] > 3
    assert found["documents_found"] >= 1 and len({r["revision_id"] for r in found["results"]}) == len(found["results"])
    assert "ELR MRD v1" not in [r["best"]["source"] for r in search.documents("ELR preamble")["results"]]  # superseded stay out


def test_find_documents_tool_lists_documents_with_refs_and_ignores_unknown_filters(engine):
    from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools
    search, *_ = engine
    tools = WifiTools(search, AgentSettings(), CitationRegistry())
    result = tools.find_documents("ELR preamble", publisher="No Such Vendor")
    assert result["ignored_filters"] == {"publisher": "No Such Vendor"} and result["count"] > 0
    row = next(d for d in result["documents"] if d["title"] == "ELR MRD v2")
    assert row["ref"].startswith("S") and row["matching_chunks"] >= 1 and row["current_version"] is True
    assert tools.call("find_documents", {"query": "ELR preamble", "limit": 1})["count"] == 1
    assert "找不到" not in str(tools.call("find_documents", {"query": "ELR", "bogus": 1}).get("error", ""))  # bad arguments are reported, not raised


def test_documents_rank_a_document_that_matches_on_many_chunks_above_one_with_a_single_chunk(engine):
    search, *_ = engine
    ranked = search.documents("network design gNB")["results"]
    by_title = {r["best"]["source"]: r for r in ranked}
    assert by_title["3GPP TS 38.300 NR Overall Description"]["matching_chunks"] > by_title["Mesh Network Design Guide"]["matching_chunks"]
    assert ranked[0]["best"]["source"] == "3GPP TS 38.300 NR Overall Description"


AGENDAS = [doc("ag1", "WFA - TTG Agenda PF1", publisher="WFA"), doc("ag2", "WFA - TTG Agenda PF2", publisher="WFA"),
           doc("ag3", "WFA - TTG Agenda PF3", publisher="WFA"), doc("res", "WFA - Ballot Package Results", publisher="WFA")]
AGENDA_SEGS = ([seg(f"ag{n}", 1, "Blind Poll Questionnaire Review: Blind Poll will be launched on 4/6/2026") for n in (1, 2, 3)]
               + [seg("res", 1, "Blind Poll Methodology: web survey fielded April 6-20, 2026; 24 companies responded to the survey")])


@pytest.fixture
def agendas(tmp_path):
    client = QdrantClient(":memory:")
    settings = Wifi8Settings(root=tmp_path / "wifi8", collection="wifi8_agendas", embed_batch_size=50, chunk_max_chars=300)
    encoder = FakeEncoder()
    importer = Wifi8Importer(settings, qdrant=client, encoder=encoder, embedding_model="fake")
    path = tmp_path / "a.zip"
    make_package(path, AGENDAS, AGENDA_SEGS)
    assert run(importer, importer.submit(path, submitted_by="t"))["status"] == "completed"
    return Wifi8Search.for_current(importer, qdrant=client, encoder=encoder, embedding_model="fake")


def test_identical_text_repeated_across_versions_takes_one_slot(agendas):
    result = agendas.search("Blind Poll launched questionnaire", SearchOptions(top_k=10))
    repeated = [r for r in result["results"] if r["content"].startswith("Blind Poll Questionnaire")]
    assert len(repeated) == 1
    assert result["duplicates_hidden"] == 2
    assert "res" in {r["revision_id"] for r in agendas.search("Blind Poll companies responded survey", SearchOptions(top_k=2))["results"]}


def test_identical_text_is_kept_when_history_is_requested_or_the_document_is_named(agendas):
    history = agendas.search("Blind Poll launched questionnaire", SearchOptions(top_k=10, include_history=True))
    assert len([r for r in history["results"] if r["content"].startswith("Blind Poll Questionnaire")]) == 3
    assert history["duplicates_hidden"] == 0
    named = agendas.search("PF3 agenda Blind Poll launched questionnaire", SearchOptions(top_k=10))
    assert "ag3" in {r["revision_id"] for r in named["results"]}
