"""Equipment aggregate: what is a conflict and what is not (CSIT's review of 2026-11-23, equipment 6666: 7 'conflicts' that were not).
Runs under pytest and on its own: python tests/csit_v1/test_equipment_aggregate_conflicts.py"""
import sys
import traceback
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.csit_integration_v1.equipment_aggregate import V2JobMetadataSource, analyze  # noqa: E402
from src.csit_integration_v1.equipment_aggregate_models import EquipmentAggregateRequest  # noqa: E402


def _fid(n):
    return str(uuid.UUID(int=n))


def _sha(n):
    return format(n, "064x")


def _result(technical=None, specs=None, measurements=None):
    return {"metadataSchemaVersion": "2.0",
            "document": {"title": None, "documentType": "Specification", "summary": None, "language": "en", "documentDate": None, "authors": [], "department": None,
                         "documentVersionLabel": None, "keywords": [], "tags": []},
            "technical": {"productNames": [], "modelNumbers": [], "vendorNames": [], "technologies": [], "standards": [], "softwareVersions": [], "hardwareVersions": [],
                          "projectNames": [], "testItems": [], "measurements": measurements or [], "issueKeys": [], "errorCodes": [], **(technical or {})},
            "extraction": {"sourceFormat": "pdf", "method": "Text", "pageCount": 1, "sheetNames": [], "extractedCharacterCount": 100, "ocrUsed": False},
            "indexing": {"status": "Completed", "indexId": "i", "chunkCount": 1, "indexedAt": "2026-11-23T00:00:00Z"},
            "warnings": [], "sourceSpecific": {"specifications": specs or [], "capabilitySummary": None, "limitations": []}}


def _run(*docs):
    """docs: (technical, specs, measurements) per document -> the aggregate result."""
    rows, request_docs = [], []
    for n, (tech, specs, meas) in enumerate(docs, start=1):
        rows.append({"document_id": uuid.UUID(_fid(n)), "version": 1, "expected_sha256": _sha(n), "km_job_id": "KM-ING-%06d" % n, "status": "Completed",
                     "result_json": _result(tech, specs, meas)})
        request_docs.append({"fileId": _fid(n), "version": 1, "sha256": _sha(n), "kmJobId": "KM-ING-%06d" % n, "analysisResultId": str(uuid.UUID(int=1000 + n)),
                             "fileName": "doc%d.pdf" % n, "analyzedAt": "2026-11-23T00:00:00Z"})
    req = EquipmentAggregateRequest.model_validate({"schemaVersion": "1.0", "requestId": str(uuid.uuid4()), "sourceSystem": "CSIT", "moduleCode": "equipment", "apparatusId": "6666",
                                                    "manifestHash": _sha(999), "analysisVersion": "1.0", "documents": request_docs, "requestedAt": "2026-11-23T00:00:00Z"})
    return analyze(req, V2JobMetadataSource(rows))


def spec(result, name):
    return next((s for s in result["technicalSpecifications"] if s["name"] == name), None)


S = lambda field, value, unit=None: {"field": field, "value": value, "unit": unit}


def test_equipment_6666_case_has_no_false_conflicts():
    """The two Anritsu MT8821C documents: one brochure listing base and optional frequency and 4x4/8x8 MIMO, one deck comparing three models."""
    brochure = ({"vendorNames": ["ANRITSU"], "modelNumbers": ["MT8821C"], "productNames": ["Radio Communication Analyzer"], "technologies": ["LTE-Advanced", "WLAN", "GSM"],
                 "standards": ["3GPP TS 36.521-1"]},
                [S("frequency", "30 MHz to 3.8 GHz"), S("frequency", "3.8 GHz to 6.0 GHz (Option)"), S("MIMO", "4 x 4"), S("MIMO", "8 x 8"),
                 S("Supported 3GPP/3GPP2 Standards", "GSM (GPRS, EGPRS)"), S("Supported 3GPP/3GPP2 Standards", "TD-SCDMA")], None)
    deck = ({"vendorNames": ["Anritsu"], "modelNumbers": ["MT8820C", "MT8821C", "MT8870A"], "productNames": ["One Box Tester"], "technologies": ["LTE-A", "WLAN", "HSPA"],
             "standards": ["3GPP", "3GPP TS 34.121-1"]}, [S("CA Supports", "4 CA")], None)
    r = _run(brochure, deck)
    assert r["conflicts"] == [], r["conflicts"]
    assert spec(r, "frequency")["value"] == "30 MHz to 3.8 GHz"                                   # the base range, on its own
    assert spec(r, "frequency（Option）")["value"] == "3.8 GHz to 6.0 GHz"                         # the option, with its condition
    assert spec(r, "MIMO")["value"] == "4 x 4；8 x 8"
    assert "MT8820C" in spec(r, "型號")["value"] and "MT8870A" in spec(r, "型號")["value"]
    assert spec(r, "廠牌")["value"].lower() == "anritsu" and len(spec(r, "廠牌")["evidenceIds"]) == 2      # same maker written twice is one maker, both documents as evidence
    assert "WLAN" in spec(r, "技術")["value"] and "HSPA" in spec(r, "技術")["value"]
    assert any("多個型號" in w for w in r["warnings"]) and not any("不一致" in w for w in r["warnings"])


