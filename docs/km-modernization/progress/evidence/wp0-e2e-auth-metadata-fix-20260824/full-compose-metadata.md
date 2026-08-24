# WP0 Full Compose Metadata Evidence

## Scope

This is an isolated, disposable verification of the PR #20 candidate. It does not deploy, restart, or write the production system.

## Candidate

- Source commit: `2ef93d6b47d05b1acbc05fadc0df8393fefd41a0`
- Release ID: `wp0-e2e-auth-metadata-fix-20260824-r1`
- Image digest: `sha256:18039a96b063b3fd85d7c40b975b323f25de71b169efcd9a7d20c2f0f7a5a749`
- Build timestamp: `2026-08-24T16:18:21+08:00`

## Results

- Rendered Compose image pinning: PASS
- Four-service runtime image identity: PASS
- Four-service metadata equality: PASS
- `/api/v1/version`: HTTP 200, exact metadata: PASS
- Shared ledger path and mount: PASS
- `web`: running
- `search_worker`: running
- `ingest_worker`: running
- `beat`: running
- Production touched: `false`
- Secrets included in evidence: `false`

All four services used the exact candidate image digest and the following identical metadata:

```text
KM_GIT_COMMIT=2ef93d6b47d05b1acbc05fadc0df8393fefd41a0
KM_RELEASE_ID=wp0-e2e-auth-metadata-fix-20260824-r1
KM_IMAGE_DIGEST=sha256:18039a96b063b3fd85d7c40b975b323f25de71b169efcd9a7d20c2f0f7a5a749
KM_BUILD_TIMESTAMP=2026-08-24T16:18:21+08:00
```

The shared ledger path was `/home/da40_ai_gb10/knowledge-base/data/job-ledger.sqlite3`, mounted at `/home/da40_ai_gb10/knowledge-base/data` in every application container.

## Reproduction

```bash
python3 scripts/verify_candidate_full_compose.py \
  --source-root /home/da40_ai_gb10/knowledge-base \
  --image kb-wp0-release:wp0-e2e-auth-metadata-fix-20260824-r1 \
  --commit 2ef93d6b47d05b1acbc05fadc0df8393fefd41a0 \
  --release-id wp0-e2e-auth-metadata-fix-20260824-r1 \
  --image-digest sha256:18039a96b063b3fd85d7c40b975b323f25de71b169efcd9a7d20c2f0f7a5a749 \
  --build-timestamp 2026-08-24T16:18:21+08:00 \
  --output /tmp/wp0-full-compose-metadata-20260824.json
```

The isolated Compose project was removed after verification. The complete redacted result is in `full-compose-metadata.json`.
