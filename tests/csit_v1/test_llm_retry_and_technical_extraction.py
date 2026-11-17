"""CSIT device AI aggregate analysis, part 1+2: real single-document technical extraction grounded in the text, and LLM error handling
that never turns a 429/5xx/timeout/invalid-JSON failure into a silently-empty "complete" result (CSIT requirement doc 2026-11-17)."""
import json
import httpx
import pytest
from src.csit_integration_v1 import doclib_llm
from src.csit_integration_v1.doclib_llm import LlmCallError
from src.csit_integration_v1.doclib_metadata import clean_semantic, llm_prompt, make_semantic_extractor, parse_llm_json
from src.csit_integration_v1.errors import IntegrationError
from src.csit_integration_v1.pipeline import Extraction
from src.csit_integration_v1.v2_pipeline import build_result_v2


def _request(prefix, env, monkeypatch):
    monkeypatch.setenv(prefix + "_API_KEY_FILE", str(env["key_file"]))
    monkeypatch.setenv(prefix + "_MODEL", "test-model")
    monkeypatch.setenv(prefix + "_BASE_URL", "https://llm.test/v1")
    monkeypatch.setenv(prefix + "_TIMEOUT", "5")


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(doclib_llm.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(doclib_llm, "MAX_ATTEMPTS", 3)


@pytest.fixture
def key_file(tmp_path):
    f = tmp_path / "key"
    f.write_text("test-key", encoding="utf-8")
    return f


_DUMMY_REQUEST = httpx.Request("POST", "https://llm.test/v1/chat/completions")


def _response(status, **kw):
    return httpx.Response(status, request=_DUMMY_REQUEST, **kw)


def _ok_response(content):
    return _response(200, json={"choices": [{"message": {"content": content}}]})


def _responder(*responses):
    calls = []

    def handler(request):
        calls.append(request)
        resp = responses[len(calls) - 1]
        if isinstance(resp, Exception):
            raise resp
        return resp
    handler.calls = calls
    return handler


# ---------------------------------------------------------------- doclib_llm: retry, backoff, classification

def test_a_429_is_retried_and_then_succeeds(monkeypatch, key_file):
    _request("KM_CSIT_LLM", {"key_file": key_file}, monkeypatch)
    handler = _responder(_response(429, json={"error": "quota"}), _ok_response("second try"))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: handler(kw))
    assert doclib_llm._chat("KM_CSIT_LLM", "hi") == "second try"
    assert len(handler.calls) == 2


def test_a_retry_after_header_is_honoured(monkeypatch, key_file):
    _request("KM_CSIT_LLM", {"key_file": key_file}, monkeypatch)
    slept = []
    monkeypatch.setattr(doclib_llm.time, "sleep", lambda seconds: slept.append(seconds))
    handler = _responder(_response(429, headers={"Retry-After": "7"}, json={"error": "quota"}), _ok_response("ok"))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: handler(kw))
    doclib_llm._chat("KM_CSIT_LLM", "hi")
    assert slept == [7.0]


def test_5xx_and_timeout_are_retryable(monkeypatch, key_file):
    _request("KM_CSIT_LLM", {"key_file": key_file}, monkeypatch)
    handler = _responder(_response(503, json={"error": "down"}), httpx.ReadTimeout("slow"), _ok_response("ok"))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: handler(kw))
    assert doclib_llm._chat("KM_CSIT_LLM", "hi") == "ok"
    assert len(handler.calls) == 3


def test_a_400_is_never_retried(monkeypatch, key_file):
    _request("KM_CSIT_LLM", {"key_file": key_file}, monkeypatch)
    handler = _responder(_response(400, json={"error": "bad request"}))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: handler(kw))
    with pytest.raises(LlmCallError) as exc:
        doclib_llm._chat("KM_CSIT_LLM", "hi")
    assert exc.value.retryable is False and exc.value.code == "HTTP_400"
    assert len(handler.calls) == 1  # no retry budget spent on a request that will never succeed unchanged


