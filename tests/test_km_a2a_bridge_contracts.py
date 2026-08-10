import pytest
from pydantic import ValidationError

from km_a2a_bridge import (
    A2ATaskCorrelation,
    BridgeConfig,
    BridgeDispatchError,
    IngestStatus,
    RejectionReason,
    ReportStatus,
    RunStatus,
    TestJob as JobContract,
    TestStatus as JobTestStatus,
    validate_dispatch,
)

CONTROL_HASH = "a" * 64


def valid_job(**overrides):
    values = {
        "job_type": "run_iperf_test",
        "environment": "anritsu",
        "profile_id": "profile-1",
        "run_id": "run_1",
        "requested_by": "operator@example.test",
        "duration_seconds": 1,
        "test_cases": ["downlink_1", "uplink.v2"],
    }
    values.update(overrides)
    return JobContract(**values)


@pytest.mark.parametrize("duration", [1, 3600])
def test_job_accepts_duration_boundaries(duration):
    assert valid_job(duration_seconds=duration).duration_seconds == duration


@pytest.mark.parametrize("duration", [0, 3601])
def test_job_rejects_duration_outside_boundaries(duration):
    with pytest.raises(ValidationError):
        valid_job(duration_seconds=duration)


@pytest.mark.parametrize("environment", ["anritsu", "amarisoft"])
def test_job_accepts_only_supported_environments(environment):
    assert valid_job(environment=environment).environment == environment


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("job_type", "other"),
        ("environment", "unknown"),
        ("profile_id", "  "),
        ("run_id", ""),
        ("requested_by", "\t"),
        ("run_id", "unsafe/run"),
        ("profile_id", "unsafe profile"),
        ("test_cases", []),
        ("test_cases", ["bad case"]),
        ("test_cases", ["../unsafe"]),
    ],
)
def test_job_rejects_invalid_contract_values(field, value):
    with pytest.raises(ValidationError):
        valid_job(**{field: value})


def test_job_forbids_extra_fields():
    with pytest.raises(ValidationError):
        valid_job(unexpected=True)


def test_config_is_disabled_by_default_and_profiles_are_frozen():
    config = BridgeConfig()
    assert config.enabled is False
    assert config.allowed_profiles == {"anritsu": frozenset(), "amarisoft": frozenset()}
    assert all(isinstance(profiles, frozenset) for profiles in config.allowed_profiles.values())


def test_enabled_config_accepts_https_endpoints_with_separate_credentials_and_redacts_repr():
    config = BridgeConfig(
        enabled=True,
        control_token_sha256=CONTROL_HASH,
        allowed_profiles={"anritsu": {"p1"}},
        agent_endpoints={"anritsu": "https://anritsu.example", "amarisoft": "https://amarisoft.example"},
        agent_credentials={"anritsu": "anritsu-secret", "amarisoft": "amarisoft-secret"},
    )
    rendered = repr(config)
    assert "anritsu-secret" not in rendered
    assert "amarisoft-secret" not in rendered
    assert "<redacted>" in rendered


def test_enabled_config_requires_at_least_one_complete_agent():
    with pytest.raises(ValidationError):
        BridgeConfig(enabled=True, allowed_profiles={"anritsu": {"p1"}})


def test_enabled_config_accepts_only_mock_or_sdk_dry_run_transport():
    with pytest.raises(ValidationError):
        BridgeConfig(
            enabled=True,
            transport_mode="real",
            control_token_sha256=CONTROL_HASH,
            agent_endpoints={"anritsu": "https://agent.example"},
            agent_credentials={"anritsu": "secret"},
        )


def test_config_rejects_unknown_environment_keys():
    with pytest.raises(ValidationError):
        BridgeConfig(allowed_profiles={"unknown": {"p1"}})


def test_config_rejects_profile_strings_as_collections():
    with pytest.raises(ValidationError):
        BridgeConfig(allowed_profiles={"anritsu": "profile-1"})


def test_validation_errors_hide_secret_inputs():
    secret = "must-not-appear"
    with pytest.raises(ValidationError) as caught:
        BridgeConfig(
            enabled=True,
            control_token_sha256=CONTROL_HASH,
            agent_endpoints={"anritsu": "http://unsafe.example"},
            agent_credentials={"anritsu": secret},
        )
    assert secret not in str(caught.value)


@pytest.mark.parametrize("endpoint", ["http://agent.example/a2a", "https://", "agent.example/a2a"])
def test_enabled_config_rejects_non_https_urls(endpoint):
    with pytest.raises(ValidationError):
        BridgeConfig(enabled=True, control_token_sha256=CONTROL_HASH, agent_endpoints={"anritsu": endpoint}, agent_credentials={"anritsu": "secret"})


@pytest.mark.parametrize("credentials", [{}, {"agent": "  "}])
def test_enabled_config_requires_nonblank_credential_per_endpoint(credentials):
    with pytest.raises(ValidationError):
        BridgeConfig(enabled=True, control_token_sha256=CONTROL_HASH, agent_endpoints={"anritsu": "https://agent.example"}, agent_credentials={"anritsu": credentials.get("agent", "")})


def test_enabled_config_requires_distinct_agent_credentials():
    with pytest.raises(ValidationError):
        BridgeConfig(
            enabled=True,
            control_token_sha256=CONTROL_HASH,
            agent_endpoints={"anritsu": "https://a.example", "amarisoft": "https://b.example"},
            agent_credentials={"anritsu": "same", "amarisoft": "same"},
        )


def test_validate_dispatch_accepts_allowlist_for_matching_environment_only():
    config = BridgeConfig(
        enabled=True,
        control_token_sha256=CONTROL_HASH,
        allowed_profiles={"anritsu": {"shared"}, "amarisoft": {"other"}},
        agent_endpoints={"anritsu": "https://anritsu.example", "amarisoft": "https://amarisoft.example"},
        agent_credentials={"anritsu": "secret-a", "amarisoft": "secret-b"},
    )
    assert validate_dispatch(config, valid_job(environment="anritsu", profile_id="shared")) is None
    with pytest.raises(BridgeDispatchError) as caught:
        validate_dispatch(config, valid_job(environment="amarisoft", profile_id="shared"))
    assert caught.value.reason is RejectionReason.PROFILE_NOT_ALLOWED


def test_validate_dispatch_rejects_disabled_bridge_with_stable_reason():
    with pytest.raises(BridgeDispatchError) as caught:
        validate_dispatch(BridgeConfig(), valid_job())
    assert caught.value.reason is RejectionReason.POLICY_DENIED


def test_rejection_reason_values_are_stable():
    assert {reason.value for reason in RejectionReason} == {
        "busy", "policy_denied", "capacity_exceeded", "profile_not_allowed",
        "invalid_request", "agent_offline",
    }


def test_correlation_ids_can_be_assigned_over_time():
    correlation = A2ATaskCorrelation(run_id="run-1")
    assert correlation.context_id is None
    assert correlation.a2a_task_id is None
    assert correlation.ingest_task_id is None
    assert correlation.file_hash is None
    assigned = correlation.model_copy(update={"context_id": "ctx-1", "a2a_task_id": "task-1", "ingest_task_id": "ingest-1", "file_hash": "abc123"})
    assert assigned.model_dump() == {
        "context_id": "ctx-1", "a2a_task_id": "task-1", "run_id": "run-1",
        "ingest_task_id": "ingest-1", "file_hash": "abc123",
    }


def test_a2a_completion_does_not_imply_report_or_ingest_completion():
    status = RunStatus(test_status=JobTestStatus.COMPLETED)
    assert status.report_status is ReportStatus.PENDING
    assert status.ingest_status is IngestStatus.PENDING
