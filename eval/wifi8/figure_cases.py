"""圖片／圖表題：答案只在圖片裡（文件本文沒有），用來驗證圖片轉文字、檢索圖片與引用圖片。

標準圖片以「文件標題 + 位置 + 第幾張圖」指定，從匯出包的 images.jsonl 解析成 image_id（必須唯一）；
同一張圖表也出現在其他文件時一併列入，任一張都算答對。標準來源＝含這些圖片的文件。

用法：
  python figure_cases.py <匯出包解開的目錄> <golden-set.jsonl>
    只更新題庫中「圖片圖表」類的題目（其他題目原樣保留），沒有就加在最後。
  build_golden_set.py 產生整份題庫時，若 documents.jsonl 旁有 images.jsonl，也會自動加入這些題目。
"""
import json
import sys
from pathlib import Path

CATEGORY = "圖片圖表"

# (文件標題開頭, 第幾張圖, 位置) — 位置與 images.jsonl 的 location 相同（slide／page／paragraph；單獨圖片檔為 {}）
CASES = [
    dict(id="F01", question="Wi-Fi 8 的 DSO 和 Wi-Fi 7 的 Preamble Puncturing 比較表中，Purpose 各是什麼？",
         figures=[("Wi-Fi NOW - DSO-Comparison - Image", 1, {}),
                  ("Wi-Fi NOW - Wi-Fi 8 Guide Part Six - Dynamic Subchannel Operation(DSO)", 2, {"page": 3})],
         facts=[["避開", "避免", "avoid", "略過", "跳過", "不可用", "受干擾", "interfered", "unavailable"],
                ["暫時", "temporar"], ["另一", "其他", "another", "不同"]]),
    dict(id="F02", question="Wi-Fi Sensing 的居家監控用例中，感測結果如何用來控制 HVAC？",
         figures=[("WFA - Sensing TG Overview - 2027 Feature Release - v0.9", 6, {"slide": 5})],
         facts=[["Occupancy", "佔用", "占用", "有人", "人員", "在場", "存在"], ["HVAC", "空調"],
                ["Home Monitoring", "居家監控", "家庭監控", "家居監控"]]),
    dict(id="F03", question="根據 Wi-Fi NOW 的 Wi-Fi 8 時程圖，Wi-Fi 8 認證預計何時啟動？IEEE 802.11bn 最終標準預計何時核准？",
         figures=[("Wi-Fi NOW - Wi-Fi 8 Timeline - Estimated IEEE 802.11bn and Certification Milestones", 1, {})],
         facts=[["2028年1月", "January 2028", "Jan 2028", "2028/1", "2028-01", "2028年一月"],
                ["2028年5月", "May 2028", "2028/5", "2028-05", "2028年五月"]]),
    dict(id="F04", question="Wi-Fi 6 Spatial Reuse 和 Wi-Fi 8 Coordinated Spatial Reuse 的比較表中，功率控制（Power Control）有什麼不同？",
         figures=[("Wi-Fi NOW - Co-SR - Image", 1, {}),
                  ("Wi-Fi NOW - Wi-Fi 8 Guide Part Five - Coordinated Spatial Reuse(Co-SR)", 2, {"page": 2})],
         facts=[["自行", "各自", "自己", "own", "self", "獨立"], ["上限", "limit", "限制"]]),
    dict(id="F05", question="Wi-Fi 8 PF1 Report 的 APUT 結果表中，UHR-4.5.2 在 2.4G、5G、6G 的數值各是多少？",
         figures=[("WFA - Wi-Fi 8 PF1 Report", 1, {"slide": 6})],
         facts=[["25"], ["30"]]),
    dict(id="F06", question="Wi-Fi 8 EE1 Report 的 APUT 結果表中，UHR-4.2.1 在 2.4G、5G、6G 的數值各是多少？",
         figures=[("WFA - Wi-Fi 8 EE1 Report", 1, {"slide": 6})],
         facts=[["17"], ["13"], ["15"]]),
    dict(id="F07", question="Wi-Fi 世代優先事項演進圖中，Wi-Fi 6、Wi-Fi 7、Wi-Fi 8 各自聚焦在什麼？",
         figures=[("Wi-Fi NOW - The Evolution of Wi-Fi Priorities", 1, {}),
                  ("Wi-Fi NOW - Wi-Fi 8 Guide Part Two - Why Wi-Fi 8", 1, {"page": 1})],
         facts=[["效率", "efficien"], ["吞吐", "throughput", "最大效能", "maximum performance"], ["可靠", "reliab"]]),
    dict(id="F08", question="Multi-AP Coordination Toolbox 圖中列出哪幾項協同技術？",
         figures=[("Wi-Fi NOW - MultiAP Coordination Toolbox", 1, {}),
                  ("Wi-Fi NOW - Wi-Fi 8 Guide Part Four - Guide to Multi-AP coordination", 4, {"page": 4})],
         facts=[["Spatial Reuse", "空間重用", "空間複用", "Co-SR"], ["Beamforming", "波束成形", "波束賦形", "Co-BF"], ["OFDMA"], ["TDMA"],
                ["Channel Recommendation", "通道推薦", "通道建議", "頻道建議", "頻道推薦", "信道推薦", "信道建議"],
                ["TWT", "Target Wake Time", "目標喚醒"], ["Mobility", "漫遊", "移動"]]),
    dict(id="F09", question="MediaTek 的 Wi-Fi 4 到 Wi-Fi 8 比較表中，Wi-Fi 8 的最大通道頻寬、最高 PHY rate 和調變方式分別是什麼？",
         figures=[("MediaTek - Wi-Fi 8 - Challenges and Opportunities", 2, {"page": 2}),
                  ("來源待確認 - Wi-Fi 8 - 建立超可靠Wi-Fi通信時代", 12, {"page": 4}),
                  ("eefocue-與非網 - Wi-Fi 8，玩出新花樣！", 1, {"paragraph": 18})],
         facts=[["320"], ["23Gbps", "23Gb"], ["4096"]]),
]


