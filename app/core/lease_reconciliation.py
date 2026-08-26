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
    retry_count: int = 0,
    max_retries: int = 3,
) -> LeaseClaimDecision:
    """Classify a failed claim without changing state or stealing a lease.

    Missing ledger state is retryable during the bounded producer/worker
    initialization window. The caller must terminalize only after the retry
    budget is exhausted; no decision here steals or mutates a lease.
    """
    if lease_row is None:
        if retry_count < max_retries:
            return LeaseClaimDecision("retry", "ledger_record_missing_transient")
        return LeaseClaimDecision("terminal_failure", "ledger_record_missing_retry_exhausted")
    if lease_row.get("status") == "succeeded":
        return LeaseClaimDecision("idempotent_success", "already_completed")
    if (
        lease_row.get("status") == "running"
        and float(lease_row.get("lease_until") or 0) > now
        and lease_row.get("owner") != owner
    ):
        if retry_count < max_retries:
            return LeaseClaimDecision("retry", "active_lease")
        return LeaseClaimDecision("terminal_failure", "active_lease_retry_exhausted")
    return LeaseClaimDecision("terminal_failure", "claim_rejected_inconsistent_state")
