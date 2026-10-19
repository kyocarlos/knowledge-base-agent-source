import math

from src.wifi8.grounding import GroundingSettings, check_answer, extract_values, split_claims

SOURCES = {
    "S1": {"text": "DBE is optional for APs, and only applicable to 5 GHz and 6 GHz band APs. "
                   "If WPA3-Enterprise is implemented, the AP shall implement DBE.", "publisher": "WFA", "analysis_eligible": True},
    "S2": {"text": "ELR Rx support: the AP receives ELR 1.67 Mbps and 3.33 Mbps PPDUs in each supported band.",
           "publisher": "Wi-Fi NOW", "analysis_eligible": True},
    "S3": {"text": "Old draft text.", "publisher": "WFA", "analysis_eligible": False},
}

ANSWER = """## 結論

**DBE 對 AP 是選用功能，只適用 5 GHz 與 6 GHz。** 若 AP 實作 WPA3-Enterprise，就必須實作 DBE。[S1]

### 補充
- AP 需能接收 1.67 Mbps 與 3.33 Mbps 的 ELR PPDU。[S1]
- DBE 最高可擴展到 640 MHz 的頻寬設定。

| 項目 | 說明 |
|---|---|
| ELR 速率 | 1.67 Mbps、3.33 Mbps [S2] |
"""


def test_split_claims_skips_headings_and_inherits_line_refs():
    claims = split_claims(ANSWER)
    texts = [c["text"] for c in claims]
    assert not any(t.startswith(("結論", "補充")) for t in texts)
    first = next(c for c in claims if c["text"].startswith("DBE 對 AP 是選用"))
    assert first["refs"] == ["S1"] and not first["own_refs"]  # the line's [S1] supports both sentences
    assert next(c for c in claims if "640 MHz" in c["text"])["refs"] == ["S1"]  # same list as a cited item
    assert any(c["text"].startswith("ELR 速率") and c["refs"] == ["S2"] for c in claims)


def test_values_are_checked_against_full_cited_text():
    result = check_answer(ANSWER, SOURCES)
    rates = next(c for c in result["claims"] if c["text"].startswith("AP 需能接收"))
    assert {v["value"]: v["status"] for v in rates["values"]} == {"1.67 Mbps": "other_source", "3.33 Mbps": "other_source"}
    table = next(c for c in result["claims"] if c["text"].startswith("ELR 速率"))
    assert all(v["status"] == "verified" for v in table["values"])
    wpa = next(c for c in result["claims"] if "WPA3" in c["text"])
    assert {v["value"]: v["status"] for v in wpa["values"]} == {"WPA3-Enterprise": "verified"}
    s = result["summary"]
    assert s["claims_cited"] == s["claims"]
    assert s["values_not_found"] == 1  # 640 MHz appears in no source
    assert s["sources"] == {"total": 2, "wfa": 1, "current": 2}
    reasons = {f["text"][:10]: f["reasons"] for f in result["flagged"]}
    assert any(r == ["value_not_found"] for r in reasons.values())


def test_extract_values_handles_chinese_context_and_symbols():
    assert extract_values("是BCM6718支援4K-QAM與 320 MHz") == ["BCM6718", "4K-QAM", "320 MHz"]
    assert extract_values("BCM43840 是 4×4，Wi\u2011Fi 8 規格 v1.7") == ["BCM43840", "4x4", "v1.7"]
    assert extract_values("第 3 段沒有數值") == []


def test_similarity_levels_follow_thresholds():
    def encoder(texts):  # identical text -> 1.0; otherwise orthogonal unless it shares the word "DBE"
        return [[1.0, 0.0] if "DBE" in t else [0.0, 1.0] for t in texts]
    result = check_answer(ANSWER, SOURCES, encoder=encoder, settings=GroundingSettings(similarity=True, similarity_high=0.9, similarity_low=0.5))
    levels = {c["text"]: c["similarity_level"] for c in result["claims"]}
    assert next(v for k, v in levels.items() if k.startswith("DBE 對 AP 是")) == "high"
    assert set(levels.values()) <= {"high", "medium", "low"}
    assert all(c["similarity"] is None or math.isclose(c["similarity"], round(c["similarity"], 4)) for c in result["claims"])


def test_check_without_answer_or_sources():
    empty = check_answer("", {})
    assert empty["summary"]["claims"] == 0 and empty["flagged"] == []


def test_similarity_is_off_by_default():
    result = check_answer(ANSWER, SOURCES, encoder=lambda texts: [[1.0, 0.0]] * len(texts))
    assert result["summary"]["similarity_enabled"] is False
    assert all(c["similarity"] is None for c in result["claims"])
    assert not any("low_similarity" in f["reasons"] for f in result["flagged"])


