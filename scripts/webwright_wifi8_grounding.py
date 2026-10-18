"""Webwright：WiFi AI Agent「依據檢核」驗收（不輸出密碼與 session）。

用法：python scripts/webwright_wifi8_grounding.py RUN_DIR ZONE USER PASS_KEY [--scenario all|panel|table|code_block]

情境（每題都實際在 AI Agent 頁提問，並讀取同一回答的 /api/wifi8/agent 結果）：
  panel       D07（DBE）、V03（版本清單）：依據檢核區塊、摘要標籤、展開明細；D07 須答出
              「實作 WPA3-Enterprise 則必須實作 DBE」並引用 MRD v1.0 或 DBE Contribution。
  table       要求用表格比較（P01、D10）：回答含表格，表格標題列不出現在檢核句子中。
  code_block  要求在 ``` 中畫 ASCII 示意圖（D03、D10）：回答含程式碼區塊，區塊內容不出現在檢核句子中。
每題共通：區塊顯示、有「有依據的句子」「數值核對」標籤、不顯示相似度、API 有 grounding、console 無錯誤。
環境變數見 webwright_wifi8_common.py。
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webwright_wifi8_common import Run, ask_agent, login_to_wifi, open_agent, wifi_page  # noqa: E402

SCENARIOS = {
    "panel": [("D07", "DBE（Dynamic Bandwidth Expansion）是什麼？什麼情況下 AP 必須實作？"),
              ("V03", "2xLDPC Test Case 有哪些版本？哪一版是目前版本？")],
    "table": [("P01", "Broadcom BCM43840 和 BCM43820 有什麼差異？請用表格比較。"),
              ("D10", "DRU（Distributed Resource Unit）和一般 RU 有什麼不同？請用表格比較。")],
    "code_block": [("D03", "DSO（Dynamic Sub-band Operation）怎麼運作？請在程式碼區塊（```）中用 ASCII 示意圖說明。"),
                   ("D10", "DRU（Distributed Resource Unit）和一般 RU 有什麼不同？請在程式碼區塊（```）中用 ASCII 示意圖說明。")],
}
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}")
FENCE = re.compile(r"^\s*(```|~~~)")


def _norm(text: str) -> str:
    return re.sub(r"[\s*`]+", "", text)


def analyze(pg, reply: dict) -> dict:
    panel = reply["panel"]
    chips = panel.locator(".g-chip").all_inner_texts() if panel is not None else []
    if panel is not None and panel.locator("details").count():
        panel.locator("details summary").first.click()
        pg.wait_for_timeout(300)
    flagged = panel.locator(".g-flags li").all_inner_texts() if panel is not None else []
    result = reply["result"] or {}
    grounding = result.get("grounding") or {}
    answer = result.get("answer") or ""
    claims = [c["text"] for c in grounding.get("claims") or []]
    lines = [l for l in answer.splitlines() if l.strip()]
    headers = [[c.strip().strip("*") for c in l.strip().strip("|").split("|") if c.strip()]
               for i, l in enumerate(lines[:-1]) if l.lstrip().startswith("|") and TABLE_RULE.match(lines[i + 1])]
    fenced, inside = [], False
    for line in answer.splitlines():
        if FENCE.match(line):
            inside = not inside
        elif inside and len(re.sub(r"[\W_]+", "", line)) >= 4:
            fenced.append(line.strip())
    return {
        "panel": panel is not None, "chips": chips, "flagged": [f[:120] for f in flagged],
        "summary": grounding.get("summary"), "answer": answer, "citations": [c.get("source") for c in result.get("citations") or []],
        "tables": len(headers), "header_claims": [t for t in claims for cells in headers if cells and t.startswith(cells[0] + "：")],
        # A claim taken from a code block is part of one of its lines; a short diagram label ("一般 RU") that
        # merely occurs inside a normal sentence does not make that sentence a code-block claim.
        "fenced_lines": len(fenced), "fenced_sample": fenced[:6],
        "fenced_claims": [{"claim": t, "line": f} for t in claims for f in fenced if _norm(t) and _norm(t) in _norm(f)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("run_dir", "zone", "user", "pass_key"):
        parser.add_argument(name)
    parser.add_argument("--scenario", choices=["all", *SCENARIOS], default="all")
    args = parser.parse_args()
    scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    run = Run(args.run_dir, args.zone, args.user)
    details = {}
    with wifi_page(run) as pg:
        login_to_wifi(pg, args.zone, args.user, args.pass_key)
        open_agent(pg)
        for scenario in scenarios:
            for case_id, question in SCENARIOS[scenario]:
                key = f"{scenario}_{case_id}"
                info = details[key] = analyze(pg, ask_agent(pg, run, question))
                common = (info["panel"] and any(t.startswith("有依據的句子") for t in info["chips"])
                          and any(t.startswith("數值核對") for t in info["chips"]) and not any("原文相似度" in t for t in info["chips"])
                          and bool(info["summary"] and info["summary"].get("claims")))
                specific, note = True, ""
                if scenario == "panel" and case_id == "D07":
                    answer = info["answer"].replace("‑", "-")
                    specific = ("WPA3-Enterprise" in answer and bool(re.search(r"必須|shall|強制", answer))
                                and any(s and ("MRD v1.0" in s or "DBE Contribution" in s) for s in info["citations"]))
                    note = f"；WPA3-Enterprise 條件與 DBE 來源={specific}"
                elif scenario == "table":
                    specific = info["tables"] > 0 and not info["header_claims"]
                    note = f"；表格 {info['tables']} 個，標題列被當句子 {info['header_claims']}"
                elif scenario == "code_block":
                    specific = info["fenced_lines"] > 0 and not info["fenced_claims"]
                    note = f"；程式碼區塊 {info['fenced_lines']} 行，被當句子 {info['fenced_claims']}"
                target = pg.locator("#conversation .grounding").last if info["panel"] else None
                run.act(pg, key, f"{case_id} 依據檢核：標籤={info['chips']}；需留意 {len(info['flagged'])} 句{note}", common and specific, target=target)
    for info in details.values():
        info.pop("answer", None)
    return run.finish(scenarios=scenarios, details=details)


if __name__ == "__main__":
    raise SystemExit(main())
