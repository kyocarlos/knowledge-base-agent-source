# WP1 PR #9～#16 Consolidation Strategy

Status: **Prepared, not merged**

## Accepted Runtime

The supervisor accepted WP1 at 100% with:

- Source: `703075efe862736cffe5159edfcb3b1940c5ae09`
- Release: `wp1-metadata-validation-fix-20260824-r2`
- Image: `sha256:8f009d19a8bfec29736cfb08b1175795aaabdc44449bf298e29d5c8974ed129c`
- Evidence head: `6024e80cb4081579729174a7b1ae9cfe9003e481`

These are separate identities: the source commit identifies runtime code, while the evidence head identifies the final review record. A future merge commit must not replace either value.

## Dependency Map

| PR | Base | Role | Canonical treatment |
|---:|---|---|---|
| 9 | `agent/km-plan-v2.6-anderson` | WP1 reliability implementation and historical closure evidence | Do not merge separately; its ancestry is included in PR #10 |
| 10 | `agent/km-plan-v2.6-anderson` | v2.6 source baseline and WP1 release convergence | First canonical integration layer |
| 11 | `agent/wp1-release-convergence` | Production ingest blocker and CI portability fixes | Integrate after #10 |
| 12 | `agent/wp1-production-fix-review` | Runtime release metadata injection | Integrate after #11 |
| 13 | `agent/wp1-deployment-metadata-fix` | Search 500 fix | Integrate after #12 |
| 14 | `agent/wp1-search-500-fix` | E2E cleanup router and shared-ledger evidence | Integrate after #13 |
| 15 | `agent/wp1-e2e-cleanup-router-fix` | SQLite startup initialization lock | Integrate after #14 |
| 16 | `agent/wp1-job-lease-startup-fix` | Final metadata contract and accepted production evidence | Proposed final canonical head |

PR #16 is a nested chain, so PR #10 through #15 are already represented in its ancestry. PR #9 is also represented through PR #10 and must not be applied a second time.

## Contributions and Superseded Candidates

PR #9 supplies the original JobLease/recovery implementation and shadow evidence. PR #10 adds the v2.6 workbook baseline, release convergence, deployment support and release image gate. PR #11 addresses production attribution blockers and CI fallback. PR #12 adds runtime identity injection. PR #13 fixes the uncaught Search request bug. PR #14 mounts the existing E2E cleanup router. PR #15 serializes SQLite WAL/schema startup. PR #16 establishes the shared RFC3339 metadata contract and records the accepted production deployment.

The older runtime images from PR #10 through #15 are historical evidence only. They are superseded by the accepted PR #16 image; no historical evidence should be deleted or rewritten.

## Proposed Merge Order

After supervisor approval, use `agent/km-plan-v2.6-anderson` as the target and integrate in this order:

1. PR #10 as the release-convergence entry point. This already contains PR #9 ancestry.
2. PR #11.
3. PR #12.
4. PR #13.
5. PR #14.
6. PR #15.
7. PR #16.

Preserve individual code and evidence commits. A squash merge would change commit identities referenced by CI, image and production evidence. If a squash is required for repository policy, create an explicit commit mapping artifact before squashing and retain all original Draft PR links as historical records.

## Post-Merge Gates

After integration, rerun WP0 Contract Baseline, WP1 Job Reliability and weekly/repository hygiene workflows on the exact merged head. Reconfirm `/api/v1/version`, the accepted production image digest, shared ledger configuration, and the production acceptance evidence. The merge commit is an integration identity only; production attribution remains tied to the accepted source/release/image above.

Do not archive or close PR #9～#16 before supervisor Merge Strategy Review. After canonical merge and evidence-link verification, close PR #9 and #11～#16 as superseded historical PRs; retain PR #10 or a final consolidation PR as the canonical delivery record.

## Current Decision

All PR #9～#16 remain **Draft / Open / Unmerged**. No merge, archive, close, force-push or production change was performed by this preparation.
