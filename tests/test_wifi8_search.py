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
