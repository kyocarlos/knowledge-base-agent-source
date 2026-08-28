# WP1 WebSocket-Fix Production Preflight Revalidation

- Result: `PASS_READ_ONLY_PREFLIGHT`
- Production Gate: `NO-GO_PENDING_SUPERVISOR_GO`
- Run ID: `TR-E2E-WP1-PROD-WS-PREFLIGHT-20260828-RO-092300-d355eb14`
- Production write/restart: `false/false`

## Baseline

Baseline application image is `sha256:18039a96...f7a5a749`. Health and Version returned HTTP 200; WP0/WP1 runtime gates passed; Celery had 2 nodes, with active/reserved/scheduled tasks and queues at zero.

Checkpoint verification and rollback readiness passed using the approved checkpoint and checksum `1801a67e87c5f1019587052e4b1e4d53f258334c3f806ab829c11ca889c3a4e5`. The rollback target matches the current runtime and `production_drift=false`.

## Candidate

The approved tag resolves to exact image `sha256:54650d64...9c80bee3`, with source `914d7c829269779f13c47d71ebd27ecb9dde84ec`, release `wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`, and build timestamp `2026-08-26T15:21:36+08:00`. `restart_kb.sh --deploy-pinned --dry-run` passed with no mutation.

The active nginx dynamic resolver configuration remains hash `7696757b...f2e86e93`; formal ingress Health and Version both returned HTTP 200.

## WebSocket hard gates

The isolated PASS runner is commit `62b8410dcf0711589082374409dcc29fd6332804`. Its protocol matrix proves empty, invalid, and removed identities fail closed with `4401`; a valid temporary identity must receive `res(id=c1, ok=true)` before `chat.send`, and then receives the final chat event. The planned production runner rejects empty token and premature `chat.send` before any protocol action.

Run-ID uniqueness, fixture/multipart, additive identity, cleanup availability, protected secret, and failure-window persistence gates are PASS. No credential material is recorded. This preflight requests a fresh supervisor Production GO review; it does not authorize deployment.
