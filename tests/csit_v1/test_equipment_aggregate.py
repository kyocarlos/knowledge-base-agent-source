"""Equipment-level cross-document synthesis against CSIT's real contract (CSIT requirement doc, 2026-11-17)."""
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from src.csit_integration_v1.api import create_app
from src.csit_integration_v1.auth import ServiceIdentity
from src.csit_integration_v1.doclib_client import DocLibClient
from src.csit_integration_v1.equipment_aggregate import V2JobMetadataSource, analyze
from src.csit_integration_v1.equipment_aggregate_models import EquipmentAggregateRequest, build_equipment_aggregate_callback
from src.csit_integration_v1.errors import IntegrationError
from src.csit_integration_v1.v2_repository import V2Repository
from src.csit_integration_v1.v2_worker import V2Processor
from conftest import TestTokenValidator

ROUTE = "/api/integrations/csit/v1/equipment-aggregate-analyses"
AUTH = {"Authorization": "Bearer test-service"}


def _file_id(n):
    return str(uuid.UUID(int=n))


def _sha(n):
    return format(n, "064x")


def _result(technical=None, source_specific=None):
    return {
        "metadataSchemaVersion": "2.0",
        "document": {"title": None, "documentType": "Specification", "summary": None, "language": "zh", "documentDate": None,
                     "authors": [], "department": None, "documentVersionLabel": None, "keywords": [], "tags": []},
        "technical": {"productNames": [], "modelNumbers": [], "vendorNames": [], "technologies": [], "standards": [],
                      "softwareVersions": [], "hardwareVersions": [], "projectNames": [], "testItems": [], "measurements": [],
                      "issueKeys": [], "errorCodes": [], **(technical or {})},
        "extraction": {"sourceFormat": "pdf", "method": "Text", "pageCount": 1, "sheetNames": [], "extractedCharacterCount": 100,
                       "ocrUsed": False},
        "indexing": {"status": "Completed", "indexId": "i", "chunkCount": 1, "indexedAt": "2026-11-17T00:00:00Z"},
        "warnings": [], "sourceSpecific": {"specifications": [], "capabilitySummary": None, "limitations": [], **(source_specific or {})},
    }


def _v2_job_row(file_id, version, sha256, km_job_id, result):
    return {"document_id": uuid.UUID(file_id), "version": version, "expected_sha256": sha256, "km_job_id": km_job_id,
            "status": "Completed", "result_json": result}


def _request_doc(n, version=1, analysis_result_id=None, sha256=None, km_job_id="KM-ING-000001"):
    return {"fileId": _file_id(n), "version": version, "sha256": sha256 or _sha(n), "kmJobId": km_job_id,
            "analysisResultId": str(analysis_result_id or uuid.UUID(int=1000 + n)), "fileName": "doc%d.pdf" % n,
            "analyzedAt": "2026-11-17T00:00:00Z"}


def _request(documents, **over):
    base = {"schemaVersion": "1.0", "requestId": str(uuid.uuid4()), "sourceSystem": "CSIT", "moduleCode": "equipment",
            "apparatusId": "APP-1", "manifestHash": _sha(999), "analysisVersion": "1.0", "documents": documents,
            "requestedAt": "2026-11-17T00:00:00Z"}
    base.update(over)
    return EquipmentAggregateRequest.model_validate(base)


# ---------------------------------------------------------------- analyze(): the merge itself

def test_two_documents_agreeing_on_a_fact_merge_with_both_sources_as_evidence():
    # identity facts alone (vendor/model with nothing else) do not make a document "used" -- extract_contribution()'s honesty rule -- so
    # each row also carries one substantive specification claim.
    row1 = _v2_job_row(_file_id(1), 1, _sha(1), "KM-ING-000001",
                        _result(technical={"vendorNames": ["Askey"], "modelNumbers": ["FSW26"]},
                                source_specific={"specifications": [{"field": "重量", "value": "2kg"}]}))
    row2 = _v2_job_row(_file_id(2), 1, _sha(2), "KM-ING-000002",
                        _result(technical={"vendorNames": ["Askey"]}, source_specific={"specifications": [{"field": "頻率", "value": "5GHz"}]}))
    req = _request([_request_doc(1, km_job_id="KM-ING-000001"), _request_doc(2, km_job_id="KM-ING-000002")])
    result = analyze(req, V2JobMetadataSource([row1, row2]))
    vendor = next(s for s in result["technicalSpecifications"] if s["name"] == "廠牌")
    assert vendor["value"] == "Askey" and len(vendor["evidenceIds"]) == 2
    all_evidence_ids = {e["evidenceId"] for e in result["evidence"]}
    assert all(eid in all_evidence_ids for eid in vendor["evidenceIds"])  # every id a spec names resolves to a real evidence item
    model = next(s for s in result["technicalSpecifications"] if s["name"] == "型號")
    assert model["value"] == "FSW26" and len(model["evidenceIds"]) == 1


