# KM v2.6 CI/CD validation boundary

This pipeline validates the KM side only. CSIT runtime, CSIT write APIs, and
the final CSIT+KM integration automation are deliberately out of scope.

## CI

`km-v26-ci.yml` runs on pull requests and pushes to `main`, plus manual runs.
It checks the non-secret 18-WP manifest, Python tests and compilation, isolated
CI Compose configuration, shell syntax, frontend build, whitespace, and common
credential patterns. A separate job starts ephemeral Qdrant, Neo4j, and
TimescaleDB containers and runs the KM database contract smoke test; it never
uses Production volumes, databases, or tokens.

The security job runs KM authorization/upload negative contracts, `pip-audit`,
Bandit, and the high-severity frontend dependency audit. Upload filenames are
fail-closed for path separators, and the checks do not require CSIT.

## Release-candidate validation

`km-v26-release-validation.yml` is manual and accepts a commit/tag/branch.
It verifies a clean source checkout, release contract tests, source hashes,
and publishes a source provenance artifact. It does not deploy, mutate a
database, call CSIT, or consume Production secrets. Protected environment
approval and rollback evidence remain required before any future deployment.

## Later CD gate

A future KM staging/Production deployment workflow may be added only after
the target environment supplies protected secrets, image registry policy,
runtime preflight, migration/restore rules, approval gates, and tested
rollback. The final CSIT+KM integration workflow remains a separate future
deliverable after Patty's CSIT validation contract is ready.
