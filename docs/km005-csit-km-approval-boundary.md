# KM005 CSIT / KM Approval Ownership Boundary

## Decision

CSIT is the business approval system of record. KM validates the received
package, records indexing status, and executes the existing
`Upload -> Review -> Ingest` pipeline. KM does not create or overwrite the
CSIT business decision.

The existing WP1 report API remains the only ingestion path. A CSIT-compatible
request may attach these headers to `POST /api/agent/v1/reports`:

| Header | Meaning |
| --- | --- |
| `X-CSIT-Source-Record-ID` | CSIT canonical record identifier |
| `X-CSIT-Approval-Status` | `pending`, `approved`, or `rejected` |
| `X-CSIT-Revision` | CSIT report revision |
| `X-CSIT-Correlation-ID` | CSIT-to-KM trace identifier |

The same fields may be supplied in the report manifest under `csit`. If any
CSIT field is supplied, all four fields are required and the values are
validated before the file is registered. The sanitized values are persisted
in the KM submission registry and returned by the existing review API.

## Boundary rules

- `rejected` or `pending` CSIT state cannot enter KM indexing through the KM
  approve endpoint.
- `approved` CSIT state may enter the existing KM validation/review step; KM
  records this separately as `km_validation_status=validated`.
- Only the existing approved/queued/completed ingest path writes the knowledge
  indexes. No second CSIT ingestion or approval registry is created.
- Default Search continues to use the existing published/current filters.
- Requests without CSIT headers remain compatible with the existing WP1
  reviewer-controlled flow while the external CSIT adapter is being deployed.

## Runtime validation contract

The KM005 isolated runtime review must use real FastAPI, Celery, Redis,
PostgreSQL registry, Qdrant, Neo4j, and Search services. It must demonstrate:

1. CSIT-approved upload is registered with the four CSIT fields.
2. CSIT-rejected upload is not indexed or visible to default Search.
3. CSIT-approved upload completes through the existing reviewer and ingest
   path and becomes searchable.
4. CSIT and KM statuses remain separately traceable by submission and
   correlation identifiers.
5. WP1 health, upload, review, and ingest behavior remains available.

The shared Main User Entry Baseline is reused for browser mechanics; KM005
only validates the CSIT ownership behavior specific to this change.
