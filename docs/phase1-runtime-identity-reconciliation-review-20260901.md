# Phase 1 Runtime Identity Reconciliation Review

## Decision

The first live read-only reconciliation run is valid infrastructure evidence.
Its `MISMATCH` result exposed an identity-model problem, not a Production
regression.

## Identity model

| Field | Meaning |
| --- | --- |
| `accepted_release` | Last candidate accepted by the WP1 production acceptance run. |
| `deployed_release` | Runtime identity expected to be deployed now. |
| `historical_acceptance_run` | Evidence reference only; it is not the current deployment identity. |

WP1 acceptance intentionally restored the application services to the
production baseline after the controlled E2E window. Therefore the last
accepted candidate and the current deployed baseline are different valid
states.

## Current baseline declaration

The `deployed_release.deployment_state` is `BASELINE`. Its four service image
IDs are taken from the sanitized snapshot published by workflow `33478779515`.
The snapshot recorded Health/Version `200/200`, all four application services
running, and no production mutation. Git identity and Version release metadata
were unavailable in that broker snapshot; those remain P2 provenance debt for
the baseline state and are not used to force a false mismatch.

## Reconciliation rules

1. Compare runtime service status and image IDs with `deployed_release`.
2. Return `STALE` for unavailable Health/Version or non-running services.
3. Return `MISMATCH` for an identity difference; do not modify Production to
   make the result pass.
4. For `RELEASE`, additionally compare application release metadata and the
   operational Git identity.
5. Keep `accepted_release` and its historical run as audit evidence only.

No Production, database, container lifecycle, or acceptance run was changed by
this semantic reconciliation.
