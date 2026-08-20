# WP1 Application Idempotency Shadow Evidence

## Scope

This evidence covers the application/business-flow layer, beyond the existing
Redis `SETNX` primitive test. It uses a synthetic request, a temporary SQLite
ledger, four concurrent duplicate submissions, and a simulated first-attempt
failure after the business side effect is committed but before lease completion.

No production service, database, instrument, ingest pipeline, or user data was
used.

## Acceptance checks

- Exactly one concurrent submission owns the live application lease.
- The first attempt's side effect is committed before simulated worker death.
- The expired job is recovered and reclaimed as attempt 2.
- Recovery completion succeeds.
- A duplicate side-effect insert is ignored by the business operation key.
- Exactly one side-effect row remains.
- A late delivery after success cannot claim the job.
- Final application ledger state is `succeeded`.

## Reproduction

```bash
python scripts/drill_wp1_application_idempotency_shadow.py \
  --report outputs/wp1-application-idempotency-shadow-20260820
```

The command writes a machine-readable JSON report. The report must contain
`application_idempotency_verified=true`, `live_owner_count=1`,
`recovery_attempt=2`, `side_effect_count=1`, and
`late_duplicate_claim_after_success=false`.

## Result

The result is isolated-shadow evidence only. It does not establish production
acceptance or complete Neo4j, Qdrant, Redis restore, or deployment recovery.
