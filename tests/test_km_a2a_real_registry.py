from datetime import datetime, timedelta, timezone

import pytest

from km_a2a_bridge.real_contracts import RealRunApproval
from km_a2a_bridge.real_registry import RealRegistryConflict, RealRunRegistry


NOW = datetime(2026, 8, 13, 5, 30, tzinfo=timezone.utc)


def approval(run_id="real-run-1", approval_id="approval-1"):
    return RealRunApproval(
        approval_id=approval_id,
        run_id=run_id,
        operator_id="operator@example.test",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def test_approval_survives_new_registry_and_is_single_use(tmp_path):
    path = tmp_path / "real-registry.sqlite3"
    first = RealRunRegistry(path)
    first.register_approval(approval())
    second = RealRunRegistry(path)
    second.consume_approval(approval(), NOW + timedelta(seconds=1))
    with pytest.raises(RealRegistryConflict, match="already been used"):
        RealRunRegistry(path).consume_approval(approval(), NOW + timedelta(seconds=2))


def test_expired_or_unregistered_approval_is_rejected(tmp_path):
    registry = RealRunRegistry(tmp_path / "real-registry.sqlite3")
    with pytest.raises(RealRegistryConflict, match="not registered"):
        registry.consume_approval(approval(), NOW)
    registry.register_approval(approval())
    with pytest.raises(RealRegistryConflict, match="expired"):
        registry.consume_approval(approval(), NOW + timedelta(minutes=5))


def test_lock_is_single_flight_and_owner_bound(tmp_path):
    registry = RealRunRegistry(tmp_path / "real-registry.sqlite3")
    lock = registry.acquire_lock("anritsu-instrument", "real-run-1", "operator@example.test", 60, NOW)
    with pytest.raises(RealRegistryConflict, match="busy"):
        registry.acquire_lock("anritsu-instrument", "real-run-2", "other@example.test", 60, NOW)
    with pytest.raises(RealRegistryConflict, match="another operator"):
        registry.renew_lock(lock.lock_id, "other@example.test", 60, NOW + timedelta(seconds=1))


def test_expired_lock_can_be_replaced_and_valid_owner_can_renew(tmp_path):
    registry = RealRunRegistry(tmp_path / "real-registry.sqlite3")
    lock = registry.acquire_lock("anritsu-instrument", "real-run-1", "operator@example.test", 1, NOW)
    renewed = registry.renew_lock(lock.lock_id, "operator@example.test", 60, NOW + timedelta(milliseconds=500))
    assert renewed.expires_at > lock.expires_at
    with pytest.raises(RealRegistryConflict, match="busy"):
        registry.acquire_lock("anritsu-instrument", "real-run-2", "other@example.test", 60, NOW + timedelta(seconds=1))
    registry.release_lock(lock.lock_id, "operator@example.test")
    replacement = registry.acquire_lock("anritsu-instrument", "real-run-2", "other@example.test", 60, NOW + timedelta(seconds=1))
    assert replacement.run_id == "real-run-2"


def test_release_requires_owner(tmp_path):
    registry = RealRunRegistry(tmp_path / "real-registry.sqlite3")
    lock = registry.acquire_lock("anritsu-instrument", "real-run-1", "operator@example.test", 60, NOW)
    with pytest.raises(RealRegistryConflict, match="another operator"):
        registry.release_lock(lock.lock_id, "other@example.test")
