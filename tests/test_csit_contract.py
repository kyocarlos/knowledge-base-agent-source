import json
import hashlib
import sys
from types import SimpleNamespace
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "CSIT_KM_REST_API_v1.0.xlsx"
CONTRACT_PATH = ROOT / "config/csit_api_contract.json"
sys.path.insert(0, str(ROOT))

from scripts.generate_csit_contract import generate
from src.csit import (
    CsitMetadataError,
    CsitReadOnlyClient,
    CsitReportSource,
    CsitRequestError,
    StaticHeaderAuthProvider,
    load_contract,
)
from src.csit.assistant import answer_csit_query, is_csit_query
from src.test_reports.auth import (
    authenticate_csit_reader,
    create_csit_download_ticket,
    csit_download_ticket_filename,
    safe_csit_filename,
    verify_csit_download_ticket,
)


def test_generated_contract_matches_patty_workbook():
    contract = load_contract(CONTRACT_PATH)
    generated = generate(SOURCE)
    assert json.loads(CONTRACT_PATH.read_text(encoding="utf-8")) == generated
    assert contract.source_sha256
    assert contract.known_gaps == (
        "CSIT_OPENAPI_RETRIEVAL_PENDING",
        "CSIT_SERVICE_AUTH_CONTRACT_MISSING",
        "CSIT_BOOKING_CONTRACT_PENDING",
        "CSIT_VALIDATION_REQUEST_CONTRACT_PENDING",
    )


def test_priority_read_routes_and_deferred_writes_are_explicit():
    contract = load_contract(CONTRACT_PATH)
    assert contract.endpoint("/api/modules/enabled").integration_stage == "WP2-A/B"
    assert contract.endpoint("/api/modules", "POST").integration_stage == "WP2-D-DEFERRED"
    assert all(endpoint.authorization == "CsitStaff" for endpoint in contract.endpoints)
    assert all(endpoint.read_only_allowed == (endpoint.method == "GET") for endpoint in contract.endpoints)


def test_read_only_client_renders_paths_and_rejects_writes():
    contract = load_contract(CONTRACT_PATH)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    with CsitReadOnlyClient(
        "https://csit.invalid",
        contract,
        headers={"X-Test": "yes"},
        http_transport=httpx.MockTransport(handler),
    ) as client:
        assert client.get("/api/modules/{code}", path_params={"code": "A/B"}) == {"ok": True}
        with pytest.raises(CsitRequestError, match="rejects non-GET"):
            client.request("POST", "/api/modules")

    assert requests[0].url.raw_path == b"/api/modules/A%2FB"
    assert requests[0].headers["X-Test"] == "yes"


def test_client_does_not_expose_response_body_on_failure():
    contract = load_contract(CONTRACT_PATH)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Bearer secret-must-not-appear")

    with CsitReadOnlyClient("https://csit.invalid", contract, http_transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CsitRequestError) as error:
            client.get("/api/modules/enabled")
    assert "secret" not in str(error.value)


def test_auth_provider_is_caller_owned_and_headers_are_applied_per_request():
    contract = load_contract(CONTRACT_PATH)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    with CsitReadOnlyClient(
        "https://csit.invalid",
        contract,
        auth_provider=StaticHeaderAuthProvider({"X-S2S-Test": "approved"}),
        http_transport=httpx.MockTransport(handler),
    ) as client:
        assert client.get("/api/modules/enabled") == {"ok": True}
    assert requests[0].headers["X-S2S-Test"] == "approved"


def test_empty_json_response_fails_closed():
    contract = load_contract(CONTRACT_PATH)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    with CsitReadOnlyClient("https://csit.invalid", contract, http_transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CsitRequestError, match="empty response"):
            client.get("/api/modules/enabled")


def test_cookie_login_is_reused_for_read_requests():
    contract = load_contract(CONTRACT_PATH)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/auth/login":
            assert request.content == b"username=stage-user&password=stage-pass"
            return httpx.Response(302, headers={"set-cookie": "csit_session=test-session; Path=/"})
        assert request.headers.get("cookie") == "csit_session=test-session"
        return httpx.Response(200, json={"items": []})

    with CsitReadOnlyClient(
        "https://csit.invalid",
        contract,
        username="stage-user",
        password="stage-pass",
        http_transport=httpx.MockTransport(handler),
    ) as client:
        assert client.get("/api/modules/enabled") == {"items": []}
        assert client.get("/api/modules/enabled") == {"items": []}

    assert [request.url.path for request in requests] == [
        "/auth/login",
        "/api/modules/enabled",
        "/api/modules/enabled",
    ]


