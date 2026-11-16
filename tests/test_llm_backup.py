"""Backup LLM tier (SAM ModaOne): primary gateway -> backup -> Ollama."""
import logging
import types

import pytest
import requests

from src.web_api import llm_failover as lf
from src.web_api import ollama_client as oc
from src.web_api.openai_compatible_client import OpenAICompatibleClient, StreamInterrupted

BACKUP_ENV = {
    "KM_LLM_BACKUP_PROVIDER": "modaone", "KM_LLM_BACKUP_MODEL": "gpt-oss-120b", "KM_LLM_BACKUP_BASE_URL": "https://backup.test/api/v1",
    "KM_LLM_BACKUP_API_KEY_ENV": "TEST_BACKUP_KEY", "TEST_BACKUP_KEY": "backup-test-key",
}
PRIMARY_ENV = {"KM_LLM_PRIMARY_PROVIDER": "sub2api", "KM_LLM_PRIMARY_MODEL": "gpt-test", "KM_LLM_PRIMARY_BASE_URL": "http://gateway.test/v1",
               "KM_LLM_PRIMARY_API_KEY_ENV": "TEST_PRIMARY_KEY", "TEST_PRIMARY_KEY": "primary-test-key"}


class Tier:
    """A stand-in client: answers with `name`, or raises."""

    def __init__(self, name, fail=None):
        self.name, self.fail, self.calls, self.model = name, fail, [], name + "-model"
        self.chat = self._Chat(self)

    class _Chat:
        def __init__(self, owner):
            self.owner = owner
            self.completions = types.SimpleNamespace(create=self.create)

        def __call__(self, messages, temperature=0.3):
            return self.create(messages=messages, temperature=temperature).choices[0].message.content

        def create(self, **kw):
            self.owner.calls.append(kw)
            if self.owner.fail:
                raise self.owner.fail
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=self.owner.name + " answer"))])


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def failover(primary, backup, clock=None, cooldown=30):
    return lf.FailoverClient(primary, backup, cooldown_seconds=cooldown, clock=clock or Clock())


MSG = [{"role": "user", "content": "hi"}]


def test_primary_answers_and_the_backup_is_not_touched():
    p, b = Tier("primary"), Tier("backup")
    client = failover(p, b)
    assert client.chat(MSG) == "primary answer" and client.generate("hi") == "primary answer"
    assert b.calls == [] and client.stats == {"primary_failures": 0, "backup_calls": 0, "backup_failures": 0}


@pytest.mark.parametrize("failure", [RuntimeError("OpenAI-compatible LLM request failed"), requests.Timeout(), ValueError("bad")])
def test_a_primary_failure_goes_to_the_backup(failure):
    p, b = Tier("primary", fail=failure), Tier("backup")
    client = failover(p, b)
    assert client.chat(MSG) == "backup answer" and client.stats["backup_calls"] == 1 and client.stats["primary_failures"] == 1


def test_the_primary_model_name_is_not_sent_to_the_backup():
    p, b = Tier("primary", fail=RuntimeError()), Tier("backup")
    failover(p, b).chat.completions.create(model="gpt-5.6-luna", messages=MSG, temperature=0.1)
    assert "model" in p.calls[0] and "model" not in b.calls[0]


def test_after_a_failure_the_primary_is_skipped_until_the_cooldown_ends():
    clock = Clock()
    p, b = Tier("primary", fail=RuntimeError()), Tier("backup")
    client = failover(p, b, clock, cooldown=30)
    client.chat(MSG)
    assert len(p.calls) == 1
    clock.now += 10
    client.chat(MSG)
    assert len(p.calls) == 1 and len(b.calls) == 2                      # straight to the backup
    clock.now += 25
    p.fail = None
    assert client.chat(MSG) == "primary answer" and len(p.calls) == 2    # primary tried again and recovered


def test_if_the_backup_fails_during_the_cooldown_the_primary_is_tried_once_more():
    clock = Clock()
    p, b = Tier("primary", fail=RuntimeError()), Tier("backup", fail=RuntimeError())
    client = failover(p, b, clock)
    with pytest.raises(RuntimeError, match="both failed"):
        client.chat(MSG)
    p.fail = None
    assert client.chat(MSG) == "primary answer"                          # in cooldown: backup failed, primary retried


def test_both_failing_raises_one_clear_error_that_the_ollama_fallback_can_catch():
    client = failover(Tier("p", fail=RuntimeError("a")), Tier("b", fail=RuntimeError("b")))
    with pytest.raises(RuntimeError, match="primary and backup LLM both failed"):
        client.chat(MSG)