def figure_cases(package_dir):
    package_dir = Path(package_dir)
    docs = [json.loads(line) for line in (package_dir / "documents.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    images = [json.loads(line) for line in (package_dir / "images.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    title = {d["revision_id"]: d["title"] for d in docs}

    def resolve(prefix, ordinal, location):
        rows = [i for i in images if title.get(i["revision_id"], "").startswith(prefix) and i["ordinal"] == ordinal
                and all(i["location"].get(k) == v for k, v in location.items())
                and next(d for d in docs if d["revision_id"] == i["revision_id"])["analysis_eligible"]]
        assert len(rows) == 1, (prefix, ordinal, location, len(rows))
        return rows[0]

    cases = []
    for spec in CASES:
        found = [resolve(*figure) for figure in spec["figures"]]
        gold = list(dict.fromkeys(i["revision_id"] for i in found))
        cases.append({"id": spec["id"], "category": CATEGORY, "question": spec["question"], "gold": gold, "facts": spec["facts"],
                      "gold_figures": list(dict.fromkeys(i["image_id"] for i in found)), "expect_refusal": False,
                      "gold_titles": [title[r] for r in gold],
                      "gold_figure_places": [f"{title[i['revision_id']]}｜{_place(i)}" for i in found]})
    return cases


def _place(image):
    location = image["location"]
    where = {"slide": "投影片 {}", "page": "第 {} 頁", "paragraph": "第 {} 段"}.get(location.get("type"), "")
    value = location.get(location.get("type"))
    return (where.format(value) + "・" if where and value is not None else "") + f"圖 {image['ordinal']}"


def main():
    package_dir, golden = sys.argv[1], Path(sys.argv[2])
    kept = [line for line in golden.read_text(encoding="utf-8").splitlines() if line.strip() and json.loads(line)["category"] != CATEGORY]
    added = figure_cases(package_dir)
    golden.write_text("\n".join(kept + [json.dumps(c, ensure_ascii=False) for c in added]) + "\n", encoding="utf-8")
    print(len(kept), "kept,", len(added), "figure cases")


if __name__ == "__main__":
    main()
