import json

from src.wifi8.concept_graph import write
from src.wifi8.concepts import aggregate, build_prompt, build_windows, concept_key, load_rules as _lr, norm, parse_json, validate

TEXT = ("Enhanced Long Range (ELR) improves uplink reliability. ELR uses UHR-MCS 0 and UHR-MCS 1.\n\n"
        "NPCA depends on a secondary channel; 2.4 GHz supports ELR in uplink and downlink.")


def good(**kw):
    base = {"concepts": [{"name": "ELR", "type": "Feature", "aliases": ["Enhanced Long Range"]}, {"name": "UHR-MCS", "type": "Parameter", "aliases": []},
                         {"name": "NPCA", "type": "Feature", "aliases": []}],
            "relations": [{"source": "ELR", "type": "USES", "target": "UHR-MCS", "evidence": "ELR uses UHR-MCS 0 and UHR-MCS 1", "confidence": 0.9}]}
    base.update(kw)
    return base


def test_valid_extraction_is_kept_with_alias_resolution():
    v = validate(good(relations=[{"source": "Enhanced Long Range", "type": "IMPROVES", "target": "NPCA", "evidence": "improves uplink reliability", "confidence": 0.7}]), TEXT)
    assert [c["name"] for c in v.concepts] == ["ELR", "UHR-MCS", "NPCA"] and v.relations[0]["source"] == "ELR" and not v.dropped


def test_hallucinations_are_dropped_and_counted():
    data = good(concepts=good()["concepts"] + [{"name": "WPA9", "type": "Standard", "aliases": []}, {"name": "ELR2", "type": "Gadget", "aliases": []}],
                relations=[{"source": "ELR", "type": "USES", "target": "UHR-MCS", "evidence": "ELR uses a quantum encoder", "confidence": 1},       # quote not in text
                           {"source": "ELR", "type": "FLIRTS_WITH", "target": "NPCA", "evidence": "NPCA depends on a secondary channel", "confidence": 1},  # type
                           {"source": "ELR", "type": "DEPENDS_ON", "target": "WPA9", "evidence": "NPCA depends on a secondary channel", "confidence": 1},   # unknown end
                           {"source": "ELR", "type": "USES", "target": "ELR", "evidence": "ELR uses UHR-MCS 0", "confidence": 1},                            # self loop
                           {"source": "NPCA", "type": "DEPENDS_ON", "target": "UHR-MCS", "evidence": "x" * 400, "confidence": 1},                           # too long
                           "garbage"])
    v = validate(data, TEXT)
    assert v.relations == [] and v.dropped["concept_not_in_text"] == 1 and v.dropped["concept_bad_type"] == 1
    assert v.dropped["evidence_not_in_text"] == 1 and v.dropped["relation_bad_type"] == 1 and v.dropped["relation_endpoint_unknown"] == 2
    assert v.dropped["evidence_too_long"] == 1 and v.dropped["relation_malformed"] == 1


def test_evidence_matching_ignores_case_whitespace_and_typographic_dashes():
    text = "UHR‑MCS   0 is\nBPSK"
    v = validate({"concepts": [{"name": "UHR-MCS", "type": "Parameter", "aliases": []}, {"name": "BPSK", "type": "Mechanism", "aliases": []}],
                  "relations": [{"source": "UHR-MCS", "type": "USES", "target": "BPSK", "evidence": "uhr-mcs 0 is bpsk", "confidence": 0.8}]}, text)
    assert len(v.relations) == 1


def test_invalid_json_and_missing_fields_do_not_raise():
    assert parse_json("```json\n{\"concepts\": []}\n```") == {"concepts": []} and parse_json("no json") is None and parse_json("") is None
    assert validate(None, TEXT).dropped["invalid_json"] == 1
    assert validate({"concepts": "x", "relations": None}, TEXT).concepts == []


def test_concept_keys_unify_spelling():
    assert concept_key("Wi-Fi 8") == concept_key("Wi‑Fi 8") == concept_key("wifi 8") and norm("A–B  C") == "a-b c"


