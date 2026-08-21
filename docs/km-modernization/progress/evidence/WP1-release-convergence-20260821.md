# WP1 Release Convergence Candidate

## Candidate

- Branch: `agent/wp1-release-convergence`
- Code source commit: `d44485540427f180950997831aa8c3cd789a5f0f`
- Based on PR #9 latest reviewed package; no production deployment performed.
- Local image: `kb-wp1-release:wp1-convergence-20260821`
- Local image ID: `sha256:aae454ffe5caf1a0b562ac9e6ec34b289ea14836c4941e962bf9d061796eae29`
- Build time: `2026-08-21T12:09:25+08:00`
- Registry push/digest: not performed; requires separate approval.

## Scope

The candidate includes only rollout/build support and additive release identity:

- controlled `restart_kb.sh` status/restart/deploy lifecycle with task drain,
  readiness, checkpoint and rollback gates;
- frontend runtime assets required by the build;
- empty data build marker;
- `/api/v1/version` fields for commit, release ID, image digest and build time;
- contract test coverage for the additive version metadata.

No WP2, CSIT API, Booking, Validation Request, real-instrument, or business
workflow implementation is included.

## Compare evidence

PR #9 reviewed source:
`fefcc857ee3d3e8531154b5f3b98f38878c93423` → candidate changed 10 files;
patch SHA-256=`5e2d54b7043a050f63e0cb13b8c49d29a272aa4d936d9ba95e7d66407ca2f728`.

Previously deployed source:
`5c7ea2dac186bd906a4d7df64db25d55133674cc` → candidate changed 96 files.
This large comparison includes historical branch differences and is not used
to claim that the candidate is a direct descendant of the deployed source.
The candidate is instead based on the PR #9 reviewed package and imports only
the explicitly classified rollout/build support changes.

Machine-readable comparison:
[`WP1-release-convergence-20260821.json`](WP1-release-convergence-20260821.json)

## Acceptance boundary

- Production Gate: `NO-GO`
- `accepted_for_pr9=false` until supervisor reviews this candidate.
- No production redeploy, write E2E, migration, destructive restore or registry
  push was executed.
- Recovery items remain `Deferred Disaster Recovery Gate`: application
  registry/database, Neo4j, Qdrant, Redis full persistence, and runtime config.
