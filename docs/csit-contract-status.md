# CSIT contract status

- `contracts/csit-km-integration-v1/` and `src/csit_integration_v1/` are the **CURRENT CSIT INTEGRATION V1** contract and implementation. The four vendored schemas are byte-for-byte pinned to CSIT-System commit `3a9ae52f04625aeee5fd01e7a3565f5972fc9122`; `UPSTREAM.json` records the pin and SHA-256 values. `scripts/check-csit-contract-sync.py` checks the exact commit on every CI gate.
- `config/csit_km_v1_contract.json`, `src/csit/`, `tests/test_csit_*.py`, and `.github/workflows/csit-km-manifest.yml` belong to the **LEGACY MANIFEST CONTRACT** and continue to serve that legacy integration. They are not authorities for current Integration v1 schemas or tests.

Current Integration v1 tests must load the vendored canonical JSON Schemas. They must not derive wire-contract expectations from the legacy JSON config or legacy manifest adapter.

KM DEV rollout, CI result, runtime identity, migration and offline verification are recorded in [the 2026-10-14 adoption evidence](handoff/CSIT_CANONICAL_ADOPTION_20261014.md). Integration remains disabled pending a clean Live E2E.
