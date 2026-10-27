import json

from src.web_api import wifi8_routes
from src.wifi8 import progress
from tests.test_wifi8_routes import make_client
from tests.test_wifi8_search import engine  # noqa: F401  (fixture)


class FakeRedis:
    def __init__(self):
        self.data, self.ttl = {}, {}

    def set(self, key, value, ex=None):
        self.data[key] = value.encode() if isinstance(value, str) else value
        self.ttl[key] = ex

    def get(self, key):
        return self.data.get(key)

    def rpush(self, key, value):
        self.data.setdefault(key, []).append(value.encode())

    def expire(self, key, seconds):
        self.ttl[key] = seconds

    def lrange(self, key, start, stop):
        return self.data.get(key, [])[start:stop + 1]


OWNER = {"user_id": "u1", "instance_id": "test"}


def test_text_pieces_are_batched_and_everything_arrives_in_order():
    redis, now = FakeRedis(), [0.0]
    progress.register(redis, "t1", OWNER)
    emit = progress.Emitter(redis, "t1", clock=lambda: now[0])
    emit({"type": "tool", "tool": "search_wifi", "label": "檢索文件段落"})
    for piece in ["A", "B", "C"]:
        emit({"type": "delta", "text": piece})  # all inside one flush window
    now[0] = 1.0
    emit({"type": "delta", "text": "D"})        # window elapsed: A..D go out as one event
    emit({"type": "delta", "text": "E"})
    emit.done("completed")
    got = progress.read(redis, "t1", OWNER)
    assert [e["type"] for e in got["events"]] == ["tool", "delta", "delta", "done"] and got["done"] is True
    assert "".join(e["text"] for e in got["events"] if e["type"] == "delta") == "ABCDE" and got["next"] == 4
    assert progress.read(redis, "t1", OWNER, after=3)["events"][0]["type"] == "done"
    assert redis.ttl["wifi8:agent:events:t1"] == progress.TTL_SECONDS


def test_reset_drops_unsent_text_and_tells_the_reader():
    redis = FakeRedis()
    progress.register(redis, "t1", OWNER)
    emit = progress.Emitter(redis, "t1", clock=lambda: 0.0)
    emit({"type": "delta", "text": "我先查一下"})
    emit({"type": "reset"})
    emit({"type": "tool", "tool": "x", "label": "x"})
    assert [e["type"] for e in progress.read(redis, "t1", OWNER)["events"]] == ["reset", "tool"]


def test_only_the_owner_can_read_and_unknown_tasks_look_the_same():
    redis = FakeRedis()
    progress.register(redis, "t1", OWNER)
    progress.Emitter(redis, "t1")({"type": "tool", "tool": "x", "label": "x"})
    assert progress.read(redis, "t1", {"user_id": "u2", "instance_id": "test"}) is None
    assert progress.read(redis, "nope", OWNER) is None


def test_event_count_is_capped(monkeypatch):
    redis = FakeRedis()
    progress.register(redis, "t1", OWNER)
    monkeypatch.setattr(progress, "MAX_EVENTS", 3)
    emit = progress.Emitter(redis, "t1")
    for i in range(10):
        emit({"type": "tool", "tool": str(i), "label": str(i)})
    assert len(progress.read(redis, "t1", OWNER)["events"]) == 3


def test_events_route_is_owner_checked_and_reports_unavailable_redis(monkeypatch, engine):  # noqa: F811
    from src.web_api import tasks
    redis = FakeRedis()
    monkeypatch.setattr(tasks, "get_redis_client", lambda: redis)
    progress.register(redis, "t1", OWNER)
    progress.Emitter(redis, "t1")({"type": "tool", "tool": "x", "label": "x"})
    client = make_client(monkeypatch, engine)
    body = client.get("/api/wifi8/agent/t1/events").json()
    assert body["events"][0]["type"] == "tool" and body["next"] == 1 and body["done"] is False
    assert client.get("/api/wifi8/agent/other/events").status_code == 404

    def broken():
        raise ConnectionError("down")
    monkeypatch.setattr(tasks, "get_redis_client", broken)
    assert client.get("/api/wifi8/agent/t1/events").status_code == 503


def test_submit_tells_the_page_whether_to_listen(monkeypatch, engine):  # noqa: F811
    from src.web_api import tasks
    redis = FakeRedis()
    monkeypatch.setattr(tasks, "get_redis_client", lambda: redis)
    sent = []
    monkeypatch.setattr(tasks.celery_app, "send_task", lambda name, args, queue: sent.append(args) or type("T", (), {"id": "t9"})())
    client = make_client(monkeypatch, engine)
    monkeypatch.delenv("KM_WIFI8_STREAM", raising=False)
    off = client.post("/api/wifi8/agent", json={"question": "q"}).json()
    monkeypatch.delenv("KM_WIFI8_FEEDBACK", raising=False)
    assert off == {"task_id": "t9", "status": "submitted", "stream": False, "feedback": False} and redis.get("wifi8:agent:owner:t9") is None
    monkeypatch.setenv("KM_WIFI8_STREAM", "1")
    on = client.post("/api/wifi8/agent", json={"question": "q"}).json()
    assert on["stream"] is True and json.loads(redis.get("wifi8:agent:owner:t9")) == OWNER
