# WP1 Versioned Maintenance Entrypoint Contract

The formal WP1 transaction caller is `scripts/wp1_maintenance_entrypoint.py`.
It invokes `scripts/wp1_transaction_dispatcher.py`, which invokes the
fail-closed transaction wrapper. The caller and handoff are versioned together
and must write a persistent sanitized JSONL orchestration log.

The entrypoint records `entrypoint_start`, `entrypoint_dispatch_pre`, periodic
`entrypoint_heartbeat`, `entrypoint_signal` or `entrypoint_exception`, and
`entrypoint_complete`. The dispatcher and wrapper record their own pre/post
events in the same log. Command arguments are redacted before logging.

The dispatcher requires the process-local `WP1_FORMAL_ENTRYPOINT=1` marker,
which is set only by the versioned entrypoint in this chain. Direct or legacy
inline attempts to invoke the dispatcher are rejected and logged as
`dispatcher_rejected_non_formal_caller`. This is an accidental-path guard, not
an authorization mechanism. Likewise, `WP1_DISPATCHER_CONTEXT=1` is a
process-local caller marker for the wrapper. Both fixed environment markers are
easy to forge by a caller that intentionally bypasses the chain; they defend
against accidental direct invocation and stale unchanged inline commands, not
against a deliberate bypass. A stronger boundary would require a
dispatcher-issued, single-use unpredictable credential or equivalent OS-level
execution control, which is outside this change.

The previous inline maintenance shell is not a formal caller. Inventory found no
持久化 script path to remove; it was an ephemeral command sequence in the
maintenance session. Therefore runtime activation still requires maintenance
evidence that this inline procedure is no longer used and that the versioned
entrypoint is the only permitted transaction path. The marker guard prevents an
untracked caller from silently reaching the wrapper, but cannot stop an
arbitrary shell from mutating services; that operational control must be
enforced by the activation procedure.

This contract does not authorize production enablement, acceptance traffic, a
new Run ID, or any service mutation. Activation and non-production runtime
validation require separate approvals.
