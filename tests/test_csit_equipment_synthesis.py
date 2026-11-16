"""Equipment-level cross-document synthesis: merge, conflicts, versions, idempotency, stale results, honesty about empty metadata."""
import copy
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.csit_integration_v1 import equipment_synthesis as es

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "equipment_three_documents.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
D1, D2, D3, D4, D5 = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
                      "44444444-4444-4444-8444-444444444444", "55555555-5555-4555-8555-555555555555")


class Source:
    """A metadata source that counts how often it is read."""

    def __init__(self, metadata=None):
        self.items = {(m["documentId"], m["version"]): es.DocumentMetadata(m["documentId"], m["version"], m["sha256"], m["sourceType"], m["sourceEntityId"], m["kmJobId"], m["result"])
                      for m in (metadata if metadata is not None else copy.deepcopy(FIXTURE["metadata"]))}
        self.reads = 0

    def get(self, document_id, version):
        self.reads += 1
        return self.items.get((document_id, version))


def manifest(**over):
    data = copy.deepcopy(FIXTURE["manifest"])
    data.update(over)
    return es.EquipmentManifest.model_validate(data)


def only(ids, **over):
    base = copy.deepcopy(FIXTURE["manifest"])
    base["documents"] = [d for d in base["documents"] if d["documentId"] in ids]
    base.update(over)
    return es.EquipmentManifest.model_validate(base)


def make(source=None):
    store = es.EquipmentSynthesisStore()
    return es.EquipmentSynthesizer(source or Source(), store, clock=lambda: NOW), store


def spec_of(result, field):
    return next((s for s in result["specifications"] if s["field"].casefold() == field.casefold()), None)


# ---------------------------------------------------------------- merge / conflict / coverage

def test_documents_that_agree_are_merged_once_with_every_source_even_across_unit_prefixes():
    result = make()[0].analyze(manifest()).result
    throughput = [s for s in result["specifications"] if s["field"].casefold() == "max throughput"]
    assert len(throughput) == 1 and throughput[0]["agreement"] == "agreed"              # 1.2 Gbps (datasheet) == 1200 Mbps (manual); field names differ in case
    assert {s["documentId"] for s in throughput[0]["sources"]} == {D1, D5}
    assert not any(c["field"].casefold() == "max throughput" for c in result["conflicts"])
    interface = spec_of(result, "Interface")
    assert interface["agreement"] == "single" and interface["value"] == "10GbE SFP+"


def test_documents_that_disagree_become_a_conflict_and_no_value_is_picked():
    result = make()[0].analyze(manifest()).result
    conflict = next(c for c in result["conflicts"] if c["field"].casefold() == "tx power")
    assert conflict["resolution"] == "none"
    assert {(c["value"], c["unit"]) for c in conflict["claims"]} == {("23", "dBm"), ("20", "dBm")}
    assert {c["sources"][0]["documentId"] for c in conflict["claims"]} == {D1, D5}
    assert spec_of(result, "TX power") is None                  # neither value is offered as the answer
    assert any(w["code"] == "SPEC_CONFLICTS" for w in result["warnings"])


def test_every_merged_item_carries_its_source_evidence():
    result = make()[0].analyze(manifest()).result
    for item in [*result["specifications"], *result["measurements"], *result["capabilities"], *result["limitations"]]:
        assert item["sources"] and all(s["documentId"] and s["sha256"] and s["kmJobId"] for s in item["sources"])
    freq = spec_of(result, "Frequency range")
    assert freq["sources"][0]["evidence"] == "datasheet p.2 table 1 (lower bound)" and freq["sources"][0]["kmJobId"] == "KM-ING-100001"


def test_measurements_stay_separate_from_specifications():
    result = make()[0].analyze(manifest()).result
    assert {m["field"] for m in result["measurements"]} == {"Max throughput (measured)", "TX power (measured)"}
    assert all(m["context"] == "calibration run 2026-09-02" for m in result["measurements"])


def test_capabilities_limitations_and_identity_are_merged_with_sources():
    result = make()[0].analyze(manifest()).result
    assert [c["value"] for c in result["capabilities"]] == ["FR1 TX power", "可進行 FR1 的發射功率與接收靈敏度測試。"]
    assert {l["value"] for l in result["limitations"]} == {"不支援 mmWave (FR2)", "連續量測最長 8 小時"}
    names = {e["value"]: {s["documentId"] for s in e["sources"]} for e in result["identity"]["productNames"]}
    assert names == {"ATS-NR": {D1, D2, D5}}
    assert [e["value"] for e in result["identity"]["modelNumbers"]] == ["ATS-NR-100", "ATS-NR-100A"]
    assert any(w["code"] == "IDENTITY_VARIANTS" and w["field"] == "modelNumbers" for w in result["warnings"])


def test_documents_without_technical_content_are_listed_as_excluded_not_merged():
    result = make()[0].analyze(manifest()).result
    reasons = {e["documentId"]: e["reason"] for e in result["coverage"]["excluded"]}
    assert reasons == {D3: "identity_only", D4: "no_technical_content"}
    assert result["status"] == "Partial" and result["coverage"]["usedDocuments"] == 3 and result["coverage"]["manifestDocuments"] == 5
    assert {d["documentId"] for d in result["documents"]} == {D1, D2, D5}


