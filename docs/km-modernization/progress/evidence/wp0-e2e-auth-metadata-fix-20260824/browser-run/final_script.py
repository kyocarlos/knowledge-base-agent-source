import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://127.0.0.1:3030"
RUN = Path(__file__).parent / "final_runs" / "run_4"
SHOTS = RUN / "screenshots"
RUN.mkdir(parents=True, exist_ok=True)
SHOTS.mkdir(parents=True, exist_ok=True)
LOG = RUN / "final_script_log.txt"
LOG.write_text("", encoding="utf-8")

def log(line):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def main():
    routes = [
        ("root", "/"),
        ("chat", "/chat.html"),
        ("upload", "/upload"),
        ("report_reviews", "/admin/report-reviews"),
    ]
    results = []
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 1800})
        for name, route in routes:
            log(f"step route_{name}: open {route} without credentials or write actions")
            page = context.new_page()
            console_errors = []
            page_errors = []
            failed_requests = []
            assets = []
            websocket = {"opened": False, "closed": False, "timeout": False}
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            def on_response(resp):
                u = resp.url
                if "/assets/" in u or "/lib/" in u or u.endswith(".js") or u.endswith(".css"):
                    assets.append({"url": u.split("?")[0], "status": resp.status})
            page.on("response", on_response)
            page.on("requestfailed", lambda req: failed_requests.append({"url": req.url.split("?")[0], "failure": req.failure}))
            page.on("websocket", lambda ws: (websocket.__setitem__("opened", True), ws.on("close", lambda: websocket.__setitem__("closed", True))))
            response = page.goto(BASE + route, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(1500)
            status = response.status if response else None
            title = page.title()
            if name == "chat":
                websocket = page.evaluate("""async () => {
                    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
                    const ws = new WebSocket(`${scheme}://${location.host}/ws`);
                    return await new Promise(resolve => {
                        let opened = false;
                        const timer = setTimeout(() => resolve({opened, closed: false, timeout: true}), 5000);
                        ws.addEventListener('open', () => {
                            opened = true;
                            ws.close(1000, 'browser-evidence-probe');
                        });
                        ws.addEventListener('close', () => {
                            clearTimeout(timer);
                            resolve({opened, closed: true, timeout: false});
                        });
                        ws.addEventListener('error', () => {
                            clearTimeout(timer);
                            resolve({opened, closed: false, timeout: false});
                        });
                    });
                }""")
            page.screenshot(path=str(SHOTS / f"final_execution_{name}.png"), full_page=False)
            if name == "chat" and websocket["opened"] and not websocket["closed"]:
                page.wait_for_timeout(1500)
            page.close()
            results.append({
                "route": route,
                "status": status,
                "title": title,
                "console_errors": console_errors,
                "page_errors": page_errors,
                "failed_requests": failed_requests,
                "asset_responses": assets,
                "websocket": websocket if name == "chat" else None,
            })
        context.close()
        browser.close()
    all_assets_2xx = all(a["status"] >= 200 and a["status"] < 300 for r in results for a in r["asset_responses"])
    evidence = {
        "schema": "km.wp0.post-deploy-browser-evidence.v1",
        "base": BASE,
        "routes": results,
        "all_routes_200": all(r["status"] == 200 for r in results),
        "all_assets_2xx": all_assets_2xx,
        "fatal_console_errors": any(r["console_errors"] or r["page_errors"] for r in results),
        "failed_requests": [x for r in results for x in r["failed_requests"]],
        "websocket": next((r["websocket"] for r in results if r["route"] == "/chat.html"), None),
        "credentials_used": False,
        "secrets_included": False,
    }
    (RUN / "browser-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log("final result: " + json.dumps({"all_routes_200": evidence["all_routes_200"], "all_assets_2xx": all_assets_2xx, "fatal_console_errors": evidence["fatal_console_errors"], "failed_request_count": len(evidence["failed_requests"]), "websocket": evidence["websocket"]}, ensure_ascii=False))
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["all_routes_200"] and all_assets_2xx and not evidence["fatal_console_errors"] and not evidence["failed_requests"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
