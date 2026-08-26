# WP1 Release Metadata Dependency Alignment Review

## Result

Read-only analysis completed. The production checkout is missing `app/core/release_metadata.py`, while canonical `agent/km-plan-v2.6-anderson@07c36e1...` contains the accepted 58-line module. No production files were modified.

## Dependency and Side Effects

The module imports only Python standard-library `re` and `datetime.datetime`. It does not import or access DB, Redis, FastAPI, application startup, runtime environment, secrets, network, or filesystem writes. Its functions are pure validators that return input strings or a metadata dictionary and raise `ValueError` on invalid values.

Contract:

- source commit: exactly 40 lowercase hexadecimal characters;
- release ID: 1-128 characters from `[A-Za-z0-9._/-]`;
- image digest: `sha256:` plus 64 lowercase hexadecimal characters;
- build timestamp: calendar-valid RFC3339 with `T` and explicit `Z` or `+/-HH:MM` timezone;
- combined result keys: `KM_GIT_COMMIT`, `KM_RELEASE_ID`, `KM_IMAGE_DIGEST`, `KM_BUILD_TIMESTAMP`.

## Consumers and Options

The module is consumed by `app/core/config.py`, release Compose/runtime generators, Compose metadata validation, image capability validation, and the focused release metadata/image capability tests.

Option **A** is selected: backport the canonical pure module with its focused test. This is the smallest change that preserves one source of truth and avoids duplicating validation logic in a standalone helper. Option C cannot work in the real checkout because the equivalent canonical module is absent there; Option B has avoidable contract-drift risk.

## Safety Boundary

No production sync, restart, deployment, database/Redis mutation, WP2 work, or secret handling was performed. Production remains `NO-GO` until this dependency scope is separately approved and validated.

Machine-readable evidence: `outputs/wp1-release-metadata-dependency-alignment-review-20260827.json`.
