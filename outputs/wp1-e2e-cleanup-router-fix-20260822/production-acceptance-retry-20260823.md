# Production Acceptance Retry Evidence

Date: 2026-08-23 (Asia/Taipei)

## Result

The approved candidate identity gate passed, but controlled production acceptance
failed and was rolled back. This is **not** a production acceptance PASS.

- Source: `e8455db7f36398995c0ec51647aff21aa4df3925`
- Release: `wp1-e2e-cleanup-router-fix-20260822-r1`
- Image: `sha256:f3290d5d594d20aa35e2b3799675f86a9dc615a01063acfa9efd8097bc710cf0`
- Start: `2026-08-23T09:55:04+08:00`
- End timestamp: not captured before rollback
- Production Gate: `NO-GO`

## Temporary Provisioning

An additive runtime regular-agent registry merge was used for this retry. Two
existing registry entries were preserved and the synthetic identity
`e2e-agent-01` was added in a mode-0600 runtime environment. No credential
material, token, or hash was written to this evidence. No migration occurred.

After the failed acceptance, the temporary identity was removed. Regular
authentication using it was rejected with HTTP 403, existing registry count
returned to two, and post-removal service health passed.

## Acceptance Results

Run ID: `TR-E2E-WP1-PROD-RETRY-20260823-095504-unique`

- Version identity: PASS
- Health: PASS, HTTP 200
- Search: PASS, HTTP 200
- Report agent health: PASS, HTTP 200
- Upload: PASS, HTTP 202
- Duplicate upload deduplication: PASS (`duplicate=true`)
- Report self-read: PASS, HTTP 200
- Report approve/read: **FAIL**, HTTP 409 because the submission remained `queued`
- Worker completion: **blocked by lease**
- Worker recovery, in-flight redelivery, application idempotency and report review: not run after the mandatory failure

The ingest worker received task `ingest_20260823_015605_be828d38`, but did not
acquire its lease. The submission remained queued. This is classified as a
production runtime/configuration task-lease reconciliation blocker; no source
code was modified during the attempt.

## Cleanup and Rollback

Cleanup dry-run passed and identified one report and the ingest task. Cleanup
apply correctly returned HTTP 409 because an active/queued ingest task remained.
Residual reconciliation is therefore **BLOCKED**; residual count is not
claimed as zero. No manual production deletion was performed.

The approved rollback was then executed:

```text
python3 scripts/rollback_pre_wp01.py --checkpoint /home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-current-production-20260822-110946 --execute --confirm-production PRE_WP01_ROLLBACK
```

Rollback passed. The runtime returned to image
`sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`.
Final Health was HTTP 200, Celery had two nodes, and inspected queues were
empty.

## Follow-up Boundary

Do not retry production acceptance until the ingest lease/task-state mismatch
and cleanup reconciliation are separately reviewed and approved. This evidence
does not authorize a source change, WP2 work, migration, destructive restore,
or real-instrument operation.
