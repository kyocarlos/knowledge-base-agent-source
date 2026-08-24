# WP0 Frontend Static Delivery Fix Evidence

## Scope

This is an independent WP0 fix cycle for the production frontend static mount failure. It does not change WP0 business logic, WP1 logic, production data, or the accepted production identity.

The observed production failure was a read-only nginx mount whose source was an empty temporary directory:

`/tmp/kb-metadata-validation-fix/.frontend-build-runtime-user8 -> /usr/share/nginx/html`

The fix classifies the cause as **D. temporary runtime directory lifecycle** plus **F. deployment override drift**. A bind mount can remain configured while its temporary source is empty or has been cleaned, so copying files once is not a durable deployment contract.

## Contract Change

- nginx uses configurable `KB_FRONTEND_BUILD_DIR` with the persistent project runtime directory as the default.
- Production preflight rejects `/tmp` sources and requires a directory containing `index.html`, `chat.html`, readable files, and at least one asset.
- The validator emits a SHA-256 manifest with file count, asset count, mode, and ownership.
- The same gate runs before Compose rendering, after the frontend build, and after publish before application recreation.
- Disposable isolated validation may opt into a temporary path explicitly with `--allow-temporary`; production calls do not use this flag.
- A failed post-publish validation restores the previous frontend directory and does not recreate containers.

## Isolated Results

- Source commit: `57ec8b176f2428cd0dab5c27f40fc7956a76863d`
- Frontend build: PASS, 17 files / 15 assets
- Nginx read-only static mount: PASS
- `/`: HTTP 200
- `/chat.html`: HTTP 200
- `/upload`: HTTP 200
- `/admin/report-reviews`: HTTP 200
- representative JS/CSS assets: HTTP 200
- missing asset negative check: HTTP 404
- Browser screenshots: `root.png`, `chat-html.png`, `upload.png`, `admin_report-reviews.png`
- Static asset failures: 0
- Fatal static console errors: 0

The browser run used nginx without an application backend. API JSON warnings visible on `chat.html` and `/upload` are therefore recorded as expected backend-absent warnings, not hidden or counted as static delivery success.

WebSocket is not reimplemented in this static-only cycle. The existing application WebSocket gate remains the authoritative runtime check; no production restart or write was performed.

## Safety

`production_touched=false`, `production_deploy=false`, `production_write=false`, `migration_performed=false`, and `secrets_included=false`. WP0 remains **94% Owner Accepted** pending production formal-entry E2E. W34 JSON, weekly report, PPTX, and WP0 completion percentage were intentionally not changed.
