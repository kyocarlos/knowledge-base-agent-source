#!/usr/bin/env python3
"""Read-only Firefox E2E evidence runner for the WP0 portal boundary.

Webwright is the preferred runtime, but this repository currently uses the
explicit Playwright/Firefox fallback because the Webwright runtime is not
available in the execution environment.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

BASE_URL = os.environ.get("BASE_URL", "https://61.216.9.52:3030").rstrip("/")
OUT = Path(os.environ.get("E2E_ARTIFACT_DIR", ".e2e-artifacts"))
OUT.mkdir(parents=True, exist_ok=True)
SCREENSHOTS = OUT / "screenshots"
SCREENSHOTS.mkdir(parents=True, exist_ok=True)

actions: list[dict[str, str]] = []
network: list[dict[str, str]] = []
console: list[dict[str, str]] = []
failures: list[str] = []
websocket_events: list[dict[str, str]] = []


def action(area: str, outcome: str, reason: str = "") -> None:
    item = {"area": area, "outcome": outcome}
    if reason:
        item["reason"] = reason
    actions.append(item)


def safe_category(url: str) -> str:
    path = urlparse(url).path
    known = {
        "/api/v1/health": "health",
        "/api/v1/health/live": "health_live",
        "/api/v1/health/ready": "health_ready",
        "/api/v1/version": "version",
        "/chat.html": "chat",
        "/": "search",
        "/upload": "upload",
        "/admin/report-reviews": "report_review",
    }
    return known.get(path, "other")


def status_class(status: int | None) -> str:
    if status is None:
        return "no_status"
    return f"{status // 100}xx"


def attach_observers(page: Page) -> None:
    def on_response(response) -> None:
        network.append(
            {
                "method": response.request.method,
                "route": safe_category(response.url),
                "status_class": status_class(response.status),
            }
        )

    def on_console(message) -> None:
        console.append({"level": message.type})

    def on_page_error(_error) -> None:
        console.append({"level": "pageerror"})

    def on_websocket(socket) -> None:
        category = safe_category(socket.url)
        websocket_events.append({"event": "created", "route": category})
        socket.on("close", lambda: websocket_events.append({"event": "closed", "route": category}))
        socket.on("socketerror", lambda _error: websocket_events.append({"event": "error", "route": category}))

    page.on("response", on_response)
    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("websocket", on_websocket)


def redact_page_for_screenshot(page: Page) -> None:
    # The screenshot must not contain production text, filenames, report data,
    # tokens, or query content. Replace the rendered document client-side with
    # a neutral route marker after the real route has loaded.
    page.evaluate(
        """() => {
          document.body.innerHTML = '<main style="font:16px sans-serif;padding:48px">'
            + '<h1>WP0 E2E evidence</h1><p>Route loaded; content redacted.</p></main>';
          document.body.style.background = '#ffffff';
        }"""
    )


def open_route(page: Page, label: str, path: str) -> None:
    try:
        page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded", timeout=30000)
        redact_page_for_screenshot(page)
        page.screenshot(path=str(SCREENSHOTS / f"{label}.png"), animations="disabled")
        action(label, "PASS")
    except PlaywrightError:
        action(label, "FAIL", "browser navigation or screenshot failed")
        failures.append(label)


def main() -> int:
    try:
        with sync_playwright() as playwright:
            request = playwright.request.new_context(ignore_https_errors=True)
            for label, endpoint in (
                ("health", "/api/v1/health"),
                ("version", "/api/v1/version"),
            ):
                try:
                    response = request.get(f"{BASE_URL}{endpoint}", timeout=30000)
                    network.append(
                        {
                            "method": "GET",
                            "route": label,
                            "status_class": status_class(response.status),
                        }
                    )
                    if response.status >= 400:
                        action(label, "FAIL", "HTTP status was not successful")
                        failures.append(label)
                    else:
                        action(label, "PASS")
                    response.dispose()
                except Exception:
                    action(label, "FAIL", "GET could not be completed")
                    failures.append(label)
            request.dispose()

            page = playwright.firefox.launch(
                headless=True,
                args=["--ignore-certificate-errors"],
            ).new_page()
            attach_observers(page)

            open_route(page, "chat", "/chat.html")
            if not websocket_events:
                action("websocket", "SKIP", "no lifecycle event observed without sending payload")
            else:
                action("websocket", "PASS", "lifecycle metadata only; payloads not recorded")

            open_route(page, "search", "/")
            action("chat_submit", "SKIP", "production-safe synthetic submit fixture not provided")
            action("search_submit", "SKIP", "production-safe synthetic submit fixture not provided")
            open_route(page, "upload", "/upload")
            action("upload_ingest", "SKIP_WRITE_PATH", "no disposable fixture and cleanup contract")
            open_route(page, "report_review", "/admin/report-reviews")
            action("report_decision", "SKIP_WRITE_PATH", "no scoped fixture token; approve/reject forbidden")
            page.context.browser.close()
    except Exception:
        action("browser_runtime", "FAIL", "Firefox/Playwright runtime could not start")
        failures.append("browser_runtime")
    finally:
        (OUT / "action.log").write_text(
            "\n".join(
                f"{item['area']} {item['outcome']}"
                + (f" ({item['reason']})" if item.get("reason") else "")
                for item in actions
            )
            + "\n",
            encoding="utf-8",
        )
        (OUT / "network-summary.json").write_text(
            json.dumps(network, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (OUT / "console-summary.json").write_text(
            json.dumps(console, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (OUT / "result.json").write_text(
            json.dumps(
                {
                    "gate_status": "FAIL" if failures else "PASS",
                    "failure_areas": failures,
                    "websocket_events": websocket_events,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