def test_two_documents_giving_disjoint_values_for_the_same_field_and_condition_are_a_conflict():
    r = _run((None, [S("重量", "2 kg")], None), (None, [S("重量", "3 kg")], None))
    assert [c["field"] for c in r["conflicts"]] == ["重量"] and spec(r, "重量") is None
    assert "2 kg" in r["conflicts"][0]["description"] and "3 kg" in r["conflicts"][0]["description"] and len(r["conflicts"][0]["evidenceIds"]) == 2
    assert any("不一致" in w for w in r["warnings"])


def test_a_document_that_says_more_than_another_does_not_contradict_it():
    r = _run((None, [S("頻寬", "20 MHz"), S("頻寬", "40 MHz")], None), (None, [S("頻寬", "20 MHz")], None))
    assert r["conflicts"] == [] and spec(r, "頻寬")["value"] == "20 MHz；40 MHz"


def test_the_same_field_under_different_conditions_in_different_documents_is_no_conflict():
    r = _run((None, [S("frequency", "5 GHz (Option)")], None), (None, [S("frequency", "2.4 GHz")], None))
    assert r["conflicts"] == [] and (spec(r, "frequency（Option）")["value"], spec(r, "frequency（Option）")["unit"]) == ("5", "GHz") and (spec(r, "frequency")["value"], spec(r, "frequency")["unit"]) == ("2.4", "GHz")


def test_a_different_maker_in_another_document_is_still_a_conflict():
    r = _run(({"vendorNames": ["Askey"]}, [S("重量", "2kg")], None), ({"vendorNames": ["OtherCo"]}, [S("頻率", "5GHz")], None))
    c = next(c for c in r["conflicts"] if c["field"] == "廠牌")
    assert "Askey" in c["description"] and "OtherCo" in c["description"] and spec(r, "廠牌") is None


def test_one_measurement_per_context_still_stands_and_the_same_fact_is_not_shown_twice():
    m = [{"metric": "frequency", "value": "30 MHz to 3.8 GHz", "unit": None, "context": "Radio Communication Analyzer"}]
    r = _run((None, [S("RF", "yes")], m), (None, [S("RF", "yes")], m))
    assert r["conflicts"] == [] and sum(1 for s in r["technicalSpecifications"] if s["name"] == "frequency（Radio Communication Analyzer）") == 1


def test_agreeing_documents_still_merge_with_both_sources():
    r = _run(({"vendorNames": ["Askey"], "modelNumbers": ["FSW26"]}, [S("重量", "2kg")], None), ({"vendorNames": ["Askey"]}, [S("頻率", "5GHz")], None))
    assert spec(r, "廠牌")["value"] == "Askey" and len(spec(r, "廠牌")["evidenceIds"]) == 2 and spec(r, "型號")["value"] == "FSW26" and r["conflicts"] == []


if __name__ == "__main__":
    bad = 0
    for name, fn in sorted((k, v) for k, v in dict(globals()).items() if k.startswith("test_")):
        try:
            fn()
            print("PASS", name)
        except Exception:  # noqa: BLE001
            bad += 1
            print("FAIL", name)
            traceback.print_exc()
    print("OVERALL:", "ALL PASS" if not bad else f"{bad} FAILED")
    sys.exit(1 if bad else 0)