def test_disagreeing_documents_become_a_conflict_never_a_silently_picked_value():
    row1 = _v2_job_row(_file_id(1), 1, _sha(1), "KM-ING-000001",
                        _result(technical={"vendorNames": ["Askey"]}, source_specific={"specifications": [{"field": "重量", "value": "2kg"}]}))
    row2 = _v2_job_row(_file_id(2), 1, _sha(2), "KM-ING-000002",
                        _result(technical={"vendorNames": ["OtherCo"]}, source_specific={"specifications": [{"field": "頻率", "value": "5GHz"}]}))
    req = _request([_request_doc(1, km_job_id="KM-ING-000001"), _request_doc(2, km_job_id="KM-ING-000002")])
    result = analyze(req, V2JobMetadataSource([row1, row2]))
    assert not any(s["name"] == "廠牌" for s in result["technicalSpecifications"])
    conflict = next(c for c in result["conflicts"] if c["field"] == "廠牌")
    assert "Askey" in conflict["description"] and "OtherCo" in conflict["description"]
    assert len(conflict["evidenceIds"]) == 2
    assert any("不一致" in w for w in result["warnings"])


def test_evidence_items_echo_the_exact_analysis_result_id_csit_sent_never_minted():
    aid = uuid.uuid4()
    row = _v2_job_row(_file_id(1), 1, _sha(1), "KM-ING-000001",
                       _result(technical={"vendorNames": ["Askey"]}, source_specific={"specifications": [{"field": "重量", "value": "2kg"}]}))
    req = _request([_request_doc(1, km_job_id="KM-ING-000001", analysis_result_id=aid)])
    result = analyze(req, V2JobMetadataSource([row]))
    assert result["evidence"][0]["analysisResultId"] == str(aid)
    assert result["evidence"][0]["fileId"] == _file_id(1)


def test_a_document_with_no_technical_content_is_excluded_not_merged_as_empty():
    row = _v2_job_row(_file_id(1), 1, _sha(1), "KM-ING-000001", _result())  # nothing in technical or sourceSpecific
    req = _request([_request_doc(1, km_job_id="KM-ING-000001")])
    result = analyze(req, V2JobMetadataSource([row]))
    assert result["technicalSpecifications"] == [] and result["evidence"] == []
    assert any("未納入" in w for w in result["warnings"])


def test_a_sha256_mismatch_excludes_the_document_never_trusts_the_wrong_stored_result():
    row = _v2_job_row(_file_id(1), 1, _sha(999), "KM-ING-000001", _result(technical={"vendorNames": ["Askey"]}))  # stored under a different hash
    req = _request([_request_doc(1, km_job_id="KM-ING-000001")])  # the request names _sha(1)
    result = analyze(req, V2JobMetadataSource([row]))
    assert result["technicalSpecifications"] == []  # the mismatched row is never used, so nothing is fabricated from it


def test_a_km_job_id_mismatch_also_excludes_the_document():
    row = _v2_job_row(_file_id(1), 1, _sha(1), "KM-ING-999999", _result(technical={"vendorNames": ["Askey"]}))
    req = _request([_request_doc(1, km_job_id="KM-ING-000001")])
    result = analyze(req, V2JobMetadataSource([row]))
    assert result["technicalSpecifications"] == []


def test_no_documents_at_all_gives_an_empty_result_not_an_invented_one():
    req = _request([])
    result = analyze(req, V2JobMetadataSource([]))
    assert result["technicalSpecifications"] == [] and result["evidence"] == [] and result["conflicts"] == []
    assert "Manifest" in result["overview"]


