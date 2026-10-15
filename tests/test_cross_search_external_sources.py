"""CrossSearch external sources against mock Confluence/Jira/TestRail (no real systems)."""
from __future__ import annotations

import asyncio
import importlib
import sys
import threading
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent))
from mocks import external_sources_mock as mock  # noqa: E402

from km_credentials.crypto import SourceSecret, seal  # noqa: E402

BASE = "https://mock.example.test"
PRINCIPALS = {"alice": {"user_id": "u-alice", "instance_id": "test", "role": "user", "epoch": 1},
              "bob": {"user_id": "u-bob", "instance_id": "test", "role": "user", "epoch": 1}}


@pytest.fixture()
def service(monkeypatch):
    for key, value in {
        "KM_CROSS_SEARCH_ZONE": "test", "KM_CROSS_SEARCH_REDIS_URL": "redis://127.0.0.1:1/0",
        "KM_CROSS_SEARCH_BRIDGE_URL": "http://bridge.invalid", "KM_CROSS_SEARCH_BRIDGE_SECRET": "s" * 32,
        "KM_CROSS_SEARCH_SOURCES": "km,confluence,jira,testrail",
        "KM_CROSS_SEARCH_CONFLUENCE_BASE_URL": BASE + "/confluence",
        "KM_CROSS_SEARCH_JIRA_BASE_URL": BASE + "/jira",
        "KM_CROSS_SEARCH_TESTRAIL_BASE_URL": BASE + "/testrail",
        "KM_CROSS_SEARCH_TESTRAIL_SCOPES": "1",
        "KM_CROSS_SEARCH_EXTERNAL_BUDGET_SECONDS": "2",
    }.items():
        monkeypatch.setenv(key, value)
    for name in ("MOCK_LATENCY_SECONDS", "MOCK_JIRA_LATENCY_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    sys.modules.pop("cross_search.service", None)
    module = importlib.import_module("cross_search.service")
    monkeypatch.setattr(module, "_new_client", lambda config: httpx.AsyncClient(transport=httpx.ASGITransport(app=mock.app)))
    mock.REQUESTS.clear()
    return module


class FakeBridge:
    """Stands in for the KM bridge: per-principal envelopes and validation."""

    def __init__(self, private, revoked=()):
        self.private = private
        self.revoked = set(revoked)
        self.reports = []
        self.lock = threading.Lock()
        self.store = {}

    def link(self, name, source, username, secret, auth_type="basic"):
        user_id = PRINCIPALS[name]["user_id"]
        self.store[(user_id, source)] = {"status": "active", "key_id": "k1",
                                         "envelope": seal(self.private.public_key(), "k1", user_id, source, SourceSecret(username, secret, auth_type))}

    def __call__(self, path, payload=None, cookie=None):
        if payload["user_id"] in self.revoked:
            raise HTTPException(403, "KM grant revoked")
        if path == "credentials":
            return {"sources": {s: self.store.get((payload["user_id"], s), {"status": "not_linked"}) for s in payload["sources"]}}
        if path == "credentials/result":
            with self.lock:
                self.reports.append((payload["user_id"], payload["source"], payload["ok"], payload["error_code"]))
            return {"status": "recorded"}
        if path == "validate":
            return {"status": "valid"}
        raise AssertionError(path)


@pytest.fixture()
def bridge(service, monkeypatch):
    private = X25519PrivateKey.generate()
    fake = FakeBridge(private)
    monkeypatch.setattr(service, "_bridge", fake)
    monkeypatch.setattr(service, "_PRIVATE_KEYS", {"k1": private})
    return fake


def _record(name, query="throughput n78", sources=("confluence", "jira", "testrail")):
    return {"principal": PRINCIPALS[name], "query": query, "sources": list(sources), "topK": 10}


def test_each_source_uses_the_users_own_credential(service, bridge):
    for source in ("confluence", "jira", "testrail"):
        bridge.link("alice", source, "alice", "alice-pass")
    statuses, results = service._run_external(_record("alice"), ["confluence", "jira", "testrail"])
    assert statuses == {"confluence": "completed", "jira": "completed", "testrail": "completed"}
    assert {item["sourceSystem"] for item in results} == {"confluence", "jira", "testrail"}
    assert all("alice" in item["title"].lower() for item in results)
    assert {entry["user"] for entry in mock.REQUESTS} == {"alice"}
    assert sorted(r[1] for r in bridge.reports if r[2]) == ["confluence", "jira", "testrail"]


def test_bearer_token_credentials_are_supported(service, bridge):
    bridge.link("alice", "jira", "alice", "alice-pat", auth_type="bearer")
    statuses, results = service._run_external(_record("alice", sources=["jira"]), ["jira"])
    assert statuses == {"jira": "completed"} and results


def test_concurrent_users_never_mix_credentials(service, bridge):
    for name in ("alice", "bob"):
        for source in ("confluence", "jira", "testrail"):
            bridge.link(name, source, name, f"{name}-pass")
    outputs, errors = {}, []
    barrier = threading.Barrier(10)

    def run(name, index):
        try:
            barrier.wait()
            outputs[(name, index)] = service._run_external(_record(name), ["confluence", "jira", "testrail"])
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(name, i)) for i in range(5) for name in ("alice", "bob")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    for (name, _), (statuses, results) in outputs.items():
        other = "bob" if name == "alice" else "alice"
        assert set(statuses.values()) == {"completed"}
        assert results and all(name in item["title"].lower() and other not in item["title"].lower() for item in results)
    assert len(mock.REQUESTS) == 30 and all(entry["user"] in ("alice", "bob") for entry in mock.REQUESTS)


