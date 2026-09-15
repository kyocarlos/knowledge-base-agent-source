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
Bandit stores the complete finding report as an artifact and blocks confirmed
High findings; remaining Medium/Low findings are visible follow-up hardening
items rather than hidden exclusions.

The retrieval-evaluation job validates the versioned KM golden-query seed.
Once manual chunk qrels are completed, the same evaluator will calculate
Recall@20, Precision@5, MRR@10, HitRate@5, and nDCG@10 for baseline/candidate
comparison. The reranker is disabled by default and can be controlled with
`KM_RERANK_MODE=off|shadow|active` (or `search.reranker.mode`). The legacy
`KM_RERANK_ENABLED=true` setting maps to `active`; shadow computes and logs
rank changes while returning the current ranking. Model load, timeout, or
inference failures always fall back to the existing ranking path.

The real-system runtime uses the optional pinned dependency in
`requirements-reranker.txt` and a separately provisioned local model path.
Search sources expose `retrieval_score`, `rerank_score`,
`document_quality_score`, `display_relevance_score`, `relevance_grade`,
`rerank_status`, model/embedding identity, and score breakdown. The frontend
source chips and Vue chat source hints render the relevance and quality values.
Before activating `active`, existing Qdrant points must be reindexed with
`publish_status`, `is_current`, `chunk_id`, document version, and embedding
identity because these lifecycle fields are hard filters, not ranking boosts.

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