def test_capabilities_and_limitations_carry_through_with_evidence():
    row = _v2_job_row(_file_id(1), 1, _sha(1), "KM-ING-000001",
                       _result(source_specific={"capabilitySummary": "可進行輸出功率測試", "limitations": ["高溫環境下吞吐量下降"]}))
    req = _request([_request_doc(1, km_job_id="KM-ING-000001")])
    result = analyze(req, V2JobMetadataSource([row]))
    assert result["testCapabilities"][0]["name"] == "可進行輸出功率測試"
    assert len(result["testCapabilities"][0]["evidenceIds"]) == 1
    assert result["limitations"] == ["高溫環境下吞吐量下降"]


# ---------------------------------------------------------------- the callback payload matches CSIT's exact shape

def test_the_completed_callback_has_exactly_the_contracts_ten_keys():
    row = {"request_id": uuid.uuid4(), "module_code": "equipment", "apparatus_id": "APP-1", "manifest_hash": _sha(1), "analysis_version": "1.0"}
    payload = build_equipment_aggregate_callback(uuid.uuid4(), row, "Completed",
        result={"overview": None, "technicalSpecifications": [], "testCapabilities": [], "limitations": [], "conflicts": [],
                "evidence": [], "warnings": []},
        analyzed_at=datetime.now(timezone.utc))
    assert set(payload) == {"schemaVersion", "callbackId", "requestId", "moduleCode", "apparatusId", "manifestHash",
                             "analysisVersion", "status", "result", "error", "analyzedAt"}
    assert set(payload["result"]) == {"overview", "technicalSpecifications", "testCapabilities", "limitations", "conflicts",
                                       "evidence", "warnings"}


def test_the_failed_callback_carries_no_result():
    row = {"request_id": uuid.uuid4(), "module_code": "equipment", "apparatus_id": "APP-1", "manifest_hash": _sha(1), "analysis_version": "1.0"}
    payload = build_equipment_aggregate_callback(uuid.uuid4(), row, "Failed", error=IntegrationError("E", "boom", True))
    assert payload["result"] is None and payload["error"] == {"code": "E", "message": "boom", "retryable": True}


# ---------------------------------------------------------------- repository: idempotency, claim/finish/fail

@pytest.fixture
def repo(db_url):
    r = V2Repository(db_url)
    with r.connect() as c:
        c.execute("TRUNCATE km_csit_equipment_aggregate_requests,km_csit_v13_callbacks,km_csit_v2_jobs RESTART IDENTITY CASCADE")
    return r


def test_submitting_the_same_request_id_twice_returns_the_same_row(repo):
    req = _request([])
    row1 = repo.submit_equipment_aggregate_request(req)
    row2 = repo.submit_equipment_aggregate_request(req)
    assert row1["km_job_id"] == row2["km_job_id"]


def test_the_same_request_id_with_a_different_body_is_a_conflict(repo):
    req = _request([])
    repo.submit_equipment_aggregate_request(req)
    other = _request([], requestId=req.requestId, apparatusId="APP-2")
    with pytest.raises(IntegrationError) as exc:
        repo.submit_equipment_aggregate_request(other)
    assert exc.value.code == "REQUEST_CONFLICT"


def test_claim_process_finish_enqueues_exactly_one_completed_callback(repo):
    with repo.connect() as c:
        c.execute("""INSERT INTO km_csit_v2_jobs(event_id,csit_job_id,km_job_id,event_type,source_type,source_entity_id,document_id,
              version,request_payload,original_file_name,content_type,file_size_bytes,expected_sha256,occurred_at,status,result_json)
            VALUES(%s,%s,%s,'EquipmentAttachmentArchived','EquipmentAttachment',%s,%s,1,'{}','a.pdf','application/pdf',10,%s,
              clock_timestamp(),'Completed',%s)""",
            (uuid.uuid4(), uuid.uuid4(), "KM-ING-000001", uuid.UUID(_file_id(1)), uuid.UUID(_file_id(1)), _sha(1),
             Jsonb(_result(technical={"vendorNames": ["Askey"]}))))
    req = _request([_request_doc(1, km_job_id="KM-ING-000001")])
    repo.submit_equipment_aggregate_request(req)
    processor = V2Processor(settings=SimpleNamespace(lease_seconds=60, retry_delays=(1,), equipment_aggregate_enabled=True),
                             repo=repo, pipeline=None, qdrant=None)
    assert processor.equipment_aggregate_one() is True
    row = repo.get_equipment_aggregate_request(req.requestId)
    assert row["status"] == "Completed"
    with repo.connect() as c:
        delivered = c.execute("SELECT * FROM km_csit_v13_callbacks WHERE kind='equipment_aggregate' AND ref_id=%s", (str(req.requestId),)).fetchall()
    assert len(delivered) == 1 and delivered[0]["payload"]["status"] == "Completed"


