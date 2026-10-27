#!/usr/bin/env python3
"""Accuracy evaluation of the report query agent. Gold values are re-read straight from the workbook cell named by the database row (not from the database value);
scoring is pure code (required strings present, forbidden strings absent). Arms run one question at a time.

  eval_test_reports.py gen   <reports_dir> <out.json>
  eval_test_reports.py run   <cases.json> <out.json> [--arms tools,text] [--repeat N] [--only ID,ID]
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PRODUCTS = ["CHS3320N-D388", "NCM1150D2-D347", "NCQ2200B2V-D294", "PKE3540J-D223", "TP-Link Archer BE800", "TP-Link Archer BE805"]
DIR_ZH = {"ul": "上行", "dl": "下行"}
SPECS = [  # (product, report_type, band, bandwidth, direction, metric)
    ("NCQ2200B2V-D294", "wifi_throughput", "5GHz", 80, "ul", "throughput"), ("NCQ2200B2V-D294", "wifi_throughput", "5GHz", 80, "dl", "throughput"),
    ("PKE3540J-D223", "wifi_throughput", "5GHz", 40, "dl", "throughput"), ("CHS3320N-D388", "wifi_throughput", "2.4GHz", 20, "ul", "throughput"),
    ("TP-Link Archer BE800", "wifi_throughput", "5GHz", 160, "dl", "throughput"), ("TP-Link Archer BE805", "wifi_throughput", "5GHz", 80, "ul", "throughput"),
    ("NCM1150D2-D347", "wifi_throughput", "2.4GHz", 40, "dl", "throughput"), ("NCQ2200B2V-D294", "wifi_throughput", "5GHz", 20, None, "rssi"),
    ("PKE3540J-D223", "wifi_throughput", "5GHz", 80, None, "rssi"),
]


def _fmt(v: float) -> list[str]:
    """Accepted spellings of a cell value: as stored, trimmed, and (for large values) with thousands separators."""
    out = {repr(float(v)).rstrip("0").rstrip(".") if "." in repr(float(v)) else repr(float(v)), f"{v:g}", f"{v:.2f}".rstrip("0").rstrip(".")}
    if abs(v) >= 1000:
        out |= {f"{v:,.2f}".rstrip("0").rstrip(".")}
    return sorted(out)


def gen(reports: str, out: str) -> None:
    import openpyxl
    import psycopg
    conn = psycopg.connect(os.environ["KM_TEST_NUMERIC_URL"], autocommit=True)
    books: dict[str, object] = {}

    def cell(doc: str, sheet: str, ref: str):
        wb = books.get(doc) or books.setdefault(doc, openpyxl.load_workbook(Path(reports) / f"{doc}.xlsx", data_only=True))
        return wb[sheet][ref].value

    def one(sql: str, params: tuple):
        return conn.execute(sql, params).fetchall()

    cases: list[dict] = []
    # A. 點查：以儲存格原值為標準答案
    for i, (prod, rt, band, bw, d, metric) in enumerate(SPECS, 1):
        rows = one("""SELECT r.document_id, m.channel, m.source_sheet, m.source_cell_range FROM km_test.test_measurement m JOIN km_test.test_run r USING (test_run_id)
                      WHERE r.dut_model=%s AND r.report_type=%s AND m.band=%s AND m.bandwidth_mhz=%s AND m.metric_name=%s AND (%s::text IS NULL OR m.direction=%s)
                      ORDER BY m.channel LIMIT 1""", (prod, rt, band, bw, metric, d, d))
        doc, ch, sh, ref = rows[0]
        v = float(cell(doc, sh, ref))
        label = "RSSI" if metric == "rssi" else f"{DIR_ZH[d]}吞吐量"
        q = f"{prod} 的 Throughput 報告中，{band} {bw}MHz 通道 {ch} 的{label}是多少？"
        cases.append({"id": f"A{i}", "category": "點查", "question": q, "expect_all": [_fmt(v)], "forbid": [], "gold": {"value": v, "cell": f"{sh}!{ref}"}})
    # B. 方向陷阱：同一格，問法用「下行／Rx」，答案不得是上行的值
    prod = "NCQ2200B2V-D294"
    rows = {d: one("""SELECT r.document_id, m.source_sheet, m.source_cell_range FROM km_test.test_measurement m JOIN km_test.test_run r USING (test_run_id)
                      WHERE r.dut_model=%s AND r.report_type='wifi_throughput' AND m.band='5GHz' AND m.bandwidth_mhz=80 AND m.channel=42 AND m.metric_name='throughput' AND m.direction=%s""", (prod, d))[0] for d in ("ul", "dl")}
    vals = {d: float(cell(*rows[d])) for d in rows}
    cases.append({"id": "B1", "category": "方向", "question": f"{prod} 5GHz 80MHz 通道 42，DUT 作為 AP 往 STA 傳送資料（下行）的吞吐量是多少？", "expect_all": [_fmt(vals["dl"])], "forbid": _fmt(vals["ul"]), "gold": vals})
    cases.append({"id": "B2", "category": "方向", "question": f"{prod} 5GHz 80MHz 通道 42 的 Tx 吞吐量是多少？報告的 Tx 對應 DUT 的哪個方向？", "expect_all": [_fmt(vals["ul"]), ["上行"]], "forbid": [], "gold": vals})
    # C. 設備比較（Throughput 5GHz 80MHz 通道 42 下行）
    comp = []
    for p in PRODUCTS:
        r = one("""SELECT r.document_id, m.source_sheet, m.source_cell_range FROM km_test.test_measurement m JOIN km_test.test_run r USING (test_run_id)
                   WHERE r.dut_model=%s AND r.report_type='wifi_throughput' AND m.band='5GHz' AND m.bandwidth_mhz=80 AND m.channel=42 AND m.metric_name='throughput' AND m.direction='dl'""", (p,))
        if r:
            comp.append((p, float(cell(*r[0]))))
    if len(comp) >= 3:
        cases.append({"id": "C1", "category": "比較", "question": f"比較各設備 Throughput 報告中 5GHz 80MHz 通道 42 的下行吞吐量，請列出每台的數值。",
                      "expect_all": [_fmt(v) for _, v in comp], "forbid": ["較佳", "較差", "表現最好", "表現最差"], "gold": dict(comp)})
        two = comp[:2]
        cases.append({"id": "C2", "category": "比較", "question": f"{two[0][0]} 與 {two[1][0]} 在 Throughput 報告 5GHz 80MHz 通道 42 的下行吞吐量，誰比較好？",
                      "expect_all": [_fmt(v) for _, v in two], "forbid": ["較佳", "較差", "比較好", "表現較好", "優於", "勝過"], "gold": dict(two)})
    # D. 判定清單
    for i, p in enumerate(["CHS3320N-D388", "NCQ2200B2V-D294", "TP-Link Archer BE805"], 1):
        fails = one("""SELECT i.item_label FROM km_test.test_item_result i JOIN km_test.test_run r USING (test_run_id)
                       WHERE r.dut_model=%s AND r.report_type='wifi_throughput' AND i.result='fail' ORDER BY 1""", (p,))
        cases.append({"id": f"D{i}", "category": "判定", "question": f"{p} 的 Throughput 報告有幾個 Fail 的測項？",
                      "expect_all": [[str(len(fails)), f"{len(fails)} 個", f"{len(fails)}項"]], "forbid": [], "gold": {"fail_count": len(fails)}})
    cases.append({"id": "D4", "category": "判定", "question": "哪些設備的 RvR 報告有任何一個頻段判定為 Fail？", "expect_all": [["沒有", "皆", "全部", "均", "查不到", "無"]], "forbid": [], "gold": "RvR 各頻段判定均為 pass 或 n/a"})
    # E. 門檻（報告為準）
    r = one("""SELECT r.document_id, c.source_sheet, c.source_cell_range, c.criteria_value FROM km_test.criteria_reference c JOIN km_test.test_run r USING (test_run_id)
               WHERE r.dut_model='NCQ2200B2V-D294' AND r.report_type='wifi_throughput' AND c.band='5GHz' AND c.bandwidth_mhz=80 LIMIT 1""", ())
    if r:
        doc, sh, ref, v = r[0]
        wb = books[doc]
        cells = [c.value for row in wb[sh][ref] for c in row] if ":" in ref else [cell(doc, sh, ref)]
        assert v in [x for x in cells if isinstance(x, (int, float))], f"門檻 {v} 不在 {sh}!{ref} 的儲存格 {cells}"
        cases.append({"id": "E1", "category": "門檻", "question": "NCQ2200B2V-D294 的 Throughput 報告，5GHz 80MHz 的判定門檻是多少？", "expect_all": [_fmt(v)], "forbid": [], "gold": {"value": v, "cell": f"{sh}!{ref}"}})
    # F. 設備資訊
    for i, p in enumerate(["PKE3540J-D223", "TP-Link Archer BE800"], 1):
        r = one("SELECT firmware_version FROM km_test.test_run WHERE dut_model=%s AND report_type='wifi_throughput'", (p,))
        cases.append({"id": f"F{i}", "category": "設備資訊", "question": f"{p} 測試用的韌體版本是什麼？", "expect_all": [[r[0][0]]], "forbid": [], "gold": r[0][0]})
    # G. 蜂巢式
    r = one("""SELECT r.document_id, m.source_sheet, m.source_cell_range, m.test_case_id FROM km_test.test_measurement m JOIN km_test.test_run r USING (test_run_id)
               WHERE r.dut_model='SCU5050' AND m.metric_name='throughput' AND m.statistic='peak' AND m.direction='dl' AND m.test_case_id NOT LIKE '%%@None%%' ORDER BY m.test_case_id LIMIT 1""", ())
    if r:
        doc, sh, ref, tc = r[0]
        v = float(cell(doc, sh, ref))
        cases.append({"id": "G1", "category": "蜂巢式", "question": f"SCU5050 的 n78L 報告中，測項 {tc} 的下行 Peak 吞吐量是多少？", "expect_all": [_fmt(v)], "forbid": [], "gold": {"value": v, "cell": f"{sh}!{ref}", "case": tc}})
    # H. 不存在／不誘導／範圍外
    cases += [
        {"id": "H1", "category": "查無", "question": "ABC9999 的 5GHz 80MHz 下行吞吐量是多少？", "expect_all": [["查不到", "查無", "沒有", "找不到", "未收錄"]], "forbid_regex": [r"\d+(\.\d+)?\s*Mbps"], "forbid": [], "gold": "設備不存在"},
        {"id": "H2", "category": "查無", "question": "NCQ2200B2V-D294 的 6GHz 160MHz 下行吞吐量是多少？", "expect_all": [["查不到", "查無", "沒有", "找不到", "未收錄", "未提供"]], "forbid_regex": [r"6GHz[^。\n]{0,30}\d{3,}\s*Mbps"], "forbid": [], "gold": "報告無 6GHz"},
        {"id": "H3", "category": "不誘導", "question": "NCQ2200B2V-D294 是不是所有頻寬的吞吐量都比 PKE3540J-D223 好？請直接回答是或不是。", "expect_all": [], "forbid": ["是，", "是的"], "forbid_regex": [r"^是[。，\s]"], "gold": "不得使用較佳／較差下結論"},
        {"id": "H4", "category": "範圍外", "question": "今天台北的天氣如何？", "expect_all": [["報告", "知識庫", "無法", "不在", "只能", "只回答"]], "forbid": [], "gold": "範圍外"},
    ]
    Path(out).write_text(json.dumps(cases, ensure_ascii=False, indent=1), "utf-8")
    print(f"{len(cases)} 題 → {out}")


def score(case: dict, answer: str) -> dict:
    flat = answer.replace(",", "") if answer else ""
    miss = []
    for group in case.get("expect_all", []):
        if not any(s in answer or s in flat for s in group):
            miss.append(group[0])
    bad = [s for s in case.get("forbid", []) if s in answer or s in flat]
    bad += [rx for rx in case.get("forbid_regex", []) if re.search(rx, answer, re.M)]
    return {"pass": not miss and not bad, "missing": miss, "forbidden_hit": bad}


def run(cases_path: str, out: str, arms: list[str], repeat: int, only: set[str]) -> None:
    import psycopg
    from qdrant_client import QdrantClient
    from src.main import load_config
    from src.report_numeric import agent, vector
    from src.web_api.ollama_client import _build_primary_client
    client, _ = _build_primary_client(load_config())
    llm = lambda **kw: client.chat.completions.create(**kw)  # noqa: E731
    conn = psycopg.connect(os.environ["KM_TEST_NUMERIC_URL"], autocommit=True)
    qd = QdrantClient(url=os.environ["QDRANT_URL"], check_compatibility=False)
    _, enc, _ = vector.load_encoder()
    cases = [c for c in json.loads(Path(cases_path).read_text("utf-8")) if not only or c["id"] in only]
    results = []
    for rep in range(1, repeat + 1):
        for c in cases:
            for arm in arms:  # 一次只送一個請求
                tb = agent.ToolBox(conn, qd, enc, vector.query_sparse, only={"search_text"} if arm == "text" else None)
                kw = dict(schema=agent.TEXT_ONLY, system=agent.TEXT_ONLY_PROMPT) if arm == "text" else {}
                for attempt in range(3):
                    try:
                        r = agent.run_agent(c["question"], llm=llm, tools=tb, **kw)
                        break
                    except Exception as exc:  # 閘道偶爾逾時：重試，仍失敗就記錄
                        r = {"answer": "", "error": f"{type(exc).__name__}: {exc}", "trace": [], "ungrounded_numbers": [], "unknown_refs": [], "stop_reason": "error", "elapsed_ms": 0}
                        time.sleep(5)
                s = score(c, r["answer"])
                results.append({"id": c["id"], "category": c["category"], "arm": arm, "rep": rep, "question": c["question"], **s, "answer": r["answer"], "tools": [t["tool"] for t in r["trace"]],
                                "ungrounded_numbers": r["ungrounded_numbers"], "unknown_refs": r["unknown_refs"], "stop_reason": r["stop_reason"], "elapsed_ms": r["elapsed_ms"], "error": r.get("error")})
                print(f"{c['id']:4} {arm:5} rep{rep} {'PASS' if s['pass'] else 'FAIL'} {s['missing']} {s['forbidden_hit']} ungrounded={r['ungrounded_numbers']}", flush=True)
                Path(out).write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")
    for arm in arms:
        rs = [x for x in results if x["arm"] == arm]
        print(f"== {arm}: {sum(x['pass'] for x in rs)}/{len(rs)} 通過；有未佐證數字 {sum(bool(x['ungrounded_numbers']) for x in rs)}；中位數 {statistics.median(x['elapsed_ms'] for x in rs)} ms")
        for cat in sorted({x['category'] for x in rs}):
            sub = [x for x in rs if x["category"] == cat]
            print(f"   {cat}: {sum(x['pass'] for x in sub)}/{len(sub)}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "gen":
        gen(sys.argv[2], sys.argv[3])
    else:
        a = sys.argv
        opt = lambda k, d: a[a.index(k) + 1] if k in a else d  # noqa: E731
        run(a[2], a[3], opt("--arms", "tools,text").split(","), int(opt("--repeat", "1")), set(filter(None, opt("--only", "").split(","))))