def test_unlinked_and_rejected_credentials_are_explicit_and_not_retried(service, bridge):
    bridge.link("alice", "jira", "alice", "wrong-password")
    statuses, results = service._run_external(_record("alice", sources=["confluence", "jira"]), ["confluence", "jira"])
    assert statuses == {"confluence": "not_linked", "jira": "needs_relink"} and results == []
    assert [entry["source"] for entry in mock.REQUESTS] == ["jira"]
    assert bridge.reports == [("u-alice", "jira", False, "source_rejected")]


def test_revoked_principal_gets_no_credentials(service, bridge):
    bridge.link("alice", "jira", "alice", "alice-pass")
    bridge.revoked.add("u-alice")
    statuses, results = service._run_external(_record("alice", sources=["jira"]), ["jira"])
    assert statuses == {"jira": "rejected"} and results == [] and mock.REQUESTS == []


def test_query_text_cannot_change_cql_or_jql_structure(service, bridge):
    bridge.link("alice", "confluence", "alice", "alice-pass")
    bridge.link("alice", "jira", "alice", "alice-pass")
    service._run_external(_record("alice", query='n78" OR space = "SECRET', sources=["confluence", "jira"]), ["confluence", "jira"])
    cql = next(e["query"] for e in mock.REQUESTS if e["source"] == "confluence")
    jql = next(e["query"] for e in mock.REQUESTS if e["source"] == "jira")
    # The user's quotes are stripped, so the whole input stays one string literal.
    assert cql == 'type = "page" AND text ~ "n78 OR space = SECRET"'
    assert jql.startswith('text ~ "n78 OR space = SECRET" ORDER BY')
    assert cql.count('"') == 4 and jql.count('"') == 2


def test_slow_source_is_cut_by_budget_and_others_still_return(service, bridge, monkeypatch):
    monkeypatch.setenv("MOCK_JIRA_LATENCY_SECONDS", "5")
    monkeypatch.setattr(service, "EXTERNAL_BUDGET_SECONDS", 0.5)
    for source in ("confluence", "jira"):
        bridge.link("alice", source, "alice", "alice-pass")
    statuses, results = service._run_external(_record("alice", sources=["confluence", "jira"]), ["confluence", "jira"])
    assert statuses == {"confluence": "completed", "jira": "timeout"}
    assert results and all(item["sourceSystem"] == "confluence" for item in results)


