import pytest
from pydantic import ValidationError

from km_a2a_bridge.anritsu_shadow_adapter import (
    MockAnritsuOpenClawAdapter,
    ShadowAdapterRequest,
)


def request(**changes):
    values = {
        "job_type": "run_iperf_test",
        "environment": "anritsu",
        "profile_id": "ncq2200b2v-throughput-v1",
        "run_id": "shadow-run-1",
        "requested_by": "operator-1",
        "duration_seconds": 1,
        "test_cases": ["sa_dl_tcp"],
        "context_id": "ctx-shadow-1",
        "a2a_task_id": "task-shadow-1",
    }
    values.update(changes)
    return ShadowAdapterRequest(**values)


def test_shadow_adapter_preserves_correlation_and_zero_side_effects():
    adapter = MockAnritsuOpenClawAdapter()
    response = adapter.execute(request())
    assert response.state == "accepted"
    assert response.execution_owner == "anritsu-openclaw"
    assert response.correlation.run_id == "shadow-run-1"
    assert response.correlation.context_id == "ctx-shadow-1"
    assert response.correlation.a2a_task_id == "task-shadow-1"
    assert response.instrument_available is False
    assert response.real_instrument_access is False
    assert response.side_effect_counts.model_dump() == {
        "manual_test_state_mutation": 0,
        "scpi_command": 0,
        "excel_report": 0,
        "instrument_lock": 0,
        "km_ingest": 0,
        "instrument_connection": 0,
        "iperf_process": 0,
    }


def test_shadow_request_rejects_real_flag_and_extra_commands():
    with pytest.raises(ValidationError):
        request(dry_run=False)
    with pytest.raises(ValidationError):
        request(shell_command="iperf")


@pytest.mark.parametrize("profile_id", ["other-profile", "../unsafe"])
def test_shadow_request_rejects_unknown_profile(profile_id):
    with pytest.raises(ValidationError):
        request(profile_id=profile_id)


def test_shadow_request_rejects_unknown_or_duplicate_case():
    with pytest.raises(ValidationError):
        request(test_cases=["unknown"])
    with pytest.raises(ValidationError):
        request(test_cases=["sa_dl_tcp", "sa_dl_tcp"])


def test_shadow_cancel_is_side_effect_free():
    adapter = MockAnritsuOpenClawAdapter()
    response = adapter.cancel(request())
    assert response.state == "canceled"
    assert response.side_effect_counts.instrument_lock == 0
    assert response.real_instrument_access is False
