# WP1 WebSocket Runner Ed25519 Signing Fix Review

- Result: `PASS`
- Scope: isolated localhost runner/test harness only
- Production touched: `false`
- Candidate/application code changed: `false`
- Production Gate: `NO-GO_PENDING_SUPERVISOR_REVIEW`

The runner now performs a local cryptographic preflight before opening a WebSocket. Ed25519 uses `Ed25519PrivateKey.sign(payload)` and Ed25519 verification. RSA uses a separate PKCS#1 v1.5 plus SHA-256 branch. Unsupported key types, invalid or empty keys, and failed local verification stop before network activity.

Validation matrix:

- Ed25519 valid signature: PASS
- Altered payload verification: fail-closed PASS
- Wrong public key verification: fail-closed PASS
- RSA explicit branch: PASS
- Empty key: pre-network fail-closed PASS
- Unsupported EC key: pre-network fail-closed PASS
- Deterministic v3 payload serialization: PASS
- Focused unit tests: 4 PASS

The isolated localhost lifecycle passed in the required order: crypto preflight, `connect.challenge`, signed `req.connect`, `res.connect(id=c1, ok=true)`, `chat.send`, queue/ack/final event, and normal close code `1000`. `chat.send` was sent only after the ready acknowledgment.

Evidence records only key type, payload SHA-256, implementation SHA-256, and redacted frame summaries. No token, signature bytes, private key, public key, message content, or credential material is included.

The exact candidate remains unchanged: source `914d7c829269779f13c47d71ebd27ecb9dde84ec`, release `wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`, image `sha256:54650d64a2867be1ee21bbcb47951d5bc28d85ef76fcac370310b36a9c80bee3`. A new read-only production preflight and supervisor GO are still required before any production retry.
