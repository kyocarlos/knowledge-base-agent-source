"""Webwright：WiFi 工作區顯示驗收（檢索標題、AI 回答 Markdown、引用清單；不輸出密碼與 session）。

用法：python scripts/webwright_wifi8_render.py RUN_DIR ZONE USER PASS_KEY [--static DIR]
  --static DIR  以瀏覽器端改用本機 DIR 下的 /wifi8/ index.html／JS／CSS（API 仍為線上真實資料），
                用來在部署前驗證前端，例如 --static frontend/wifi8。

檢查項目：
  overview／documents   畫面數字與 /api/wifi8/overview 一致（回歸）
  search_title_*        混合檢索結果標題是文件名稱、不是 revision 檔名代碼，且附註標出全文／語意命中
  agent_markdown        AI 回答以 Markdown 呈現（粗體、條列、[S#] 標示），沒有殘留 ** 或 ## 符號
  agent_citations       引用清單用 [S#] 與文件名稱，內文出現的 [S#] 都列在清單中
環境變數見 webwright_wifi8_common.py；KM_RENDER_SEARCH_QUERIES（| 分隔）、KM_RENDER_AGENT_QUESTION 可覆寫題目。
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webwright_wifi8_common import BASE, Run, ask_agent, hybrid_search, login_to_wifi, number, overview_counts, wifi_page  # noqa: E402

SLUG = re.compile(r"--(unversioned|v\d)|-clean-[0-9a-f]{6,}")  # revision ids look like "...--v4-clean-46472673"
SEARCH_QUERIES = [q for q in os.getenv("KM_RENDER_SEARCH_QUERIES", "漫遊|ELR uplink").split("|") if q.strip()]
AGENT_QUESTION = os.getenv("KM_RENDER_AGENT_QUESTION", "請用條列整理 ELR 的三個重點，重要名詞用粗體，並附來源。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("run_dir", "zone", "user", "pass_key"):
        parser.add_argument(name)
    parser.add_argument("--static", default="", help="serve /wifi8/ static files from this directory")
    args = parser.parse_args()
    run = Run(args.run_dir, args.zone, args.user)
    served: list[str] = []
    with wifi_page(run, static_dir=args.static or None, served=served) as pg:
        login_to_wifi(pg, args.zone, args.user, args.pass_key)
        pg.wait_for_timeout(1000)
        counts = overview_counts(pg)
        current, chunks = number(counts.get("current_documents")), number(counts.get("chunks"))
        text = pg.locator("#page-content").inner_text()
        run.act(pg, "overview", f"{args.zone} 總覽回歸：API 目前版本 {current}、檢索單位 {chunks}；畫面顯示={current in text and chunks in text}",
                counts.get("documents") and current in text and chunks in text)
        pg.goto(BASE + "/wifi8/#/documents")
        pg.wait_for_timeout(3000)
        run.act(pg, "documents", "文件瀏覽回歸", f"共 {current} 份" in pg.locator("#document-results .results-meta").inner_text())

        for index, query in enumerate(SEARCH_QUERIES, 1):
            hybrid_search(pg, query)
            titles = pg.locator("#hybrid-results .search-hit h3").all_inner_texts()
            metas = pg.locator("#hybrid-results .search-hit small").all_inner_texts()
            slugs = [t for t in titles if SLUG.search(t)]
            pg.locator("#hybrid-results").scroll_into_view_if_needed()
            run.act(pg, f"search_title_{index}",
                    f"混合檢索「{query}」→ {len(titles)} 筆；標題前 3={titles[:3]}；含檔名代碼的標題 {len(slugs)} 筆；第一筆附註={metas[0] if metas else ''!r}",
                    titles and not slugs and any(("全文" in m or "語意" in m) for m in metas), target=pg.locator("#hybrid-results"))

        pg.goto(BASE + "/wifi8/#/ai")
        pg.wait_for_timeout(2000)
        reply = ask_agent(pg, run, AGENT_QUESTION)
        message, answer = reply["message"], reply["answer"]
        tags = {t: message.locator(t).count() for t in ("strong", "ul", "ol", "li", "h3", "h4", "table", "code", ".cite-ref")}
        in_text = sorted(set(re.findall(r"\[(S\d+)\]", answer)), key=lambda r: int(r[1:]))
        listed = [m.group(1) for c in reply["citations"] if (m := re.match(r"\[(S\d+)\]", c))]
        raw_md = [m for m in ("**", "## ", "\n- ") if m in answer]
        run.act(pg, "agent_markdown", f"AI 回答：class={reply['classes']!r}；元素={tags}；殘留 Markdown 符號={raw_md}；開頭={answer[:80]!r}",
                "markdown" in reply["classes"] and not raw_md and tags["strong"] > 0 and tags["li"] > 0 and tags[".cite-ref"] > 0, target=message)
        run.act(pg, "agent_citations",
                f"引用清單 {len(reply['citations'])} 筆：{[c[:70] for c in reply['citations']]}；內文引用={in_text}；清單編號={listed}",
                reply["citations"] and listed and set(in_text) <= set(listed) and not any(SLUG.search(c.split("\n")[0]) for c in reply["citations"]),
                target=pg.locator(".citation-list").last)
        pg.screenshot(path=str(run.shots / "agent_full.png"), full_page=True)
    return run.finish(static=("local:" + args.static) if args.static else "runtime", served_local=sorted(set(served)))


if __name__ == "__main__":
    raise SystemExit(main())
