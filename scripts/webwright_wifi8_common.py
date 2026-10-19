"""Shared helpers for the WiFi workspace Webwright acceptance scripts (scripts/webwright_wifi8_*.py).

Real user flow on the KM entry: login page -> data zone -> WiFi zone -> /wifi8/ SPA.
Passwords come from an accounts file and are never printed; sessions are logged out at the end.

Environment:
  KM_BASE_URL            entry URL (default https://61.216.9.52:3030)
  KM_TEST_ACCOUNTS_FILE  KEY=VALUE accounts file (default ~/.km-control/test-accounts.env)
"""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

BASE = os.getenv("KM_BASE_URL", "https://61.216.9.52:3030").rstrip("/")
ACCOUNTS = Path(os.getenv("KM_TEST_ACCOUNTS_FILE", str(Path.home() / ".km-control/test-accounts.env")))
STATIC_TYPES = {"html": "text/html", "js": "application/javascript", "css": "text/css"}


def path_of(url: str) -> str:
    return urlsplit(url).path


def number(value: Any) -> str:
    """The SPA formats counts with zh-TW thousands separators (31395 -> 31,395)."""
    return f"{int(value or 0):,}"


def secret(key: str) -> str:
    values = dict(line.strip().split("=", 1) for line in ACCOUNTS.read_text(encoding="utf-8").splitlines() if "=" in line)
    return values[key]


class Run:
    """Output directory, step log, screenshots and the final summary of one acceptance run."""

    def __init__(self, run_dir: str | Path, zone: str, user: str):
        self.dir, self.zone, self.user = Path(run_dir), zone, user
        self.shots = self.dir / "screenshots"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.results: dict[str, bool] = {}
        self.console_errors: list[str] = []
        self.failed_requests: list[tuple[int, str]] = []
        self.wifi8_api: list[tuple[int, str, str]] = []
        self.agent_results: list[dict[str, Any]] = []
        self.step = 0
        self._log = (self.dir / "final_script_log.txt").open("w", encoding="utf-8")

    def act(self, pg, key: str, reason: str, ok: Any, target=None) -> bool:
        self.step += 1
        self.results[key] = bool(ok)
        self._log.write(f"step {self.step} action: {reason} => {'PASS' if ok else 'FAIL'}\n")
        self._log.flush()
        shot = self.shots / f"final_execution_{self.step}_{key}.png"
        (target.screenshot(path=str(shot)) if target is not None else pg.screenshot(path=str(shot), full_page=True))
        return bool(ok)

    def finish(self, expected_failures: tuple[tuple[int, str, str], ...] = (), **extra: Any) -> int:
        """expected_failures: (status, method, path) calls the flow makes on purpose (e.g. a rejected upload); they are listed, not counted as errors."""
        failures = [x for x in self.wifi8_api if x[0] >= 400 and x not in expected_failures]
        self.results["api_all_ok"] = not failures
        summary = {"zone": self.zone, "user": self.user, "base_url": BASE, "results": self.results,
                   "wifi8_api_calls": len(self.wifi8_api), "wifi8_api_failures": failures,
                   "expected_failures": [x for x in self.wifi8_api if x in expected_failures],
                   "failed_requests": self.failed_requests, "console_errors": self.console_errors, **extra}
        self._log.write("final: " + json.dumps(summary, ensure_ascii=False) + "\n")
        self._log.close()
        (self.dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if all(self.results.values()) else 1


@contextmanager
def wifi_page(run: Run, *, static_dir: str | Path | None = None, served: list[str] | None = None) -> Iterator[Any]:
    """A logged-out browser page that records console errors, failed requests, WiFi API calls and
    completed agent results. With static_dir, /wifi8/ html/js/css are served from that directory
    (evaluate a frontend before deploying it; the API stays live)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.firefox.launch()
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1400, "height": 1000})
        pg = context.new_page()
        if static_dir:
            root = Path(static_dir)

            def serve(route):
                name = path_of(route.request.url).rsplit("/wifi8/", 1)[1] or "index.html"
                path = root / name
                if not path.is_file():
                    return route.continue_()
                if served is not None:
                    served.append(name)
                route.fulfill(path=str(path), content_type=STATIC_TYPES[name.rsplit(".", 1)[1]] + "; charset=utf-8")
            pg.route(re.compile(r".*/wifi8/([^/?]*\.(html|js|css))?(\?.*)?$"), serve)

        def on_response(response):
            path = path_of(response.url)
            if response.status >= 400:
                run.failed_requests.append((response.status, path))
            if "/api/wifi8/" in path:
                run.wifi8_api.append((response.status, response.request.method, path))
                if path.startswith("/api/wifi8/agent/") and response.request.method == "GET":
                    try:
                        body = response.json()
                    except Exception:  # noqa: BLE001 - non-JSON bodies are simply not agent results
                        body = {}
                    if body.get("status") == "completed":
                        run.agent_results.append(body)
        pg.on("console", lambda m: m.type == "error" and run.console_errors.append(m.text[:160]))
        pg.on("response", on_response)
        try:
            yield pg
        finally:
            try:
                pg.goto(BASE + "/login.html")
                pg.click("#logout", timeout=5000)
            finally:
                browser.close()


def login_to_wifi(pg, zone: str, user: str, pass_key: str) -> None:
    from playwright.sync_api import expect

    pg.goto(BASE + "/login.html")
    pg.fill('input[name="username"]', user)
    pg.fill('input[name="password"]', secret(pass_key))
    pg.click('#credentials button[type="submit"]')
    expect(pg.locator("#instances")).to_be_visible(timeout=15000)
    pg.locator("#instance-buttons button", has_text=zone.upper()).click()
    pg.wait_for_url("**/chat-v2.html**", timeout=30000)
    pg.wait_for_timeout(2000)
    pg.locator('[data-knowledge-zone="wifi"]').first.click()
    pg.wait_for_url("**/wifi8/**", timeout=15000)
    pg.wait_for_timeout(3000)


def overview_counts(pg) -> dict[str, Any]:
    """Counts of the zone's live API, read with the page's own session."""
    data = pg.evaluate("() => fetch('/api/wifi8/overview', {credentials: 'same-origin'}).then(r => r.json())") or {}
    return data.get("counts") or {}


def hybrid_search(pg, query: str) -> None:
    pg.fill("#hybrid-query", query)
    pg.click("#hybrid-submit")
    for _ in range(60):
        pg.wait_for_timeout(500)
        if "正在執行" not in pg.locator("#hybrid-results").inner_text():
            return


def open_agent(pg) -> None:
    pg.locator('#primary-nav a[href="#/ai"]').click()
    pg.wait_for_timeout(1500)


def ask_agent(pg, run: Run, question: str, timeout_seconds: int = 240) -> dict[str, Any]:
    """Ask on the AI Agent page; returns the rendered message and the completed API result (if seen)."""
    seen = len(run.agent_results)
    panels = pg.locator("#conversation .grounding").count()
    pg.fill("#agent-question", question)
    pg.click("#agent-submit")
    for _ in range(timeout_seconds):
        pg.wait_for_timeout(1000)
        if pg.locator("#agent-wait").count() == 0:
            break
    message = pg.locator("#conversation .message").last
    return {"message": message, "answer": message.inner_text(), "classes": message.get_attribute("class") or "",
            "citations": pg.locator(".citation-list").last.locator("li").all_inner_texts() if pg.locator(".citation-list").count() else [],
            "panel": pg.locator("#conversation .grounding").last if pg.locator("#conversation .grounding").count() > panels else None,
            "result": run.agent_results[-1] if len(run.agent_results) > seen else None}
