"""Mock-only cancel, safe-state, and cleanup lifecycle for R1.

The adapter contract is intentionally side-effect free here. A later Anritsu
implementation must provide the same operations locally and report evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class SafetyAdapter(Protocol):
    def request_cancel(self, run_id: str, reason: str) -> None: ...

    def ensure_safe_state(self, run_id: str) -> None: ...

    def cleanup(self, run_id: str) -> None: ...


class SafetyLifecycleError(RuntimeError):
    """The lifecycle could not prove safe-state or cleanup."""


@dataclass(frozen=True)
class SafetyResult:
    run_id: str
    outcome: str
    cancel_requested: bool
    safe_state_confirmed: bool
    cleanup_confirmed: bool
    errors: tuple[str, ...] = ()


class SafetyLifecycle:
    """Execute and record the mandatory cancel/safe-state/cleanup order."""

    def __init__(self, adapter: SafetyAdapter):
        self.adapter = adapter
        self._results: dict[str, SafetyResult] = {}

    def cancel(self, run_id: str, reason: str) -> SafetyResult:
        if not run_id.strip() or not reason.strip():
            raise ValueError("run_id and reason are required")
        existing = self._results.get(run_id)
        if existing is not None:
            return existing

        errors: list[str] = []
        cancel_requested = False
        safe_state_confirmed = False
        cleanup_confirmed = False
        try:
            self.adapter.request_cancel(run_id, reason)
            cancel_requested = True
        except Exception as exc:  # noqa: BLE001 - safety actions continue independently
            errors.append(f"cancel:{exc}")
        try:
            self.adapter.ensure_safe_state(run_id)
            safe_state_confirmed = True
        except Exception as exc:  # noqa: BLE001 - cleanup must still be attempted
            errors.append(f"safe_state:{exc}")
        try:
            self.adapter.cleanup(run_id)
            cleanup_confirmed = True
        except Exception as exc:  # noqa: BLE001
            errors.append(f"cleanup:{exc}")

        outcome = "canceled" if safe_state_confirmed and cleanup_confirmed else "recovery_required"
        result = SafetyResult(run_id, outcome, cancel_requested, safe_state_confirmed, cleanup_confirmed, tuple(errors))
        self._results[run_id] = result
        return result

    def recover_after_crash(self, run_id: str) -> SafetyResult:
        """Run safe-state and cleanup when the original worker is gone."""
        if not run_id.strip():
            raise ValueError("run_id is required")
        existing = self._results.get(run_id)
        if existing is not None:
            return existing
        errors: list[str] = []
        safe_state_confirmed = False
        cleanup_confirmed = False
        try:
            self.adapter.ensure_safe_state(run_id)
            safe_state_confirmed = True
        except Exception as exc:  # noqa: BLE001
            errors.append(f"safe_state:{exc}")
        try:
            self.adapter.cleanup(run_id)
            cleanup_confirmed = True
        except Exception as exc:  # noqa: BLE001
            errors.append(f"cleanup:{exc}")
        outcome = "recovered" if safe_state_confirmed and cleanup_confirmed else "recovery_required"
        result = SafetyResult(run_id, outcome, False, safe_state_confirmed, cleanup_confirmed, tuple(errors))
        self._results[run_id] = result
        return result


@dataclass
class MockSafetyAdapter:
    """Failure-injection adapter; it never touches an external system."""

    fail_actions: set[str] = field(default_factory=set)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def _call(self, action: str, run_id: str) -> None:
        self.calls.append((action, run_id))
        if action in self.fail_actions:
            raise SafetyLifecycleError(f"injected {action} failure")

    def request_cancel(self, run_id: str, reason: str) -> None:
        self._call("cancel", run_id)

    def ensure_safe_state(self, run_id: str) -> None:
        self._call("safe_state", run_id)

    def cleanup(self, run_id: str) -> None:
        self._call("cleanup", run_id)
