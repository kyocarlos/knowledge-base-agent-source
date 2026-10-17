"""Webwright：WiFi 工作區使用者流程驗收（8 項；不輸出密碼與 session）。

用法：python scripts/webwright_wifi8_accept.py RUN_DIR ZONE USER PASS_KEY
  RUN_DIR   輸出目錄（screenshots/、final_script_log.txt、summary.json）
  ZONE      資料區按鈕文字，例如 test、da40
  USER      測試帳號，例如 km-clude1
  PASS_KEY  帳號檔中密碼的變數名稱，例如 KM_TEST_PASS1

環境變數：
  KM_BASE_URL                入口網址（預設 https://61.216.9.52:3030）
  KM_TEST_ACCOUNTS_FILE      測試帳號檔（預設 ~/.km-control/test-accounts.env；KEY=VALUE 格式）
  KM_ACCEPT_AGENT_MIN_CHARS  Agent 回答最少字數（預設 40，只用來排除空白或異常短的回答）
  KM_ACCEPT_AGENT_QUESTION   Agent 驗收問題（預設「NPCA 是什麼？請簡短說明並附來源。」）
  KM_ACCEPT_SEARCH_QUERIES   混合檢索驗收詞，以 | 分隔（預設 漫遊|ELR uplink|Broadcom BCM43840）

預期數量不寫死：在同一登入狀態下讀取 /api/wifi8/overview，再檢查畫面顯示的數字與 API 一致；
匯入新的匯出包後不需要修改本腳本。全部通過時 exit 0，否則 exit 1。
"""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = os.getenv("KM_BASE_URL", "https://61.216.9.52:3030").rstrip("/")
ACCOUNTS = Path(os.getenv("KM_TEST_ACCOUNTS_FILE", str(Path.home() / ".km-control/test-accounts.env")))
AGENT_MIN_CHARS = int(os.getenv("KM_ACCEPT_AGENT_MIN_CHARS", "40"))
AGENT_QUESTION = os.getenv("KM_ACCEPT_AGENT_QUESTION", "NPCA 是什麼？請簡短說明並附來源。")
SEARCH_QUERIES = [q for q in os.getenv("KM_ACCEPT_SEARCH_QUERIES", "漫遊|ELR uplink|Broadcom BCM43840").split("|") if q.strip()]


def path_of(url: str) -> str:
    return urlsplit(url).path