def test_a_stream_that_broke_after_text_is_not_retried_on_the_backup():
    p, b = Tier("primary", fail=StreamInterrupted("broke")), Tier("backup")
    with pytest.raises(StreamInterrupted):
        failover(p, b).chat(MSG)
    assert b.calls == []


def test_unknown_attributes_come_from_the_primary():
    assert failover(Tier("primary"), Tier("backup")).model == "primary-model"


# ---------------------------------------------------------------- settings

def test_the_backup_is_off_unless_a_provider_is_set():
    assert lf.backup_settings({}) is None and lf.backup_settings({"KM_LLM_BACKUP_PROVIDER": "off"}) is None
    p = Tier("primary")
    assert lf.with_backup(p, env={}) is p and lf.with_backup(None, env=BACKUP_ENV) is None


def test_an_incomplete_backup_is_reported_not_silently_ignored(caplog):
    with caplog.at_level(logging.ERROR):
        assert lf.backup_settings({"KM_LLM_BACKUP_PROVIDER": "modaone", "KM_LLM_BACKUP_MODEL": "gpt-oss-120b"}) is None
    assert "KM_LLM_BACKUP_BASE_URL" in caplog.text


def test_a_missing_backup_key_runs_without_the_backup_and_logs(caplog, monkeypatch):
    monkeypatch.delenv("TEST_BACKUP_KEY", raising=False)
    env = {k: v for k, v in BACKUP_ENV.items() if k != "TEST_BACKUP_KEY"}
    p = Tier("primary")
    with caplog.at_level(logging.ERROR):
        assert lf.with_backup(p, env=env) is p
    assert "could not be created" in caplog.text and "backup-test-key" not in caplog.text


def test_settings_defaults_for_the_reasoning_backup():
    s = lf.backup_settings(BACKUP_ENV)
    assert s["max_tokens_floor"] == 2048 and s["reasoning_effort"] == "low" and s["cooldown"] == 30 and s["api_key_env"] == "TEST_BACKUP_KEY"


# ---------------------------------------------------------------- the client the backup uses

class Resp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}


def test_floor_and_extra_payload_reach_the_request(monkeypatch):
    monkeypatch.setenv("TEST_BACKUP_KEY", "backup-test-key")
    sent = []
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", lambda url, headers, json, timeout: sent.append((url, headers, json)) or Resp())
    c = OpenAICompatibleClient("gpt-oss-120b", "https://backup.test/api/v1", api_key_env="TEST_BACKUP_KEY", max_tokens_floor=2048, extra_payload={"reasoning_effort": "low"})
    c.chat([{"role": "user", "content": "x"}])
    c.chat.completions.create(messages=[{"role": "user", "content": "x"}], max_tokens=500)               # a small caller limit is raised to the floor
    c.chat.completions.create(messages=[{"role": "user", "content": "x"}], max_tokens=9000, reasoning_effort="high")   # larger limits and caller fields win
    assert [s[2]["max_tokens"] for s in sent] == [4096, 2048, 9000]
    assert [s[2]["reasoning_effort"] for s in sent] == ["low", "low", "high"]
    assert sent[0][0] == "https://backup.test/api/v1/chat/completions" and sent[0][1]["Authorization"] == "Bearer backup-test-key"


def test_a_plain_client_is_unchanged(monkeypatch):
    monkeypatch.setenv("TEST_PRIMARY_KEY", "k")
    sent = []
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", lambda url, headers, json, timeout: sent.append(json) or Resp())
    OpenAICompatibleClient("m", "http://x/v1", api_key_env="TEST_PRIMARY_KEY").chat([{"role": "user", "content": "x"}])
    assert sent[0]["max_tokens"] == 4096 and "reasoning_effort" not in sent[0]


# ---------------------------------------------------------------- the whole chain: primary -> backup -> Ollama

@pytest.fixture()
def chain(monkeypatch):
    ollama = []
    monkeypatch.setattr(oc.OllamaLoadBalancer, "chat", lambda self, messages, temperature=0.3: ollama.append("chat") or "ollama answer")
    monkeypatch.setattr(oc.OllamaLoadBalancer, "generate", lambda self, prompt, temperature=0.3: ollama.append("generate") or "ollama generated")
    monkeypatch.setattr(oc.OllamaClient, "_load_config", lambda self: {})
    for k, v in {**PRIMARY_ENV, **BACKUP_ENV}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("KM_LLM_FAILOVER_COOLDOWN_SECONDS", "0")
    return ollama


