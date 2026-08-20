# WP1 Backup/Restore Shadow Evidence

## Result

**PASS for isolated filesystem backup/restore; not a production recovery claim.**

The repository backup bundle script was executed against a temporary shadow
project containing synthetic data and configuration. The bundle and manifest
were created, the source data was removed, the archive was extracted to a
separate restore directory, and the scoped source/restore tree hashes matched.

## Evidence

- Date: 2026-08-20 Asia/Taipei
- Mode: `isolated-shadow`
- Synthetic source only; no production path or database was opened
- Bundle SHA-256: `f7ea184678405bceb53009bdc3a4f656819ddefbbcada3921771ef0b1d24836a`
- Restored tree hash matched the source tree hash
- Temporary project and restore directories were removed automatically
- Evidence SHA-256: `46af1131c909f0c1f030dd0da6bed1e7574bb335dd28055a9da4f345e84ac1c4`

Full machine-readable evidence:
`outputs/backup-restore-shadow-20260820.json`

## Scope and limits

This validates filesystem bundle creation and restoration only. It does not
validate Redis reconnect/idempotency, Neo4j/Qdrant live restore, production
backup retention, or a formal deployment rollback. Those remain separate gates.
