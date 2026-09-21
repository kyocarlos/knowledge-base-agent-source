# KM canonical Knowledge Package v1

This is a KM-side implementation contract, not a CSIT business approval
contract. `schema=ai_km_knowledge_v1` is the only package shape accepted by the
formal vector-ingest boundary.

Required fields:

- `document_id` and `version`: logical identity; filename is display metadata only.
- `metadata`: source, ACL/provenance, parser and lifecycle metadata.
- `chunks`: non-empty content items with stable `chunk_id` and `source_locator`.
- `nodes` and `relationships`: graph material (possibly empty for a document).
- `publish_status`: `draft`, `published`, or `superseded`.

Missing fields, empty chunks, duplicate chunk IDs, or unsupported lifecycle
values fail closed. When a chunk ID is absent, KM derives it from
`document_id + version + source_locator + content`; rerunning the same package
therefore remains idempotent and is independent of the filename.

New Qdrant writes are draft/non-current by default. Search must continue to
filter both top-level and nested lifecycle fields. A technical publication
caller must stage Qdrant and Neo4j writes, validate both, then commit the
version; on failure it must rollback staging and leave the previous Current
version untouched. Cross-system CSIT Published remains a separate business
state and is not inferred from KM technical completion.

Implementation: `src/knowledge_package.py`, `src/lifecycle.py`, and the
receiver/pipeline adapters. The parser registry additionally records
`parser_name`, `parser_version`, and rejects known binary signature/extension
mismatches before conversion.
