# WP1 Ingress Failure Diagnostic Bundle Review

## Classification

`root_cause_classification = NOT_DETERMINABLE`.

The evidence proves direct backend readiness succeeded while formal ingress did not produce a valid response during the bounded window. It does not, by itself, prove stale DNS, network failure, nginx listener/TLS routing failure, or container lifecycle failure.

## Evidence Bundle

Bundle: `outputs/ingress-failure-diagnostics/20260827-091113/`

It contains the candidate web and nginx container IDs, IPs, networks, Docker DNS capture, nginx-to-web health/version probes, formal ingress headers/bodies, redacted nginx access/error logs, redacted effective nginx configuration, and the readiness timestamps/attempt count. The machine-readable manifest is `manifest.json`.

Readiness used `60` attempts at `2` second intervals for `120` seconds. Direct backend first success was `2026-08-27T01:09:15.109242+00:00`; formal ingress had no successful attempt.

## Safety Result

Capture was read-only and best-effort; capture failure could not block rollback. No synthetic write occurred, the stuck task was not changed, and rollback completed with Health/Celery/queues healthy. No credentials or secrets are included.

Next step is supervisor diagnosis of this bundle. Do not retry deployment, increase timeout as the sole fix, restart nginx for experimentation, or perform production writes before that review.
