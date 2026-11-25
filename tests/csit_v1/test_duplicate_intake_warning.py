"""Intake-time duplicate warning: detect only. The job is always accepted, and a failing check can never fail or undo an intake."""
import hashlib
import logging
import uuid

import pytest

from src.csit_integration_v1 import duplicate_content as dc
from src.csit_integration_v1.v2_models import DocumentJobRequest
from src.csit_integration_v1.v2_repository import V2Repository

LOGGER = "km.csit.duplicate_content"
SAME = b"identical bytes " * 20
OTHER = b"different bytes " * 20


def body(content, source="VendorFile", name="x.txt"):
    doc = str(uuid.uuid4())
    return {"schemaVersion": "2.0", "eventId": str(uuid.uuid4()), "csitJobId": str(uuid.uuid4()), "eventType": "VendorFileArchived", "sourceSystem": "CSIT",
            "source": {"type": source, "entityId": doc, "moduleCode": "vendor", "applicationId": str(uuid.uuid4()), "recordId": None, "vendorId": None, "equipmentId": None},
            "document": {"id": doc, "version": 1, "originalFileName": name, "contentType": "application/octet-stream", "sizeBytes": len(content),
                         "sha256": hashlib.sha256(content).hexdigest(), "downloadUrl": "https://csit.example/ignored", "archivedAt": "2026-11-25T01:00:00Z",
                         "approval": {"mode": "Approved", "referenceId": str(uuid.uuid4()), "approvedAt": "2026-11-25T01:00:00Z"}},
            "classification": {"l1": None, "l2": None, "l3": None}, "supersedes": None, "occurredAt": "2026-11-25T01:00:00Z"}


@pytest.fixture
def vrepo(repo, db_url):          # `repo` truncates the job tables first
    return V2Repository(db_url)


def submit(vrepo, content, **kw):
    return vrepo.submit_job(DocumentJobRequest.model_validate(body(content, **kw)))


def count_jobs(vrepo):
    with vrepo.connect() as c:
        return c.execute("SELECT count(*) AS n FROM km_csit_v2_jobs").fetchone()["n"]


def test_a_second_record_with_the_same_bytes_is_accepted_and_logged_with_both_job_ids(vrepo, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    first = submit(vrepo, SAME)
    assert not caplog.records                                   # nothing to warn about yet
    second = submit(vrepo, SAME)
    assert second["status"] == "Accepted" and count_jobs(vrepo) == 2     # never blocked
    msgs = [r.getMessage() for r in caplog.records if r.name == LOGGER]
    assert len(msgs) == 1 and second["km_job_id"] in msgs[0] and first["km_job_id"] in msgs[0] and "duplicate content" in msgs[0]


def test_different_bytes_log_nothing(vrepo, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    submit(vrepo, SAME)
    submit(vrepo, OTHER)
    assert not [r for r in caplog.records if r.name == LOGGER]


def test_replaying_the_same_event_does_not_warn_again(vrepo, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    submit(vrepo, SAME)
    req = DocumentJobRequest.model_validate(body(SAME))
    vrepo.submit_job(req)
    n = len(caplog.records)
    assert n == 1
    vrepo.submit_job(req)                                       # idempotent replay of the same eventId
    assert len(caplog.records) == n and count_jobs(vrepo) == 2


def test_a_check_that_raises_never_fails_the_intake(vrepo, caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    def boom(*a, **k):
        raise RuntimeError("log backend down")
    monkeypatch.setattr(dc, "warn_if_duplicate", boom)
    row = submit(vrepo, SAME)
    assert row["status"] == "Accepted" and count_jobs(vrepo) == 1
    assert any("intake is unaffected" in r.getMessage() for r in caplog.records)


def test_a_database_error_inside_the_check_does_not_undo_the_committed_job(vrepo, monkeypatch):
    monkeypatch.setattr(dc, "PEER_SQL", "SELECT * FROM no_such_table WHERE x = %s")
    row = submit(vrepo, SAME)
    assert row["status"] == "Accepted"
    assert count_jobs(vrepo) == 1                               # the insert was committed before the check ran


def test_the_peer_query_can_only_read():
    import re
    assert re.match(r"\s*SELECT\b", dc.PEER_SQL) and not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b", dc.PEER_SQL, re.I)
    src = open(dc.__file__, encoding="utf-8").read()
    assert "SET TRANSACTION READ ONLY" in src
