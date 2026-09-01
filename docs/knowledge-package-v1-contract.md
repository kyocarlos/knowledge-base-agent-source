# Knowledge Package v1 Contract

Every processed document revision carries the same identity fields into the
chunk, vector and graph stores:

- `package_schema_version`
- `package_id`
- `document_id`
- `document_version`
- `chunk_id` (the chunk record ID)
- `chunk_index`
- `content_hash`
- `publish_status`
- `is_current`
- source metadata such as `source_path`, `source_name`, `source_system`,
  `run_id`, `artifact_type` and `generated_at`

`package_id` is deterministic for `document_id` plus `document_version`.
`chunk_id` is deterministic for the revision, index and chunk content, so two
versions of one document cannot silently share chunk identity.

## Visibility lifecycle

New revisions start as `draft`. The allowed transitions are:

`draft -> ready -> published -> superseded`

Only `published` and `is_current=true` revisions are visible to the default
search contract. A failed draft must not replace the previously published
revision. The durable registry owns the revision transition; cross-store
readiness and publish atomicity are handled by KM-004.

## Compatibility

Existing legacy records without package fields remain readable during migration
and are treated as already published by compatibility queries. New writes must
carry the full package fields. No production migration is implied by this
source contract.
