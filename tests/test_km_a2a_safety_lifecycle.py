import pytest

from km_a2a_bridge.safety_lifecycle import MockSafetyAdapter, SafetyLifecycle


def test_cancel_requires_cancel_safe_state_cleanup_order():
    adapter = MockSafetyAdapter()
    result = SafetyLifecycle(adapter).cancel("run-1", "operator_requested")
    assert result.outcome == "canceled"
    assert result.cancel_requested is True
    assert result.safe_state_confirmed is True
    assert result.cleanup_confirmed is True
    assert adapter.calls == [("cancel", "run-1"), ("safe_state", "run-1"), ("cleanup", "run-1")]


def test_cancel_still_attempts_safe_state_and_cleanup_when_cancel_fails():
    adapter = MockSafetyAdapter(fail_actions={"cancel"})
    result = SafetyLifecycle(adapter).cancel("run-1", "timeout")
    assert result.outcome == "canceled"
    assert result.cancel_requested is False
    assert result.safe_state_confirmed is True
    assert result.cleanup_confirmed is True
    assert result.errors == ("cancel:injected cancel failure",)
    assert adapter.calls == [("cancel", "run-1"), ("safe_state", "run-1"), ("cleanup", "run-1")]


@pytest.mark.parametrize("failed_action", ["safe_state", "cleanup"])
def test_failed_safety_action_blocks_success(failed_action):
    adapter = MockSafetyAdapter(fail_actions={failed_action})
    result = SafetyLifecycle(adapter).cancel("run-1", "timeout")
    assert result.outcome == "recovery_required"
    assert result.safe_state_confirmed is (failed_action != "safe_state")
    assert result.cleanup_confirmed is (failed_action != "cleanup")


def test_crash_recovery_skips_cancel_and_runs_safe_state_cleanup():
    adapter = MockSafetyAdapter()
    result = SafetyLifecycle(adapter).recover_after_crash("run-1")
    assert result.outcome == "recovered"
    assert result.cancel_requested is False
    assert adapter.calls == [("safe_state", "run-1"), ("cleanup", "run-1")]


def test_lifecycle_is_idempotent_for_repeated_run_id():
    adapter = MockSafetyAdapter()
    lifecycle = SafetyLifecycle(adapter)
    first = lifecycle.cancel("run-1", "operator_requested")
    second = lifecycle.cancel("run-1", "retry")
    assert second == first
    assert len(adapter.calls) == 3
