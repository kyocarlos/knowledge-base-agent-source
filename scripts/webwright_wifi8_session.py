"""Webwright：WiFi 工作區的登入回原頁、新版提示與 chat-v2 圖片引用驗收（不輸出密碼與 session）。

用法：python scripts/webwright_wifi8_session.py RUN_DIR ZONE USER PASS_KEY

檢查項目：
  deep_link_login        未登入直接開 /wifi8/#/ai → 登入頁 next=/wifi8/ → 登入並選區後回到 /wifi8/#/ai
  expired_session_return 在 /wifi8/#/documents 時 session 失效（清除 cookie）→ 重新讀取 → 登入後回到 #/documents
  update_banner          伺服器上的 /wifi8/ 換成另一個版本時（以攔截模擬），切回分頁會出現「請重新整理」橫幅；
                         重新整理後載入目前版本、不再顯示
  chatv2_figure_citation chat-v2 的 WiFi 回答（KM_RENDER_FIGURE_QUESTION）中，來自圖片的引用有「圖片」標籤、位置與已載入縮圖
環境變數見 webwright_wifi8_common.py。
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webwright_wifi8_common import BASE, Run, secret, wifi_page  # noqa: E402

FIGURE_QUESTION = os.getenv("KM_RENDER_FIGURE_QUESTION", "Wi-Fi Sensing 的居家監控用例中，感測結果如何用來控制 HVAC？")


def login_here(pg, zone: str, user: str, pass_key: str) -> None:
    """Log in on the login page the browser was sent to (keeps its next= and hash)."""
    from playwright.sync_api import expect
    pg.wait_for_url("**/login.html**", timeout=15000)
    if pg.locator('input[name="username"]').is_visible():
        pg.fill('input[name="username"]', user)
        pg.fill('input[name="password"]', secret(pass_key))
        pg.click('#credentials button[type="submit"]')
    expect(pg.locator("#instances")).to_be_visible(timeout=15000)
    pg.locator("#instance-buttons button", has_text=zone.upper()).click()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("run_dir", "zone", "user", "pass_key"):
        parser.add_argument(name)
    args = parser.parse_args()
    run = Run(args.run_dir, args.zone, args.user)
    with wifi_page(run) as pg:
        # 1. Deep link without a session.
        pg.goto(BASE + "/wifi8/#/ai")
        pg.wait_for_url("**/login.html**", timeout=15000)
        login_url = pg.url.replace(BASE, "")
        login_here(pg, args.zone, args.user, args.pass_key)
        pg.wait_for_url(re.compile(r".*/wifi8/#/ai$"), timeout=30000)
        pg.wait_for_timeout(2000)
        title = pg.locator("h1").first.inner_text()
        run.act(pg, "deep_link_login", f"登入頁 {login_url}；登入後網址 {pg.url.replace(BASE, '')}；標題 {title!r}",
                "next=/wifi8/" in login_url and pg.url.endswith("/wifi8/#/ai") and "AI" in title)

        # 2. Session lost while working.
        pg.goto(BASE + "/wifi8/#/documents")
        pg.wait_for_timeout(2500)
        before = len(run.wifi8_api)
        pg.context.clear_cookies()
        pg.click("#refresh-page")
        login_here(pg, args.zone, args.user, args.pass_key)
        # The 401s between dropping the session and logging in again are what this step provokes, not failures.
        expected = [x for x in run.wifi8_api[before:] if x[0] == 401]
        run.wifi8_api = run.wifi8_api[:before] + [x for x in run.wifi8_api[before:] if x[0] != 401]
        pg.wait_for_url(re.compile(r".*/wifi8/#/documents$"), timeout=30000)
        pg.wait_for_timeout(2500)
        title = pg.locator("h1").first.inner_text()
        run.act(pg, "expired_session_return", f"session 失效後（預期的 401：{[x[2] for x in expected]}）重新登入，回到 {pg.url.replace(BASE, '')}；標題 {title!r}",
                pg.url.endswith("/wifi8/#/documents") and "文件" in title)

        # 3. A newer build on the server while this tab is open.
        loaded = pg.evaluate("[...document.scripts].map(s => s.src).find(s => /wifi8\\.[0-9a-f]{12}\\.js/.test(s)) || ''")

        def newer_build(route):
            if route.request.resource_type != "fetch":
                return route.continue_()
            body = route.fetch().text()
            route.fulfill(status=200, content_type="text/html; charset=utf-8",
                          body=re.sub(r"wifi8\.[0-9a-f]{12}\.js", "wifi8.000000000000.js", body))
        pg.route(BASE + "/wifi8/", newer_build)
        pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        pg.wait_for_timeout(2500)
        banner = pg.locator("#update-banner")
        shown = banner.count() and banner.is_visible()
        text = banner.inner_text() if banner.count() else ""
        pg.unroute(BASE + "/wifi8/")
        if shown:
            banner.locator("button").click()
            pg.wait_for_timeout(3500)
        pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        pg.wait_for_timeout(2500)
        run.act(pg, "update_banner", f"目前 {loaded.rsplit('/', 1)[-1]}；模擬新版後橫幅 {bool(shown)}：{text!r}；重新整理後橫幅 {pg.locator('#update-banner').count()}",
                bool(shown) and "重新整理" in text and pg.locator("#update-banner").count() == 0)

        # 4. chat-v2 WiFi answers (inline agent rendering).
        pg.goto(BASE + "/chat-v2.html")
        pg.wait_for_timeout(3000)
        pg.evaluate("selectKnowledgeZone('wifi')")
        pg.fill("#chatInput", FIGURE_QUESTION)
        pg.keyboard.press("Enter")
        sources = pg.locator(".wifi-agent-sources").last
        sources.wait_for(timeout=180000)
        figures = sources.locator("li.figure")
        widths = []
        for index in range(figures.count()):
            img = figures.nth(index).locator("img")
            img.scroll_into_view_if_needed()
            img.evaluate("img => img.complete || new Promise(done => { img.onload = img.onerror = done; })")
            widths.append(img.evaluate("img => img.naturalWidth"))
        first = figures.first.inner_text().replace("\n", " ") if figures.count() else ""
        run.act(pg, "chatv2_figure_citation", f"chat-v2「{FIGURE_QUESTION}」→ 引用 {sources.locator('li').count()} 筆，圖片引用 {figures.count()} 筆：{first[:100]!r}；縮圖寬度 {widths}",
                figures.count() > 0 and all(w > 0 for w in widths) and "圖片" in first and "圖 " in first, target=sources)
    return run.finish()


if __name__ == "__main__":
    raise SystemExit(main())