def test_persistent_429_exhausts_the_retry_budget_and_raises_retryable(monkeypatch, key_file):
    _request("KM_CSIT_LLM", {"key_file": key_file}, monkeypatch)
    handler = _responder(*([_response(429, json={"error": "quota"})] * 5))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: handler(kw))
    with pytest.raises(LlmCallError) as exc:
        doclib_llm._chat("KM_CSIT_LLM", "hi")
    assert exc.value.retryable is True and exc.value.code == "HTTP_429"
    assert len(handler.calls) == doclib_llm.MAX_ATTEMPTS


def test_an_invalid_http_body_is_retried_as_llm_invalid_response(monkeypatch, key_file):
    _request("KM_CSIT_LLM", {"key_file": key_file}, monkeypatch)
    handler = _responder(_response(200, json={"unexpected": "shape"}), _ok_response("ok"))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: handler(kw))
    assert doclib_llm._chat("KM_CSIT_LLM", "hi") == "ok"
    assert len(handler.calls) == 2


def test_the_backup_is_used_once_the_primary_exhausts_its_retries(monkeypatch, key_file, tmp_path):
    _request("KM_CSIT_LLM", {"key_file": key_file}, monkeypatch)
    backup_key = tmp_path / "backup-key"
    backup_key.write_text("backup-key", encoding="utf-8")
    _request("KM_CSIT_LLM_BACKUP", {"key_file": backup_key}, monkeypatch)
    primary_calls, backup_calls = [], []

    def post(url, **kw):
        if "llm.test" in url and kw["headers"]["Authorization"] == "Bearer test-key":
            primary_calls.append(kw)
            return _response(429, json={"error": "quota"})
        backup_calls.append(kw)
        return _ok_response("from backup")
    monkeypatch.setattr(httpx, "post", post)
    assert doclib_llm._gateway("hi") == "from backup"
    assert len(primary_calls) == doclib_llm.MAX_ATTEMPTS and len(backup_calls) == 1


def test_an_outright_connection_failure_is_retryable(monkeypatch, key_file):
    _request("KM_CSIT_LLM", {"key_file": key_file}, monkeypatch)
    handler = _responder(httpx.ConnectError("refused"), _ok_response("ok"))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: handler(kw))
    assert doclib_llm._chat("KM_CSIT_LLM", "hi") == "ok"


# ---------------------------------------------------------------- doclib_metadata: grounded technical extraction

TEXT = ("本文件描述 Askey FSW26 Wi-Fi 7 存取點。型號 FSW26-A1，廠牌 Askey。支援技術標準 IEEE 802.11be，軟體版本 v2.3.1。"
        "可執行測試項目：Throughput Test 與 Roaming Test。頻率 5 GHz，發射功率限制 23 dBm。"
        "已知限制：高溫環境下吞吐量下降。這台設備可以進行 Wi-Fi 7 的輸出功率與漫遊測試。")


def test_clean_semantic_keeps_only_technical_facts_that_occur_in_the_text():
    raw = {
        "productNames": ["FSW26"], "modelNumbers": ["FSW26-A1", "INVENTED-999"],
        "vendorNames": ["Askey", "NotInDocument"], "standards": ["IEEE 802.11be"],
        "softwareVersions": ["v2.3.1"], "testItems": ["Throughput Test", "Roaming Test", "Made Up Test"],
        "measurements": [{"metric": "發射功率限制", "value": "23", "unit": "dBm", "context": "頻率 5 GHz"},
                          {"metric": "Invented Metric", "value": "999"}],
        "specifications": [{"field": "頻率", "value": "5 GHz"}, {"field": "Invented Field", "value": "999"}],
        "capabilitySummary": "可進行輸出功率與漫遊測試", "limitations": ["高溫環境下吞吐量下降"],
    }
    sem = clean_semantic(raw, TEXT)
    assert sem["modelNumbers"] == ["FSW26-A1"]  # the invented model number is dropped
    assert sem["vendorNames"] == ["Askey"]
    assert sem["testItems"] == ["Throughput Test", "Roaming Test"]
    assert sem["measurements"] == [{"metric": "發射功率限制", "value": "23", "unit": "dBm", "context": "頻率 5 GHz"}]
    assert sem["specifications"] == [{"field": "頻率", "value": "5 GHz"}]  # the invented field is dropped
    assert sem["capabilitySummary"] == "可進行輸出功率與漫遊測試"
    assert sem["limitations"] == ["高溫環境下吞吐量下降"]


