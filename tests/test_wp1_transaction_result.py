import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/wp1_transaction_result.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("transaction_result", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_clean_complete_runner_passes():
    assert MODULE.determine_result(0, evidence_complete=True) == "PASS"


def test_nonzero_runner_exit_fails_closed():
    assert MODULE.determine_result(1, evidence_complete=True) == "FAIL_CLOSED"


def test_exception_fails_closed_even_with_zero_exit():
    assert MODULE.determine_result(0, evidence_complete=True, exception_type="RuntimeError") == "FAIL_CLOSED"


def test_signal_fails_closed_even_with_zero_exit():
    assert MODULE.determine_result(0, evidence_complete=True, signal_number=15) == "FAIL_CLOSED"


def test_partial_evidence_fails_closed():
    assert MODULE.determine_result(0, evidence_complete=False) == "FAIL_CLOSED"


def test_cleanup_or_rollback_cannot_override_acceptance_failure():
    assert MODULE.determine_result(1, evidence_complete=True) == "FAIL_CLOSED"


def test_wrapper_writes_authoritative_failure(tmp_path, monkeypatch):
    wrapper_path = Path(__file__).parents[1] / "scripts/wp1_transaction_wrapper.py"
    wrapper_spec = importlib.util.spec_from_file_location("transaction_wrapper", wrapper_path)
    wrapper = importlib.util.module_from_spec(wrapper_spec)
    assert wrapper_spec.loader is not None
    wrapper_spec.loader.exec_module(wrapper)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs: type("Done", (), {"returncode": 1})())
    evidence = tmp_path / "transaction.json"
    assert wrapper.run_transaction(["ignored"], evidence) == 1
    assert json.loads(evidence.read_text()) == {"runner_exit": 1, "transaction_result": "FAIL_CLOSED"}