def test_unconfigured_source_is_reported(service, bridge, monkeypatch):
    monkeypatch.delenv("KM_CROSS_SEARCH_TESTRAIL_SCOPES")
    bridge.link("alice", "testrail", "alice", "alice-pass")
    statuses, _ = service._run_external(_record("alice", sources=["testrail"]), ["testrail"])
    assert statuses == {"testrail": "not_configured"}
    monkeypatch.delenv("KM_CROSS_SEARCH_TESTRAIL_BASE_URL")
    statuses, _ = service._run_external(_record("alice", sources=["testrail"]), ["testrail"])
    assert statuses == {"testrail": "not_configured"}


def test_external_urls_are_limited_to_the_configured_origin(service):
    from cross_search.connectors import SourceConfig, _safe_external_url
    config = SourceConfig(name="jira", base_url=BASE + "/jira")
    assert _safe_external_url(config, BASE + "/jira/browse/A-1") == BASE + "/jira/browse/A-1"
    assert _safe_external_url(config, "https://evil.example.test/x") is None


def test_plain_http_source_is_refused_by_default(service, monkeypatch):
    from cross_search.connectors import load_source_config
    monkeypatch.setenv("KM_CROSS_SEARCH_JIRA_BASE_URL", "http://jira.example.test")
    with pytest.raises(ValueError):
        load_source_config("jira")


def test_weighted_fusion(service, monkeypatch):
    monkeypatch.setattr(service, "SOURCE_WEIGHTS", {"km": 2.0})
    fused = service._fuse([{"sourceSystem": "jira", "sourceRank": 1}, {"sourceSystem": "km", "sourceRank": 2},
                           {"sourceSystem": "confluence", "sourceRank": 2}], 2)
    assert [item["sourceSystem"] for item in fused] == ["km", "jira"]


def test_results_are_withheld_when_session_is_revoked_before_release(service, bridge, monkeypatch):
    bridge.link("alice", "jira", "alice", "alice-pass")
    stored, released = [], []
    record = {"queryId": "q1", "owner": "u-alice", "principal": PRINCIPALS["alice"], "query": "throughput n78",
              "sources": ["jira"], "topK": 10, "status": "queued", "results": [], "sourceStatus": {}, "createdAt": 0}
    monkeypatch.setattr(service, "_record", lambda query_id: dict(record))
    monkeypatch.setattr(service, "_store", lambda query_id, value: stored.append(value))
    monkeypatch.setattr(service, "_release_active", lambda user_id, query_id: released.append((user_id, query_id)))
    original = bridge.__call__

    def revoke_on_validate(path, payload=None, cookie=None):
        if path == "validate":
            raise HTTPException(403, "KM grant revoked")
        return original(path, payload, cookie)

    monkeypatch.setattr(service, "_bridge", revoke_on_validate)
    service.run_query.run("q1")
    assert stored[-1]["results"] == [] and stored[-1]["sourceStatus"] == {"jira": "rejected"}
    assert released == [("u-alice", "q1")]


def test_completed_run_releases_single_flight_slot(service, bridge, monkeypatch):
    bridge.link("alice", "jira", "alice", "alice-pass")
    stored, released = [], []
    record = {"queryId": "q2", "owner": "u-alice", "principal": PRINCIPALS["alice"], "query": "throughput n78",
              "sources": ["jira"], "topK": 10, "status": "queued", "results": [], "sourceStatus": {}, "createdAt": 0}
    monkeypatch.setattr(service, "_record", lambda query_id: dict(record))
    monkeypatch.setattr(service, "_store", lambda query_id, value: stored.append(value))
    monkeypatch.setattr(service, "_release_active", lambda user_id, query_id: released.append((user_id, query_id)))
    service.run_query.run("q2")
    assert stored[-1]["status"] == "completed" and stored[-1]["results"][0]["fusionScore"] > 0
    assert released == [("u-alice", "q2")]