def test_empty_metadata_only_is_insufficient_evidence_never_completed():
    result = make()[0].analyze(only({D3, D4})).result
    assert result["status"] == "InsufficientEvidence"
    for key in ("specifications", "measurements", "capabilities", "limitations", "conflicts"):
        assert result[key] == []
    assert result["summary"]["documentSummaries"] == [] and result["coverage"]["usedDocuments"] == 0


def test_a_manifest_with_no_documents_is_no_documents():
    assert make()[0].analyze(only(set())).result["status"] == "NoDocuments"


def test_all_documents_contributing_is_completed():
    result = make()[0].analyze(only({D1, D2, D5})).result
    assert result["status"] == "Completed" and result["statusReason"] is None and result["coverage"]["excluded"] == []


def test_missing_metadata_and_sha_mismatch_are_excluded_with_a_reason():
    items = copy.deepcopy(FIXTURE["metadata"])
    items = [m for m in items if m["documentId"] != D2]
    next(m for m in items if m["documentId"] == D5)["sha256"] = "f" * 64
    result = make(Source(items))[0].analyze(only({D1, D2, D5})).result
    assert {e["documentId"]: e["reason"] for e in result["coverage"]["excluded"]} == {D2: "metadata_missing", D5: "metadata_sha_mismatch"}
    assert result["status"] == "Partial" and {d["documentId"] for d in result["documents"]} == {D1}
    assert spec_of(result, "Interface") is None                 # nothing from the document whose hash did not match the manifest


def test_the_extractive_summary_lists_each_used_document_and_text_stays_null_without_a_summarizer():
    result = make()[0].analyze(manifest()).result
    assert result["summary"]["text"] is None
    assert {s["sources"][0]["documentId"] for s in result["summary"]["documentSummaries"]} == {D1, D2, D5}
    synth = es.EquipmentSynthesizer(Source(), es.EquipmentSynthesisStore(), clock=lambda: NOW, summarizer=lambda r: "整合摘要")
    assert synth.analyze(manifest()).result["summary"]["text"] == "整合摘要"


# ---------------------------------------------------------------- versions, idempotency, stale results

def test_the_same_manifest_twice_is_one_result():
    synth, store = make()
    first, second = synth.analyze(manifest()), synth.analyze(manifest())
    assert (first.kind, second.kind) == ("Created", "Duplicate")
    assert first.result["analysisResultId"] == second.result["analysisResultId"] and len(store.history("EQ-ATS-NR-0007")) == 1
    assert first.result["analysisVersion"] == 1 and first.result["supersedesAnalysisResultId"] is None


def test_a_new_manifest_revision_gets_the_next_version_and_describes_what_changed():
    synth, store = make()
    synth.analyze(only({D1, D2, D5}, manifestRevision=1, manifestHash="hash-rev-1"))
    new = only({D1, D2, D5}, manifestRevision=2, manifestHash="hash-rev-2")
    new.documents[0] = new.documents[0].model_copy(update={"version": 3, "sha256": "9" * 64})   # D1 replaced by version 3
    synth.source.items[(D1, 3)] = es.DocumentMetadata(D1, 3, "9" * 64, "EquipmentAttachment", D1, "KM-ING-100009", copy.deepcopy(FIXTURE["metadata"][0]["result"]))
    new.documents.pop()                                                                          # D5 removed
    out = synth.analyze(new).result
    assert out["analysisVersion"] == 2 and out["supersedesAnalysisResultId"] == store.history("EQ-ATS-NR-0007")[0]["analysisResultId"]
    assert out["changes"] == {"basedOn": store.history("EQ-ATS-NR-0007")[0]["analysisResultId"], "added": [], "replaced": [D1], "removed": [D5], "unchanged": [D2]}
    assert spec_of(out, "Interface") is None and store.latest("EQ-ATS-NR-0007") is out


def test_an_older_manifest_revision_never_overwrites_a_newer_result():
    synth, store = make()
    synth.analyze(only({D1, D2, D5}, manifestRevision=5, manifestHash="hash-rev-5"))
    with pytest.raises(es.StaleManifest) as caught:
        synth.analyze(only({D1}, manifestRevision=4, manifestHash="hash-rev-4"))
    assert caught.value.latest["manifestRevision"] == 5
    assert [r["manifestRevision"] for r in store.history("EQ-ATS-NR-0007")] == [5]


def test_the_same_revision_with_a_different_hash_is_rejected():
    synth, _ = make()
    synth.analyze(manifest())
    with pytest.raises(es.ManifestConflict):
        synth.analyze(manifest(manifestHash="another-hash-0001"))


def test_changed_document_metadata_under_the_same_manifest_gives_a_new_version():
    source = Source()
    synth, store = make(source)
    first = synth.analyze(manifest()).result
    source.items[(D4, 1)].result["sourceSpecific"]["specifications"].append({"field": "Weight", "value": "3.2", "unit": "kg", "evidence": "label"})   # e.g. a better single-file extraction
    second = synth.analyze(manifest())
    assert second.kind == "Created" and second.result["analysisVersion"] == 2
    assert second.result["analysisResultId"] != first["analysisResultId"] and spec_of(second.result, "Weight")["value"] == "3.2"
    assert second.result["coverage"]["usedDocuments"] == 4