def test_windows_keep_order_and_boundaries():
    chunks = [{"revision_id": "r1", "chunk_index": i, "content": "x" * 400, "source_name": "Doc"} for i in (3, 1, 2, 4)]
    w = build_windows(chunks, max_chars=1000)
    assert [x["chunk_indexes"] for x in w] == [[1, 2], [3, 4]] and w[0]["window_id"] == "r1#1-2" and w[0]["title"] == "Doc"
    assert build_windows([{"revision_id": "r", "chunk_index": 0, "content": "y" * 9000}], 1000)[0]["chunk_indexes"] == [0]  # one long chunk = own window


def test_aggregate_merges_aliases_counts_support_and_keeps_evidence():
    def rec(doc, win, name, aliases, evidence):
        return {"revision_id": doc, "window_id": win, "chunk_indexes": [1], "concepts": [{"name": name, "type": "Feature", "aliases": aliases}, {"name": "UHR-MCS", "type": "Parameter", "aliases": []}],
                "relations": [{"source": name, "type": "USES", "target": "UHR-MCS", "evidence": evidence, "confidence": 0.8}]}
    out = aggregate([rec("d1", "w1", "ELR", ["Enhanced Long Range"], "ELR uses UHR-MCS"), rec("d2", "w2", "Enhanced Long Range", [], "Enhanced Long Range uses UHR-MCS"),
                     rec("d2", "w3", "ELR", [], "ELR uses UHR-MCS")])
    elr = next(c for c in out["concepts"] if c["name"] == "ELR")
    assert len(out["concepts"]) == 2 and elr["doc_count"] == 2 and "Enhanced Long Range" in elr["aliases"] and set(elr["mentions"]) == {"d1", "d2"}
    (rel,) = out["relations"]
    assert rel["type"] == "USES" and rel["support_windows"] == 3 and rel["support_docs"] == 2 and len(rel["evidence"]) == 2  # same quote only once


def test_prompt_lists_types_relations_and_known_names():
    p = build_prompt("T", "body", ["ELR", "NPCA"])
    assert "Feature" in p and "DEPENDS_ON" in p and "ELR、NPCA" in p and p.rstrip().endswith("body")


class Session:
    def __init__(self):
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        return type("R", (), {"consume": lambda s: None})()


def test_graph_write_is_merge_only_with_fixed_relation_types():
    out = aggregate([{"revision_id": "d1", "window_id": "w1", "chunk_indexes": [1], "concepts": [{"name": "A", "type": "Feature", "aliases": []}, {"name": "B", "type": "Feature", "aliases": []}],
                      "relations": [{"source": "A", "type": "DEPENDS_ON", "target": "B", "evidence": "A needs B", "confidence": 0.9}]}])
    s = Session()
    counts = write(s, out, {"run_id": "r", "model": "m", "extracted_at": "t"}, {"d1": "Doc 1"})
    assert counts == {"concepts": 2, "mentions": 2, "relations": 1}
    text = "\n".join(q for q, _ in s.calls).upper()
    assert "MERGE" in text and "DELETE" not in text and "DETACH" not in text and "-[X:DEPENDS_ON]->" in text
    rel_params = next(p for q, p in s.calls if "DEPENDS_ON" in q)
    assert rel_params["rows"][0]["evidence"] == ["d1: A needs B"]


# ---- 2026-10-22 改善規則（報告第 7 節）
from src.wifi8.concepts import aggregate as _agg, load_rules  # noqa: E402

RULES = load_rules()
BODY = ("DSO shall be implemented when ELR is implemented. Reference [1] IEEE 802.11bn D1.3\n\n"
        "TCVs – Traffic Indication Update\n\nQualcomm and the TTG discussed the NPCA timer and security.")


def one(src, kind, dst, quote, concepts=None, text=BODY, types=None):
    names = concepts or [src, dst]
    return validate({"concepts": [{"name": n, "type": (types or {}).get(n, "Feature"), "aliases": []} for n in names],
                     "relations": [{"source": src, "type": kind, "target": dst, "evidence": quote, "confidence": 0.9}]}, text, RULES)


def test_organizations_and_generic_concepts_are_dropped():
    v = validate({"concepts": [{"name": "Qualcomm", "type": "Feature", "aliases": []}, {"name": "TTG", "type": "Feature", "aliases": []},
                               {"name": "Security", "type": "Feature", "aliases": []}, {"name": "NPCA timer", "type": "Parameter", "aliases": []}], "relations": []}, BODY, RULES)
    assert [c["name"] for c in v.concepts] == ["NPCA timer"] and v.dropped["concept_generic_or_org"] == 3


