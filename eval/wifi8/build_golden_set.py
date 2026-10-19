"""由題目定義＋匯出包 documents.jsonl 產生 golden-set（標題→revision_id，必須唯一）。"""
import json, sys
docs = [json.loads(l) for l in open(sys.argv[1])]
out = sys.argv[2]
def rid(title, current=None):
    rows = [d for d in docs if d["title"] == title and (current is None or d["analysis_eligible"] == current)]
    assert len(rows) == 1, (title, len(rows))
    return rows[0]["revision_id"]
S = "Springer Nature - A Tutorial on Wi-Fi 8 - The Journey to Ultra High Reliability"
SPR = next(d["title"] for d in docs if d["title"].startswith(S))
SAM = next(d["title"] for d in docs if d["title"].startswith("Samsung - IEEE 802.11bn"))
MTK = next(d["title"] for d in docs if d["title"].startswith("MediaTek - Pioneering the Future with Wi-Fi 8 - Part One"))
RFW_DPS = next(d["title"] for d in docs if d["title"].startswith("RFWirelessWorld - Wi-Fi 8 Power Management"))
COTDMA = "WFA - Wi-Fi 8 MRD - Co-TDMA Contribution v12 - SP Changes Rev2 - 2026-03-25 - Comments"
MAPC = next(d["title"] for d in docs if d["title"].startswith("arXiv - A Tutorial on Wi-Fi 8 - Multi-AP Coordination-From"))
ASKEY = [d["title"] for d in docs if d["title"] == "Askey - Wi-Fi 8技術介紹_邁向極高可靠性新時代"]
REFUSE = ["沒有", "未提及", "未提供", "找不到", "查無", "無法", "不足", "未包含", "沒提到", "not found", "no information", "does not contain"]
cases = [
 # ---- 功能定義 ----
 dict(id="D01", category="功能定義", question="ELR 是什麼？在 Wi-Fi 8 認證中是上行還是下行功能？AP 要能接收哪些速率？",
      gold=[rid("WFA - Wi-Fi 8 MRD - ELR v4")], facts=[["PPDU"], ["UL", "uplink", "上行"], ["1.67"], ["3.33"]]),
 dict(id="D02", category="功能定義", question="NPCA 是什麼？它要解決什麼問題？",
      gold=[rid(SPR), rid(SAM), rid(MTK)], facts=[["NPCA primary", "non-primary", "非主", "次要通道", "其他 20 MHz", "secondary"], ["primary channel", "主通道", "主要通道", "primary 通道"], ["OBSS", "busy", "忙", "佔用", "被占用", "被佔用", "blocked"]]),
 dict(id="D03", category="功能定義", question="DSO（Dynamic Sub-band Operation）怎麼運作？",
      gold=[rid(SAM), rid(MTK), rid(SPR)], facts=[["sub-band", "subband", "sub-channel", "次頻段", "子頻段", "子通道", "子頻帶"], ["AP"], ["switch", "hop", "切換", "跳"]]),
 dict(id="D04", category="功能定義", question="Wi-Fi 8 的 DPS（Dynamic Power Save）是什麼？",
      gold=[rid(RFW_DPS), rid(SAM)], facts=[["Low Capability", "低能力"], ["High Capability", "高能力"]]),
 dict(id="D05", category="功能定義", question="Co-TDMA 在 Wi-Fi 8 MRD 中如何定義？對 AP 是必要還是選用？",
      gold=[rid(COTDMA)], facts=[["TXOP"], ["optional", "選用", "可選", "非必要"], ["MAPC"]]),
 dict(id="D06", category="功能定義", question="Co-BF 是什麼？適用哪些頻段？",
      gold=[rid("WFA - Wi-Fi 8 MRD - CoBF Contribution v9")], facts=[["5 GHz", "5GHz"], ["6 GHz", "6GHz"], ["interference", "干擾"]]),
 dict(id="D07", category="功能定義", question="DBE（Dynamic Bandwidth Expansion）是什麼？什麼情況下 AP 必須實作？",
      gold=[rid("WFA - Wi-Fi 8 MRD - DBE Contribution v5")], facts=[["BSS bandwidth", "BSS 頻寬", "頻寬"], ["WPA3-Enterprise", "WPA3 Enterprise"]]),
 dict(id="D08", category="功能定義", question="Bounded ESS 對 AP 的要求是什麼？哪些 AP 必須支援？",
      gold=[rid("WFA - Wi-Fi 8 MRD - Bounded ESS Contribution v3")], facts=[["Bounded ESS bit", "Bounded ESS 位元", "Bounded ESS 欄位"], ["AP Channel Report"], ["Mobile AP", "行動 AP"]]),
 dict(id="D09", category="功能定義", question="UEQM（Unequal Modulation）是什麼？有什麼限制？",
      gold=[rid(SPR)], facts=[["spatial stream", "SS", "空間串流", "空間流"], ["modulation", "調變", "constellation"], ["LDPC"]]),
 dict(id="D10", category="功能定義", question="DRU（Distributed Resource Unit）和一般 RU 有什麼不同？",
      gold=[rid(SPR)], facts=[["spread", "分散", "distribution bandwidth", "DBW", "分布", "分佈"], ["contiguous", "連續"]]),
 dict(id="D11", category="功能定義", question="SMD（Seamless Mobility Domain）是什麼？對漫遊有什麼幫助？",
      gold=[rid(SAM), rid(SPR)], facts=[["SMD-ME", "management entity", "管理實體"], ["roam", "漫遊", "transition", "轉移"], ["MLD", "multi-link", "多鏈路", "多連結"]]),
 # ---- 測試驗證 ----
 dict(id="T01", category="測試驗證", question="Wi-Fi 8 Security Profile 從哪一次 Plugfest 開始變成強制？",
      gold=[rid("WFA - Wi-Fi CERTIFIED 8 Test Plan Comments - 2026-10-08"), rid("WFA - Wi-Fi CERTIFIED 8 Test Plan Comments - 09202026 - v2 - 2026-09-20"), rid("WFA - Wi-Fi 8 TTG Minutes - 2026-06-09")],
      facts=[["PF2", "PF#2", "PF 2", "Plugfest 2", "第二次"]]),
 dict(id="T02", category="測試驗證", question="Wi-Fi 8 PF#1 是什麼時候舉行的？有多少 AP 和 STA 參加？Required goal 測試結果如何？",
      gold=[rid("WFA - Wi-Fi 8 PF1 Report")], facts=[["August 03", "Aug 3", "August 3", "8 月 3", "8/3", "08-03", "8月3"], ["6 APs", "6 個 AP", "6 AP", "6 台 AP", "6 x 7", "6x7"], ["7 STAs", "7 個 STA", "7 STA", "7 台 STA", "6 x 7", "6x7"], ["23"]]),
 dict(id="T03", category="測試驗證", question="PF#1 使用的 IEEE 規格草案和測試計畫是哪個版本？",
      gold=[rid("WFA - Wi-Fi 8 PF1 Report")], facts=[["D1.5"], ["0.0.3"]]),
 dict(id="T04", category="測試驗證", question="Co-TDMA 的 MAPC agreement 若透過 out-of-band 機制建立，認證會怎麼處理？",
      gold=[rid(COTDMA)], facts=[["over-the-air", "over the air", "空中", "OTA"], ["out of band", "out-of-band", "頻外", "帶外"], ["not tested", "不測試", "不會測試", "不進行測試", "不予測試", "allowed but not tested", "不測"]]),
 dict(id="T05", category="測試驗證", question="Navbits 少於 3888 時可以使用 2xLDPC 嗎？",
      gold=[rid("WFA - Wi-Fi 8 TTG Minutes - 2026-04-13")], facts=[["not allowed", "不允許", "不可", "不能", "不得", "不行"], ["3888"]]),
 # ---- 版本判斷 ----
 dict(id="V01", category="版本判斷", question="EMLSR Test Case 目前有效的是哪一版？",
      gold=[rid("WFA - Wi-Fi CERTIFIED 8 Test Case - EMLSR v1.7", True)], facts=[["1.7"]]),
 dict(id="V02", category="版本判斷", question="DL OFDMA Test Case 現行版本是哪一版？之前有哪些版本？",
      gold=[rid("WFA - Wi-Fi CERTIFIED 8 Test Case - DL OFDMA v6")], facts=[["v6", "V6", "version 6", "第 6 版", "第6版"], ["v4", "v3", "v2", "v1"]]),
 dict(id="V03", category="版本判斷", question="2xLDPC Test Case 有哪些版本？哪一版是目前版本？",
      gold=[rid("WFA - Wi-Fi CERTIFIED 8 Test Case - 2xLDPC v14")], facts=[["v14", "V14"], ["v8", "V8"], ["v5", "V5"]]),
 dict(id="V04", category="版本判斷", question="SMD Roaming testing scope 最新的是哪一版？",
      gold=[rid("WFA - SMD Roaming - testing - scope - and - TCVs - v1.5")], facts=[["1.5"]]),
 dict(id="V05", category="版本判斷", question="Wi-Fi 8 Technical Scope of Work 現行版本是哪一版？是否已經核准？",
      gold=[rid("WFA - Wi-Fi 8 Technical Scope of Work v1.0")], facts=[["1.0"], ["Board", "董事會", "理事會", "核准", "approved"]]),
 # ---- 會議紀錄 ----
 dict(id="M01", category="會議紀錄", question="2026-08-18 的 Wi-Fi 8 MTG 會議討論了哪些主題？下一次會議是什麼時候？",
      gold=[rid("WFA - Wi-Fi 8 MTG Minutes - 2026-08-18")], facts=[["PF1", "PF#1"], ["Security", "安全"], ["MRD 1.1"], ["09/08", "9/8", "9 月 8", "9月8", "September 8", "Sep 8", "09-08"]]),
 dict(id="M02", category="會議紀錄", question="Wi-Fi 8 Plugfest blind poll 有多少家公司回覆？調查期間？最早何時有足夠設備？",
      gold=[rid("WFA - Wi-Fi 8 Program Feature Ballot Package - Results")], facts=[["24"], ["April 6", "4 月 6", "4/6", "4月6", "04-06"], ["August 2026", "2026 年 8 月", "2026-08", "2026年8月", "Aug 2026"]]),
 dict(id="M03", category="會議紀錄", question="Wi-Fi 8 Marketing Task Group（MTG）的主席是誰？來自哪家公司？",
      gold=[rid("WFA - Wi-Fi 8 MTG Minutes - 2026-08-18")], facts=[["Manish Kumar"], ["NXP"]]),
 # ---- 廠商產品 ----
 dict(id="P01", category="廠商產品", question="Broadcom BCM43840 和 BCM43820 有什麼差異？",
      gold=[rid("Broadcom - BCM43840 and BCM43820 Wi-Fi 8 Access Point Product Brief - 2025-09-26")], facts=[["4x4"], ["2x2"], ["320 MHz", "320MHz"]]),
 dict(id="P02", category="廠商產品", question="Broadcom BCM6718 支援哪些 Wi-Fi 8 功能？最高調變是多少？",
      gold=[rid("Broadcom - BCM6718 Wi-Fi 8 Access Point Product Brief - 2026-05-18")], facts=[["DSO"], ["NPCA"], ["DBE"], ["ELR"], ["4K-QAM", "4K QAM", "4096-QAM", "4096 QAM"]]),
 dict(id="P03", category="廠商產品", question="Broadcom Wi-Fi 8 產品規劃中第 5 波（5th Wave）包含哪些晶片？",
      gold=[rid("Broadcom - 5th Wave Wi-Fi 8 Launch - The Mass-Market Transition")], facts=[["BCM6772"], ["BCM6774"], ["BCM6776"]]),
 dict(id="P04", category="廠商產品", question="Keysight 的 Wi-Fi 7&8 設計驗證簡報是誰講的？什麼時候？",
      gold=[rid("Keysight - Wi-Fi 7&8設計驗證與效能分析")], facts=[["Tim Huang"], ["2025"]]),
 # ---- 研究與內部 ----
 dict(id="R01", category="研究與內部", question="IEEE 802.11bn 定義了哪些主要的 MAPC 方案？",
      gold=[rid(MAPC)], facts=[["Co-BF", "CoBF"], ["Co-SR", "CoSR"], ["Co-TDMA", "CoTDMA"]]),
 dict(id="R02", category="研究與內部", question="Askey 的 Wi-Fi 8 技術介紹簡報預計 Wi-Fi 8 什麼時候全面成熟？",
      gold=[d["revision_id"] for d in docs if d["title"] == ASKEY[0]], facts=[["2028"]]),
 # ---- 總覽統計（隨匯入資料改變） ----
 dict(id="O01", category="總覽統計", question="WiFi 專區目前有多少份有效文件？其中 WFA 的有幾份？",
      gold=[], facts=[["368"], ["220"]], package_id="wifi8-0216bc31ebf95107"),
 # ---- 應拒答 ----
 dict(id="N01", category="應拒答", question="Wi-Fi 8 認證每台設備的認證費用是多少美元？",
      gold=[], facts=[], expect_refusal=True, refusal_markers=REFUSE, must_not_regex=[r"US\$ ?\d|\$ ?\d[\d,]*|\d[\d,]* ?(美元|USD)"]),
 dict(id="N02", category="應拒答", question="Askey 哪一款 Wi-Fi 8 產品已經通過 WFA 認證？",
      gold=[], facts=[], expect_refusal=True, refusal_markers=REFUSE),
 dict(id="N03", category="應拒答", question="Wi-Fi 8 PF#3 的舉辦日期和地點是什麼？",
      gold=[], facts=[], expect_refusal=True, refusal_markers=REFUSE),
]

