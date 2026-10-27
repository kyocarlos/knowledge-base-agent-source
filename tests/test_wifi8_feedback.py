import json
import time

import pytest

from src.web_api import wifi8_routes
from src.wifi8 import feedback
from tests.test_wifi8_routes import make_client
from tests.test_wifi8_search import engine  # noqa: F401  (fixture)

OWNER = {"user_id": "u1", "instance_id": "test"}
TASK = "3f9c1e52-aaaa-bbbb-cccc-0123456789ab"
VALUE = {"owner": OWNER, "status": "completed", "question": "ELR 是什麼？", "answer": "## 結論\nELR 是增強長距離 [S1]", "model": "m", "package_id": "p1", "stop_reason": "answered",
         "citations": [{"ref": "S1", "source": "ELR MRD v2", "revision_id": "elr2"}], "trace": [{"tool": "search_wifi"}], "elapsed_ms": 1234,
         "grounding": {"summary": {"claims": 3, "claims_cited": 3, "values": 0, "secret": "x"}}}


def fake_celery(monkeypatch, value, ready=True):
    class FakeResult:
        def __init__(self, task_id, app=None):
            self.result = value

        def ready(self):
            return ready
    monkeypatch.setattr("celery.result.AsyncResult", FakeResult)


def client(monkeypatch, engine, tmp_path, enabled=True):  # noqa: F811
    monkeypatch.setenv("KM_WIFI8_FEEDBACK", "1" if enabled else "0")
    monkeypatch.setattr(wifi8_routes, "_wifi8_root", lambda: tmp_path)
    return make_client(monkeypatch, engine)


def test_a_thumbs_down_keeps_reasons_comment_and_a_snapshot_of_the_case(monkeypatch, engine, tmp_path):  # noqa: F811
    fake_celery(monkeypatch, VALUE)
    c = client(monkeypatch, engine, tmp_path)
    out = c.post(f"/api/wifi8/agent/{TASK}/feedback", json={"rating": "down", "reasons": ["wrong_fact", "wrong_fact", "bogus"], "comment": "  版本寫錯  "}).json()
    assert out == {"task_id": TASK, "rating": "down", "reasons": ["wrong_fact"]}
    saved = json.loads((tmp_path / "feedback" / f"{TASK}.json").read_text(encoding="utf-8"))
    assert saved["comment"] == "版本寫錯" and saved["owner"] == OWNER and saved["question"] == "ELR 是什麼？" and saved["cited"] == ["ELR MRD v2"]
    assert saved["tools"] == ["search_wifi"] and saved["grounding"] == {"claims": 3, "claims_cited": 3, "values": 0}  # only the known counters


def test_rating_again_replaces_and_thumbs_up_drops_reasons(monkeypatch, engine, tmp_path):  # noqa: F811
    fake_celery(monkeypatch, VALUE)
    c = client(monkeypatch, engine, tmp_path)
    c.post(f"/api/wifi8/agent/{TASK}/feedback", json={"rating": "down", "reasons": ["unclear"]})
    c.post(f"/api/wifi8/agent/{TASK}/feedback", json={"rating": "up", "reasons": ["unclear"]})
    assert len(list((tmp_path / "feedback").glob("*.json"))) == 1
    assert json.loads((tmp_path / "feedback" / f"{TASK}.json").read_text(encoding="utf-8"))["reasons"] == [] and feedback.summarize(tmp_path)["up"] == 1


@pytest.mark.parametrize("value, ready", [
    (dict(VALUE, owner={"user_id": "someone-else", "instance_id": "test"}), True),  # someone else's task
    (dict(VALUE, status="failed"), True),                                           # nothing to rate
    (None, True), (VALUE, False),                                                   # unknown or still running
])
def test_only_the_asker_can_rate_a_finished_answer(monkeypatch, engine, tmp_path, value, ready):  # noqa: F811
    fake_celery(monkeypatch, value, ready)
    response = client(monkeypatch, engine, tmp_path).post(f"/api/wifi8/agent/{TASK}/feedback", json={"rating": "up"})
    assert response.status_code == 404 and not (tmp_path / "feedback").exists()


def test_bad_input_is_rejected_and_ids_cannot_escape_the_folder(monkeypatch, engine, tmp_path):  # noqa: F811
    fake_celery(monkeypatch, VALUE)
    c = client(monkeypatch, engine, tmp_path)
    assert c.post(f"/api/wifi8/agent/{TASK}/feedback", json={"rating": "meh"}).status_code == 422
    assert c.post(f"/api/wifi8/agent/{TASK}/feedback", json={"rating": "up", "comment": "x" * 501}).status_code == 422
    assert c.post("/api/wifi8/agent/..%2F..%2Fetc/feedback", json={"rating": "up"}).status_code in (404, 422)
    with pytest.raises(feedback.FeedbackError):
        feedback.save(tmp_path, "../../x", OWNER, "up", [], "", VALUE)
    assert not (tmp_path / "feedback").exists() and not list(tmp_path.rglob("*../*"))


def test_summary_and_options_expose_counts_and_labels_only(monkeypatch, engine, tmp_path):  # noqa: F811
    fake_celery(monkeypatch, VALUE)
    c = client(monkeypatch, engine, tmp_path)
    for n, (rating, reasons) in enumerate([("up", []), ("down", ["wrong_fact", "unclear"]), ("down", ["wrong_fact"])]):
        c.post(f"/api/wifi8/agent/3f9c1e52-aaaa-bbbb-cccc-0123456789a{n}/feedback", json={"rating": rating, "reasons": reasons, "comment": "秘密內容"})
    body = c.get("/api/wifi8/agent-feedback/summary").json()
    assert (body["up"], body["down"], body["total"]) == (1, 2, 3) and body["down_reasons"][0] == {"key": "wrong_fact", "label": "內容有誤", "count": 2}
    assert "秘密內容" not in json.dumps(body, ensure_ascii=False) and "ELR" not in json.dumps(body, ensure_ascii=False)
    assert {r["key"] for r in c.get("/api/wifi8/agent-feedback/options").json()["reasons"]} == set(feedback.REASONS)


def test_old_records_fall_out_of_the_window(tmp_path):
    feedback.save(tmp_path, TASK, OWNER, "up", [], "", VALUE)
    old = time.time() - 40 * 86400
    import os
    os.utime(tmp_path / "feedback" / f"{TASK}.json", (old, old))
    assert feedback.summarize(tmp_path, 30)["total"] == 0 and feedback.summarize(tmp_path, 60)["total"] == 1


def test_with_the_flag_off_there_is_no_feedback_at_all(monkeypatch, engine, tmp_path):  # noqa: F811
    fake_celery(monkeypatch, VALUE)
    c = client(monkeypatch, engine, tmp_path, enabled=False)
    assert c.post(f"/api/wifi8/agent/{TASK}/feedback", json={"rating": "up"}).status_code == 404
    assert c.get("/api/wifi8/agent-feedback/summary").status_code == 404 and c.get("/api/wifi8/agent-feedback/options").status_code == 404
    assert not (tmp_path / "feedback").exists()


def test_routes_need_a_login(monkeypatch, engine, tmp_path):  # noqa: F811
    monkeypatch.setenv("KM_WIFI8_FEEDBACK", "1")
    monkeypatch.setattr(wifi8_routes, "_wifi8_root", lambda: tmp_path)
    c = make_client(monkeypatch, engine, authenticated=False)
    assert c.get("/api/wifi8/agent-feedback/summary").status_code in (401, 403)
    assert c.post(f"/api/wifi8/agent/{TASK}/feedback", json={"rating": "up"}).status_code in (401, 403)