def test_cookie_client_rejects_non_get_requests():
    contract = load_contract(CONTRACT_PATH)
    with CsitReadOnlyClient(
        "https://csit.invalid",
        contract,
        username="stage-user",
        password="stage-pass",
        http_transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    ) as client:
        with pytest.raises(CsitRequestError, match="rejects non-GET"):
            client.request("POST", "/api/modules")


def test_dedicated_km_manifest_endpoint_is_used_without_general_file_dto():
    contract = load_contract(CONTRACT_PATH)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": []})

    with CsitReadOnlyClient(
        "https://csit.invalid",
        contract,
        headers={"X-Test": "yes"},
        http_transport=httpx.MockTransport(handler),
    ) as client:
        assert client.get_km_manifest("project/1") == {"items": []}

    assert requests[0].url.raw_path == b"/api/km/v1/projects/project%2F1/manifest"


def test_csit_reader_scope_is_separate_and_hash_only(monkeypatch):
    token = "csit-reader-test-token"
    monkeypatch.setenv(
        "KB_CSIT_READER_TOKEN_HASHES_JSON",
        json.dumps({"reader-01": hashlib.sha256(token.encode()).hexdigest()}),
    )

    request = type(
        "Request",
        (),
        {"headers": {"X-CSIT-Reader-ID": "reader-01", "Authorization": f"Bearer {token}"}},
    )()
    assert authenticate_csit_reader(request) == {"reader_id": "reader-01", "scope": "csit:read"}


def test_csit_reader_scope_rejects_wrong_identity_or_token(monkeypatch):
    monkeypatch.setenv(
        "KB_CSIT_READER_TOKEN_HASHES_JSON",
        json.dumps({"reader-01": hashlib.sha256(b"correct").hexdigest()}),
    )
    with pytest.raises(Exception, match="未知的 CSIT reader"):
        authenticate_csit_reader(SimpleNamespace(headers={"X-CSIT-Reader-ID": "other", "Authorization": "Bearer correct"}))
    with pytest.raises(Exception, match="CSIT reader token 無效"):
        authenticate_csit_reader(SimpleNamespace(headers={"X-CSIT-Reader-ID": "reader-01", "Authorization": "Bearer wrong"}))


def test_csit_download_ticket_is_short_lived_and_file_bound(monkeypatch):
    monkeypatch.setenv(
        "KB_CSIT_READER_TOKEN_HASHES_JSON",
        json.dumps({"reader-01": hashlib.sha256(b"reader-token").hexdigest()}),
    )
    ticket = create_csit_download_ticket("file-001", "../report.xlsx", ttl_seconds=60)
    assert ticket
    assert verify_csit_download_ticket("file-001", ticket)
    assert not verify_csit_download_ticket("file-002", ticket)
    assert csit_download_ticket_filename("file-001", ticket) == "report.xlsx"
    assert safe_csit_filename("../report.xlsx") == "report.xlsx"

    request = SimpleNamespace(
        headers={},
        path_params={"file_id": "file-001"},
        query_params={"ticket": ticket},
    )
    assert authenticate_csit_reader(request)["scope"] == "csit:download"


def test_csit_download_ticket_cannot_replace_reader_auth_for_other_routes(monkeypatch):
    monkeypatch.setenv(
        "KB_CSIT_READER_TOKEN_HASHES_JSON",
        json.dumps({"reader-01": hashlib.sha256(b"reader-token").hexdigest()}),
    )
    ticket = create_csit_download_ticket("file-001")
    with pytest.raises(Exception, match="缺少 X-CSIT-Reader-ID"):
        authenticate_csit_reader(SimpleNamespace(headers={}, path_params={}, query_params={"ticket": ticket}))


