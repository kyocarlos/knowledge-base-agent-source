# Synthetic Run ID Audit Note

The isolated run executed on `2026-08-22` used:

`TR-E2E-WP1-FIX-20220822-ababfe786265`

This is a naming typo. The prefix contains `20220822` because the fixture prefix was written with the wrong year literal; it does not represent a different execution date. The original JSON evidence is not modified.

- `actual_execution_date=2026-08-22`
- `run_id_contains_20220822_due_to_naming_typo=true`
- `run_id_was_not_reused=true`
- `original_evidence_unchanged=true`

Future run generation must derive the prefix from the runtime date and validate it before submitting a synthetic job.
