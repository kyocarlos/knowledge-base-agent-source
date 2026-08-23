# Temporary Production E2E Agent Provisioning Shadow Review

Date: 2026-08-23 (Asia/Taipei)

## Current Auth Design

Regular agent authentication loads `KB_AGENT_TOKEN_HASHES_JSON`. Report
self-read uses this regular registry; it does not use the E2E-only registry.
The current production registry contained two entries. Their values were not
written to evidence.

## Additive Procedure

1. Read the current regular JSON registry in a protected operator shell.
2. Generate a single-use synthetic identity and token outside the repository.
3. Merge only the synthetic identity into a new temporary JSON object. Never
   replace or edit the original registry.
4. Write a temporary runtime env file with mode `0600`, containing the merged
   registry. Do not commit or log its contents.
5. Use an ephemeral Compose override and controlled application-service restart
   to inject the merged value. Keep the approved candidate image unchanged.
6. Run the controlled synthetic acceptance within the approved run-id prefix.
7. Remove the temporary env/override and recreate the affected service(s) with
   the original registry value.
8. Re-test the temporary identity; it must receive HTTP 401/403. Confirm the
   original registry and service health remain intact.

## Shadow Result

The shadow test passed:

- additive merge: PASS
- existing registry preserved: PASS, 2 entries retained
- temporary identity authenticates while provisioned: PASS
- temporary identity rejected after removal: PASS
- temporary env mode: `0600`
- secrets in evidence: false
- migration/WP2/real instrument: not used
- rollback safe: PASS

No production provisioning or deployment was performed in this shadow step.

## Gate

Production Gate remains `NO-GO`. A production retry requires separate approval
for this temporary additive provisioning procedure and its time-bounded removal
verification.
