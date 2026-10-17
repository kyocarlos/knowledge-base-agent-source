"""Webwright：WiFi 工作區使用者流程驗收（8 項；不輸出密碼與 session）。

用法：python scripts/webwright_wifi8_accept.py RUN_DIR ZONE USER PASS_KEY
  RUN_DIR   輸出目錄（screenshots/、final_script_log.txt、summary.json）
  ZONE      資料區按鈕文字，例如 test、da40
  USER      測試帳號，例如 km-clude1
  PASS_KEY  帳號檔中密碼的變數名稱，例如 KM_TEST_PASS1

環境變數（另見 webwright_wifi8_common.py：KM_BASE_URL、KM_TEST_ACCOUNTS_FILE）：
  KM_ACCEPT_AGENT_MIN_CHARS  Agent 回答最少字數（預設 40，只用來排除空白或異常短的回答）
  KM_ACCEPT_AGENT_QUESTION   Agent 驗收問題（預設「NPCA 是什麼？請簡短說明並附來源。」）
  KM_ACCEPT_SEARCH_QUERIES   混合檢索驗收詞，以 | 分隔（預設 漫遊|ELR uplink|Broadcom BCM43840）

預期數量不寫死：在同一登入狀態下讀取 /api/wifi8/overview，再檢查畫面顯示的數字與 API 一致；
匯入新的匯出包後不需要修改本腳本。全部通過時 exit 0，否則 exit 1。
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webwright_wifi8_common import BASE, Run, ask_agent, hybrid_search, login_to_wifi, number, overview_counts, wifi_page  # noqa: E402

AGENT_MIN_CHARS = int(os.getenv("KM_ACCEPT_AGENT_MIN_CHARS", "40"))
AGENT_QUESTION = os.getenv("KM_ACCEPT_AGENT_QUESTION", "NPCA 是什麼？請簡短說明並附來源。")
SEARCH_QUERIES = [q for q in os.getenv("KM_ACCEPT_SEARCH_QUERIES", "漫遊|ELR uplink|Broadcom BCM43840").split("|") if q.strip()]


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    run_dir, zone, user, pass_key = sys.argv[1:5]
    run = Run(run_dir, zone, user)
    expected = {}
    with wifi_page(run) as pg:
        login_to_wifi(pg, zone, user, pass_key)
        pg.wait_for_timeout(1000)
        # Expected counts come from the live API of this zone, not from constants.
        counts = overview_counts(pg)
        expected = {"documents": number(counts.get("documents")), "current": number(counts.get("current_documents")),
                    "superseded": number(counts.get("superseded_documents")), "chunks": number(counts.get("chunks"))}
        text = pg.locator("#page-content").inner_text()
        status = pg.locator("#zone-status").inner_text()
        shown = {k: v in text for k, v in expected.items() if k != "documents"}
        run.act(pg, "overview", f"{zone} 總覽：狀態={status}；API 數量={expected}；畫面顯示={shown}",
                counts.get("documents") and expected["documents"] in status and all(shown.values()) and "載入失敗" not in text)

        pg.goto(BASE + "/wifi8/#/documents")
        pg.wait_for_timeout(3000)
        meta = pg.locator("#document-results .results-meta").inner_text()
        run.act(pg, "documents", f"文件瀏覽：{meta}（API 目前版本 {expected['current']}）", f"共 {expected['current']} 份" in meta)

        pg.locator("#document-results [data-document]").first.click()
        pg.wait_for_timeout(3000)
        body = pg.locator("#document-dialog-body").inner_text()
        dialog_errors = pg.locator("#document-dialog-body .error-card").count()
        run.act(pg, "document_detail",
                f"開啟文件「{pg.locator('#document-dialog-title').inner_text()[:50]}」：段落內容長度 {len(body)}，有錯誤={dialog_errors > 0}",
                dialog_errors == 0 and len(body) > 200)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(500)

        for index, query in enumerate(SEARCH_QUERIES, 1):
            hybrid_search(pg, query)
            hits = pg.locator("#hybrid-results .search-hit")
            top = hits.first.locator("h3").inner_text() if hits.count() else ""
            head = pg.locator("#hybrid-results").inner_text()[:80]
            run.act(pg, f"search_{index}", f"混合檢索「{query}」→ {hits.count()} 筆，第一筆={top[:60]!r}，{head!r}",
                    hits.count() > 0 and "error" not in head.lower())

        pg.goto(BASE + "/wifi8/#/ai")
        pg.wait_for_timeout(2000)
        reply = ask_agent(pg, run, AGENT_QUESTION)
        # A short answer is fine when the question asks for one: require a real, cited answer instead of a length.
        answer, cites = reply["answer"], len(reply["citations"])
        run.act(pg, "agent", f"AI Agent 提問 → 長度 {len(answer)}（下限 {AGENT_MIN_CHARS}）；引用 {cites} 筆；開頭={answer[:100]!r}",
                "error" not in reply["classes"] and len(answer) >= AGENT_MIN_CHARS and re.search(r"\[S\d+\]", answer) and cites > 0)
    return run.finish(expected_counts=expected)


if __name__ == "__main__":
    raise SystemExit(main())
