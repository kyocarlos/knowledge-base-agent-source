"""Deletion readiness (CSIT, 2026-11-13): a document KM accepted but could not analyse is deleted and verified like any other,
a deletion for a source KM never saw is answered NotPresent after a check, the deletion callback asks for its own scope, and the search cache is checked again."""
import urllib.parse
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from src.csit_integration_v1.auth import ClientCredentialsProvider
from src.csit_integration_v1.config import Settings
from src.csit_integration_v1.doclib_models import DeletionRequest, DocLibRequest
from src.csit_integration_v1.doclib_pipeline import doclib_dir
from src.csit_integration_v1.errors import IntegrationError

from test_doclib_v13 import (Csit, FakeQdrant, make_worker, submit, drain_callbacks, deletion_body, file_resource, request_body,  # noqa: F401 (fixtures)
                             dsettings, drepo, client)
from conftest import *  # noqa: F401,F403  (settings, repo fixtures)

SCOPE = "csit.km.deletion-status.write"


def with_scope(dsettings):
    return replace(dsettings, outbound_scopes=tuple(dsettings.outbound_scopes) + (SCOPE,))


def delete(drepo, file_id):
    return drepo.submit_deletion(DeletionRequest.model_validate(deletion_body(file_resource(file_id))))


def all_not_present(cleanup, *, metadata):
    expect = {"metadata": metadata, "extractedText": "NotPresent", "chunks": "NotPresent", "vectorIndex": "NotPresent",
              "graphRelations": "NotPresent", "cache": "NotPresent", "storedCopies": "NotPresent"}
    return cleanup == expect


# ---- accepted, then failed: the KM-DOC-000024 situation ---------------------------------------------------------------------------------

def test_a_document_that_failed_analysis_is_deleted_and_the_missing_index_is_verified_not_present(dsettings, drepo):
    ds = with_scope(dsettings)
    csit, q = Csit(), FakeQdrant()
    w = make_worker(ds, drepo, csit, q)
    body, job = submit(drepo, name="tool.exe")                        # a format KM cannot analyse: Failed before any download
    assert w.process_one(); drain_callbacks(w)
    assert csit.callbacks[-1][1]["error"]["code"] == "UNSUPPORTED_DOCUMENT_FORMAT" and csit.downloads == 0 and not q.points
    csit.callbacks.clear()

    delete(drepo, body["documentFileId"])
    assert w.delete_one(); drain_callbacks(w)

    assert [p["status"] for _, p in csit.callbacks] == ["Processing", "Completed"]
    assert all(path.endswith("/document-deletion-status") for path, _ in csit.callbacks)
    done = csit.callbacks[-1][1]
    assert done["result"]["cleanupVerified"] is True
    assert all_not_present(done["result"]["cleanup"], metadata="Deleted")   # the request payload and the file name were still stored; nothing else existed
    with drepo.connect() as c:
        row = c.execute("SELECT status,original_file_name,request_payload FROM km_csit_doclib_jobs WHERE document_file_id=%s", (body["documentFileId"],)).fetchone()
    assert row["status"] == "Failed" and row["original_file_name"] == "[deleted]" and row["request_payload"] == {}   # the failure stays on record, the content does not
    assert drepo.file_deleted(body["documentFileId"])
    with pytest.raises(IntegrationError) as e:                         # the tombstone refuses a late re-send of the same file
        drepo.submit(DocLibRequest.model_validate(request_body(documentFileId=body["documentFileId"])))
    assert e.value.code == "DOCUMENT_DELETED"