def test_truncated_concept_names_are_dropped():
    assert validate({"concepts": [{"name": "Enhanced long range (ELR", "type": "Feature", "aliases": []}], "relations": []}, "Enhanced long range (ELR) operation", RULES).dropped["concept_truncated_name"] == 1


def test_introduced_in_needs_both_endpoints_in_the_quote():
    v = one("DSO", "INTRODUCED_IN", "IEEE 802.11bn D1.3", "Reference [1] IEEE 802.11bn D1.3")
    assert v.relations == [] and v.dropped["evidence_missing_endpoint"] == 1
    ok = one("ELR", "INTRODUCED_IN", "Wi-Fi 8", "ELR is only defined for UL in Wi-Fi 8", text="ELR is only defined for UL in Wi-Fi 8 program")
    assert len(ok.relations) == 1


def test_related_to_hubs_and_heading_echoes_are_dropped():
    assert one("NPCA timer", "RELATED_TO", "Wi-Fi 8", "NPCA timer", concepts=["NPCA timer", "Wi-Fi 8"], text="NPCA timer for Wi-Fi 8 devices").relations == []
    v = one("TCVs – Traffic Indication Update", "TESTED_BY", "Traffic Indication", "TCVs – Traffic Indication Update", concepts=["TCVs – Traffic Indication Update", "Traffic Indication"])
    assert v.relations == [] and v.dropped["evidence_is_heading_echo"] == 1


def test_evidence_cut_in_the_middle_of_a_word_is_dropped():
    v = one("NPCA timer", "USES", "OBSS PPDU", "the NPCA timer is limited by the OBSS PPDU dur", concepts=["NPCA timer", "OBSS PPDU"], text="the NPCA timer is limited by the OBSS PPDU duration")
    assert v.relations == [] and v.dropped["evidence_cut_mid_word"] == 1
    # flattened table: the quote ends exactly at a cell boundary ("...transmissionUHR DL OFDMA") and is complete
    cell = one("AP", "USES", "UHR SU transmission", "AP is forced to transmit using UHR SU transmission", concepts=["AP", "UHR SU transmission"],
               text="AP is forced to transmit using UHR SU transmissionUHR DL OFDMA: testbed AP")
    assert len(cell.relations) == 1


def test_aliases_plurals_and_suffix_words_collapse_to_one_concept():
    assert concept_key("802.11bn Draft 1.3", RULES) == concept_key("IEEE 802.11bn D1.3", RULES) == concept_key("11bn d1.3", RULES)
    assert concept_key("latencies", RULES) == concept_key("transmission latency", RULES) == concept_key("latency", RULES)
    assert concept_key("AP Channel Report element", RULES) == concept_key("AP Channel Report", RULES) and concept_key("PPDU formats", RULES) == concept_key("PPDU format", RULES)
    assert concept_key("BA bitmap", RULES) != concept_key("BA", RULES)  # not every suffix is dropped


def test_canonical_name_and_weak_flag_in_aggregate():
    rec = lambda w, doc, kind: {"revision_id": doc, "window_id": w, "chunk_indexes": [1], "concepts": [{"name": "802.11bn Draft 1.3", "type": "Standard", "aliases": []}, {"name": "ELR", "type": "Feature", "aliases": []}],
                                "relations": [{"source": "ELR", "type": kind, "target": "802.11bn Draft 1.3", "evidence": "x", "confidence": 0.5}]}
    out = _agg([rec("w1", "d1", "RELATED_TO"), rec("w2", "d2", "RELATED_TO"), rec("w3", "d3", "PART_OF")], RULES)
    assert {c["name"] for c in out["concepts"]} == {"IEEE 802.11bn D1.3", "ELR"}
    weak = {r["type"]: r["weak"] for r in out["relations"]}
    assert weak == {"RELATED_TO": False, "PART_OF": False}  # two windows support RELATED_TO: not weak
    assert _agg([rec("w1", "d1", "RELATED_TO")], RULES)["relations"][0]["weak"] is True


