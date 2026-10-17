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
