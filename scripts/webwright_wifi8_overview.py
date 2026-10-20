"""Webwright：WiFi 專區總覽（分類統計、文件概況、待處理事項）的使用者流程驗收（不輸出密碼與 session）。

用法：python scripts/webwright_wifi8_overview.py RUN_DIR ZONE USER PASS_KEY
環境變數見 webwright_wifi8_common.py。預期數字不寫死：一律讀同一登入狀態下該區的 /api/wifi8/overview 再對照畫面。

檢查項目：
  classification_panel   「分類統計」面板的每一列（名稱、說明、數量、占比）與 API 一致；列數量加總＝合計＝全部文件數；
                         使用者指定的 8 個名稱依序出現；占比加總約 100%
  classification_bars    每一列有占比進度條，數值與 API 一致
  overview_cards         「文件概況」四張卡片的數字與 API 一致（知識庫文件、問答與研究採用文件、檢索單位、依政策未匯入）
  attention_panel        「待處理事項」的項目與 API 的 attention 一致；沒有項目時顯示「目前沒有待處理事項」；每項連結可點
  regression             既有面板（系統狀態、發布者、文件角色、主題、資料處理狀態）仍在
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webwright_wifi8_common import BASE, Run, login_to_wifi, number, wifi_page  # noqa: E402

EXPECTED_LABELS = ["WFA", "標準與學術機構", "晶片與零組件商", "測試與量測廠商", "網路產品品牌商", "媒體與產業研究機構", "內部資料", "其他來源"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("run_dir", "zone", "user", "pass_key"):
        parser.add_argument(name)
    args = parser.parse_args()
    run = Run(args.run_dir, args.zone, args.user)
    with wifi_page(run) as pg:
        login_to_wifi(pg, args.zone, args.user, args.pass_key)
        pg.goto(BASE + "/wifi8/#/overview")
        pg.locator(".classification-row").first.wait_for(timeout=15000)
        pg.wait_for_timeout(800)
        data = pg.evaluate("() => fetch('/api/wifi8/overview', {credentials: 'same-origin'}).then(r => r.json())")
        stats, counts = data["by_category"], data["counts"]
        panel = pg.locator("section.panel", has=pg.locator("h2", has_text="分類統計"))

        rows = panel.locator(".classification-row")
        shown = [{"label": rows.nth(i).locator(".category-name span").inner_text(), "desc": rows.nth(i).locator(".category-name small").inner_text(),
                  "count": rows.nth(i).locator(".category-value strong").inner_text(), "share": rows.nth(i).locator(".category-value span").inner_text()}
                 for i in range(rows.count())]
        expected = [{"label": r["label"], "desc": r["description"], "count": number(r["total"]), "share": f"{r['share']:.1f}%"} for r in stats["rows"]]
        total_text = panel.locator(".classification-total strong").inner_text()
        ok_rows = shown == expected and sum(r["total"] for r in stats["rows"]) == stats["total"] == counts["documents"] and total_text == number(stats["total"])
        labels = [r["label"] for r in stats["rows"]]
        ok_names = labels == EXPECTED_LABELS and abs(sum(r["share"] for r in stats["rows"]) - 100) < 0.5
        run.act(pg, "classification_panel", f"{len(shown)} 列；合計畫面 {total_text}／API {stats['total']}／全部文件 {counts['documents']}；名稱 {labels}；"
                f"列與 API 一致={shown == expected}", ok_rows and ok_names, target=panel)

        bars = panel.locator("progress.category-bar")
        bar_ok = bars.count() == len(stats["rows"]) and all(int(float(bars.nth(i).get_attribute("value"))) == stats["rows"][i]["total"] and
                                                              int(float(bars.nth(i).get_attribute("max"))) == stats["total"] for i in range(bars.count()))
        notes = panel.locator(".classification-row .classification-bar small").all_inner_texts()
        notes_ok = notes == [f"目前版本 {number(r['current'])}・歷史版本 {number(r['history'])}" for r in stats["rows"]]
        run.act(pg, "classification_bars", f"進度條 {bars.count()} 個，值與 API 一致={bar_ok}；目前／歷史版本標示一致={notes_ok}", bar_ok and notes_ok, target=panel)

        cards = pg.locator("section.panel", has=pg.locator("h2", has_text="文件概況"))
        excluded = sum(int(n) for n in (counts.get("excluded") or {}).values())
        want = {"知識庫文件": number(counts["documents"]), "問答與研究採用文件": number(data["qna_documents"]),
                "檢索單位": number(counts.get("chunks")), "依政策未匯入": number(excluded)}
        got = {cards.locator(".metric").nth(i).locator(".metric-copy span").inner_text(): cards.locator(".metric").nth(i).locator(".metric-copy strong").inner_text()
               for i in range(cards.locator(".metric").count())}
        note = cards.locator(".metric").first.locator("small").inner_text()
        run.act(pg, "overview_cards", f"卡片 {got}；預期 {want}；第一張註記={note!r}", got == want and f"目前版本 {number(counts['current_documents'])}" in note
                and f"歷史版本 {number(counts['superseded_documents'])}" in note, target=cards)

        attention = pg.locator("section.panel", has=pg.locator("h2", has_text="待處理事項"))
        tasks = attention.locator("a.attention-task")
        titles = [tasks.nth(i).locator("strong").inner_text() for i in range(tasks.count())]
        hrefs = [tasks.nth(i).get_attribute("href") for i in range(tasks.count())]
        want_titles = [item["title"] for item in data["attention"]]
        empty_ok = (not want_titles and "目前沒有待處理事項" in attention.inner_text()) or bool(want_titles)
        links_ok = hrefs == [f"#/{item['route']}" for item in data["attention"]]
        run.act(pg, "attention_panel", f"待處理 {titles}（API {want_titles}）；連結 {hrefs}", titles == want_titles and empty_ok and links_ok, target=attention)
        if tasks.count():
            tasks.first.click()
            pg.wait_for_timeout(1200)
            run.act(pg, "attention_link_works", f"點第一項後網址 {pg.url.split('#')[-1]}（預期 {data['attention'][0]['route']}）", pg.url.endswith("#/" + data["attention"][0]["route"]))
            pg.goto(BASE + "/wifi8/#/overview")
            pg.wait_for_timeout(1200)

        text = pg.locator("#page-content").inner_text()
        needed = ["系統狀態", "發布者", "文件角色", "主題", "資料處理狀態"]
        run.act(pg, "regression", f"既有面板：{[n for n in needed if n in text]}", all(n in text for n in needed) and "載入失敗" not in text)
        pg.screenshot(path=str(run.shots / "overview_full.png"), full_page=True)
    return run.finish()


if __name__ == "__main__":
    raise SystemExit(main())
