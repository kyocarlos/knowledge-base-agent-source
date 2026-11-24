"""The RCA checker must not call a firmware version the evidence already contains "a number outside the evidence", and must still catch a version it made up."""
from src.report_numeric import rca

EVIDENCE = {
    "F1": {"kind": "factor", "factor": "firmware_version", "values": ["V0.0.7_260421_eng", "V0.0.8_260512_eng"]},
    "P1": {"kind": "pattern", "label": "5GHz 80MHz 下行", "unit": "Mbps", "per_run": [{"median": 1800.88}, {"median": 1440.71}], "median_delta_pct": -20.0},
}


def _analysis(text: str) -> dict:
    return {"summary": text, "observations": [{"text": "觀察", "evidence": ["P1"]}],
            "hypotheses": [{"cause": "待驗證", "mechanism": "待驗證", "supports": ["F1", "P1"], "against": [], "missing_evidence": [], "confidence": "low", "verify_steps": ["重測"]}],
            "unexplained": [], "data_gaps": []}


def _verify(text: str) -> dict:
    pack = {"evidence": EVIDENCE, "directions_defined": True}
    return rca.verify(_analysis(text), pack)


def test_a_version_string_that_is_in_the_evidence_is_not_a_stray_number():
    out = _verify("韌體由 V0.0.7_260421_eng 變為 V0.0.8_260512_eng，吞吐量中位數由 1800.88 變為 1440.71。")
    assert out["ok"], out["violations"]


def test_allowed_numbers_include_the_neighbouring_pairs_of_a_dotted_version():
    allowed = rca.allowed_numbers(EVIDENCE)
    assert {"0.7", "0.8", "0", "7", "8"} <= allowed


def test_a_version_the_model_made_up_is_still_caught():
    out = _verify("韌體升級到 V2.10.4 之後吞吐量下降。")
    assert not out["ok"] and any("10.4" in v or "2.1" in v for v in out["violations"]), out["violations"]


def test_an_invented_plain_number_is_still_caught():
    out = _verify("吞吐量下降了 12.5 Mbps。")
    assert not out["ok"] and any("12.5" in v for v in out["violations"])


def test_a_version_in_the_question_is_allowed_too():
    allowed = rca.allowed_numbers({}, "V1.2.3 之後變慢了嗎？")
    assert "1.2" in allowed and "2.3" in allowed


def test_numbers_are_not_widened_beyond_the_dotted_tokens():
    allowed = rca.allowed_numbers({"F": {"values": ["V0.0.7"]}})
    assert "0.9" not in allowed and "7.5" not in allowed
