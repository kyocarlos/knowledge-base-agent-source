"""Callback delivery: which failures are retried, for how long, and that a retry re-sends the same callback and never re-runs the analysis."""
import json

from dataclasses import replace

import httpx
import pytest

from src.csit_integration_v1.config import Settings

from test_v2_spec14 import Csit, FakeQdrant, make, submit, dsettings, vrepo, drain  # noqa: F401  (fixtures)
from conftest import *  # noqa: F401,F403  (settings, repo fixtures)


class FlakyCsit(Csit):
    """The file download always works; the status callback answers from a script (an int status or an exception to raise)."""
    def __init__(self):
        super().__init__()
        self.script = []
        self.sent = []

    def __call__(self, r):
        if r.method == "GET":
            return super().__call__(r)
        self.sent.append(json.loads(r.content))
        step = self.script.pop(0) if self.script else 204
        if isinstance(step, Exception):
            raise step
        return httpx.Response(step)


def callbacks(vrepo):
    with vrepo.connect() as c:
        return c.execute("SELECT callback_id,status,attempt_count,last_error_code,next_retry_at FROM km_csit_v13_callbacks ORDER BY sequence").fetchall()


def due_now(vrepo):
    with vrepo.connect() as c:
        c.execute("UPDATE km_csit_v13_callbacks SET next_retry_at=clock_timestamp()-interval '1 second' WHERE status='Pending'")


def setup(dsettings, vrepo, script):
    dsettings = replace(dsettings, callback_retry_delays=Settings().callback_retry_delays)   # the production delays, not the test fixture's zeros
    csit = FlakyCsit()
    csit.script = list(script)
    w = make(dsettings, vrepo, csit, FakeQdrant())
    submit(vrepo)
    assert w.v2.ingest_one()
    return w, csit


@pytest.mark.parametrize("failure,code", [(503, "CSIT_HTTP_ERROR"), (502, "CSIT_HTTP_ERROR"), (500, "CSIT_HTTP_ERROR"), (429, "CSIT_HTTP_ERROR"),
                                           (httpx.ConnectTimeout("t"), "CSIT_CALLBACK_NETWORK_ERROR"), (httpx.ReadTimeout("t"), "CSIT_CALLBACK_NETWORK_ERROR"),
                                           (httpx.ConnectError("refused"), "CSIT_CALLBACK_NETWORK_ERROR")])
def test_a_transient_failure_is_retried_with_the_same_callback_until_csit_answers(dsettings, vrepo, failure, code):
    w, csit = setup(dsettings, vrepo, [failure])
    assert w.callback_one()
    first = callbacks(vrepo)[0]
    assert first["status"] == "Pending" and first["last_error_code"] == code and first["next_retry_at"] is not None and first["attempt_count"] == 1
    due_now(vrepo)
    drain(w)
    rows = callbacks(vrepo)
    assert [r["status"] for r in rows] == ["Delivered", "Delivered"] and rows[0]["callback_id"] == first["callback_id"] and rows[0]["attempt_count"] == 2
    assert csit.sent[0]["callbackId"] == csit.sent[1]["callbackId"]     # the same callback again, same Idempotency-Key
    assert len(csit.downloads) == 1                                      # the analysis is not run again


@pytest.mark.parametrize("status,code", [(400, "CSIT_HTTP_ERROR"), (401, "CSIT_AUTH_FORBIDDEN"), (403, "CSIT_AUTH_FORBIDDEN"), (404, "CSIT_DOCUMENT_NOT_FOUND"),
                                          (409, "CSIT_CALLBACK_CONFLICT")])
def test_a_permanent_contract_or_authorisation_error_is_not_retried(dsettings, vrepo, status, code):
    w, csit = setup(dsettings, vrepo, [status])
    assert w.callback_one()
    first = callbacks(vrepo)[0]
    assert first["status"] == "Failed" and first["last_error_code"] == code and first["next_retry_at"] is None
    due_now(vrepo)
    assert w.callback_one()                      # only the next callback (Completed) goes out; the Failed one is never re-sent
    assert callbacks(vrepo)[0]["status"] == "Failed" and callbacks(vrepo)[0]["attempt_count"] == 1
    assert [p["status"] for p in csit.sent] == ["Processing", "Completed"]


def test_the_retry_budget_is_five_attempts_over_about_twenty_one_minutes_and_then_the_callback_fails(dsettings, vrepo):
    assert Settings().callback_retry_delays == (10, 60, 300, 900) and sum(Settings().callback_retry_delays) == 1270
    w, csit = setup(dsettings, vrepo, [503] * 10)
    for attempt in range(1, 6):
        assert w.callback_one()
        row = callbacks(vrepo)[0]
        assert row["attempt_count"] == attempt
        assert row["status"] == ("Pending" if attempt < 5 else "Failed")
        due_now(vrepo)
    first = callbacks(vrepo)[0]
    assert first["last_error_code"] == "CSIT_HTTP_ERROR" and first["status"] == "Failed" and first["attempt_count"] == 5
    assert {p["callbackId"] for p in csit.sent[:5]} == {str(first["callback_id"])}   # five sends of one callback, then it stops for good


def test_a_later_callback_waits_for_an_earlier_pending_one_of_the_same_job(dsettings, vrepo):
    w, csit = setup(dsettings, vrepo, [503])
    assert w.callback_one()                      # Processing hits a 503 and is Pending
    assert not w.callback_one()                  # Completed must not overtake it
    assert [r["status"] for r in callbacks(vrepo)] == ["Pending", "Pending"]
    due_now(vrepo)
    drain(w)
    assert [p["status"] for p in csit.sent if p["status"] in ("Processing", "Completed")][-2:] == ["Processing", "Completed"]
