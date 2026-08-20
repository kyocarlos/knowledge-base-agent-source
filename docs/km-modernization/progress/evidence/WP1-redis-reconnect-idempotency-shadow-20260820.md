# WP1 Redis Reconnect/Idempotency Shadow Evidence

## Result

**PASS for isolated Redis reconnect and SETNX idempotency behavior.**

The drill started a temporary Redis 7 container, wrote a scoped synthetic
idempotency key with `SET NX`, restarted the same container, verified the key
and value remained available, and confirmed a duplicate `SET NX` did not
overwrite the original value. The container was forcibly removed at cleanup.

## Evidence

- Date: 2026-08-20 Asia/Taipei
- Mode: `isolated-shadow`
- Initial Redis ping: pass
- Post-restart Redis ping: pass
- Original value after restart: `accepted`
- Duplicate `SET NX`: rejected
- Cleanup assertion: pass
- Evidence SHA-256: `cd6324c8cf5191c2770e02f7991c400e5fe64ba772ba90d46b0d8160bdae086e`

Full machine-readable evidence:
`outputs/redis-reconnect-idempotency-shadow-20260820.json`

## Scope and limits

This validates Redis process restart and a scoped key-level idempotency
primitive in isolation. It does not claim production Celery failover,
multi-worker race testing, or formal report-submission database idempotency;
those remain covered by separate application tests and later acceptance gates.
