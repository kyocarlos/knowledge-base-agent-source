# WP1 Nginx Dynamic Upstream Resolution Remediation Review

## Root Cause

`STALE_NGINX_UPSTREAM_RESOLUTION` was confirmed. The prior `proxy_pass http://web:8000` configuration retained the old resolved address after the web container was force-recreated.

## Remediation

The nginx `http` block now uses Docker's embedded resolver `127.0.0.11` with `valid=5s`. Proxy locations use a runtime variable (`$web_upstream`) so hostname resolution can refresh without nginx restart/reload. The `/ws` proxy location is included and preserves its `/ws` upstream path.

No application business logic changed and production nginx was not restarted or reloaded.

## Isolated A/B Validation

Using nginx `1.31.0` and a disposable Compose network:

- Initial web IP A: `172.24.0.2`; `/health` returned `backend=A`.
- Only the isolated web container was replaced; nginx was not restarted/reloaded.
- New web IP B: `172.24.0.4`; Docker DNS resolved `web` to B.
- `/health` through the unchanged nginx process returned `backend=B`.
- Old IP A was not used after replacement.
- nginx config syntax: PASS.
- Proxied route probes for `/health`, `/api/test`, `/search`, `/tasks/test`, and `/ws`: HTTP 200.

The static mock backend does not implement a real WebSocket handshake, so protocol lifecycle is recorded as `NOT_RUN_WITH_STATIC_MOCK_BACKEND`; the production WebSocket lifecycle remains a separate acceptance check.

## Safety

The isolated stack was removed after testing. No production deployment, nginx restart/reload, synthetic write, stuck-task mutation, Redis/ledger mutation, migration, restore, WP2 change, or real instrument operation occurred. No secrets are included.
