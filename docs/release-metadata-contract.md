# Release Metadata Contract

Release identity is non-secret runtime metadata. A production candidate must provide all four fields together:

- `KM_GIT_COMMIT`: exactly 40 lowercase hexadecimal characters.
- `KM_RELEASE_ID`: 1-128 characters from letters, numbers, dot, underscore, slash, and hyphen.
- `KM_IMAGE_DIGEST`: `sha256:` followed by 64 lowercase hexadecimal characters.
- `KM_BUILD_TIMESTAMP`: RFC3339 date-time with `T` and an explicit `Z` or `+/-HH:MM` timezone. Examples: `2026-08-24T06:47:20+08:00` and `2026-08-23T22:47:20Z`.

Development compatibility permits all release fields to be absent. `KM_BUILD_TIMESTAMP` values that are empty or `unknown` map to `null` in `/api/v1/version`. A release runtime must not use that compatibility mode.

`scripts/build_wp1_release_candidate.sh` produces the timestamp with `date --iso-8601=seconds`. `scripts/generate_release_runtime_env.py` validates all four fields and writes a mode `0600` env file. Application startup validates the same timestamp contract, and `/api/v1/version` returns the accepted value unchanged.

Before restart or deployment, `restart_kb.sh` renders Compose with the scheduler profile and runs `scripts/validate_release_compose_metadata.py`. The preflight requires web, search worker, ingest worker, and beat to receive values exactly equal to the approved release identity. This is important because an unquoted YAML timestamp can be implicitly converted from RFC3339 into a value such as `2026-08-24 06:47:20 +0800 CST`.

The Retry 4 failure was not caused by the legal `+08:00` offset. The temporary production override used an unquoted YAML mapping value; Compose converted it before container startup. Earlier CI and isolated validation passed because they injected the timestamp directly through process/container environment variables and did not inspect rendered Compose metadata. The rendered-Compose preflight and regression tests close that gap without weakening timestamp validation.