# ---- 人工審核後擴充的標準來源（原則：領域人員會接受為此題依據的文件；特定文件／版本題不擴充）----
import re as _re, collections as _col
def T(title):
    rows = [d for d in docs if d["title"] == title and d["analysis_eligible"]]
    assert len(rows) == 1, (title, len(rows))
    return rows[0]["revision_id"]
_text = _col.defaultdict(str)
for _line in open(sys.argv[1].replace("documents.jsonl", "segments.jsonl")):
    _s = json.loads(_line); _text[_s["revision_id"]] += "\n" + _s["text"]
_n = lambda t: _re.sub(r"\s+", "", t).casefold()
def having(*terms, title=""):
    return [d["revision_id"] for d in docs if d["analysis_eligible"] and title.lower() in d["title"].lower()
            and all(_n(x) in _n(_text[d["revision_id"]]) for x in terms)]
MRD = T("WFA - Wi-Fi 8 MRD v1.0")
EXTRA = {
    "D01": [MRD, T("WFA - Wi-Fi CERTIFIED 8 Test Case - ELR v1"), T(SPR), T(SAM), T(next(d["title"] for d in docs if d["title"].startswith("MediaTek - Pioneering the Future with Wi-Fi 8 - Part Three")))],
    "D02": [MRD, T("WFA - Wi-Fi 8 MRD - NPCA Contribution v0.6"), T("Wi-Fi NOW - Wi-Fi 8 Guide Part Seven - Non-Primary Channel Access(NPCA)"),
            T("RFWirelessWorld - What is Non-Primary Channel Access (NPCA) in Wi-Fi 8")],
    "D03": [MRD, T("WFA - Wi-Fi 8 MRD - DSO feature description v7")],
    "D04": [MRD, T("WFA - Wi-Fi 8 MRD - DPS assisting STA v5"), T("WFA - Wi-Fi 8 MRD - DPS feature description v6 - Apple-Intel"),
            T("arXiv - A Primer on AP Power Save in Wi-Fi 8 - Overview, Analysis, and Open Challenges"), T(SPR)],
    "D05": [MRD, T("WFA - Overview of Co-TDMA TCVs"), T("WFA - Wi-Fi CERTIFIED 8 Test Case - CoTDMA for D2p1"), T(MAPC)],
    "D06": [MRD, T("WFA - Wi-Fi 8 MRD - CoBF Contribution v8 SP changes rev2 - Comments"), T(MAPC)],
    "D07": [MRD],
    "D08": [MRD, T("WFA - Bounded ESS for SMD BSS transition"), T("WFA - Wi-Fi CERTIFIED 8 Test Case - Bounded ESS v0")],
    "D09": [MRD, T("WFA - Wi-Fi 8 MRD - UEQM v2"), T(SAM)],
    "D10": [MRD, T("WFA - Wi-Fi 8 MRD - DRU v6"), T(SAM), T("RFWirelessWorld - RRU vs. DRU in Wi-Fi 8_ Key Differences & Benefits"),
            T("Rohde & Schwarz - Understanding Wi-Fi 8 - Unmatched reliability, efficiency and speed"), T("eefocue-與非網 - Wi-Fi 8新特性 - DRU"),
            T("Rohde & Schwarz - Setting New Performance Standards with IEEE 802.11bn - V01"),
            T("Rohde & Schwarz - Setting New Performance Standards with IEEE 802.11bn - V02")],
    # The question asks which versions exist: every 2xLDPC Test Case revision (current or not) is a valid source.
    "V03": [d["revision_id"] for d in docs if d["title"].startswith("WFA - Wi-Fi CERTIFIED 8 Test Case - 2xLDPC")],
    "D11": [MRD, T("WFA - Wi-Fi 8 MRD - SMD Roaming Contribution v10"), T("WFA - SMD Roaming - testing - scope - and - TCVs - v1.5"),
            T(next(d["title"] for d in docs if d["title"].startswith("arXiv - Towards Ultra-High Reliability in Wi-Fi 8")))],
    "T02": having("PF#1", "23 out of 23", title="TTG Agenda"),
    "T03": [T("WFA - Wi-Fi 8 TTG Minutes - 2026-07-27")],
    "T04": [MRD, T("WFA - Overview of Co-TDMA TCVs"), T("WFA - Wi-Fi CERTIFIED 8 Test Case - CoTDMA for D2p1")],
    "T05": [T("WFA - 2xLDPC Navbits computation update v2"), T("WFA - Wi-Fi CERTIFIED 8 Test Case - 2xLDPC v14")],
    "M01": [T("WFA - Wi-Fi 8 MTG Agenda - 2026-08-18 v1")],
    "M03": having("Manish Kumar", "NXP", title="MTG"),
    "R01": having("Co-BF", "Co-SR", "Co-TDMA", "MAPC"),
}
for c in cases:
    c["gold"] = list(dict.fromkeys(c["gold"] + EXTRA.get(c["id"], [])))
# 圖片圖表題（eval/wifi8/figure_cases.py）：匯出包 v2 才有 images.jsonl
import os as _os
if _os.path.exists(sys.argv[1].replace("documents.jsonl", "images.jsonl")):
    sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from figure_cases import figure_cases
    _figures = figure_cases(_os.path.dirname(_os.path.abspath(sys.argv[1])))
else:
    _figures = []
# 行為題（eval/wifi8/behavior_cases.py）：需要 segments.jsonl 計算列舉題的標準清單
if _os.path.exists(sys.argv[1].replace("documents.jsonl", "segments.jsonl")):
    sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from behavior_cases import behavior_cases
    _figures = _figures + behavior_cases(_os.path.dirname(_os.path.abspath(sys.argv[1])))
with open(out, "w", encoding="utf-8") as f:
    for c in cases:
        c.setdefault("expect_refusal", False)
        c["gold_titles"] = [next(d["title"] for d in docs if d["revision_id"] == r) for r in c["gold"]]
        f.write(json.dumps(c, ensure_ascii=False) + "\n")
    for c in _figures:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")
print(len(cases) + len(_figures), "cases")