def test_a_test_item_named_after_what_it_tests_is_valid_tested_by_evidence():
    text = "5.5 STAUT transmits and receives LDPC codes of block length 3888 bits test"
    v = one("LDPC codes", "TESTED_BY", "5.5 STAUT transmits and receives LDPC codes of block length 3888 bits test", text, concepts=["LDPC codes", "5.5 STAUT transmits and receives LDPC codes of block length 3888 bits test"], text=text,
            types={"5.5 STAUT transmits and receives LDPC codes of block length 3888 bits test": "TestItem"})
    assert len(v.relations) == 1
    part = one("Per-SMD PTK", "PART_OF", "Per-SMD PTK, Exec via Current, SN Reset", "Per-SMD PTK, Exec via Current, SN Reset", concepts=["Per-SMD PTK", "Per-SMD PTK, Exec via Current, SN Reset"], text="Per-SMD PTK, Exec via Current, SN Reset")
    assert part.relations == [] and part.dropped["evidence_is_heading_echo"] == 1


def test_limited_to_is_a_valid_relation_and_the_prompt_explains_it():
    v = one("ELR", "LIMITED_TO", "uplink operation", "ELR is only defined for uplink operation", text="ELR is only defined for uplink operation in the program")
    assert len(v.relations) == 1 and "LIMITED_TO" in build_prompt("t", "x", [])
    assert "最常用的寫法" in build_prompt("t", "x", [])


def test_evidence_that_differs_only_in_punctuation_or_hyphenation_is_accepted_but_rewording_is_not():
    text = "Wi-Fi 8 improves re-\nliability of links and decreases laten-\ncy at the cell edge for STAs"
    ok = one("Wi-Fi 8", "IMPROVES", "reliability", "Wi-Fi 8 improves reliability of links", concepts=["Wi-Fi 8", "reliability"], text=text)
    assert len(ok.relations) == 1
    bad = one("Wi-Fi 8", "IMPROVES", "reliability", "Wi-Fi 8 greatly boosts the robustness of every link", concepts=["Wi-Fi 8", "reliability"], text=text)
    assert bad.relations == [] and bad.dropped["evidence_not_in_text"] == 1


# ---- round 3: relevance filter, cross-document merge, accumulate-on-combine ----
from src.wifi8 import concept_merge as cm
from src.wifi8.concepts import document_relevance, relevance_applies, window_relevant

R3 = _lr()


def test_relevance_filter_applies_to_papers_only_and_uses_density_not_tags():
    assert relevance_applies("Research Paper", R3) and not relevance_applies("MRD Feature Contribution", R3)
    wifi = "Wi-Fi 8 adds MLO and coordinated OFDMA for the access point and STA. " * 20
    other = "We train a convolutional network on a nano-antenna dataset with gradient descent. " * 20
    assert document_relevance("Some paper", wifi, R3)["relevant"] and not document_relevance("Some paper", other, R3)["relevant"]
    assert document_relevance("Towards Wi-Fi 8 reliability", other, R3)["relevant"]  # a Wi-Fi word in the title is enough
    assert window_relevant(wifi, R3) and not window_relevant(other, R3)


def test_scope_instruction_is_inserted_before_the_output_format_only_when_given():
    plain, scoped = build_prompt("t", "body", []), build_prompt("t", "body", [], R3.relevance["scope_instruction"])
    assert "範圍限制" not in plain and scoped.index("範圍限制") < scoped.index("輸出格式：") and scoped.endswith("body")


def _c(cid, name, aliases=(), doc_count=1, kind="Feature"):
    return {"concept_id": cid, "name": name, "type": kind, "aliases": list(aliases), "doc_count": doc_count}


def test_merge_candidates_find_acronyms_and_spelling_but_never_direction_or_band_variants():
    cs = [_c("1", "multi-link operation"), _c("2", "MLO"), _c("3", "UL OFDMA"), _c("4", "DL OFDMA"), _c("5", "5 GHz operation"), _c("6", "6 GHz operation"),
          _c("7", "target wake time"), _c("8", "target wake-up time"), _c("9", "coordinated spatial reuse"), _c("10", "coordinated spatial re-use")]
    pairs = {(c["a"], c["b"]) for c in cm.candidates(cs, R3)}
    assert ("1", "2") in pairs and ("7", "8") in pairs
    assert ("10", "9") not in pairs and ("9", "10") not in pairs  # already one concept by key
    assert ("3", "4") not in pairs and ("5", "6") not in pairs


