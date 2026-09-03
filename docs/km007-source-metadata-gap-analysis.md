# KM007 Reliable Source Metadata Parsing

## Scope

KM007 is the source metadata contract for the existing document-to-chunk,
Neo4j and Qdrant ingestion path. It does not create another ingestion or
revision framework. The canonical v2.6 requirement is to preserve source
identity and fail explicitly when source metadata is malformed.

## Initial gap analysis

| Area | Before KM007 | First increment |
| --- | --- | --- |
| Sidecar path discovery | Duplicated in callers; converted files need an `original/` fallback | Shared `find_source_metadata_path()` |
| JSON loading | `chunker` could raise an unclassified JSON error; ingest/Neo4j callers logged and fell back to defaults | Shared typed `SourceMetadataError` |
| Missing sidecar | Implicit empty metadata and normal fallback identity | Remains backward compatible unless a caller explicitly requires a sidecar |
| Non-object JSON | Not rejected by a shared contract | Explicit fail-closed rejection |
| Runtime status | Existing source paths, no KM007-specific runtime evidence | `IMPLEMENTED` and `INTEGRATED` candidate; real runtime pending |

## Reuse and integration

- Reuses `src/chunker`, `src/ingest`, the existing `.source.json` format and
  existing package identity fields.
- The first increment centralizes path lookup and strict JSON loading in
  `src/source_metadata.py` and integrates it into `chunk_document()`.
- No Production deployment, data migration, reingest, or database mutation is
  part of this increment.

## Validation gate

Focused tests cover valid sibling metadata, converted-file original-sidecar
fallback, malformed JSON, and non-object JSON. The remaining gate is a real
production-compatible runtime using an actual document and the existing
FastAPI/Celery/Qdrant/Neo4j path. It must show valid identity propagation and
an explicit failed ingest for malformed metadata before KM007 can be marked
`RUNTIME_VALIDATED` or `DONE`.
