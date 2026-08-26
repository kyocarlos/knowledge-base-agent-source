"""Deterministic decisions for an application lease claim failure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class LeaseClaimDecision:
    """Action selected after a lease claim returned no owner."""

    action: str
    reason: str


def decide_claim_failure(
    lease_row: Mapping[str, object] | None,
    *,
    owner: str,
    now: float,
) -> LeaseClaimDecision:
    """Classify a failed claim without changing state or stealing a lease.

    The caller must retry only ``active_lease``. Missing or inconsistent ledger
    state is terminalized by the task layer and requires explicit reconciliation.
    """
    if lease_row is None:
        return LeaseClaimDecision("terminal_failure", "ledger_record_missing")
    if lease_row.get("status") == "succeeded":
        return LeaseClaimDecision("idempotent_success", "already_completed")
    if (
        lease_row.get("status") == "running"
        and float(lease_row.get("lease_until") or 0) > now
        and lease_row.get("owner") != owner
    ):
        return LeaseClaimDecision("retry", "active_lease")
    return LeaseClaimDecision("terminal_failure", "claim_rejected_inconsistent_state")
