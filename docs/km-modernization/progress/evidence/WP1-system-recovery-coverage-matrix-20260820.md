# WP1 System Recovery Coverage Matrix

## Decision

**Overall status: PENDING.** This matrix separates the filesystem shadow PASS
from the remaining system recovery areas. It does not claim that a filesystem
restore is a complete KM system restore.

| Component | Status | Reason | Evidence |
|---|---|---|---|
| filesystem/data | PASS | Synthetic backup bundle restored with matching scoped source/restored hashes. | `outputs/backup-restore-shadow-20260820.json` |
| application registry/database | PENDING | Application lease and business idempotency passed in shadow, but deployed application registry/database restore was not tested. | `outputs/wp1-application-idempotency-shadow-20260820/application-idempotency-shadow-20260820.json` |
| Neo4j | PENDING | No isolated Neo4j backup/restore or consistency evidence in this closure stage. | None |
| Qdrant | PENDING | No isolated Qdrant snapshot/restore or point/payload consistency evidence in this closure stage. | None |
| Redis | PENDING | Restart and `SETNX` shadow passed, but persistence restore and production recovery were not tested. | `outputs/redis-reconnect-idempotency-shadow-20260820.json` |
| configuration | PENDING | Synthetic `config/config.yaml` was in the filesystem bundle, but runtime config, secret references and deployment pin restore were not independently validated. | `outputs/backup-restore-shadow-20260820.json` |

## Evidence rules

- `PASS` means the named component's stated recovery behavior was directly
  exercised in an isolated shadow and has machine-readable evidence.
- `PENDING` means the evidence is absent or only covers a narrower behavior.
- No item is promoted to `PASS` from code presence or from another component's
  evidence.

## Safety boundary

`production_gate=NO-GO`. This matrix does not authorize production writes,
migrations, credential bypass, deployment, or live database restore. The
pending items require separately approved, isolated validation windows.

Machine-readable source:
`outputs/wp1-system-recovery-coverage-matrix-20260820.json`
