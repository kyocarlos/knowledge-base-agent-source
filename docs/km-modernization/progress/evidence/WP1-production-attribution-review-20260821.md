# WP1 Production Attribution Review

## Decision

The deployed release `5c7ea2dac186bd906a4d7df64db25d55133674cc` cannot be
attributed to PR #9 reviewed implementation source
`fefcc857ee3d3e8531154b5f3b98f38878c93423`.

The two tips share common ancestor
`d39f9f790eb0cd0ebaf4a992b2664bd1d8b3143e`, but the deployed branch contains
93 changed files relative to the PR #9 branch. The binary/text diff SHA-256 is
`1785abf7503e00c560d09078fac439926aaca46c5fad463a6b21b5c9332cf549`.

## Why Option B is rejected

The delta is not limited to deployment fixes. It includes application and
runtime behavior such as:

- deletion of `app/core/job_lease.py`;
- changes to `src/ingest_registry.py`, `src/test_reports/auth.py`,
  `src/web_api/__init__.py`, `src/web_api/report_routes.py` and
  `src/web_api/tasks.py`;
- changes to `docker-compose.yml`, `restart_kb.sh`, `start.sh` and workflows;
- deletion of job lease, write-E2E and credential tests.

Therefore the deployed release requires an independent review and CI result.
It must not be treated as an approved PR #9 release.

## Safety decision

- `accepted_for_pr9=false`
- Production Gate: `NO-GO`
- WP1: `96% Conditional Accept`
- No production write, migration, destructive restore, real instrument access
  or WP2 work was performed by this review.

The machine-readable comparison is
[`WP1-production-attribution-review-20260821.json`](WP1-production-attribution-review-20260821.json).
The existing deployment evidence remains separate and continues to record the
checkpoint, image digests and rollback drill without changing PR #9 acceptance.
