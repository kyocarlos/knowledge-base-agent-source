# WP1 Deployment Readiness Probe False-Negative Remediation Review

## Scope

Canonical integration is limited to `scripts/check_deployment_readiness.py`, `tests/test_deployment_readiness.py`, and this focused evidence record. No nginx remediation history or old failure bundle was reintroduced.

## Root Cause

`READINESS_PROBE_FALSE_NEGATIVE / READINESS_OBSERVATION_MISMATCH`: the formal ingress uses a deployment-managed HTTPS certificate, while the checker did not use the equivalent controlled `curl -k` TLS behavior. A valid HTTPS response could therefore be recorded as `status=0`.

## Contract Preserved

- HTTP status extraction remains explicit.
- JSON parsing remains required.
- Exact source/release/image/build metadata matching remains fail-closed.
- Earlier failed attempts do not overwrite a later successful attempt.
- The final successful attempt and `first_success_at.ingress` are written to evidence.

## Validation

- Readiness regression tests: **3 passed**
- Python compile: **PASS**
- `git diff --check`: **PASS**
- Production mutation: **NONE**
