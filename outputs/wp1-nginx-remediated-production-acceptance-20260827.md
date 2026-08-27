# WP1 Production Acceptance Final Review - Nginx Remediated

## Result

`Production Acceptance = FAIL before synthetic acceptance`.
`Rollback = PASS`. `Production Gate = NO-GO`.

The approved candidate was recreated only for the four application services. Direct backend readiness passed. Formal ingress readiness failed for the bounded window, so no synthetic Upload/Ingest or other production write was started.

## Evidence

- Candidate source: `914d7c829269779f13c47d71ebd27ecb9dde84ec`.
- Candidate image: `sha256:54650d64a2867be1ee21bbcb47951d5bc28d85ef76fcac370310b36a9c80bee3`.
- Readiness: `60` attempts, `2s` interval, `120s` timeout.
- Direct backend first success: `2026-08-27T01:41:25.852318+00:00`.
- Formal ingress first success: none in the readiness evidence.
- Diagnostic bundle: `outputs/ingress-failure-diagnostics/20260827-094324/`.

The captured nginx config contains the dynamic resolver and variable upstream. During the failure window, the first formal request attempted the old web IP `172.20.0.6` while the candidate web IP was `172.20.0.7`; direct nginx-to-web probes were successful. After rollback, formal ingress returned 200.

The readiness probe records ingress status `0` / `unavailable_or_invalid_json` because it uses Python `urllib` against the local HTTPS endpoint. This requires a separate diagnostic/review; it is not treated as proof of application regression.

## Rollback and Safety

Rollback completed to the approved baseline. Post-rollback Health, WP0/WP1 runtime gates, Celery 2 nodes, and tasks/queues were healthy/empty. Synthetic acceptance did not start. The stuck task was not retried or changed; no Redis/ledger mutation, migration, restore, WP2 deployment, or real instrument operation occurred. No secrets are included.
