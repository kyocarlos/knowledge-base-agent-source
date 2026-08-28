# WP1 Production Ingress Upstream Resolution Review

## Read-only findings

Current `kb-nginx` and `kb-web` both belong to Compose project `knowledge-base` and share `knowledge-base_default`. Current nginx IP is `172.20.0.9`; current web IP is `172.20.0.6`. Nginx configuration uses `proxy_pass http://web:8000` for `/api/` and `/health`, with no pinned web IP.

From inside nginx, Docker DNS resolves `web` to `172.20.0.6`, and direct upstream `/health` and `/api/v1/version` both return HTTP 200. Current formal ingress `/health` also returns HTTP 200.

## Failure-window limits

During the candidate attempt, direct backend readiness passed but formal ingress had no valid response for 60 attempts over 120 seconds. The rollback procedure recreated nginx, so the original failure-window nginx logs were not retained. The candidate web IP and rollback-baseline web IP are not available in retained evidence. Therefore stale upstream IP/hostname resolution is **not confirmed** and the root cause is **NOT_DETERMINABLE** from current evidence.

## Deterministic next design

Before any future retry, the procedure must capture nginx DNS resolution, nginx-to-web connectivity, nginx access/error logs, web IP, and container/network identity during the recreate window, and preserve those records before rollback. No nginx restart, timeout increase, production retry, application change, or data mutation is authorized by this diagnosis.

Machine-readable evidence: `outputs/wp1-production-ingress-upstream-diagnosis-20260826.json`.
