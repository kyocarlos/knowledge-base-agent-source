# WP1 Canonical Integration Dry-Run

Status: **PASS_NOT_MERGED**

This is a read-only ancestry and repository-tree check. No merge, rebase, squash,
force push, production change, or PR state change was performed.

## Compare

- Target: `agent/km-plan-v2.6-anderson`
- Target SHA: `d29bca3a2d4b58f255f7878ae9d663908270d407`
- Proposed final head: `e47823629e5ec9013fa35f96898191049c943674`
- GitHub compare: `ahead`
- Ahead / behind: `53 / 0`
- Compared commits: `53`
- Changed files: `150`
- Interpretation: the target is an ancestor of the proposed final head; the dry-run
  does not itself authorize or perform the integration.

## Ancestry And Scope

The required PR #9 JobLease contribution and the code contributions from PR #10
through PR #16 are present in the proposed final ancestry. The final tree contains
the Search fix, cleanup router, shared ledger configuration, SQLite startup lock,
release metadata contract/render validation, v2.6 workbook, W34 report, and WP1
closure evidence.

PR #9 is not a separate merge candidate. Its required code is already in the
ancestry and its review/evidence remains a historical record. PR #10 through PR
#16 retain their individual commits; no historical commit is rewritten.

## Production Attribution

The accepted production identity remains separate from the repository integration
identity:

- Production source: `703075efe862736cffe5159edfcb3b1940c5ae09`
- Production release: `wp1-metadata-validation-fix-20260824-r2`
- Production image: `sha256:8f009d19a8bfec29736cfb08b1175795aaabdc44449bf298e29d5c8974ed129c`
- Production evidence head: `6024e80cb4081579729174a7b1ae9cfe9003e481`
- Proposed repository integration head: `e47823629e5ec9013fa35f96898191049c943674`

Superseded runtime identities remain historical evidence only. The dry-run did not
change the active production source or image attribution.

## Conflict And Integration Plan

No merge was performed, so no merge conflict was created. The GitHub comparison
shows the target is an ancestor of the proposed head, and PR #16 was reported
mergeable during inspection. The recommended method is one ancestry-preserving
integration of the proposed final head into `agent/km-plan-v2.6-anderson` after
explicit supervisor approval. Do not perform seven independent merges, squash,
history rewrite, or force push.

After approval, rerun WP0, WP1, weekly/repository checks, read-only portal E2E,
and `/api/v1/version` attribution checks. Keep PR #9 through PR #16 Draft until
the supervisor approves the canonical integration and historical-link plan.

Machine-readable details are in:
`WP1-canonical-integration-dry-run-20260824.json`.
