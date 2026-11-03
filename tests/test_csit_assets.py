from pathlib import Path

import httpx
import pytest

from src.csit import CsitAssetPuller, CsitReadOnlyClient, load_contract
from src.csit.assets import ASSET_DETAIL_PATH, ASSET_FILE_CONTENT_PATH, ASSET_FILES_PATH, ASSET_LIST_PATH

CONTRACT = Path(__file__).resolve().parents[1] / "config" / "csit_api_contract.json"


class FakeClient:
    def __init__(self):
        self.calls = []

    def get(self, path, *, path_params=None, query=None):
        self.calls.append((path, path_params, query))
        code = (path_params or {}).get("moduleCode")
        if path == ASSET_LIST_PATH:
            if code == "goods":
                raise RuntimeError("boom")
            return [{"id": "a1"}, {"name": "no id"}, {"id": "bad"}]
        if path == ASSET_DETAIL_PATH:
            if path_params["id"] == "bad":
                return ["not", "an", "object"]
            return {
                "id": "a1", "name": "頻譜分析儀", "kind": "Instrument", "Model": "FSW26", "place": "TP-3F",
                "custodian": "Alice", "costPrice": 99999, "custodianAccount": "corp\\alice", "imei": "123",
                "spec": "2Hz-26.5GHz", "note": "  ", "Files": [{"id": "ignored-nested"}],
            }
        if path == ASSET_FILES_PATH:
            return [{"id": "f1", "fileName": "manual.pdf", "contentType": "application/pdf", "fileSize": "2048"}, {"fileName": "orphan"}]
        raise AssertionError(path)


def test_contract_maps_the_four_phase1_asset_endpoints():
    contract = load_contract(CONTRACT)
    for path in (ASSET_LIST_PATH, ASSET_DETAIL_PATH, ASSET_FILES_PATH, ASSET_FILE_CONTENT_PATH):
        assert contract.endpoint(path, "GET").read_only_allowed
    # the workbook's write verbs are mapped as data but remain blocked by the client
    assert not contract.endpoint(ASSET_LIST_PATH, "POST").read_only_allowed


def test_pull_builds_entry_and_drops_finance_and_personal_fields():
    client = FakeClient()
    result = CsitAssetPuller(client).pull()

    assert [e.asset_id for e in result.entries] == ["a1"]
    entry = result.entries[0]
    assert entry.name == "頻譜分析儀" and entry.value("model") == "FSW26"
    names = {k.lower() for k, _ in entry.fields}
    assert not names & {"costprice", "custodianaccount", "imei", "files", "note"}
    assert [(f.file_id, f.file_name, f.file_size) for f in entry.files] == [("f1", "manual.pdf", 2048)]
    assert entry.document_id == "csit-asset:equipment:a1"
    assert entry.to_source_metadata()["csit_asset_file_ids"] == ["f1"]
    assert "- place: TP-3F" in entry.to_text() and "manual.pdf" in entry.to_text()


def test_failures_are_skipped_fail_closed_with_sanitized_reasons():
    result = CsitAssetPuller(FakeClient()).pull()
    reasons = {(s["stage"], s["reason"]) for s in result.skipped}
    assert ("list", "RuntimeError") in reasons
    assert ("asset", "missing asset id") in reasons
    assert ("detail", "ValueError") in reasons
    assert all("boom" not in str(s) for s in result.skipped)


def test_only_get_is_used_and_keyword_kind_are_forwarded():
    client = FakeClient()
    CsitAssetPuller(client, module_codes=("equipment",), include_files=False).pull(keyword="FSW", kind="Instrument")
    assert client.calls[0][2] == {"keyword": "FSW", "kind": "Instrument"}
    assert all(path != ASSET_FILES_PATH for path, _, _ in client.calls)


def test_real_client_reaches_asset_endpoints_via_contract_and_rejects_writes():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json=[])

    client = CsitReadOnlyClient("https://csit.example", load_contract(CONTRACT), http_transport=httpx.MockTransport(handler))
    assert CsitAssetPuller(client, module_codes=("equipment",)).pull().entries == ()
    assert seen == [("GET", "/api/assets/equipment")]
    with pytest.raises(Exception):
        client.request("POST", ASSET_LIST_PATH)


def test_empty_module_codes_rejected():
    with pytest.raises(ValueError):
        CsitAssetPuller(FakeClient(), module_codes=())
