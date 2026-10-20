"""覆蓋補強題：多輪追問、錯誤前提、口語改寫、跨文件比較、數值計算。

這五類原本題庫沒有或太少。事實取自匯出包原文，不寫死在程式裡：
* evidence 是（來源代號, 原文片段）；產生題目時逐一確認片段真的出現在該來源的目前版本文件中，找不到就中止；
* 數值計算題另附 calc，算出的結果必須等於 facts 的第一個寫法；
* 標準來源可用 gold_like 沿用題庫既有題目的 gold（例如口語改寫題沿用對應「功能定義」題），也可用 gold_titles 指定標題開頭，
  或用 gold_where（一組 regex）取「內文同時符合全部 regex」的目前版本文件（同一份行程表會重複出現在許多議程裡時用）；
* 多輪追問題的 history 是先前的問答（助理那句也要有 evidence 支持）；有 history 的題目不計檢索分數，因為追問本身不是自足的檢索問題。

用法：
  python coverage_cases.py <匯出包解開的目錄> <golden-set.jsonl>
    只更新本檔負責的類別（其他題目原樣保留），沒有就加在最後。gold_like 引用的題目要已在 golden-set 內。
  build_golden_set.py 產生整份題庫時，若有 segments.jsonl 也會自動加入這些題目。
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

CATEGORIES = ["多輪追問", "錯誤前提", "口語改寫", "跨文件比較", "數值計算"]

# 來源代號 → 標題開頭（只取目前版本）
SOURCES = {
    "pf1": "WFA - Wi-Fi 8 PF1 Report",
    "ee1": "WFA - Wi-Fi 8 EE1 Report",
    "ballot": "WFA - Wi-Fi 8 Program Feature Ballot Package - Results",
    "elr": "WFA - Wi-Fi 8 MRD - ELR v4",
    "npca06": "WFA - Wi-Fi 8 MRD - NPCA Contribution v0.6",
    "mrd10": "WFA - Wi-Fi 8 MRD v1.0",
    "dps": "WFA - Wi-Fi 8 MRD - DPS feature description",
    "cotdma": "WFA - Overview of Co-TDMA TCVs",
    "bounded": "WFA - Bounded ESS for SMD BSS transition",
    "agenda": "WFA - Wi-Fi 8 TTG Agenda - 2026-10-12",
    "tpc": "WFA - Wi-Fi CERTIFIED 8 Test Plan Comments - 09202026",
}

NEGATION = ["不對", "並非", "不是", "不正確", "有誤", "不符", "錯", "incorrect"]
MANDATORY = ["必要", "mandatory", "必須"]
UPLINK = ["UL", "uplink", "上行"]
SMD_ROAMING = ["SMD Roaming", "SMD"]


def turn(question, answer):
    return [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]


# id, category, question, facts, gold_like／gold_titles, evidence，其餘欄位（history、calc）
CASES = [
    # ---- 多輪追問：追問用代名詞或省略主詞，必須承接前一輪 ----
    dict(id="H01", category="多輪追問", question="那它對 5 GHz 或 6 GHz 的 AP 是必要還是選用？",
         history=turn("NPCA 是什麼？", "Non-Primary Channel Access（NPCA）是 802.11bn 定義的功能，讓 AP 與 STA 在主頻道偵測到 OBSS 活動時，改到次要子頻帶中的替代主頻道傳輸。"),
         facts=[MANDATORY], gold_like="B05",
         evidence=[("npca06", "is mandatory for APs that support 5 GHz or 6 GHz")]),
    dict(id="H02", category="多輪追問", question="那 EE1 呢？",
         history=turn("PF1 有多少台 AP 與 STA 參加？", "Wi-Fi 8 PF#1 有 6 台 AP 與 7 台 STA 參加。"),
         facts=[["4"], ["7"]], gold_titles=["WFA - Wi-Fi 8 EE1 Report"],
         evidence=[("pf1", "6 APs x 7 STAs participated"), ("ee1", "4 APs x 7 STAs participated")]),
    dict(id="H03", category="多輪追問", question="它是上行還是下行？",
         history=turn("ELR 是什麼？", "ELR（Enhanced Long Range）是一種新的 PPDU 格式，用來提高遠距離連線的穩健度。"),
         facts=[UPLINK], gold_like="D01",
         evidence=[("elr", "ELR (Enhanced Long Range) is a new PPDU format"), ("elr", "ELR is only defined for UL operation")]),
    dict(id="H04", category="多輪追問", question="那 PF#3 要審查哪些 Test Case？",
         history=turn("2026-10-12 的 TTG 議程要審查哪一天的會議紀錄？", "要審查 2026 年 9 月 28 日的會議紀錄。"),
         facts=[["NPCA"], ["DPS"], SMD_ROAMING], gold_like="B01",
         evidence=[("agenda", "Latest minutes September 28, 2026"), ("agenda", "NPCA Test Case"), ("agenda", "DPS Test Case"),
                   ("agenda", "SMD Roaming Test Case")]),
    dict(id="H05", category="多輪追問", question="有多少家公司回覆？",
         history=turn("Wi-Fi 8 Plugfest Blind Poll 是什麼時候進行的？", "Blind Poll 在 2026 年 4 月 6 日至 20 日進行。"),
         facts=[["24"]], gold_like="M02",
         evidence=[("ballot", "fielded April 6-20, 2026"), ("ballot", "24 companies responded to the survey")]),

    # ---- 錯誤前提：問題帶著錯的前提，要指出並給出原文的正確值 ----
    dict(id="W01", category="錯誤前提", question="ELR 是下行功能，AP 要能接收哪些速率？",
         facts=[UPLINK, ["1.67"], ["3.33"], NEGATION], gold_like="D01",
         evidence=[("elr", "ELR is only defined for UL operation"), ("elr", "1.67 Mbps and 3.33 Mbps")]),
    dict(id="W02", category="錯誤前提", question="Blind Poll 有 30 家公司回覆，對嗎？",
         facts=[["24"], NEGATION], gold_like="M02", evidence=[("ballot", "24 companies responded to the survey")]),
    dict(id="W03", category="錯誤前提", question="Security Profile 從 PF1 就開始強制，對嗎？",
         facts=[["PF2", "PF#2", "Plugfest 2", "第二次"], NEGATION], gold_like="T01",
         evidence=[("tpc", "Starting with PF2, the Security Profile will be mandatory")]),
    dict(id="W04", category="錯誤前提", question="PF1 是 2026 年 6 月舉行的，對嗎？",
         facts=[["August", "8 月", "8月", "Aug", "2026-08", "8/3"], NEGATION], gold_like="T02",
         evidence=[("pf1", "PF#1 was conducted from August 03")]),
    dict(id="W05", category="錯誤前提", question="NPCA 對 5 GHz 或 6 GHz 的 AP 是選用功能，對嗎？",
         facts=[MANDATORY, NEGATION], gold_like="B05",
         evidence=[("npca06", "is mandatory for APs that support 5 GHz or 6 GHz")]),

    # ---- 口語改寫：不用文件裡的術語，測語意檢索 ----
    dict(id="Y01", category="口語改寫", question="有沒有一種功能，讓手機平常用低規格待命省電，收到 AP 的通知才切回全速？",
         facts=[["DPS", "Dynamic Power Save", "dynamic power save"]], gold_like="D04",
         evidence=[("dps", "allows a STA to listen or exchange frames in low capability (LC) mode")]),
    dict(id="Y02", category="口語改寫", question="Wi-Fi 8 有沒有新的傳輸格式，是專門讓距離很遠的設備上傳時比較不容易斷線？",
         facts=[["ELR", "Enhanced Long Range"]], gold_like="D01",
         evidence=[("elr", "designed to improve the robustness of the link at long range")]),
    dict(id="Y03", category="口語改寫", question="主要頻道被別人的網路占住的時候，可以改用旁邊的頻道繼續傳，這是 Wi-Fi 8 哪個功能？",
         facts=[["NPCA", "Non-Primary Channel Access", "Non-primary Channel Access"]], gold_like="D02",
         evidence=[("npca06", "alternate primary channel"), ("npca06", "when OBSS activity is detected on the BSS primary channel")]),
    dict(id="Y04", category="口語改寫", question="好幾台 AP 怎麼約好輪流使用時間，避免互相搶頻道？Wi-Fi 8 有對應的功能嗎？",
         facts=[["Co-TDMA", "Coordinated TDMA"]], gold_like="D05",
         evidence=[("cotdma", "MAPC Co-TDMA agreement success")]),
    dict(id="Y05", category="口語改寫", question="手機在不同 AP 之間走動時，Wi-Fi 8 有什麼機制讓切換更順、資料不掉？",
         facts=[["SMD", "Seamless Mobility", "Bounded ESS"]], gold_like="D11",
         evidence=[("bounded", "enables faster and more seamless roaming between AP MLDs within an SMD")]),

    # ---- 跨文件比較：答案分散在兩份以上文件 ----
    dict(id="X01", category="跨文件比較", question="EE1 與 PF1 各自使用哪一版 IEEE 規格草案？",
         facts=[["D1.4"], ["D1.5"]], gold_titles=["WFA - Wi-Fi 8 EE1 Report", "WFA - Wi-Fi 8 PF1 Report"],
         evidence=[("ee1", "Draft P802.11bn_D1.4"), ("pf1", "Draft P802.11bn_D1.5")]),
    dict(id="X02", category="跨文件比較", question="EE1 與 PF1 各自使用哪一版 Wi-Fi CERTIFIED 8 測試計畫？",
         facts=[["0.0.1"], ["0.0.3"]], gold_titles=["WFA - Wi-Fi 8 EE1 Report", "WFA - Wi-Fi 8 PF1 Report"],
         evidence=[("ee1", "Wi-Fi CERTIFIED 8 Test Plan v0.0.1"), ("pf1", "Wi-Fi CERTIFIED 8 Test Plan v0.0.3")]),
    dict(id="X03", category="跨文件比較", question="PF1 實際參加的 AP 與 STA 數量，有達到 Blind Poll 回報的最低開辦要求嗎？",
         facts=[["5"], ["6"], ["7"], ["達到", "足夠", "符合", "滿足", "超過", "達標", "高於", "多於"]],
         gold_titles=["WFA - Wi-Fi 8 PF1 Report", "WFA - Wi-Fi 8 Program Feature Ballot Package - Results"],
         evidence=[("ballot", "Minimum number of devices to hold a Plugfest: 5 APs and 5 STAs"), ("pf1", "6 APs x 7 STAs participated")]),
    dict(id="X04", category="跨文件比較", question="EE1 的 STAUT 有幾個 test case variations 達到至少 1x1 涵蓋？PF1 的 Required goal 有沒有全部通過？",
         facts=[["16"], ["23"], ["全部", "全數", "皆", "100%", "all"]],
         gold_titles=["WFA - Wi-Fi 8 EE1 Report", "WFA - Wi-Fi 8 PF1 Report"],
         evidence=[("ee1", "16 out of 20 test case variations achieved at least 1x1 coverage"),
                   ("pf1", "23 out of 23 Required goal test case variations passed")]),
    dict(id="X05", category="跨文件比較", question="NPCA 在 Wi-Fi 8 MRD v1.0 與 NPCA Contribution v0.6 中，對 5 GHz 或 6 GHz AP 的要求一致嗎？",
         facts=[MANDATORY, ["一致", "相同", "都", "同樣"]], gold_like="B05",
         evidence=[("mrd10", "is mandatory for APs that support 5 GHz or 6 GHz"), ("npca06", "is mandatory for APs that support 5 GHz or 6 GHz")]),

    # ---- 數值計算：原文只給運算元，答案要自己算（calc 在產生題目時驗算） ----
    dict(id="C01", category="數值計算", question="PF1 的 Required goals 與 Stretch goals 中，APUT 的測試案例合計幾個？",
         facts=[["21"]], gold_titles=["WFA - Wi-Fi 8 PF1 Report"], calc=lambda: 12 + 9,
         evidence=[("pf1", "Required Goals (APUT: 12; STAUT: 11)"), ("pf1", "Stretch Goals (APUT: 9; STAUT: 9)")]),
    dict(id="C02", category="數值計算", question="PF1 有 6 台 AP 與 7 台 STA 參加，兩兩配對最多有幾種組合？",
         facts=[["42"]], gold_titles=["WFA - Wi-Fi 8 PF1 Report"], calc=lambda: 6 * 7,
         evidence=[("pf1", "6 APs x 7 STAs participated")]),
    dict(id="C03", category="數值計算", question="Blind Poll 顯示，預計參加 Plugfest 與 Test Bed 的 STA 合計幾台？",
         facts=[["18"]], gold_titles=["WFA - Wi-Fi 8 Program Feature Ballot Package - Results"], calc=lambda: 11 + 7,
         evidence=[("ballot", "including 14 APs and 11 STAs"), ("ballot", "including 7 APs and 7 STAs")]),
    dict(id="C04", category="數值計算", question="PF#1 開始日到 PF#2 開始日相隔幾天？",
         facts=[["63", "九週", "9 週", "9 weeks", "nine weeks"]], gold_titles=["WFA - Wi-Fi 8 PF1 Report"],
         gold_where=[r"PF#?1\W+(\|\W*)?August 3", r"PF#?2\W+(\|\W*)?October 5"],
         calc=lambda: (date(2026, 10, 5) - date(2026, 8, 3)).days,
         evidence=[("pf1", "PF#1 | August 3-14, 2026"), ("pf1", "PF#2 | October 5-16, 2026")]),
    dict(id="C05", category="數值計算", question="EE1 的 APUT 與 STAUT 測試案例合計幾個？",
         facts=[["41"]], gold_titles=["WFA - Wi-Fi 8 EE1 Report"], calc=lambda: 21 + 20,
         evidence=[("ee1", "21 APUT test cases and 20 STAUT test cases")]),
]


def _read(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _plain(text):
    """原文常見的不換行連字號、en dash 與連續空白，比對前統一。"""
    text = str(text).replace("‑", "-").replace("–", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def coverage_cases(package_dir, golden_path):
    package_dir = Path(package_dir)
    docs = _read(package_dir / "documents.jsonl")
    current = [d for d in docs if d["analysis_eligible"]]
    golden = {c["id"]: c for c in _read(golden_path) if c["category"] not in CATEGORIES}
    text_by_revision = {}
    for segment in _read(package_dir / "segments.jsonl"):
        text_by_revision.setdefault(segment["revision_id"], []).append(segment["text"])
    source_text = {}
    for key, prefix in SOURCES.items():
        revisions = [d["revision_id"] for d in current if d["title"].startswith(prefix)]
        assert revisions, f"沒有目前版本文件的標題以「{prefix}」開頭（來源 {key}）"
        source_text[key] = _plain("\n".join(t for r in revisions for t in text_by_revision.get(r, [])))

    def resolve(prefix):
        found = [d["revision_id"] for d in current if d["title"].startswith(prefix)]
        assert found, f"沒有目前版本文件的標題以「{prefix}」開頭"
        return found

    cases = []
    for spec in CASES:
        for key, snippet in spec["evidence"]:
            assert _plain(snippet) in source_text[key], f"{spec['id']}：來源 {key} 找不到原文片段「{snippet}」"
        if spec.get("calc"):
            assert str(spec["calc"]()) in spec["facts"][0], f"{spec['id']}：驗算 {spec['calc']()} 不在 facts {spec['facts'][0]}"
        gold = []
        if spec.get("gold_like"):
            gold += golden[spec["gold_like"]]["gold"]
        gold += [r for prefix in spec.get("gold_titles", []) for r in resolve(prefix)]
        if spec.get("gold_where"):
            matched = [d["revision_id"] for d in current
                       if all(re.search(p, _plain("\n".join(text_by_revision.get(d["revision_id"], [])))) for p in spec["gold_where"])]
            assert matched, f"{spec['id']}：沒有文件同時符合 gold_where"
            gold += matched
        gold = list(dict.fromkeys(gold))
        title_of = {d["revision_id"]: d["title"] for d in docs}
        case = {"id": spec["id"], "category": spec["category"], "question": spec["question"], "gold": gold, "facts": spec["facts"],
                "expect_refusal": False, "gold_titles": [title_of[r] for r in gold]}
        if spec.get("history"):
            case["history"] = spec["history"]
        cases.append(case)
    ids = [c["id"] for c in cases] + list(golden)
    assert not {c["id"] for c in cases} & set(golden), "題目編號與其他題目重複"
    assert len(ids) == len(set(ids)), "題目編號與題庫重複"
    return cases


def main():
    package_dir, golden = sys.argv[1], Path(sys.argv[2])
    kept = [line for line in golden.read_text(encoding="utf-8").splitlines() if line.strip() and json.loads(line)["category"] not in CATEGORIES]
    added = coverage_cases(package_dir, golden)
    golden.write_text("\n".join(kept + [json.dumps(c, ensure_ascii=False) for c in added]) + "\n", encoding="utf-8")
    print(len(kept), "kept,", len(added), "coverage cases")


if __name__ == "__main__":
    main()