def test_a_failed_job_that_left_a_stored_copy_has_the_copy_removed_and_reported_deleted(dsettings, drepo):
    ds = with_scope(dsettings)
    csit, q = Csit(), FakeQdrant()
    w = make_worker(ds, drepo, csit, q)
    body, job = submit(drepo, name="tool.exe")
    w.process_one(); drain_callbacks(w); csit.callbacks.clear()
    d = doclib_dir(ds.storage_root, body["csitJobId"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "source-tool.exe").write_bytes(b"MZ stored copy")
    delete(drepo, body["documentFileId"])
    assert w.delete_one(); drain_callbacks(w)
    result = csit.callbacks[-1][1]["result"]
    assert result["cleanupVerified"] is True and result["cleanup"]["storedCopies"] == "Deleted" and not d.exists()


def test_a_job_accepted_but_not_started_is_cancelled_and_cannot_start_later(dsettings, drepo):
    ds = with_scope(dsettings)
    csit, q = Csit(), FakeQdrant()
    w = make_worker(ds, drepo, csit, q)
    body, job = submit(drepo)                                         # Accepted, no worker has claimed it
    delete(drepo, body["documentFileId"])
    assert drepo.get_job(body["csitJobId"])["status"] == "Cancelled"
    assert w.delete_one() and not w.process_one(); drain_callbacks(w)
    assert csit.downloads == 0 and not q.points
    done = [p for _, p in csit.callbacks if p["status"] == "Completed"][-1]
    assert done["result"]["cleanupVerified"] is True and done["result"]["cleanup"]["chunks"] == "NotPresent"


def test_a_deletion_for_a_source_km_never_received_is_answered_not_present_and_blocks_a_later_job(dsettings, drepo):
    ds = with_scope(dsettings)
    csit, q = Csit(), FakeQdrant()
    w = make_worker(ds, drepo, csit, q)
    fid = str(uuid.uuid4())
    delete(drepo, fid)
    assert w.delete_one(); drain_callbacks(w)
    done = csit.callbacks[-1][1]
    assert done["status"] == "Completed" and done["result"]["cleanupVerified"] is True
    assert all_not_present(done["result"]["cleanup"], metadata="NotPresent")
    with pytest.raises(IntegrationError) as e:
        drepo.submit(DocLibRequest.model_validate(request_body(documentFileId=fid)))
    assert e.value.code == "DOCUMENT_DELETED"


# ---- the search cache is a store like the others ------------------------------------------------------------------------------------------

def test_cleanup_is_not_verified_while_a_cached_search_still_mentions_the_source(dsettings, drepo):
    ds = with_scope(dsettings)
    csit, q = Csit(), FakeQdrant()
    w = make_worker(ds, drepo, csit, q)
    body, _ = submit(drepo)
    w.process_one(); drain_callbacks(w); csit.callbacks.clear()
    w.executor.cache_clear = lambda resource: 0
    w.executor.cache_check = lambda resource: 2
    delete(drepo, body["documentFileId"])
    w.delete_one(); drain_callbacks(w)
    assert all(p["status"] != "Completed" for _, p in csit.callbacks)
    with drepo.connect() as c:
        assert c.execute("SELECT last_error_code FROM km_csit_deletion_jobs").fetchone()["last_error_code"] == "CLEANUP_NOT_VERIFIED"


def test_cache_entries_cleared_are_reported_deleted_when_the_check_finds_nothing_left(dsettings, drepo):
    ds = with_scope(dsettings)
    csit, q = Csit(), FakeQdrant()
    w = make_worker(ds, drepo, csit, q)
    body, _ = submit(drepo)
    w.process_one(); drain_callbacks(w); csit.callbacks.clear()
    w.executor.cache_clear = lambda resource: 4
    w.executor.cache_check = lambda resource: 0
    delete(drepo, body["documentFileId"])
    assert w.delete_one(); drain_callbacks(w)
    result = csit.callbacks[-1][1]["result"]
    assert result["cleanupVerified"] is True and result["cleanup"]["cache"] == "Deleted" and result["cleanup"]["chunks"] == "Deleted"


# ---- the deletion callback asks for its own scope ------------------------------------------------------------------------------------------

class ScopeAuth:
    def __init__(self):
        self.asked = []

    def headers(self, scopes=None):
        self.asked.append(tuple(scopes) if scopes else None)
        return {"Authorization": "Bearer fake-outbound"}


def callbacks(drepo):
    with drepo.connect() as c:
        return c.execute("SELECT kind,status,last_error_code FROM km_csit_v13_callbacks ORDER BY sequence").fetchall()


def test_the_deletion_callback_uses_its_own_scopes_and_ordinary_callbacks_keep_theirs(dsettings, drepo):
    ds = replace(dsettings, deletion_callback_scopes=(SCOPE,))          # SCOPE is not in outbound_scopes
    assert SCOPE not in ds.outbound_scopes
    csit, q = Csit(), FakeQdrant()
    w = make_worker(ds, drepo, csit, q)
    w.client.auth = ScopeAuth()
    body, _ = submit(drepo)
    w.process_one(); drain_callbacks(w)
    delete(drepo, body["documentFileId"])
    assert w.delete_one(); drain_callbacks(w)
    asked = w.client.auth.asked
    assert asked[:3] == [None, None, None]                              # the download, then Processing and Completed of the ingestion: the ordinary token
    assert asked[3:] and all(a is not None and SCOPE in a and set(ds.outbound_scopes) <= set(a) for a in asked[3:])
    assert [r["status"] for r in callbacks(drepo)] == ["Delivered"] * len(callbacks(drepo))
    assert csit.callbacks[-1][1]["status"] == "Completed"


def test_without_the_deletion_scope_the_v1_deletion_callback_is_held_and_ordinary_callbacks_are_not_affected(dsettings, drepo):
    ds = replace(dsettings, callback_retry_delays=Settings().callback_retry_delays)   # the production delays: the held callback waits, it is not used up at once
    csit, q = Csit(), FakeQdrant()
    w = make_worker(ds, drepo, csit, q)                                  # no deletion scope anywhere
    body, _ = submit(drepo)
    w.process_one(); drain_callbacks(w)
    delete(drepo, body["documentFileId"])
    assert w.delete_one(); drain_callbacks(w)
    rows = callbacks(drepo)
    assert [r["status"] for r in rows if r["kind"] == "ingestion"] == ["Delivered", "Delivered"]
    held = [r for r in rows if r["kind"] == "deletion"]
    assert held and held[0]["status"] == "Pending" and held[0]["last_error_code"] == "M2M_SCOPE_MISSING"
    assert not any(p["status"] in ("Processing", "Completed") and path.endswith("document-deletion-status") for path, p in csit.callbacks)


def make_provider(settings, grant):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    asked = []

    def handler(r):
        scope = dict(urllib.parse.parse_qsl(r.content.decode()))["scope"]
        asked.append(scope)
        granted = grant(scope)
        now = datetime.now(timezone.utc)
        token = jwt.encode({"iss": settings.authority, "aud": settings.outbound_audience, "iat": now, "exp": now + timedelta(minutes=5), "principal_type": "service",
                            "client_id": settings.client_id, "sub": settings.client_id, "scope": granted}, key, algorithm="RS256")
        return httpx.Response(200, json={"access_token": token, "token_type": "Bearer", "expires_in": 300, "scope": granted})
    provider = ClientCredentialsProvider(settings, httpx.MockTransport(handler))
    provider.keys = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key()))
    return provider, asked


def test_a_token_is_requested_and_cached_per_scope_set(settings):
    provider, asked = make_provider(settings, lambda scope: scope)
    base = tuple(settings.outbound_scopes)
    wanted = base + (SCOPE,)
    a, b = provider.headers(), provider.headers(scopes=wanted)
    assert a != b and asked == [" ".join(base), " ".join(wanted)]
    assert provider.headers() == a and provider.headers(scopes=wanted) == b and len(asked) == 2   # each one cached on its own
    provider.close()


def test_when_the_identity_server_does_not_grant_the_deletion_scope_only_the_deletion_token_fails(settings):
    provider, asked = make_provider(settings, lambda scope: " ".join(x for x in scope.split() if x != SCOPE))
    base = tuple(settings.outbound_scopes)
    with pytest.raises(IntegrationError, match="M2M_SCOPE_MISSING"):
        provider.headers(scopes=base + (SCOPE,))
    assert provider.headers()["Authorization"].startswith("Bearer ")     # the ordinary token is untouched
    provider.close()
