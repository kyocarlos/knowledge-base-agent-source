# Search 500 Diagnosis

## Classification

`C — existing Search bug previously uncaught`

The metadata injection in PR #12 is not the cause. The failing candidate
`9e610ed1643dd0489511cfaf5f918522c8c25b82` raises an `AttributeError` before
Celery submission:

```text
AttributeError: 'SearchRequest' object has no attribute 'headers'
```

The `/search` handler used its Pydantic body parameter named `request` to read
`request.headers`. The fix adds a separate FastAPI `Request` parameter and
reads the trace header from that object.

## Evidence

- Failing endpoint: `POST /search`
- Failing status: HTTP 500
- Failing source: `9e610ed1643dd0489511cfaf5f918522c8c25b82`
- Failing image: `sha256:71c8a464da334098a87de25afd517dbf4bc125511c11f7d58d708ede635cb805`
- Redis and Qdrant started normally; the web exception occurred before a
  Celery task was submitted.

The same faulty handler shape is present in the prior `12328e19...` source
lineage, so this is not introduced by the PR #12 metadata change.

## Fix Candidate

- Branch: `agent/wp1-search-500-fix`
- Source: `cf00ac55fa6aa2e197164eddf9116f812af8e1e2`
- Release: `wp1-search-fix-20260822-r1`
- Image: `sha256:d9b21fd0d3c43438ad38b6866d5aef767ae8c2d24b4b24fe05e5588fbff8991a`
- Search rerun: HTTP 200 with task ID
- Web/search/ingest/beat: running in isolated smoke

The isolated Search rerun passed. Full Report API, Upload/Ingest, Review,
idempotency and cleanup smoke remains pending because this diagnosis run did
not use write-enabled E2E credentials. Production remains untouched and
`NO-GO`.
