# Weekly Progress Validator Governance Fix

The weekly validator still enforces the 100% gate. It now accepts exactly two
auditable delivery contracts:

1. Traditional delivery: `pr`, `tests`, `acceptance`, and `merged=true`.
2. Canonical ancestry delivery: tests and acceptance pass, Production Gate is
   `PASS`, and an integration record proves a completed fast-forward to a named
   target branch and exact target SHA. The compare must be `identical` or
   `equivalent` with `ahead_by=0` and `behind_by=0`, and an evidence path is
   required.

The second contract does not pretend that a historical PR was merged. It records
the canonical target integration separately and preserves the historical PR
state. History rewrite, squash, and missing delivery evidence remain rejected.

W34 WP1 uses the canonical contract with target
`agent/km-plan-v2.6-anderson@e47823629e5ec9013fa35f96898191049c943674` and
evidence `progress/evidence/WP1-canonical-integration-dry-run-20260824.json`.

No production service, data, credential, or WP2 implementation was changed.

Local PPTX validation passed: 161329 bytes, SHA-256
`c35177fc91fbc0b3af0793cde05562943d72fab60b96a4a470229f6f7fef4189`, seven
pages rendered and visually inspected without visible overflow or occlusion.
The GitHub Actions run remains the authoritative downloadable artifact record.