def test_csit_assistant_runs_bounded_read_chain_and_formats_files():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def get(self, path, **kwargs):
            self.calls.append((path, kwargs))
            return {
                "/api/modules/enabled": {"items": [{"id": "m1", "code": "verification", "name": "Verification"}]},
                "/api/modules/{moduleCode}/records": {"items": [{"id": "r1", "recordNo": "PRJ-001", "name": "NR throughput"}]},
                "/api/records/{id}": {"id": "r1", "recordNo": "PRJ-001", "status": "Active"},
                "/api/records/{recordId}/cases": {"items": [{"id": "c1", "caseNo": "CASE-001", "name": "下載測試報告"}]},
                "/api/cases/{id}": {"id": "c1", "caseNo": "CASE-001", "status": "Completed"},
                "/api/cases/{caseId}/files": {"items": [{"id": "cf1", "fileName": "case-note.txt"}]},
                "/api/cases/{caseId}/tasks": {"items": [{"id": "t1", "taskNo": "TASK-001", "name": "驗證附件"}]},
                "/api/tasks/{id}": {"id": "t1", "taskNo": "TASK-001", "status": "Completed"},
                "/api/tasks/{taskId}/files": {"items": [{"id": "f1", "fileName": "report.xlsx"}]},
            }[path]

    client = FakeClient()
    result = answer_csit_query(client, "請查詢 CSIT NR throughput")

    assert "NR throughput" in result
    assert "下載測試報告" in result
    assert "report.xlsx" in result
    assert "/api/csit/files/f1/download" in result
    assert [path for path, _ in client.calls] == [
        "/api/modules/enabled",
        "/api/modules/{moduleCode}/records",
        "/api/records/{id}",
        "/api/records/{recordId}/cases",
        "/api/cases/{id}",
        "/api/cases/{caseId}/files",
        "/api/cases/{caseId}/tasks",
        "/api/tasks/{id}",
        "/api/tasks/{taskId}/files",
    ]


def test_csit_assistant_renders_controlled_download_button(monkeypatch):
    monkeypatch.setenv(
        "KB_CSIT_READER_TOKEN_HASHES_JSON",
        json.dumps({"reader-01": hashlib.sha256(b"reader-token").hexdigest()}),
    )
    class FakeClient:
        def get(self, path, **kwargs):
            return {
                "/api/modules/enabled": {"items": [{"id": "m1", "code": "verification", "name": "Verification"}]},
                "/api/modules/{moduleCode}/records": {"items": [{"id": "r1", "name": "NR throughput"}]},
                "/api/records/{id}": {"id": "r1"},
                "/api/records/{recordId}/cases": {"items": [{"id": "c1", "name": "report"}]},
                "/api/cases/{id}": {"id": "c1"},
                "/api/cases/{caseId}/files": {"items": []},
                "/api/cases/{caseId}/tasks": {"items": [{"id": "t1", "name": "task"}]},
                "/api/tasks/{id}": {"id": "t1"},
                "/api/tasks/{taskId}/files": {"items": [{"id": "f1", "fileName": "report.xlsx"}]},
            }[path]

    result = answer_csit_query(FakeClient(), "請查詢 CSIT NR throughput")
    assert "[下載報告](" in result
    assert "ticket=" in result
    assert "CSIT_USERNAME" not in result
    assert "reader-token" not in result


def test_csit_assistant_only_intercepts_explicit_csit_query():
    assert is_csit_query("請查詢 CSIT 的 Project")
    assert not is_csit_query("請查詢 KM 的文件")


def test_csit_report_source_maps_provenance_without_publishing():
    source = CsitReportSource.from_csit({
        "report_id": "RPT-1", "file_id": "FILE-1", "task_id": "TASK-1",
        "case_id": "CASE-1", "record_id": "REC-1", "version": "v1",
        "approval_status": "approved", "correlation_id": "CORR-1",
        "test_run_id": "TR-1",
    })
    metadata = source.to_source_metadata(file_name="report.xlsx")
    assert metadata["source_system"] == "CSIT"
    assert metadata["source_record_id"] == "RPT-1"
    assert metadata["source_file_id"] == "FILE-1"
    assert metadata["approval_status"] == "approved"
    assert metadata["run_id"] == "TR-1"
    assert "publish_status" not in metadata


def test_csit_report_source_rejects_missing_identity():
    with pytest.raises(CsitMetadataError, match="file_id"):
        CsitReportSource.from_csit({"report_id": "RPT-1"})