def test_unchanged_documents_are_not_extracted_again():
    source = Source()
    synth, store = make(source)
    synth.analyze(manifest())
    assert store.extractions == 5
    synth.analyze(manifest(manifestRevision=4, manifestHash="hash-rev-4"))                      # nothing changed in the documents
    assert store.extractions == 5
    source.items[(D2, 1)].result["technical"]["testItems"].append("calibration")                # one document's stored metadata changed
    synth.analyze(manifest(manifestRevision=5, manifestHash="hash-rev-5"))
    assert store.extractions == 6


def test_the_result_does_not_depend_on_the_order_of_the_manifest_documents():
    a = make()[0].analyze(manifest()).result
    shuffled = manifest()
    shuffled.documents.reverse()
    b = make()[0].analyze(shuffled).result
    for key in ("analysisResultId", "specifications", "measurements", "capabilities", "limitations", "conflicts", "identity", "coverage"):
        assert a[key] == b[key], key


def test_concurrent_commits_leave_the_newest_revision_as_latest():
    synth, store = make()
    revisions = list(range(1, 9))
    errors = []

    def run(rev):
        try:
            synth.analyze(only({D1, D2, D5}, manifestRevision=rev, manifestHash=f"hash-rev-{rev:04d}"))
        except es.StaleManifest:
            pass
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=run, args=(r,)) for r in reversed(revisions)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    history = store.history("EQ-ATS-NR-0007")
    assert not errors and history[-1]["manifestRevision"] == 8
    assert [r["manifestRevision"] for r in history] == sorted(r["manifestRevision"] for r in history)
    assert [r["analysisVersion"] for r in history] == list(range(1, len(history) + 1))


def test_inputs_are_not_modified_and_the_result_validates():
    source = Source()
    before = copy.deepcopy([m.result for m in source.items.values()])
    result = make(source)[0].analyze(manifest()).result
    assert [m.result for m in source.items.values()] == before
    es.validate_result(result)


# ---------------------------------------------------------------- wire validation

def test_equipment_id_is_a_free_string_not_a_uuid():
    assert manifest(equipmentId="EQ-ATS-NR-0007").equipmentId == "EQ-ATS-NR-0007"
    assert manifest(equipmentId="設備 A-12").equipmentId == "設備 A-12"


@pytest.mark.parametrize("change", [
    {"equipmentId": "  "}, {"manifestRevision": 0}, {"manifestHash": "short"}, {"generatedAt": "2026-11-16T08:00:00"}, {"unexpected": 1},
])
def test_manifest_rejects_bad_header_fields(change):
    with pytest.raises(ValidationError):
        manifest(**change)


def test_manifest_rejects_bad_documents():
    bad = copy.deepcopy(FIXTURE["manifest"])
    bad["documents"][0]["sha256"] = "xyz"
    with pytest.raises(ValidationError):
        es.EquipmentManifest.model_validate(bad)
    twice = copy.deepcopy(FIXTURE["manifest"])
    twice["documents"].append({**twice["documents"][0], "version": 3})
    with pytest.raises(ValidationError):
        es.EquipmentManifest.model_validate(twice)


def test_job_rows_source_only_knows_completed_jobs_with_a_result():
    rows = [{"document_id": D1, "version": 2, "expected_sha256": "a" * 64, "source_type": "EquipmentAttachment", "source_entity_id": D1, "km_job_id": "KM-ING-1",
             "status": "Completed", "result_json": {"x": 1}, "completed_at": "2026-11-16T01:00:00"},
            {"document_id": D2, "version": 1, "expected_sha256": "b" * 64, "source_type": "TestReport", "source_entity_id": D2, "km_job_id": "KM-ING-2",
             "status": "Failed", "result_json": None, "completed_at": None},
            {"document_id": D3, "version": 1, "expected_sha256": "c" * 64, "source_type": "VendorFile", "source_entity_id": D3, "km_job_id": "KM-ING-3",
             "status": "Deleted", "result_json": {"x": 1}, "completed_at": None}]
    source = es.JobRowsSource(rows)
    assert source.get(D1, 2).kmJobId == "KM-ING-1" and source.get(D2, 1) is None and source.get(D3, 1) is None


@pytest.mark.parametrize("a,b,same", [
    (("1.2", "Gbps"), ("1200", "Mbps"), True), (("2.4", "GHz"), ("2400", "MHz"), True), (("23", "dBm"), ("23 dBm", None), True),
    (("23", "dBm"), ("20", "dBm"), False), (("1,200", "Mbps"), ("1200", "mbps"), True), (("100", "mW"), ("0.1", "W"), True),
    (("10GbE SFP+", None), ("10gbe  sfp+", None), True), (("5", "V"), ("5", "A"), False),
])
def test_value_normalisation(a, b, same):
    assert (es.normalise_claim(*a)[0] == es.normalise_claim(*b)[0]) is same
