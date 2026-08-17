# WP0 Webwright E2E boundary

This is a de-identified test design for the formal portal entrypoint:

`https://61.216.9.52:3030/chat.html`

The workflow must not send credentials, upload business files, approve/reject reports, clear logs/cache, change scheduler settings, or expose response bodies. Action logs and summaries must contain only route names, selector labels, HTTP status classes, and pass/skip/fail outcomes.

## Route and selector inventory

| Area | Entry / selector evidence | Safe read-only scope |
| --- | --- | --- |
| Health / Version | `/api/v1/health`, `/api/v1/health/live`, `/api/v1/health/ready`, `/api/v1/version` | GET only; assert status/envelope/trace shape without logging values |
| Chat | `chat.html`, `.chat-fab`, `.chat-window`, `.chat-input` | Open/close UI and observe WebSocket lifecycle only; do not send a prompt unless a disposable test backend is provided |
| Search | Vue route `/`, textarea, `.search-btn`, mode buttons | No safe fixture is currently declared; do not submit a query to the production portal |
| Upload / Ingest | Vue route `/upload`, file input, `.upload-submit-btn` | FAIL CLOSED: upload and ingest mutate business data; requires a disposable fixture, isolated target, and cleanup contract |
| Report Review | Vue route `/admin/report-reviews`, Reviewer Token input, refresh button | FAIL CLOSED: requires a valid token and report fixture; approve/reject are state mutations |
| WebSocket | `chat.html` chat runtime | Observe connection/error/close event metadata only; no message content or token capture |

Selectors are intentionally limited to stable class names and visible labels already present in the branch. No selector should capture rendered content, filenames, tokens, report IDs, or query text.

## Fixture and cleanup requirements

The current repository does not declare a disposable production-portal fixture. Therefore Upload/Ingest and Report Review are skipped, not attempted, until all of the following are supplied:

1. An isolated test tenant or disposable backend.
2. A de-identified fixture with a non-sensitive filename and contents.
3. An explicit cleanup endpoint or documented teardown procedure.
4. A test reviewer credential scoped only to the fixture.
5. Confirmation that the target is not the production business dataset.

A failed precondition must produce a redacted `SKIP_WRITE_PATH` result and exit successfully for the read-only audit job; it must never click upload, approve, reject, clear, or scheduler controls.

## Artifact contract

A future `workflow_dispatch` E2E job may publish only:

- `action.log`: timestamps, route labels, selector labels, and outcomes;
- screenshots with sensitive text regions masked or omitted;
- `network-summary.json`: request method, route category, status class, and failure category;
- `console-summary.json`: console level and redacted message category.

It must not publish request/response bodies, headers, cookies, authorization values, query text, rendered report contents, filenames, task IDs, or raw URLs containing identifiers.

## Current blocker

The connected browser runner cannot start because the Chromium distribution is unavailable. No E2E success is claimed, and no write-capable E2E workflow is added until a browser runtime and disposable fixture are available.