# ---------------------------------------------------------------- API route: disabled by default, idempotency, auth

def _app(settings, repo, enabled):
    from dataclasses import replace
    return create_app(replace(settings, doclib_enabled=True, equipment_aggregate_enabled=enabled), repo, TestTokenValidator(), doclib=repo)


def test_the_route_is_503_until_the_feature_flag_is_on(settings, repo):
    client = TestClient(_app(settings, repo, enabled=False))
    body = _request([]).model_dump(mode="json")
    r = client.post(ROUTE, json=body, headers=AUTH)
    assert r.status_code == 503


def test_an_accepted_request_returns_202_with_the_km_job_id(settings, repo):
    client = TestClient(_app(settings, repo, enabled=True))
    body = _request([]).model_dump(mode="json")
    r = client.post(ROUTE, json=body, headers=AUTH)
    assert r.status_code == 202 and r.json()["status"] == "Accepted" and r.json()["requestId"] == body["requestId"]


def test_an_idempotency_key_that_does_not_match_the_body_is_refused(settings, repo):
    client = TestClient(_app(settings, repo, enabled=True))
    body = _request([]).model_dump(mode="json")
    r = client.post(ROUTE, json=body, headers={**AUTH, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 400


def test_a_token_without_the_required_scope_is_refused(settings, repo):
    client = TestClient(_app(settings, repo, enabled=True))
    body = _request([]).model_dump(mode="json")
    r = client.post(ROUTE, json=body, headers={"Authorization": "Bearer test-wrong-scope"})
    assert r.status_code == 403


def test_no_bearer_token_at_all_is_refused(settings, repo):
    client = TestClient(_app(settings, repo, enabled=True))
    r = client.post(ROUTE, json=_request([]).model_dump(mode="json"))
    assert r.status_code == 401


# ---------------------------------------------------------------- part 4: callback 409 classification, worker restart, retry exhaustion

class FakeAuth:
    def headers(self, scopes=None):
        return {"Authorization": "Bearer fake-outbound"}


class StatusCsit:
    def __init__(self, answers):
        self.answers = list(answers)
        self.posts = []
    def __call__(self, r):
        self.posts.append((r.url.path, r.headers.get("idempotency-key")))
        status, body = self.answers.pop(0) if self.answers else (204, "")
        return httpx.Response(status, text=body)


def _post_equipment_aggregate(settings, answers):
    csit = StatusCsit(answers)
    client = DocLibClient(settings, FakeAuth(), transport=httpx.MockTransport(csit))
    err = None
    try:
        client.post_status("equipment_aggregate", {"callbackId": str(uuid.uuid4()), "status": "Completed"})
    except IntegrationError as e:
        err = e
    return err, csit


@pytest.mark.parametrize("code", ["feature_disabled", "callback_id_conflict", "stale_or_mismatched_manifest",
                                   "request_already_failed", "stale_manifest"])
def test_every_csit_409_reason_is_classified_and_not_retried(settings, code):
    err, _ = _post_equipment_aggregate(settings, [(409, '{"error":"%s"}' % code)])
    assert err.retryable is False and err.code == "CSIT_EQUIPMENT_AGGREGATE_" + code.upper()


def test_an_unrecognised_409_body_is_still_refused_not_retried(settings):
    err, _ = _post_equipment_aggregate(settings, [(409, "not json")])
    assert err.retryable is False and err.code == "CSIT_EQUIPMENT_AGGREGATE_UNKNOWN"


def test_429_and_5xx_on_the_equipment_aggregate_callback_still_retry_like_every_other_kind(settings):
    for status in (429, 500, 503):
        err, _ = _post_equipment_aggregate(settings, [(status, "")])
        assert err.retryable is True


def test_the_idempotency_key_header_sent_to_csit_is_the_callback_id(settings):
    callback_id = str(uuid.uuid4())
    csit = StatusCsit([(204, "")])
    client = DocLibClient(settings, FakeAuth(), transport=httpx.MockTransport(csit))
    client.post_status("equipment_aggregate", {"callbackId": callback_id, "status": "Completed"})
    assert csit.posts[0][1] == callback_id


def test_a_lease_that_expired_after_a_worker_crash_is_reclaimed_by_the_next_worker(repo):
    req = _request([])
    repo.submit_equipment_aggregate_request(req)
    row = repo.claim_equipment_aggregate("worker-a", lease_seconds=60)
    assert row is not None
    # worker-a crashed mid-processing without finishing or failing it: simulate the lease having already expired.
    with repo.connect() as c:
        c.execute("UPDATE km_csit_equipment_aggregate_requests SET lease_until=clock_timestamp()-interval '1 second' WHERE request_id=%s",
                   (req.requestId,))
    reclaimed = repo.claim_equipment_aggregate("worker-b", lease_seconds=60)
    assert reclaimed is not None and reclaimed["request_id"] == row["request_id"] and reclaimed["attempt_count"] == 2
    assert reclaimed["worker_id"] == "worker-b"


def test_retrying_a_renewed_lease_is_refused_as_lease_lost(repo):
    from src.csit_integration_v1.errors import LeaseLost
    req = _request([])
    repo.submit_equipment_aggregate_request(req)
    row = repo.claim_equipment_aggregate("worker-a", lease_seconds=60)
    with repo.connect() as c:
        c.execute("UPDATE km_csit_equipment_aggregate_requests SET lease_token=NULL,lease_until=NULL,status='Accepted' WHERE request_id=%s",
                   (req.requestId,))
    with pytest.raises(LeaseLost):
        repo.finish_equipment_aggregate(row, {}, datetime.now(timezone.utc))


def test_a_retryable_failure_is_requeued_with_a_backoff_then_fails_for_good_once_the_budget_is_spent(repo):
    req = _request([])
    repo.submit_equipment_aggregate_request(req)
    row = repo.claim_equipment_aggregate("worker-a", lease_seconds=60)
    repo.fail_equipment_aggregate(row, IntegrationError("TRANSIENT", "try later", True), retry_delays=(0, 0))
    after_first = repo.get_equipment_aggregate_request(req.requestId)
    assert after_first["status"] == "Accepted" and after_first["next_retry_at"] is not None
    row2 = repo.claim_equipment_aggregate("worker-b", lease_seconds=60)
    repo.fail_equipment_aggregate(row2, IntegrationError("TRANSIENT", "try later", True), retry_delays=(0, 0))
    after_second = repo.get_equipment_aggregate_request(req.requestId)
    assert after_second["status"] == "Accepted"
    row3 = repo.claim_equipment_aggregate("worker-c", lease_seconds=60)
    repo.fail_equipment_aggregate(row3, IntegrationError("TRANSIENT", "try later", True), retry_delays=(0, 0))
    final = repo.get_equipment_aggregate_request(req.requestId)
    assert final["status"] == "Failed" and final["last_error_code"] == "TRANSIENT"
    with repo.connect() as c:
        delivered = c.execute("SELECT * FROM km_csit_v13_callbacks WHERE kind='equipment_aggregate' AND ref_id=%s",
                               (str(req.requestId),)).fetchall()
    assert len(delivered) == 1 and delivered[0]["payload"]["status"] == "Failed"


def test_a_non_retryable_failure_goes_straight_to_failed_on_the_first_attempt(repo):
    req = _request([])
    repo.submit_equipment_aggregate_request(req)
    row = repo.claim_equipment_aggregate("worker-a", lease_seconds=60)
    repo.fail_equipment_aggregate(row, IntegrationError("PERMANENT", "will never work", False), retry_delays=(0, 0, 0))
    final = repo.get_equipment_aggregate_request(req.requestId)
    assert final["status"] == "Failed"
