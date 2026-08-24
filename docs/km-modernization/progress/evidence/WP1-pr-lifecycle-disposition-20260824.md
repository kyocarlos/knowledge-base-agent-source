# WP1 PR Lifecycle Disposition Plan

## Status

This is a proposal for supervisor approval. It does not close, merge, delete, or
rewrite any pull request or branch.

Canonical repository target:

- Branch: `agent/km-plan-v2.6-anderson`
- Integrated SHA: `e47823629e5ec9013fa35f96898191049c943674`
- WP1 status: `100% FINAL CLOSED`
- Production Gate: `PASS`

Accepted production attribution remains separate from repository integration:

- Source: `703075efe862736cffe5159edfcb3b1940c5ae09`
- Release: `wp1-metadata-validation-fix-20260824-r2`
- Image: `sha256:8f009d19a8bfec29736cfb08b1175795aaabdc44449bf298e29d5c8974ed129c`
- Production evidence: `6024e80cb4081579729174a7b1ae9cfe9003e481`

## Current GitHub Disposition

| PR | Current state | Role | Proposed disposition after supervisor approval |
|---|---|---|---|
| #9 | Merged, Draft flag retained by GitHub | Original WP1 reliability closure and historical evidence | Retain merged record; do not reopen or rewrite |
| #10 | Merged, Draft flag retained by GitHub | Release convergence and v2.6 baseline integration | Retain merged record; do not reopen or rewrite |
| #11 | Open, Draft | Blocker-fix historical evidence: startup/ledger fixes | Close as superseded, preserve branch and evidence |
| #12 | Open, Draft | Deployment metadata historical evidence | Close as superseded, preserve branch and evidence |
| #13 | Open, Draft | Search 500 diagnosis/fix historical evidence | Close as superseded, preserve branch and evidence |
| #14 | Open, Draft | Cleanup router and isolated acceptance evidence | Close as superseded, preserve branch and evidence |
| #15 | Open, Draft | SQLite startup race fix historical evidence | Close as superseded, preserve branch and evidence |
| #16 | Open, Draft | Metadata validation and production acceptance evidence | Close as superseded, preserve branch and evidence |
| #17 | Open, Draft | Weekly validator governance delivery record | Keep open until governance record is accepted; then close only if requested |

The current states were read from GitHub on 2026-08-24. No lifecycle mutation is
part of this plan.

## Evidence Preservation Rules

1. Do not delete historical branches, commits, PR conversations, CI runs, or
   artifacts.
2. Keep each PR URL and its evidence paths in the repository history.
3. Do not replace historical source, evidence, or production identities with the
   canonical repository integration SHA.
4. Do not describe PR #11--#16 as individually merged. Their reviewed commits
   are preserved through the canonical ancestry and the production attribution
   record.
5. Keep PR #9 and #10 as GitHub ancestry-recognized merged records; no reopen,
   revert, or second merge is required.
6. Retain PR #17 as the weekly validator governance delivery record until the
   supervisor explicitly approves its lifecycle disposition.

## Proposed Post-Approval Actions

After supervisor approval only:

1. Leave #9 and #10 unchanged.
2. Close #11--#16 with a short comment stating `superseded by canonical
   ancestry integration at e47823629e5ec9013fa35f96898191049c943674`; do not
   delete their branches.
3. Preserve each PR's final review, CI, evidence, and production-attribution
   links in the PR conversation and repository evidence index.
4. Leave #17 open until the weekly governance record is accepted; then close it
   as the delivery record only if the supervisor requests closure.
5. Do not mark a PR Ready merely to make lifecycle status look complete.

## Verification Checklist

- [x] Canonical target and integrated SHA recorded.
- [x] #9/#10 ancestry-recognized merged state recorded.
- [x] #11--#16 open Draft historical chain recorded.
- [x] #17 open Draft governance record recorded.
- [x] Production identity attribution kept separate.
- [x] Evidence preservation and no-delete rules recorded.
- [ ] Supervisor approves lifecycle disposition.
- [ ] Approved post-review close comments, if requested, are executed.

## Explicit Non-Scope

- No production changes.
- No WP1 code changes.
- No WP2 implementation or prerequisite execution.
- No merge, close, branch deletion, force push, rebase, squash, or history rewrite
  in this plan.