def number(value) -> str:
    """The SPA formats counts with zh-TW thousands separators (31395 -> 31,395)."""
    return f"{int(value or 0):,}"


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    run, zone, user, pass_key = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    secrets = dict(line.strip().split("=", 1) for line in ACCOUNTS.read_text(encoding="utf-8").splitlines() if "=" in line)
    shots = run / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    results, bad, errs, api, step = {}, [], [], [], [0]
    log = (run / "final_script_log.txt").open("w", encoding="utf-8")

    def act(pg, key, reason, ok):
        step[0] += 1
        results[key] = bool(ok)
        log.write(f"step {step[0]} action: {reason} => {'PASS' if ok else 'FAIL'}\n")
        log.flush()
        pg.screenshot(path=str(shots / f"final_execution_{step[0]}_{key}.png"), full_page=True)

    def hybrid(pg, query):
        pg.fill("#hybrid-query", query)
        pg.click("#hybrid-submit")
        for _ in range(60):
            pg.wait_for_timeout(500)
            if "正在執行" not in pg.locator("#hybrid-results").inner_text():
                break
        hits = pg.locator("#hybrid-results .search-hit")
        return hits.count(), (hits.first.locator("h3").inner_text() if hits.count() else ""), pg.locator("#hybrid-results").inner_text()[:80]

    with sync_playwright() as p:
        browser = p.firefox.launch()
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1400, "height": 1000})
        pg = context.new_page()
        pg.on("console", lambda m: m.type == "error" and errs.append(m.text[:160]))
        pg.on("response", lambda r: r.status >= 400 and bad.append((r.status, path_of(r.url))))
        pg.on("response", lambda r: "/api/wifi8/" in r.url and api.append((r.status, r.request.method, path_of(r.url))))

        pg.goto(BASE + "/login.html")
        pg.fill('input[name="username"]', user)
        pg.fill('input[name="password"]', secrets[pass_key])
        pg.click('#credentials button[type="submit"]')
        expect(pg.locator("#instances")).to_be_visible(timeout=15000)
        pg.locator("#instance-buttons button", has_text=zone.upper()).click()
        pg.wait_for_url("**/chat-v2.html**", timeout=30000)
        pg.wait_for_timeout(2000)
        pg.locator('[data-knowledge-zone="wifi"]').first.click()
        pg.wait_for_url("**/wifi8/**", timeout=15000)
        pg.wait_for_timeout(4000)

        # Expected counts come from the live API of this zone, not from constants.
        counts = (pg.evaluate("() => fetch('/api/wifi8/overview', {credentials: 'same-origin'}).then(r => r.json())") or {}).get("counts") or {}
        expected = {"documents": number(counts.get("documents")), "current": number(counts.get("current_documents")),
                    "superseded": number(counts.get("superseded_documents")), "chunks": number(counts.get("chunks"))}
        text = pg.locator("#page-content").inner_text()
        status = pg.locator("#zone-status").inner_text()
        shown = {k: v in text for k, v in expected.items() if k != "documents"}
        act(pg, "overview", f"{zone} 總覽：狀態={status}；API 數量={expected}；畫面顯示={shown}",
            counts.get("documents") and expected["documents"] in status and all(shown.values()) and "載入失敗" not in text)

        pg.goto(BASE + "/wifi8/#/documents")
        pg.wait_for_timeout(3000)
        meta = pg.locator("#document-results .results-meta").inner_text()
        act(pg, "documents", f"文件瀏覽：{meta}（API 目前版本 {expected['current']}）", f"共 {expected['current']} 份" in meta)

        pg.locator("#document-results [data-document]").first.click()
        pg.wait_for_timeout(3000)
        body = pg.locator("#document-dialog-body").inner_text()
        errors_in_dialog = pg.locator("#document-dialog-body .error-card").count()
        act(pg, "document_detail",
            f"開啟文件「{pg.locator('#document-dialog-title').inner_text()[:50]}」：段落內容長度 {len(body)}，有錯誤={errors_in_dialog > 0}",
            errors_in_dialog == 0 and len(body) > 200)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(500)

        for index, query in enumerate(SEARCH_QUERIES, 1):
            count, top, head = hybrid(pg, query)
            act(pg, f"search_{index}", f"混合檢索「{query}」→ {count} 筆，第一筆={top[:60]!r}，{head!r}", count > 0 and "error" not in head.lower())

        pg.goto(BASE + "/wifi8/#/ai")
        pg.wait_for_timeout(2000)
        pg.fill("#agent-question", AGENT_QUESTION)
        pg.click("#agent-submit")
        for _ in range(240):
            pg.wait_for_timeout(1000)
            if pg.locator("#agent-wait").count() == 0:
                break
        last = pg.locator("#conversation .message").last
        answer = last.inner_text()
        # A short answer is fine when the question asks for one: require a real, cited answer instead of a length.
        cites = pg.locator(".citation-list").last.locator("li").count() if pg.locator(".citation-list").count() else 0
        act(pg, "agent", f"AI Agent 提問 → 長度 {len(answer)}（下限 {AGENT_MIN_CHARS}）；引用 {cites} 筆；開頭={answer[:100]!r}",
            "error" not in (last.get_attribute("class") or "") and len(answer) >= AGENT_MIN_CHARS
            and re.search(r"\[S\d+\]", answer) and cites > 0)

        pg.goto(BASE + "/login.html")
        pg.click("#logout")
        browser.close()

    wifi_failures = [x for x in api if x[0] >= 400]
    results["api_all_ok"] = not wifi_failures
    summary = {"zone": zone, "user": user, "base_url": BASE, "expected_counts": expected, "results": results,
               "wifi8_api_calls": len(api), "wifi8_api_failures": wifi_failures, "failed_requests": bad, "console_errors": errs}
    log.write("final: " + json.dumps(summary, ensure_ascii=False) + "\n")
    log.close()
    (run / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