def test_tool_data_supports_values_and_uncited_tables():
    answer = """版本如下：

| 版本 | WFA ID |
|---|---|
| v14 | 103720 |
| v8 | 103248 |

目前有效文件共 368 份，其中 WFA 有 220 份。
另外推測最新版是 v99。"""
    context = 'question\n{"versions": [{"version_label": "v14", "wfa_document_id": "103720"}, {"version_label": "v8", "wfa_document_id": "103248"}]}\n{"current_documents": 368, "by_publisher": [["WFA", 220]]}'
    result = check_answer(answer, {}, context=context)
    support = {c["text"]: c["support"] for c in result["claims"]}
    assert support["v14：103720"] == "tool_data" and support["v8：103248"] == "tool_data"
    assert support["目前有效文件共 368 份，其中 WFA 有 220 份。"] == "tool_data"
    assert support["另外推測最新版是 v99。"] == "none"
    s = result["summary"]
    assert s["values_not_found"] == 1 and s["values_tool_data"] == s["values"] - 1 and s["claims_tool_data"] == 3
    assert [f["text"] for f in result["flagged"]] == ["另外推測最新版是 v99。"]


def test_list_items_inherit_the_intro_line_and_refusals_are_not_claims():
    answer = "支援下列功能：[S2]\n\n- Low Latency Indication\n- Seamless Roaming support\n\n另一段沒有來源的說明文字在這裡出現。\n- 這個項目不該沿用引用的內容喔\n\n目前已取得的工具結果未列出 PF#3 的舉辦地點，因此尚未查證。"
    refs = {c["text"]: c["refs"] for c in split_claims(answer)}
    assert refs == {"Low Latency Indication": ["S2"], "Seamless Roaming support": ["S2"],
                    "另一段沒有來源的說明文字在這裡出現。": [], "這個項目不該沿用引用的內容喔": []}


def test_value_matching_boundaries_units_ordinals_and_underscores():
    from src.wifi8.grounding import _norm, _value_in
    assert _value_in("5 GHz", _norm("2.4/5/6 GHz band")) and _value_in("6 GHz", _norm("5 GHz and 6 GHz"))
    assert not _value_in("5 GHz", _norm("15 GHz")) and not _value_in("320", _norm("13200"))
    assert _value_in("v1.7", _norm("EMLSR version 1.7")) and _value_in("3888", _norm("L_LDPC=3888"))
    assert extract_values("第 5 波（5th Wave）") == []
    assert extract_values("Draft **P802.11bn_D1.5**") == ["P802.11bn", "D1.5"]


def test_list_shares_refs_cited_on_a_short_item():
    answer = "### 功能\n- DSO（Dynamic Sub-band Operation）\n- NPCA（Non-Primary Channel Access）\n- ELR 與 DRU [S2]\n\n其他說明段落沒有來源的文字內容。"
    refs = {c["text"]: c["refs"] for c in split_claims(answer)}
    assert refs["DSO（Dynamic Sub-band Operation）"] == ["S2"] and refs["NPCA（Non-Primary Channel Access）"] == ["S2"]
    assert refs["其他說明段落沒有來源的文字內容。"] == []


def test_values_tolerate_hyphenated_units_without_gluing_numbers():
    from src.wifi8.grounding import _norm, _value_in
    text = _norm("Radio Configuration 2x2 2.4-GHz + 2x2 5-GHz 2x2 2.4-GHz + 4x4 5-GHz")
    assert all(_value_in(v, text) for v in ("2x2", "4x4", "5 GHz", "2.4 GHz"))
    assert not _value_in("6 GHz", text) and not _value_in("MCS1", _norm("MCS17"))


def test_lines_introducing_a_list_are_labels_not_claims():
    answer = "AP 不只是宣告能力，還必須：\n- 接受 STA 的 DBE 啟用請求 [S1]\n\n依目前有效的 Wi-Fi 8 MRD：\n- DBE 對 AP 是選用功能，只適用於部分頻段 [S1]"
    texts = [c["text"] for c in split_claims(answer)]
    assert texts == ["接受 STA 的 DBE 啟用請求", "DBE 對 AP 是選用功能，只適用於部分頻段"]


def test_table_header_rows_are_not_claims_but_their_refs_are_shared():
    answer = "| 條件 | AP 是否必須實作 DBE [S1] |\n|---|---|\n| 實作 WPA3-Enterprise | 必須實作 DBE |\n| 一般 5/6 GHz AP | 選用 |"
    claims = split_claims(answer)
    assert [c["text"] for c in claims] == ["實作 WPA3-Enterprise：必須實作 DBE", "一般 5/6 GHz AP：選用"]
    assert all(c["refs"] == ["S1"] for c in claims)
    plain = "| 版本 | WFA ID |\n|---|---|\n| v14 | 103720 |"
    assert [c["text"] for c in split_claims(plain)] == ["v14：103720"]


def test_colon_lines_with_values_stay_claims():
    answer = "目前最新的是 **v1.5**：\n- 取代 v1.4 的測試範圍文件內容 [S2]\n\n- **Certification Development**：\n  - TTG 正審查 test case contributions [S1]"
    texts = [c["text"] for c in split_claims(answer)]
    assert "目前最新的是 v1.5" in texts and "Certification Development" not in texts


