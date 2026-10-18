# KM 3030 Control Login Cutover Runbook

## Preconditions

1. Distribute the current `/home/da40_ai_gb10/nginx_certs/cert.pem` to managed client trust stores. The exact self-signed certificate is accepted for this deployment; do not distribute `key.pem`.
2. Create a protected, Git-ignored environment file from `deploy/legacy-test/control-3030.env.example`; generate distinct Control DB, Control session, and Test entry-session secrets.
3. Execute the existing maintenance checkpoint procedure and confirm the Test baseline manifest before any container or Nginx change.

## Shadow validation

1. Start `deploy/legacy-test/docker-compose.control-auth.yml` with no published port.
2. Attach only a disposable Test web/Nginx shadow stack to `km-control-private`; configure `KM_INSTANCE_ID=test`, `KM_REDIS_KEY_PREFIX=km:test:`, `KM_CONTROL_DB_URL`, `KM_ENTRY_SESSION_SIGNING_KEY`, and `KM_CONTROL_PUBLIC_ORIGIN`.
3. Use `deploy/legacy-test/nginx.3030-login-gateway.conf` only in the shadow gateway. It mounts the existing cert/key directory read-only, exposes `/login.html` and `/_control/api/`, and keeps Control DB/Auth private.
4. Run the authentication, WebSocket, revocation, query, and rollback tests. Stop if the browser does not trust the exact deployed self-signed certificate.

## Controlled cutover

1. Drain jobs and enter maintenance. Capture the Nginx configuration/static runtime, web image ID, container inspect, source revision, Test statistics, and file manifest in an immutable checkpoint.
2. Start the independent Control DB/Auth. Run `scripts/km_control_admin.py --username <approved-admin>` in `control_auth`, supplying the password only through its interactive standard input. A second bootstrap administrator is refused.
3. Apply the Test web environment and attach only `kb-web` and `kb-nginx` to `km-control-private` through reviewed Compose configuration; never recreate Neo4j, Qdrant, TimescaleDB, report registry, Redis, or Test data volumes.
4. Copy `frontend/login.html` and `frontend/control-admin.html` to the existing static runtime. Confirm the 3030 Nginx mounts `/home/da40_ai_gb10/nginx_certs` read-only, then replace the Nginx configuration only after `nginx -t` succeeds and reload Nginx.
5. On any failure, restore the checkpointed Nginx/static runtime and prior web image/configuration. Do not restore or alter Test data stores.

## Acceptance cases

- Anonymous `/`, `chat.html`, and `chat-v2.html` redirect to `/login.html`; direct data API, task, download, and WebSocket calls are unauthorized.
- A new registration is pending and cannot select Test. The bootstrap administrator activates it and grants Test; the user selects Test, completes callback, queries KM, and receives a WebSocket response.
- Replayed/expired callback codes, deleted entry cookie, a tampered token, revoked Test grant, and disabled user fail closed. DA40/RD2 grant and selection fail validation.
- Test baseline counts/checksums match the checkpoint before and after cutover. The live certificate fingerprint equals the local `cert.pem`, SAN contains `61.216.9.52`, browser trust succeeds, Control health, Test health, and rollback drill pass.
