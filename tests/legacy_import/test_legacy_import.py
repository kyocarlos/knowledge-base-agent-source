"""Legacy (NAS) document import: taxonomy, grounded model output, chunking and the Qdrant / Neo4j writers (fakes, no model, no stores)."""
import json
import re

import pytest

from src.legacy_import import analyze, stores, taxonomy, textio

PATH = "認證專區/WiFi/各年度認證/2012/PKE1630-D38_Wi-Fi_Application Form.pdf"
TEXT = ("Wi-Fi Application Form\nDUT model PKE1630-D38 from Technicolor. Firmware v003.002.000. Standard IEEE 802.11n.\n"
        "Date of application 2012/04/12. Certification item: Wi-Fi CERTIFIED n.")


def reply(**override):
    data = {"classification": {"row_id": "4", "l2_value": "PKE1630-D38", "l3_value": "Wi-Fi", "technology": "Wi-Fi", "confidence": 0.9,
                               "evidence": "Wi-Fi Application Form"},
            "document": {"title": "Wi-Fi Application Form", "documentType": "Other", "summary": "認證申請表", "language": "en", "documentDate": "2012-04-12",
                         "authors": [], "department": None, "documentVersionLabel": None, "keywords": ["認證"], "tags": ["Wi-Fi"]},
            "technical": {"productNames": [], "modelNumbers": ["PKE1630-D38", "XYZ-999"], "vendorNames": ["Technicolor"], "technologies": ["Wi-Fi"],
                          "standards": ["IEEE 802.11n"], "softwareVersions": ["v003.002.000"], "hardwareVersions": [], "projectNames": [],
                          "testItems": [], "issueKeys": [], "errorCodes": []}}
    for key, value in override.items():
        section, _, name = key.partition("__")
        data[section][name] = value
    return json.dumps(data, ensure_ascii=False)


def run(**override):
    return analyze.analyze(lambda messages: "```json\n" + reply(**override) + "\n```", PATH, TEXT)


def test_table_has_the_expected_rows_and_zones():
    rows = taxonomy.load()
    assert len(rows) == 35 and {r.id for r in rows} >= {"1", "14", "30b", "34"} and "23" not in {r.id for r in rows}   # no catch-all row for cross-technology seminars
    ids = {r.id for r in taxonomy.choices(rows)}
    assert len(ids) == 37 and ids.isdisjoint({"3b", "30b"})         # Jira/Confluence rows are not files; HR, procurement and Time Report rows are ordinary rows
    assert {"29", "32", "33", "s1", "s2", "s3", "s4"} <= ids        # s1-s4: supplement rows for documents the CSIT table has no row for
    assert {r.id: r.topic for r in taxonomy.SUPPLEMENT} == {"s1": "固網寬頻知識專區", "s2": "設備預約知識專區", "s3": "實驗室與測試環境知識專區", "s4": "CSIT雜項專區"}
    zones = taxonomy.zones(rows)
    assert "WiFi 知識專區" in zones and "認證與法規知識專區" in zones and "部門與公司文管專區" in zones and "Confluence / Jira / TestRail 查詢專區" not in zones


def test_grounded_answer_is_accepted():
    result = run()
    assert result.row.id == "4" and result.row.topic == "認證與法規知識專區" and not result.needs_review
    assert (result.l2_value, result.l3_value, result.technology) == ("PKE1630-D38", "Wi-Fi", "Wi-Fi")
    assert result.document["documentDate"] == "2012-04-12" and result.document["title"] == "Wi-Fi Application Form"


def test_values_not_in_the_text_are_dropped():
    result = run()
    assert result.technical["modelNumbers"] == ["PKE1630-D38"]          # XYZ-999 is not in the document
    assert any("dropped" in w for w in result.warnings)
    assert run(document__documentDate="2013-01-01").document["documentDate"] is None   # a date the document does not state
    assert run(document__title="Invented Title").document["title"] is None


def test_unknown_row_or_missing_evidence_goes_to_review():
    bad_row = run(classification__row_id="999")
    assert bad_row.row is taxonomy.UNCLASSIFIED and bad_row.needs_review and bad_row.suggested_row is None
    no_evidence = run(classification__evidence="text that is nowhere in the file")
    assert no_evidence.row is taxonomy.UNCLASSIFIED and no_evidence.needs_review and no_evidence.suggested_row == "4" and no_evidence.confidence <= 0.4


def test_hr_procurement_and_time_report_documents_are_imported_into_their_rows_only_contracts_stay_out():
    held = run(classification__row_id="32")                              # the model names an HR document: an ordinary row now (no access rules)
    assert held.skip_reason is None and held.row.id == "32" and held.row.topic == "部門與公司文管專區"
    assert run(classification__row_id="33", classification__confidence=0.45).skip_reason is None
    for path in ("SIT文管專區/人力資源/人才管理學習.docx", "認證專區/認証預算/RD認証測試預算表.pptx", "設備廠商資訊/X/2015簽呈_X.docx",
                 "部門/Time Report/2020.xlsx", "DA40費用支出統計料號表/DA40_July.xlsx", "認證/DLNA Certification Quotation For Swisscom.xlsx"):
        assert taxonomy.sensitive_path(path) is None, path
    for path in ("廠商/Meshlink Druid contract V3.docx", "法務/NDA_Vendor.pdf", "廠商/保密協議.docx"):   # the topic table has no row for contracts
        assert taxonomy.sensitive_path(path), path
    for path in ("標準/IEEE Standard 802.11.pdf", "會議/Agenda 2015.docx"):          # "nda" only counts as a whole word
        assert taxonomy.sensitive_path(path) is None, path


