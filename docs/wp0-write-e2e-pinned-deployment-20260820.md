# WP0 Production Write E2E: Pinned Deployment Path

## Purpose

The normal `docker-compose.yml` build path is not a safe runtime-only E2E
activation path. Its application services use `build:` without an explicit
image tag while their commands assume the `app.main` package layout. A raw
recreate can therefore select a different local image and fail closed.

This procedure uses an already-built, reviewed candidate image and an
ephemeral Compose override. It does not change the normal Compose file.

## Preconditions

- A verified checkpoint exists in restricted persistent storage.
- The candidate image is reviewed and contains `/app/app/main.py` and
  `/app/src/main.py`.
- E2E credentials and hash registries are generated outside the repository,
  with mode `0600`.
- No active, reserved, scheduled, or queued Celery work exists.
- The operator has explicitly approved the production write E2E.

## Prepare The Override

```bash
python3 scripts/prepare_wp01_pinned_e2e_override.py \
  --image kb-wp01-candidate:<reviewed-tag> \
  --output /tmp/kb-wp01-production-e2e-override.yml
```

The script validates the image and only writes the ephemeral override. It
does not start or recreate containers.

## Controlled Activation

Generate the temporary E2E env with the shell-safe helper. Do not hand-write
the JSON hash registry: unquoted JSON is modified by shell parsing and causes
the API to return a configuration-format 503.

```bash
python3 scripts/generate_e2e_runtime_env.py \
  --hash-file /tmp/<e2e-dir>/e2e-token-hashes.json \
  --output /tmp/<e2e-dir>/production-e2e-runtime.env \
  --run-id-prefix TR-E2E-WP0-<unique-prefix>-
```

Load the managed deployment env, then load this temporary E2E env last so the
repository's default-disabled values cannot overwrite it. Use the override
with `--no-build` and `--force-recreate`; do not use plain `docker compose
restart` because restart does not apply environment changes.

```bash
docker compose \
  -f docker-compose.yml \
  -f /tmp/kb-wp01-production-e2e-override.yml \
  up -d --no-build --no-deps --force-recreate \
  web celery_search_worker celery_ingest_worker celery_beat nginx
```

Before any write request, verify the container image IDs and the E2E flags.
The flags must be present only for the approved test window.

## Acceptance And Recovery

Run the synthetic upload, review/approve, ingest terminal-state, cleanup
dry-run, cleanup apply, and post-cleanup 404 checks using a unique
`TR-E2E-WP0-` run ID. Save sanitized evidence. If any step fails, do not
retry with the same run ID; disable the E2E env and execute the verified
checkpoint rollback procedure.

```bash
python3 scripts/rollback_pre_wp01.py \
  --checkpoint backups/kb-pre-wp01-backups-20260819/pre-wp01-write-e2e-20260819-1605 \
  --execute --confirm-production PRE_WP01_ROLLBACK
```

After either pass or failure, verify E2E flags are false, cleanup is 404,
Health/Ready/Version are 200, and all task queues are idle. Delete temporary
plaintext credentials.

## Current Status

The image mismatch was diagnosed on 2026-08-20. The previous activation was
rolled back successfully, with no E2E write request or test data created.
The formal production write gate remains `NO-GO` until this pinned path is
reviewed and a new controlled run is explicitly approved.

## Shared Report Staging

The web service and ingest worker must mount the same host-backed
`KB_REPORT_STAGING_ROOT_HOST` at `/app/data/report-staging`. Without this
shared mount, upload succeeds in the web container but the ingest worker sees
no Excel file and ends in `ingest_failed`. The default is
`./data/report-staging`; create the directory before deployment and include it
in the checkpoint/data backup.