def test_a_measurement_whose_value_is_not_in_the_text_is_dropped():
    sem = clean_semantic({"measurements": [{"metric": "發射功率限制", "value": "999"}]}, TEXT)
    assert sem["measurements"] == []


def test_llm_prompt_asks_for_every_technical_field_and_the_retry_note_only_on_retry():
    first = llm_prompt("x")
    retried = llm_prompt("x", retry=True)
    for key in ("productNames", "modelNumbers", "vendorNames", "measurements", "specifications", "capabilitySummary", "limitations"):
        assert key in first
    assert "不是合法 JSON" not in first and "不是合法 JSON" in retried


def test_extractor_retries_on_invalid_json_with_a_corrective_prompt_then_succeeds():
    replies = iter(["not json at all", json.dumps({"documentType": "Manual"})])
    seen_prompts = []

    def complete(prompt):
        seen_prompts.append(prompt)
        return next(replies)
    extract = make_semantic_extractor(complete)
    assert extract("some text") == {"documentType": "Manual"}
    assert len(seen_prompts) == 2 and "合法 JSON" in seen_prompts[1]


def test_extractor_degrades_to_the_parse_failed_marker_after_exhausting_retries():
    extract = make_semantic_extractor(lambda prompt: "still not json")
    result = extract("some text")
    assert result == {"_extraction_parse_failed": True}
    # fed back through clean_semantic this behaves exactly like an empty {}, never an invented fact
    assert clean_semantic(result, "some text")["modelNumbers"] == []


def test_extractor_propagates_a_retryable_llm_failure_as_integration_error_not_none():
    def complete(prompt):
        raise LlmCallError("HTTP_429", "quota exhausted", True)
    extract = make_semantic_extractor(complete)
    with pytest.raises(IntegrationError) as exc:
        extract("some text")
    assert exc.value.retryable is True and exc.value.code == "HTTP_429"


def test_extractor_propagates_a_non_retryable_llm_failure_as_such():
    def complete(prompt):
        raise LlmCallError("HTTP_401", "bad credentials", False)
    extract = make_semantic_extractor(complete)
    with pytest.raises(IntegrationError) as exc:
        extract("some text")
    assert exc.value.retryable is False and exc.value.code == "HTTP_401"


# ---------------------------------------------------------------- v2_pipeline: the Completed.result actually carries the extraction

def test_build_result_v2_carries_the_grounded_technical_fields_and_equipment_specifics():
    from datetime import datetime, timezone
    import pathlib
    job = {"source_type": "EquipmentAttachment"}
    semantic = {"modelNumbers": ["FSW26-A1"], "vendorNames": ["Askey"], "testItems": ["Throughput Test"],
                "specifications": [{"field": "頻率", "value": "5 GHz"}], "capabilitySummary": "可進行輸出功率測試",
                "limitations": ["高溫環境下吞吐量下降"]}
    r = build_result_v2(job, Extraction(text=TEXT), ".txt", pathlib.Path("a.txt"), semantic, "i", 1, datetime.now(timezone.utc))
    assert r["technical"]["modelNumbers"] == ["FSW26-A1"]
    assert r["technical"]["vendorNames"] == ["Askey"]
    assert r["technical"]["testItems"] == ["Throughput Test"]
    assert r["sourceSpecific"] == {"specifications": [{"field": "頻率", "value": "5 GHz"}], "capabilitySummary": "可進行輸出功率測試",
                                    "limitations": ["高溫環境下吞吐量下降"]}
    assert r["warnings"] == []  # a real, successful extraction needs no warning


def test_build_result_v2_warns_specifically_when_the_model_never_produced_parseable_json():
    from datetime import datetime, timezone
    import pathlib
    job = {"source_type": "VendorFile"}
    r = build_result_v2(job, Extraction(text=TEXT), ".txt", pathlib.Path("a.txt"),
                         {"_extraction_parse_failed": True}, "i", 1, datetime.now(timezone.utc))
    assert any("could not be parsed" in w for w in r["warnings"])
    assert r["technical"]["modelNumbers"] == []
