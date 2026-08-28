# WP1 WebSocket Authentication / Protocol Contract Diagnostic

- Result: `PASS_ISOLATED_PROTOCOL_CONTRACT`; Production Gate remains `NO-GO`.
- Scope: isolated/non-production only; `production_touched=false`; `secrets_included=false`.
- Candidate: source `914d7c829269779f13c47d71ebd27ecb9dde84ec`, release `wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`, image `sha256:54650d64a2867be1ee21bbcb47951d5bc28d85ef76fcac370310b36a9c80bee3`.

## Contract

The candidate proxy accepts an initial browser `auth` frame and forwards the OpenClaw protocol. The gateway protocol then requires `connect.challenge` followed by `req connect` containing the operator token/device authentication. The client must wait for `res` with `id=c1` and `ok=true` before sending `req chat.send` with `sessionKey`, `message`, and `idempotencyKey`.

## Matrix

- Empty token: close `4401`, no ready acknowledgment, no `chat.send`.
- Invalid token: close `4401`, no ready acknowledgment, no `chat.send`.
- Valid temporary identity: ready acknowledgment, `chat.send`, queue/ack, final chat event, normal close `1000`.
- Removed identity: close `4401`, no ready acknowledgment, no `chat.send`.

The deterministic matrix produced `4 PASS`. The exact candidate isolated runner was also rerun with the corrected challenge/connect sequence: handshake, valid authentication, ready acknowledgment, `chat.send`, final event, gateway frame capture, and close `1000` all passed. Payload content and credential material were excluded from evidence.

## Root Cause

`TEST_CLIENT_EXPECTATION_ERROR`: the failed production probe sent an empty token and sent `chat.send` before the OpenClaw `connect` ready acknowledgment. This evidence does not establish a candidate application regression.

The isolated runner now enforces the WebSocket Auth/Protocol hard gate and cannot send `chat.send` until `res(id=c1, ok=true)` is observed. Production retry remains unauthorized pending a new supervisor preflight and GO review.
