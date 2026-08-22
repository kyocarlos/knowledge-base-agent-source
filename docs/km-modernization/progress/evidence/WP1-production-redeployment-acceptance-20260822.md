# WP1 Production Redeployment Acceptance

## Final decision

- Production GO was exercised only within the supervisor-approved scope.
- The frozen release identity was verified in runtime.
- Controlled synthetic Upload/Ingest did not pass, so the release was rolled back.
- Production Gate is `NO-GO`; WP1 remains `99% Conditional Accept`.
- Frozen source was not modified and PR #10 remains Draft.

## Release identity

| Item | Value |
| --- | --- |
| Source commit | `38dda63f4ba53762d926d9874bdf310e3a0eb324` |
| Release ID | `wp1-final-20260821` |
| Release image | `sha256:aae454ffe5caf1a0b562ac9e6ec34b289ea14836c4941e962bf9d061796eae29` |
| `/api/v1/version` | HTTP 200; exact commit, release ID and image digest matched |

## Acceptance result

The synthetic run `TR-E2E-WP0-20260822-prod-001` uploaded successfully, but the approved ingest task remained queued. The worker logged that it could not acquire a lease and did not execute ingest side effects. The frozen image also exposed a report retrieval defect: `authenticate_agent` is referenced but undefined in `src/web_api/report_routes.py`. This is a source-fix/review blocker, not a production data issue.

Cleanup completed with zero residual synthetic data:

- one staging file deleted;
- one Redis task state deleted;
- one report submission deleted;
- Neo4j deleted nodes: 0;
- Qdrant deleted points: 0;
- post-cleanup residuals: 0.

The temporary E2E write mode and credentials were disabled before rollback.

## Rollback

Rollback was executed with the supervisor-approved command and checkpoint:

```text
python3 scripts/rollback_pre_wp01.py --checkpoint /home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-current-production-20260822-110946 --execute --confirm-production PRE_WP01_ROLLBACK
```

The final runtime is the previous known-good image `sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`. Health is HTTP 200, and after the startup settling period all WP0/WP1 runtime gates, Celery (2 nodes), queues and legacy gates passed.

## Scope boundary

No migration, destructive Neo4j/Qdrant restore, real instrument access, WP2 deployment, or frozen-source modification was performed. A new source fix/review cycle is required before retrying deployment.