def test_judge_decisions_become_a_merge_file_that_load_rules_understands(tmp_path):
    by_id = {"1": _c("1", "multi-link operation", doc_count=1), "2": _c("2", "MLO", doc_count=5), "3": _c("3", "multi link operation", doc_count=1)}
    decisions = [{"a": "1", "b": "2", "same": True, "canonical": "MLO"}, {"a": "2", "b": "3", "same": True, "canonical": ""}, {"a": "1", "b": "3", "same": False}]
    merges = cm.merges_file(decisions, by_id)
    assert merges == {"MLO": ["multi link operation", "multi-link operation"]}
    path = tmp_path / "merges.json"
    path.write_text(json.dumps(merges), "utf-8")
    rules = _lr(merges=path)
    assert concept_key("multi-link operation", rules) == concept_key("MLO", rules) == concept_key("multi link operation", rules)
    assert parse_decision_ok()


def parse_decision_ok():
    return cm.parse_decision('{"same": true, "canonical": "MLO", "reason": "縮寫"}')["same"] is True and cm.parse_decision('{"same": "yes"}') is None


def test_combined_runs_accumulate_support_instead_of_overwriting(tmp_path):
    def rec(run, doc, win, a, b):
        return {"run": run, "revision_id": doc, "window_id": win, "chunk_indexes": [0], "concepts": [{"name": a, "type": "Feature", "aliases": []}, {"name": b, "type": "Feature", "aliases": []}],
                "relations": [{"source": a, "type": "USES", "target": b, "evidence": f"{a} uses {b}", "confidence": 0.8}]}
    rows = aggregate([rec("mrd", "d1", "d1#0-0", "ELR", "UHR-MCS"), rec("testcase", "d2", "d2#0-0", "ELR", "UHR-MCS")], R3)
    assert len(rows["relations"]) == 1 and rows["relations"][0]["support_docs"] == 2 and rows["relations"][0]["runs"] == ["mrd", "testcase"]
    assert all(c["runs"] == ["mrd", "testcase"] for c in rows["concepts"])
    assert merged_with_alias_changes_support(tmp_path)


def merged_with_alias_changes_support(tmp_path):
    # the same concept written under two spellings in two documents counts as one concept once the merge file is applied
    def rec(doc, name):
        return {"run": "r", "revision_id": doc, "window_id": doc + "#0-0", "chunk_indexes": [0], "concepts": [{"name": name, "type": "Feature", "aliases": []}, {"name": "latency", "type": "Metric", "aliases": []}],
                "relations": [{"source": name, "type": "IMPROVES", "target": "latency", "evidence": f"{name} improves latency", "confidence": 0.8}]}
    before = aggregate([rec("d1", "multi-link operation"), rec("d2", "MLO")], R3)
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"MLO": ["multi-link operation"]}), "utf-8")
    after = aggregate([rec("d1", "multi-link operation"), rec("d2", "MLO")], _lr(merges=path))
    return len(before["concepts"]) == 3 and len(after["concepts"]) == 2 and after["relations"][0]["support_docs"] == 2


def test_loader_refuses_to_overwrite_concepts_from_another_run():
    from src.wifi8.concept_graph import foreign_overlap

    class Result:
        def single(self):
            return {"n": 3}

    class Session:
        def run(self, query, **kw):
            assert "run_id <> $run" in query and kw["run"] == "combined"
            return Result()

    assert foreign_overlap(Session(), {"concepts": [{"concept_id": "C:1"}]}, "combined") == 3


def test_tested_by_must_end_at_a_test_item():
    text = "ELR link test verifies ELR range. ELR uses UHR-MCS 0."
    cs = [{"name": "ELR", "type": "Feature", "aliases": []}, {"name": "ELR link test", "type": "TestItem", "aliases": []}, {"name": "UHR-MCS", "type": "Parameter", "aliases": []}]
    ok = {"source": "ELR", "type": "TESTED_BY", "target": "ELR link test", "evidence": "ELR link test verifies ELR range", "confidence": 1}
    bad = {"source": "ELR", "type": "TESTED_BY", "target": "UHR-MCS", "evidence": "ELR uses UHR-MCS 0", "confidence": 1}
    v = validate({"concepts": cs, "relations": [ok, bad]}, text)
    assert [r["target"] for r in v.relations] == ["ELR link test"] and v.dropped["relation_target_type"] == 1
