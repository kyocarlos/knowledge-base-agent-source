# Search Fix Runtime Identity

- Source commit: `cf00ac55fa6aa2e197164eddf9116f812af8e1e2`
- Release ID: `wp1-search-fix-20260822-r1`
- Build timestamp: `2026-08-22T20:00:29+08:00`
- Image: `sha256:d9b21fd0d3c43438ad38b6866d5aef767ae8c2d24b4b24fe05e5588fbff8991a`
- Runtime env mode: `0600`
- Secrets included: `false`

An isolated `/api/v1/version` probe returned HTTP 200 with all four identity
fields equal to the values above. The isolated Search probe returned HTTP 200
with a Celery task ID. Web, search worker, ingest worker and beat were all
running before teardown. Production was not touched.

Full write-enabled smoke remains pending until approved isolated E2E
credentials are available.