def test_fenced_code_blocks_are_not_claims():
    answer = ("DRU 把 tone 分散到較寬的 distribution bandwidth。[S1]\n\n```text\n一般 RU：\n[ tone tone tone tone tone ] .................\n"
              "DRU：\n[ tone ]...[ tone ]...[ tone ]...[ tone ]...\n└──tone 分散於較寬 DBW──┘ 320 MHz\n```\n\n"
              "~~~\n另一種 fence 內的內容 640 MHz 也不是句子\n~~~\n- 一般 RU 的 tone 是連續排列的資源單位")
    texts = [c["text"] for c in split_claims(answer)]
    assert texts == ["DRU 把 tone 分散到較寬的 distribution bandwidth。", "一般 RU 的 tone 是連續排列的資源單位"]
    assert check_answer(answer, SOURCES)["summary"]["values"] == 0  # 320/640 MHz inside the diagrams are not checked


def test_unclosed_fence_hides_the_rest_but_does_not_fail():
    texts = [c["text"] for c in split_claims("第一句說明 DBE 的頻寬擴展用途。[S1]\n```\n未關閉的程式碼區塊內容")]
    assert texts == ["第一句說明 DBE 的頻寬擴展用途。"]


PF1_EE1 = {
    "S1": {"source": "WFA - Wi-Fi 8 PF1 Report", "text": "【圖片】Results: APUT\nUHR-4.5.2_24G | G1 | 25\nUHR-4.5.2_5G | G1 | 30\nUHR-4.5.2_6G | G1 | 30"},
    "S2": {"source": "WFA - Wi-Fi 8 EE1 Report", "text": "【圖片】Results: APUT\nUHR-4.5.2_24G | G1 | 6\nUHR-4.5.2_5G | G1 | 9\nUHR-4.5.2_6G | G1 | 9"},
    "S3": {"source": "WFA - Wi-Fi 8 PF1 Report", "text": "Results: APUT"},
}
PF1_QUESTION = "Wi-Fi 8 PF1 Report 的 APUT 結果表中，UHR-4.5.2 在 2.4G、5G、6G 的數值各是多少？"


def _table_answer(ref, intro="Wi-Fi 8 PF1 Report 的 UHR-4.5.2 數值為："):
    return f"{intro}\n- **2.4G：{{a}}** [{ref}]\n- **5G：{{b}}** [{ref}]\n- **6G：{{b}}** [{ref}]"


def test_assigned_numbers_are_numbers_after_a_label():
    from src.wifi8.grounding import assigned_numbers
    assert assigned_numbers("2.4G：6") == ["6"]
    assert assigned_numbers("UHR-4.5.2: 25、30、30") == ["25", "30"]
    assert assigned_numbers("最大頻寬：320 MHz，調變：4096-QAM") == []  # units and ids belong to extract_values
    assert assigned_numbers("沒有標籤的 6 與 9") == []
    assert assigned_numbers("舉行時間：2026/08/03–2026/08/14。") == []  # dates are not assigned numbers
    assert assigned_numbers("比例：3/4") == []


def test_numbers_the_cited_chunk_does_not_show_are_flagged():
    wrong = _table_answer("S3").format(a=6, b=9)  # PF1 slide text only says "Results: APUT"
    result = check_answer(wrong, PF1_EE1, question=PF1_QUESTION)
    assert result["summary"]["values_not_in_cited"] == 3
    flagged = {f["text"]: f["reasons"] for f in result["flagged"]}
    assert all("value_not_in_cited" in flagged[t] for t in flagged if t.endswith(("：6", "：9")))
    right = check_answer(_table_answer("S1").format(a=25, b=30), PF1_EE1, question=PF1_QUESTION)
    assert right["summary"]["values_not_in_cited"] == 0
    assert not any(r in f["reasons"] for f in right["flagged"] for r in ("value_not_in_cited", "source_name_mismatch"))


def test_a_claim_naming_one_document_but_citing_another_is_flagged():
    wrong = _table_answer("S2").format(a=6, b=9)  # the numbers are in S2, but S2 is the EE1 report
    result = check_answer(wrong, PF1_EE1, question=PF1_QUESTION)
    assert result["summary"]["claims_source_mismatch"] == 3  # the list items take the name from the question
    item = next(f for f in result["flagged"] if f["text"].endswith("：6"))
    assert "source_name_mismatch" in item["reasons"] and item["names"] == ["PF1"]
    intro = next(c for c in result["claims"] if c["text"].startswith("Wi-Fi 8 PF1 Report"))
    assert intro["refs"] == []  # the lead-in is not itself cited; only the cited rows are compared


def test_document_names_not_seen_in_this_run_or_found_in_the_chunk_are_not_mismatches():
    sources = {"S1": {"source": "WFA - Wi-Fi 8 Test Plan", "text": "AP1 and AP2 run EE1 test cases."},
               "S2": {"source": "WFA - Wi-Fi 8 PF1 Report", "text": "x"}}
    answer = "EE1 測項由 AP1 與 AP2 執行 [S1]。"  # EE1 is in no title, AP1 is not a document name
    assert check_answer(answer, sources)["summary"]["claims_source_mismatch"] == 0
    two = "此測項屬於 PF1 Report 的範圍，需要 AP1 與 AP2 同時參與 [S1]。"  # PF1 is a document name, S1 is not that document
    assert check_answer(two, sources)["summary"]["claims_source_mismatch"] == 1
