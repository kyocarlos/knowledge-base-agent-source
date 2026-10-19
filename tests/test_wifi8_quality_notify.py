import copy
import importlib.util
import urllib.error
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("wifi8_quality_notify", Path(__file__).resolve().parent.parent / "scripts" / "wifi8_quality_notify.py")
notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify)

TOKEN = "123456:SECRET-TOKEN-VALUE"
REPORT = {"status": "WARN", "created_utc": "2026-10-18T03:30:00+00:00", "commit": "abc1234",
          "zones": {"da40": {"_status": "WARN",
                             "retrieval": {"status": "PASS", "checks": [{"metric": "retrieval.hit_at_10", "value": 0.93, "status": "PASS"}]},
                             "agent": {"status": "WARN", "checks": [{"metric": "agent.answer_pass", "value": 0.88, "previous": 0.97,
                                                                     "status": "WARN", "reason": "超過警示門檻"}],
                                       "failed_cases": ["M01"]}}}}


def write_env(tmp_path, text, mode=0o600):
    path = tmp_path / "notify.env"
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def test_settings_require_private_file(tmp_path):
    path = write_env(tmp_path, f"KM_NOTIFY_CHANNEL=telegram\nTELEGRAM_BOT_TOKEN='{TOKEN}'\n# comment\n")
    assert notify.load_settings(path) == {"KM_NOTIFY_CHANNEL": "telegram", "TELEGRAM_BOT_TOKEN": TOKEN}
    with pytest.raises(PermissionError):
        notify.load_settings(write_env(tmp_path, "X=1", mode=0o644))
    with pytest.raises(FileNotFoundError):
        notify.load_settings(tmp_path / "missing.env")


def test_message_lists_only_failing_levels_and_metrics():
    text = notify.build_message(REPORT, "/reports/r/report.md")
    assert text.startswith("[KM WiFi 品質驗證] WARN") and "DA40 ②Agent：WARN" in text
    assert "agent.answer_pass=0.88（上次 0.97）超過警示門檻" in text and "retrieval" not in text and "報告：/reports/r/report.md" in text


def test_send_telegram_and_line(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "_post", lambda url, payload, headers=None: calls.append((url, payload, headers)))
    settings = {"KM_NOTIFY_CHANNEL": "telegram, line", "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "-100",
                "LINE_CHANNEL_ACCESS_TOKEN": "line-token", "LINE_TO": "Cxyz"}
    assert notify.send("hi", settings) == ["telegram", "line"]
    (t_url, t_payload, _), (l_url, l_payload, l_headers) = calls
    assert t_url.endswith(f"/bot{TOKEN}/sendMessage") and t_payload == {"chat_id": "-100", "text": "hi", "disable_web_page_preview": True}
    assert l_url == "https://api.line.me/v2/bot/message/push" and l_payload == {"to": "Cxyz", "messages": [{"type": "text", "text": "hi"}]}
    assert l_headers == {"Authorization": "Bearer line-token"}


def test_errors_never_contain_tokens(monkeypatch):
    def fail(url, payload, headers=None):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", None, None)
    monkeypatch.setattr(notify, "_post", fail)
    with pytest.raises(RuntimeError) as err:
        notify.send("hi", {"KM_NOTIFY_CHANNEL": "telegram", "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "1"})
    assert "HTTP 401" in str(err.value) and TOKEN not in str(err.value)

    def boom(url, payload, headers=None):
        raise OSError(f"cannot reach {url}")
    monkeypatch.setattr(notify, "_post", boom)
    with pytest.raises(RuntimeError) as err:
        notify.send("hi", {"KM_NOTIFY_CHANNEL": "telegram", "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "1"})
    assert TOKEN not in str(err.value) and "OSError" in str(err.value)
    with pytest.raises(RuntimeError, match="缺少 LINE_TO"):
        notify.send("hi", {"KM_NOTIFY_CHANNEL": "line", "LINE_CHANNEL_ACCESS_TOKEN": "x"})
    with pytest.raises(RuntimeError, match="未設定"):
        notify.send("hi", {})


def test_notify_report_respects_levels_and_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(notify, "load_settings", lambda: {"KM_NOTIFY_CHANNEL": "telegram", "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "1"})
    sent = []
    monkeypatch.setattr(notify, "_post", lambda url, payload, headers=None: sent.append(payload["text"]))
    assert notify.notify_report({**REPORT, "status": "PASS"}, "r", ["WARN", "FAIL"]) == "未達通知條件" and not sent
    assert notify.notify_report(REPORT, "r", ["WARN", "FAIL"]) == "已通知：telegram" and "②Agent" in sent[0]
    monkeypatch.setattr(notify, "load_settings", lambda: (_ for _ in ()).throw(FileNotFoundError("通知設定檔不存在")))
    assert notify.notify_report(REPORT, "r", ["WARN"]).startswith("通知失敗：通知設定檔不存在")


def test_message_names_the_data_change_and_the_failed_questions_by_kind():
    report = {**copy.deepcopy(REPORT), "changes": ["TEST：wifi8-a → wifi8-b"], "failure_class_names": {"answer": "回答內容不符", "infra": "LLM／連線逾時（非資料問題）"}}
    report["zones"]["da40"]["agent"].update(failure_classes={"answer": ["D09", "T01"], "infra": ["L01"]}, retried=["L01"], retry_failed=True)
    text = notify.build_message(report, "/r/report.md")
    assert "資料更新：TEST：wifi8-a → wifi8-b" in text
    assert "回答內容不符：D09、T01" in text and "LLM／連線逾時（非資料問題）：L01" in text and "已自動重試（LLM 逾時）：L01，重試仍失敗" in text
    assert "檢索" not in text  # a passing level is left out unless the message is requested for every level


def test_a_data_change_is_reported_even_when_everything_passes(monkeypatch):
    report = {**copy.deepcopy(REPORT), "status": "PASS", "changes": ["DA40：wifi8-a → wifi8-b"]}
    for zone in report["zones"].values():
        zone["agent"]["status"] = "PASS"
    assert notify.notify_report(report, "/r", ["WARN", "FAIL"]) == "未達通知條件"
    sent = []
    monkeypatch.setattr(notify, "load_settings", lambda: {"KM_NOTIFY_CHANNEL": "telegram"})
    monkeypatch.setattr(notify, "send", lambda text, settings: sent.append(text) or ["telegram"])
    assert notify.notify_report(report, "/r", ["WARN", "FAIL"], always=True) == "已通知：telegram"
    assert "資料更新：DA40" in sent[0] and "DA40 ①檢索：PASS" in sent[0]
