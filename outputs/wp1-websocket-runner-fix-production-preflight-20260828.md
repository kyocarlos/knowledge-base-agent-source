# WP1 WebSocket Runner Fix Production Preflight Revalidation

**Result:** `PASS_READY_FOR_PRODUCTION_GO_REVIEW`  
**Run ID:** `TR-E2E-WP1-PROD-WS-CRYPTO-PREFLIGHT-20260828-213658-3ee9e169`  
**Production mutation:** false (no deploy, restart, WebSocket session, or write)

## Baseline and rollback

- Baseline Health passed through direct backend and formal ingress; `/api/v1/version` returned HTTP 200. The rolled-back baseline still reports null release metadata, recorded as a baseline observation only.
- WP0/WP1 runtime gates passed. Celery had two nodes; active, reserved, scheduled, and all queues were empty.
- Persistent checkpoint verification passed: `pre-deploy-wp1-lease-current-runtime-20260826-145148`; manifest SHA-256 `1801a67e87c5f1019587052e4b1e4d53f258334c3f806ab829c11ca889c3a4e5`.
- Rollback helper is absolute and executable. Rollback readiness passed and production drift was false.
- Nginx dynamic Docker DNS configuration remains active: approved `nginx.conf` SHA-256 `7696757b4800ec6b8778e17a4fc9222aee2c90242a87a0a7b57b4d18f2e86e93`, resolver `127.0.0.11`, and variable upstream `$web_upstream`.

## Candidate and deployment contract

- Candidate source: `914d7c829269779f13c47d71ebd27ecb9dde84ec`
- Release: `wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`
- Release tag: `kb-wp1-release:wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`
- Exact image ID: `sha256:54650d64a2867be1ee21bbcb47951d5bc28d85ef76fcac370310b36a9c80bee3`
- Build timestamp: `2026-08-26T15:21:36+08:00`
- Image-ID inspection and `restart_kb.sh --deploy-pinned --dry-run` both passed. The dry-run performed no container, image, or worktree mutation.

## Runner and WebSocket hard gates

- The runner revision is isolated-pass commit `920b9ac3aa85f2ac2933256db7adf8207ff3b2ec`; crypto implementation SHA-256 is `eabed02c15d4234e99188e572616aa2132446b19e5a96b186427ac39d926501b` and matched the reviewed source.
- Focused tests passed: 4 WebSocket crypto tests plus 11 run-ID/acceptance-hard-gate tests.
- The fresh run ID passed the complete production evidence-root uniqueness scan. A disposable `/tmp` fixture passed manifest, attachment, multipart header, idempotency, and cleanup-scope equality checks.
- A read-only, sanitized runtime crypto probe confirmed token source presence, Ed25519 key type, deterministic payload serialization, and local sign/verify. It did not create a WebSocket session or disclose credential material.
- The runner hard gate requires local crypto preflight before any session and requires `res(id=c1, ok=true)` before `chat.send`. Failure-window persistence is ready; capture failure is tested not to block rollback.

## Decision

All approved read-only gates passed. Production Gate remains `NO-GO_PENDING_SUPERVISOR_PRODUCTION_GO`; this evidence requests the next Production GO review and does not authorize deployment.
