import json

import pytest

from src.web_api.llm_factory import create_llm_client


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "id": "chatcmpl-test",
            "model": "test-model",
            "choices": [{"message": {"content": "test answer"}}],
        }


def test_openai_compatible_factory_uses_env_key_and_chat_facade(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return FakeResponse()

    monkeypatch.setenv("SUB2API_API_KEY", "test-only-key")
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", fake_post)

    client = create_llm_client({
        "llm_provider": "sub2api",
        "llm_model": "test-model",
        "openai": {
            "base_url": "http://gateway.test/v1",
            "api_key_env": "SUB2API_API_KEY",
            "timeout": 12,
            "max_tokens": 123,
        },
    })

    assert client.chat([{"role": "user", "content": "hello"}]) == "test answer"
    response = client.chat.completions.create(
        model="override-model",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert response.choices[0].message.content == "test answer"
    assert calls[0][0] == "http://gateway.test/v1/chat/completions"
    assert calls[0][1]["Authorization"] == "Bearer test-only-key"
    assert calls[0][2]["model"] == "test-model"
    assert calls[0][2]["max_tokens"] == 123
    assert calls[1][2]["model"] == "override-model"


def test_openai_compatible_client_requires_credential(monkeypatch):
    monkeypatch.delenv("SUB2API_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SUB2API_API_KEY"):
        create_llm_client({
            "llm_provider": "openai_compatible",
            "llm_model": "test-model",
            "openai": {"base_url": "http://gateway.test/v1"},
        })


def test_openai_compatible_response_errors_do_not_include_body(monkeypatch):
    class ErrorResponse:
        status_code = 401
        text = json.dumps({"secret": "must-not-be-logged"})

        def raise_for_status(self):
            import requests
            raise requests.HTTPError(response=self)

    monkeypatch.setenv("SUB2API_API_KEY", "test-only-key")
    monkeypatch.setattr(
        "src.web_api.openai_compatible_client.requests.post",
        lambda url, **kwargs: ErrorResponse(),
    )
    client = create_llm_client({
        "llm_provider": "openai_compatible",
        "llm_model": "test-model",
        "openai": {"base_url": "http://gateway.test/v1"},
    })

    with pytest.raises(RuntimeError, match="request failed"):
        client.generate("hello")
