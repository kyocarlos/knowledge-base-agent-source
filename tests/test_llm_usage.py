"""The LLM usage ledger: KM's own running total for a metered external account (no official balance API exists for ModaOne)."""
import json

from src.web_api import llm_usage as lu


def env(tmp_path):
    return {"KM_LLM_USAGE_FILE": str(tmp_path / "usage.json")}


def test_no_file_means_zero_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("KM_LLM_USAGE_FILE", str(tmp_path / "missing.json"))
    out = lu.summary("modaone")
    assert out == {"tokensUsed": 0, "pointsUsed": 0.0, "callsRecorded": 0, "official": False}


def test_recording_accumulates_tokens_and_points(tmp_path, monkeypatch):
    monkeypatch.setenv("KM_LLM_USAGE_FILE", str(tmp_path / "usage.json"))
    lu.record("modaone", 60000, 40000)
    lu.record("modaone", 10000, 0)
    out = lu.summary("modaone")
    assert out["tokensUsed"] == 110000 and out["pointsUsed"] == 1.1 and out["callsRecorded"] == 2 and out["official"] is False


def test_zero_token_calls_are_not_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("KM_LLM_USAGE_FILE", str(tmp_path / "usage.json"))
    lu.record("modaone", 0, 0)
    lu.record("", 1000, 1000)
    assert lu.summary("modaone")["callsRecorded"] == 0


def test_granted_points_adds_remaining(tmp_path, monkeypatch):
    monkeypatch.setenv("KM_LLM_USAGE_FILE", str(tmp_path / "usage.json"))
    lu.record("modaone", 50000, 50000)   # 1 point
    out = lu.summary("modaone", granted_points=1000)
    assert out["grantedPoints"] == 1000 and out["pointsRemaining"] == 999.0
    assert "pointsRemaining" not in lu.summary("modaone")   # unknown total: no remaining figure is invented


def test_remaining_never_goes_negative(tmp_path, monkeypatch):
    monkeypatch.setenv("KM_LLM_USAGE_FILE", str(tmp_path / "usage.json"))
    lu.record("modaone", 200_000_000, 0)   # far more than any plausible grant
    assert lu.summary("modaone", granted_points=1000)["pointsRemaining"] == 0.0


def test_accounts_do_not_mix(tmp_path, monkeypatch):
    monkeypatch.setenv("KM_LLM_USAGE_FILE", str(tmp_path / "usage.json"))
    lu.record("modaone", 50000, 50000)
    lu.record("other-provider", 10000, 10000)
    assert lu.summary("modaone")["tokensUsed"] == 100000 and lu.summary("other-provider")["tokensUsed"] == 20000


def test_the_ledger_is_a_shared_file_surviving_a_fresh_process(tmp_path, monkeypatch):
    monkeypatch.setenv("KM_LLM_USAGE_FILE", str(tmp_path / "usage.json"))
    lu.record("modaone", 50000, 0)
    data = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert data["modaone"]["prompt_tokens"] == 50000 and data["modaone"]["calls"] == 1
    # a second "process" reading the same file sees the same total
    assert lu.summary("modaone")["pointsUsed"] == 0.5


def test_an_unwritable_ledger_file_does_not_raise(tmp_path, monkeypatch):
    bad_dir = tmp_path / "not-a-dir"
    bad_dir.write_text("x")   # a file where record() expects to mkdir a parent directory
    monkeypatch.setenv("KM_LLM_USAGE_FILE", str(bad_dir / "usage.json"))
    lu.record("modaone", 1000, 1000)   # must not raise
    assert lu.summary("modaone")["callsRecorded"] == 0


def test_a_corrupt_ledger_file_is_treated_as_empty_not_fatal(tmp_path, monkeypatch, caplog):
    f = tmp_path / "usage.json"
    f.write_text("not json")
    monkeypatch.setenv("KM_LLM_USAGE_FILE", str(f))
    with caplog.at_level("WARNING"):
        assert lu.summary("modaone")["tokensUsed"] == 0
    lu.record("modaone", 1000, 0)
    assert lu.summary("modaone")["tokensUsed"] == 1000


def test_reset_removes_only_that_account(tmp_path, monkeypatch):
    monkeypatch.setenv("KM_LLM_USAGE_FILE", str(tmp_path / "usage.json"))
    lu.record("modaone", 50000, 0)
    lu.record("other", 50000, 0)
    lu.reset("modaone")
    assert lu.summary("modaone")["callsRecorded"] == 0 and lu.summary("other")["callsRecorded"] == 1