def test_noise_files_are_left_out_but_documents_are_not():
    for path in ("WiFi/Drivers/Binaries/x.pdf", "VoIP/G729/readme.txt", "WiFi/tools/Readme.txt", "a\\Drivers\\v1\\notes.txt"):
        assert taxonomy.noise_path(path), path
    assert taxonomy.noise_path("xDSL Lab/DSLAM/Exceed/Program Files/Hummingbird/Connectivity/Default.txt")
    for path in ("WiFi/Test Plan/TR-398.pdf", "固網/ITU-T 規範摘要.docx", "認證/driver_test_report.pdf"):
        assert taxonomy.noise_path(path) is None, path


def test_supplement_rows_route_and_loose_json_is_accepted():
    row = run(classification__row_id="s1")
    assert row.row.id == "s1" and row.row.topic == "固網寬頻知識專區"
    loose = analyze.analyze(lambda m: reply(document__summary="a\tb").replace('"認證申請表"', '"認證申請表",'), PATH, TEXT)
    assert loose.row.id == "4"
    calls = []

    def flaky(messages):
        calls.append(messages)
        return "{ \"classification\": { \"row_id\": \"4\" \"x\": 1 }" if len(calls) == 1 else reply()

    again = analyze.analyze(flaky, PATH, TEXT)
    assert again.row.id == "4" and len(calls) == 2 and "合法 JSON" in calls[1][1]["content"]


def test_low_confidence_keeps_the_suggestion_but_not_the_zone():
    result = run(classification__confidence=0.3)
    assert result.row is taxonomy.UNCLASSIFIED and result.row.topic == "CSIT雜項專區" and result.needs_review and result.suggested_row == "4"


def test_enums_are_checked():
    result = run(document__documentType="Memo", classification__technology="LoRa")
    assert result.document["documentType"] == "Other" and result.technology is None


def test_unusable_model_output_raises():
    with pytest.raises(ValueError):
        analyze.analyze(lambda messages: "I cannot do that", PATH, TEXT)


def test_chunks_cover_the_text_and_respect_the_limit():
    text = "\n\n".join(f"段落{i} " + "字" * 300 for i in range(20)) + "\n\n" + "長" * 2000
    chunks = textio.chunk(text)
    assert all(0 < len(c) <= textio.CHUNK_CHARS for c in chunks)
    assert re.sub(r"\s", "", "".join(chunks)) == re.sub(r"\s", "", text)
    assert textio.chunk("") == []


def test_text_file_decoding_and_unsupported_format(tmp_path):
    big5 = tmp_path / "a.txt"
    big5.write_bytes("測試報告 Wi-Fi".encode("big5"))
    assert textio.extract_text(big5) == "測試報告 Wi-Fi"
    with pytest.raises(ValueError):
        textio.extract_text(tmp_path / "a.doc")


def make_record(**kw):
    result = run()
    return stores.record(sha256="ab" * 32, paths=[PATH, "other/copy.pdf"], batch="b1", result=result, chars=len(TEXT)) | kw


def test_document_identity_is_content_based():
    assert stores.document_id("ab" * 32) == stores.document_id("ab" * 32) != stores.document_id("cd" * 32)
    rec = make_record()
    assert rec["origin"] == "legacy_nas" and rec["source_system"] == "LEGACY_NAS" and rec["classification_basis"] == "llm_mapped"
    assert rec["topic_zone"] == "認證與法規知識專區" and rec["source_paths"][1] == "other/copy.pdf"


class FakeQdrant:
    def __init__(self):
        self.upserts, self.deletes = [], []

    def delete(self, collection, points_selector, wait):
        self.deletes.append(points_selector)

    def upsert(self, collection, points, wait):
        self.upserts.extend(points)


def test_qdrant_writer_tags_every_point_and_replaces_by_document():
    client = FakeQdrant()
    writer = stores.LegacyQdrantWriter(client, lambda texts: [[0.1] * 4 for _ in texts], lambda text: ([1, 2], [1.0, 1.0]), "bge")
    rec = make_record()
    assert writer.write(rec, ["第一段", "第二段", "第三段"]) == 3 and len(client.deletes) == 1
    payloads = [p.payload for p in client.upserts]
    assert {p["origin"] for p in payloads} == {"legacy_nas"} and {p["import_batch"] for p in payloads} == {"b1"}
    assert {p["visibility"] for p in payloads} == {"open"} and payloads[0]["topic_zone"] == "認證與法規知識專區"
    assert [p["chunk_index"] for p in payloads] == [0, 1, 2] and len({p.id for p in client.upserts}) == 3
    assert payloads[0]["model_numbers"] == ["PKE1630-D38"] and payloads[0]["l1"] == "外部認證資料"


class FakeSession:
    def __init__(self):
        self.runs = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.runs.append((query, params))

        class Consumed:
            def consume(self):
                return None
        return Consumed()


class FakeDriver:
    def __init__(self):
        self.session_obj = FakeSession()

    def session(self, **kw):
        return self.session_obj


def test_neo4j_writer_uses_legacy_labels_only_and_binds_every_parameter():
    driver = FakeDriver()
    writer = stores.LegacyNeo4jWriter(driver)
    writer.ensure()
    out = writer.write(make_record())
    assert out["entities"] >= 4
    for query, params in driver.session_obj.runs:
        assert set(re.findall(r"\$(\w+)", query)) <= set(params), query[:60]
        for label in re.findall(r"\(\w*:(\w+)", query):
            assert label.startswith("Legacy"), label                      # new CSIT-defined labels are never touched
    writer.purge("b1")
    purge = [q for q, _ in driver.session_obj.runs if "DETACH DELETE" in q]
    assert purge and "import_batch" in purge[0]
