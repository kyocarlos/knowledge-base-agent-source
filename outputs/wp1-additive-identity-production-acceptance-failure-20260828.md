# WP1 Additive Identity Provisioning Production Acceptance Failure

## Result

`FAIL_CLOSED_ROLLBACK_PASS`. Production Gate returns to `NO-GO`. The candidate application regression is not established.

## Failure

Run ID: `TR-E2E-WP1-PROD-IDENTITY-20260827-163555-6937da3f`

The pinned candidate deployed successfully and passed readiness and identity checks. Health, version, Search, agent health, Upload `202`, and duplicate detection (`duplicate=true`) passed. Report self-read returned HTTP `403`; acceptance stopped before Ingest, Report Review, and WebSocket.

## Root Cause

The temporary runtime env contained both the E2E Upload mapping and the additive regular `KB_AGENT_TOKEN_HASHES_JSON` self-read mapping. The deployment procedure then loaded `config/report-ingest.env`, which also defines `KB_AGENT_TOKEN_HASHES_JSON` later in the environment load order. That later value replaced the temporary self-read mapping; the cleanup mapping was likewise not effective. This is classified as `PROVISIONING_ENV_PRECEDENCE_AND_CLEANUP_MAPPING_GAP`, not an application or candidate regression.

No source code was modified and no candidate image was rebuilt. The procedure must be corrected in an isolated cycle before another production retry; do not retry in this deployment window.

## Rollback

Rollback to the approved checkpoint passed. The baseline application image is `sha256:18039a96b063b3fd85d7c40b975b323f25de71b169efcd9a7d20c2f0f7a5a749`; post-rollback Health was HTTP `200`, Celery had `2` nodes, active/reserved/scheduled tasks were `0`, and queues were empty. The temporary identity returned HTTP `404` after rollback.

The cleanup endpoint returned `503` before rollback because its mapping was overwritten. Residual count is therefore not claimed as an endpoint-verified value; rollback restored the approved clean baseline. No manual Redis/ledger mutation or forced cleanup was performed.

## Safety

`production_touched=true` because the approved controlled deployment and synthetic Upload occurred. No stuck task was touched, no retry/resubmit was performed, no migration/restore/WP2/real instrument action occurred, and no credential material is included in this evidence.