def _post(primary_status=200, backup_status=200, seen=None):
    def post(url, headers, json, timeout):
        backup = url.startswith("https://backup.test")
        if seen is not None:
            seen.append(("backup" if backup else "primary", json["model"]))
        r = Resp()
        r.status_code = backup_status if backup else primary_status
        if r.status_code >= 400:
            def boom():
                raise requests.HTTPError(response=r)
            r.raise_for_status = boom
        elif backup:
            r.json = lambda: {"choices": [{"message": {"content": "backup answer"}}]}
        else:
            r.json = lambda: {"choices": [{"message": {"content": "primary answer"}}]}
        return r
    return post


def test_chain_primary_ok_uses_neither_backup_nor_ollama(chain, monkeypatch):
    seen = []
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", _post(seen=seen))
    client = oc.OllamaClient(model="gemma4:12b")
    assert client.chat(MSG) == "primary answer" and client.generate("hi") == "primary answer"
    assert {s[0] for s in seen} == {"primary"} and chain == []


def test_chain_primary_quota_429_uses_the_backup_not_ollama(chain, monkeypatch):
    seen = []
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", _post(primary_status=429, seen=seen))
    client = oc.OllamaClient(model="gemma4:12b")
    assert client.chat(MSG) == "backup answer" and client.generate("hi") == "backup answer"
    assert ("backup", "gpt-oss-120b") in seen and chain == []


def test_chain_both_remote_tiers_down_still_falls_back_to_ollama(chain, monkeypatch, caplog):
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", _post(primary_status=429, backup_status=403))
    client = oc.OllamaClient(model="gemma4:12b")
    with caplog.at_level(logging.WARNING):
        assert client.chat(MSG) == "ollama answer" and client.generate("hi") == "ollama generated"
    assert chain == ["chat", "generate"] and "backup-test-key" not in caplog.text and "primary-test-key" not in caplog.text


def test_chain_without_backup_settings_is_the_old_behaviour(chain, monkeypatch):
    for k in BACKUP_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", _post(primary_status=429, seen=None))
    assert oc.OllamaClient(model="gemma4:12b").chat(MSG) == "ollama answer"


# ---------------------------------------------------------------- the CSIT worker's direct gateway call

def test_csit_worker_gateway_uses_the_backup_when_the_primary_fails(monkeypatch, tmp_path):
    import httpx
    from src.csit_integration_v1 import doclib_llm
    (tmp_path / "primary").write_text("primary-key\n")
    (tmp_path / "backup").write_text("backup-key\n")
    for k, v in {"KM_CSIT_LLM_BASE_URL": "http://gw.test/v1", "KM_CSIT_LLM_MODEL": "gpt-test", "KM_CSIT_LLM_API_KEY_FILE": str(tmp_path / "primary"),
                 "KM_CSIT_LLM_BACKUP_BASE_URL": "https://backup.test/api/v1", "KM_CSIT_LLM_BACKUP_MODEL": "gpt-oss-120b",
                 "KM_CSIT_LLM_BACKUP_API_KEY_FILE": str(tmp_path / "backup")}.items():
        monkeypatch.setenv(k, v)
    sent = []

    class R:
        def __init__(self, status, text):
            self.status_code, self.text = status, text

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("x", request=None, response=None)

        def json(self):
            return {"choices": [{"message": {"content": self.text}}]}

    def post(url, headers, timeout, json):
        sent.append((url, headers["Authorization"], json))
        return R(429, "") if url.startswith("http://gw.test") else R(200, "from backup")
    monkeypatch.setattr(httpx, "post", post)
    assert doclib_llm._gateway("prompt") == "from backup"
    assert [s[0] for s in sent] == ["http://gw.test/v1/chat/completions", "https://backup.test/api/v1/chat/completions"]
    assert sent[1][1] == "Bearer backup-key" and sent[1][2]["model"] == "gpt-oss-120b" and sent[1][2]["reasoning_effort"] == "low" and sent[1][2]["max_tokens"] >= 4096
    assert "max_tokens" not in sent[0][2]


def test_csit_worker_gateway_without_a_backup_still_raises(monkeypatch, tmp_path):
    import httpx
    from src.csit_integration_v1 import doclib_llm
    (tmp_path / "primary").write_text("k")
    for k, v in {"KM_CSIT_LLM_BASE_URL": "http://gw.test/v1", "KM_CSIT_LLM_MODEL": "m", "KM_CSIT_LLM_API_KEY_FILE": str(tmp_path / "primary")}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("KM_CSIT_LLM_BACKUP_BASE_URL", raising=False)

    class R:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("x", request=None, response=None)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    with pytest.raises(httpx.HTTPStatusError):
        doclib_llm._gateway("p")
