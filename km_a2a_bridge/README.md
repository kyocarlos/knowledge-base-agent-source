# KM A2A Delegation Bridge

This is an isolated, default-disabled control-plane service for KM-initiated A2A test delegation.
The default transport is the in-process mock. The optional SDK mode is dry-run only; neither mode uploads
Excel or intentionally acquires an instrument lock.

## Run the mock phase

Create a dedicated virtual environment and install `requirements.txt`. Generate separate control and
remote-agent credentials; never reuse the existing KM ingest token. Store only the control token SHA-256
in `KM_A2A_CONTROL_TOKEN_SHA256`.

```bash
uvicorn km_a2a_bridge.app:create_app --factory --host 127.0.0.1 --port 18181
```

`GET /health` is unauthenticated and reports `real_instrument_access: false`. `POST /v1/tasks` and task
lookup require the bridge control Bearer token. Jobs must use an allowlisted profile. The bridge records
`context_id`, `a2a_task_id`, `run_id`, `ingest_task_id` and independent test/report/ingest status in its
own SQLite journal.

`KM_A2A_AGENT_ENDPOINTS` contains discovery base URLs such as `https://anritsu.example`. The bridge
loads `/.well-known/agent-card.json`; the Agent Card selects the actual JSON-RPC `/a2a` interface.

Do not add this service to the production KM Compose or expose it through Nginx until mock and dry-run
acceptance tests pass and the main Agent approves the Anritsu endpoint, Agent Card and A2A credential.

## SDK wire dry-run

`KM_A2A_TRANSPORT=sdk-dry-run` enables the official A2A SDK client, but every outbound job still contains
`dry_run: true`. The discovery URL must be an HTTPS origin without a path. The returned Agent Card must
advertise A2A 1.x JSON-RPC and `run_iperf_test`; its interface URL must remain on the same origin so the
outbound Bearer credential cannot be redirected to another host. Do not use this mode with a real instrument
executor until the remote agent proves that `dry_run: true` cannot acquire the instrument lock.
