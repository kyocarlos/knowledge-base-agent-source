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


class StreamResponse:
    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        return iter(self.lines)


def _sse(*chunks):
    return [("data: " + json.dumps(c, ensure_ascii=False)).encode() for c in chunks] + [b"", b"data: [DONE]"]


def _client(monkeypatch, post):
    from src.web_api.openai_compatible_client import OpenAICompatibleClient
    monkeypatch.setenv("SUB2API_API_KEY", "test-only-key")
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", post)
    return OpenAICompatibleClient(model="m", base_url="http://gateway.test/v1")


def test_streaming_delivers_text_pieces_and_returns_the_whole_message(monkeypatch):
    seen = {}

    def post(url, headers, json, timeout, stream=False):
        seen["payload"] = json
        return StreamResponse(_sse({"id": "r1", "choices": [{"delta": {"role": "assistant"}}]}, {"choices": [{"delta": {"content": "你"}}]},
                                  {"choices": [{"delta": {"content": "好"}, "finish_reason": "stop"}]}))
    pieces = []
    out = _client(monkeypatch, post).chat.completions.create(messages=[{"role": "user", "content": "hi"}], on_delta=pieces.append)
    assert pieces == ["你", "好"] and out.choices[0].message.content == "你好" and out.choices[0].message.tool_calls == []
    assert seen["payload"]["stream"] is True and out.choices[0].finish_reason == "stop"


def test_streaming_assembles_tool_calls_from_deltas(monkeypatch):
    def post(url, headers, json, timeout, stream=False):
        return StreamResponse(_sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "type": "function", "function": {"name": "search_wifi", "arguments": ""}}]}}]},
                                   {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"query\":"}}]}}]},
                                   {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\"ELR\"}"}}]}, "finish_reason": "tool_calls"}]}))
    pieces = []
    out = _client(monkeypatch, post).chat.completions.create(messages=[], on_delta=pieces.append)
    call = out.choices[0].message.tool_calls[0]
    assert pieces == [] and call["id"] == "c1" and call["function"] == {"name": "search_wifi", "arguments": "{\"query\":\"ELR\"}"}


def test_a_stream_that_fails_before_any_text_falls_back_to_one_normal_request(monkeypatch):
    import requests
    calls = []

    def post(url, headers, json, timeout, stream=False):
        calls.append(stream)
        if stream:
            raise requests.ConnectionError("no stream")
        return FakeResponse()
    pieces = []
    out = _client(monkeypatch, post).chat.completions.create(messages=[], on_delta=pieces.append)
    assert calls == [True, False] and out.choices[0].message.content == "test answer" and pieces == []


def test_a_stream_that_breaks_after_text_is_an_error_not_a_silent_retry(monkeypatch):
    def post(url, headers, json, timeout, stream=False):
        return StreamResponse(_sse({"choices": [{"delta": {"content": "半"}}]})[:1] + [b"data: {not json"])
    with pytest.raises(RuntimeError, match="interrupted"):
        _client(monkeypatch, post).chat.completions.create(messages=[], on_delta=lambda _: None)
