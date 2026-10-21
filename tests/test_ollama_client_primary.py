"""OllamaClient：主要 LLM（OpenAI 相容）優先、Ollama 備援。"""
from __future__ import annotations

import logging

import pytest
import requests

from src.web_api import ollama_client as oc

PRIMARY_ENV = {
    "KM_LLM_PRIMARY_PROVIDER": "sub2api",
    "KM_LLM_PRIMARY_MODEL": "gpt-test",
    "KM_LLM_PRIMARY_BASE_URL": "http://gateway.test/v1",
    "KM_LLM_PRIMARY_API_KEY_ENV": "TEST_PRIMARY_KEY",
    "TEST_PRIMARY_KEY": "test-only-key",
}


class FakeResponse:
    def __init__(self, status=200, content="primary answer"):
        self.status_code = status
        self._content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


@pytest.fixture()
def ollama_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(oc.OllamaLoadBalancer, "chat", lambda self, messages, temperature=0.3: calls.append(("chat", messages)) or "ollama answer")
    monkeypatch.setattr(oc.OllamaLoadBalancer, "generate", lambda self, prompt, temperature=0.3: calls.append(("generate", prompt)) or "ollama generated")
    monkeypatch.setattr(oc.OllamaClient, "_load_config", lambda self: {})
    for key in list(PRIMARY_ENV):
        monkeypatch.delenv(key, raising=False)
    return calls


def _with_primary(monkeypatch, post):
    for key, value in PRIMARY_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", post)


def test_default_is_unchanged_ollama_only(ollama_calls, monkeypatch):
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", lambda *a, **k: pytest.fail("must not call primary"))
    client = oc.OllamaClient(model="gemma4:12b")
    assert client.chat([{"role": "user", "content": "hi"}]) == "ollama answer"
    assert client.generate("hi") == "ollama generated"
    assert [c[0] for c in ollama_calls] == ["chat", "generate"]


def test_primary_serves_chat_generate_and_sdk_style(ollama_calls, monkeypatch):
    sent = []
    _with_primary(monkeypatch, lambda url, headers, json, timeout: sent.append((url, json["model"], headers["Authorization"])) or FakeResponse())
    client = oc.OllamaClient(model="gemma4:12b")
    assert client.chat([{"role": "user", "content": "hi"}]) == "primary answer"
    assert client.generate("hi") == "primary answer"
    assert client.chat.completions.create(messages=[{"role": "user", "content": "hi"}]).choices[0].message.content == "primary answer"
    assert ollama_calls == []
    assert {s[0] for s in sent} == {"http://gateway.test/v1/chat/completions"}
    assert {s[1] for s in sent} == {"gpt-test"} and {s[2] for s in sent} == {"Bearer test-only-key"}


@pytest.mark.parametrize("failure", ["http_401", "timeout", "bad_schema"])
def test_primary_failure_falls_back_to_ollama(ollama_calls, monkeypatch, caplog, failure):
    def post(url, headers, json, timeout):
        if failure == "http_401":
            return FakeResponse(status=401)
        if failure == "timeout":
            raise requests.Timeout()
        bad = FakeResponse()
        bad.json = lambda: {"unexpected": True}
        return bad
    _with_primary(monkeypatch, post)
    client = oc.OllamaClient(model="gemma4:12b")
    with caplog.at_level(logging.WARNING):
        assert client.chat([{"role": "user", "content": "hi"}]) == "ollama answer"
        assert client.generate("hi") == "ollama generated"
    assert [c[0] for c in ollama_calls] == ["chat", "generate"]
    assert "改用 Ollama 備援" in caplog.text and "test-only-key" not in caplog.text


def test_image_messages_go_straight_to_ollama(ollama_calls, monkeypatch):
    _with_primary(monkeypatch, lambda *a, **k: pytest.fail("image requests must not reach primary"))
    client = oc.OllamaClient(model="gemma4:12b")
    assert client.chat([{"role": "user", "content": "describe", "images": ["b64"]}]) == "ollama answer"


def test_missing_key_keeps_ollama_and_logs_error(ollama_calls, monkeypatch, caplog):
    _with_primary(monkeypatch, lambda *a, **k: pytest.fail("must not call primary"))
    monkeypatch.delenv("TEST_PRIMARY_KEY")
    with caplog.at_level(logging.ERROR):
        client = oc.OllamaClient(model="gemma4:12b")
    assert client.chat([{"role": "user", "content": "hi"}]) == "ollama answer"
    assert "建立失敗" in caplog.text


def test_env_overrides_config_section(ollama_calls, monkeypatch):
    sent = []
    monkeypatch.setattr(oc.OllamaClient, "_load_config", lambda self: {"llm_primary": {"provider": "sub2api", "model": "from-config", "base_url": "http://config.test/v1", "api_key_env": "TEST_PRIMARY_KEY"}})
    monkeypatch.setenv("TEST_PRIMARY_KEY", "test-only-key")
    monkeypatch.setenv("KM_LLM_PRIMARY_MODEL", "from-env")
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", lambda url, headers, json, timeout: sent.append((url, json["model"])) or FakeResponse())
    oc.OllamaClient(model="gemma4:12b").generate("hi")
    assert sent == [("http://config.test/v1/chat/completions", "from-env")]


def test_unknown_provider_is_reported_and_ignored(ollama_calls, monkeypatch, caplog):
    monkeypatch.setenv("KM_LLM_PRIMARY_PROVIDER", "mystery")
    with caplog.at_level(logging.ERROR):
        client = oc.OllamaClient(model="gemma4:12b")
    assert client.generate("hi") == "ollama generated" and "未知的主要 LLM provider" in caplog.text
