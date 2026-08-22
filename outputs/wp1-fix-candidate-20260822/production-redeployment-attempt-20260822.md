# Production Redeployment Attempt

Date: 2026-08-22 (Asia/Taipei)

The approved candidate was deployed twice under the controlled GO window. No
synthetic acceptance write was started.

## Attempt 1

- 13:23:12 to 13:23:17 +08:00
- Candidate image identity matched `sha256:9ee779ae...591f376a`
- Health and WP0 gates passed
- Celery ping and search/ingest queue checks failed during immediate startup
- Rollback executed with the approved current-production checkpoint: PASS

## Attempt 2

- 13:25:00 to 13:25:04 +08:00
- Waited 35 seconds for worker model preload
- Candidate image identity matched the approved digest
- Health, WP0 and WP1 gates passed
- `/api/v1/version` returned HTTP 200 but `commit`, `release_id`,
  `image_digest` and `build_timestamp` were all null
- Identity gate failed because production Compose did not inject the candidate
  runtime metadata
- No Chat/Search/WebSocket/report/upload/ingest or synthetic write acceptance
  was started
- Rollback executed with the approved checkpoint: PASS

## Final state

Production is back on the known-good image
`sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`.
Health, WP0/WP1 gates, Celery 2 nodes and empty queues are PASS.

Production Gate is `NO-GO`. The candidate requires a separate reviewed fix
cycle to inject and validate release metadata. The frozen candidate was not
modified in place, and no production data write, migration or restore occurred.
