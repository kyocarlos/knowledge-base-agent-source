"""Findings: Throughput and RvR reports are reduced to a few scopes before the model sees anything. No database, no model."""
import json
import pytest
from src.report_numeric import compare, findings, rca


def m(metric, value, *, band="5GHz", bw=80, ch=36, d="dl", att=None, angle=None, basis="measured", proto="tcp"):
    return {"test_case_id": "T", "test_case_name": None, "metric_name": metric, "value": value, "unit": "Mbps" if metric == "throughput" else "dBm", "value_basis": basis,
            "band": band, "bandwidth_mhz": bw, "channel": ch, "direction": d, "attenuation_db": att, "angle_deg": angle, "traffic_mode": None, "protocol": proto,
            "statistic": None, "sample_index": None, "wireless_mode": None, "time_slot": None, "source_sheet": "S", "source_cell_range": "A1"}


def run(rid, rtype, ms, *, fw="1.0", hw="A"):
    return {"test_run_id": rid, "product_id": "P", "dut_model": "P", "report_type": rtype, "technology": "WiFi7", "document_id": "D" + rid, "document_version": "1",
            "report_revision": None, "npi_stage": "EVT", "firmware_version": fw, "hardware_version": hw, "chipset_vendor": "Q", "ethernet_type": None,
            "test_date": "2026-10-01", "overall_result": "pass", "quality_status": "clean", "formula_error_count": 0, "approval_basis": "x",
            "measurements": ms, "results": [], "criteria": [], "conditions": []}


def curve(peak, cliff_at, *, ch=36, angle=None, d="dl", step=3, top=51):
    """Flat at `peak` until `cliff_at`, then a quarter of it."""
    return [m("throughput", peak if a < cliff_at else peak * 0.25, ch=ch, d=d, att=a, angle=angle) for a in range(0, top + 1, step)]


def tp_run(rid, dl_values, **kw):
    ms = [m("throughput", v, ch=ch) for ch, v in dl_values.items()] + [m("rssi", -40.0, ch=ch) for ch in dl_values]
    return run(rid, "wifi_throughput", ms, **kw)


def test_throughput_is_reduced_to_scopes_with_median_and_channel_agreement():
    a = tp_run("A", {36: 1000, 40: 1100, 44: 1200})
    b = tp_run("B", {36: 800, 40: 880, 44: 1210})
    f = compare.compare_runs([a, b])["findings"]
    assert f["report_type"] == "wifi_throughput" and len(f["scopes"]) == 1
    row = f["scopes"][0]["per_run"][1]
    assert f["scopes"][0]["scope"] == "5GHz 80MHz 下行" and row["median"] == 880 and row["median_delta_pct"] == -20.0
    assert row["agreement"] == {"common_points": 3, "higher": 0, "lower": 2, "within_threshold": 1}   # two channels fell, one stayed


def test_rvr_curves_become_peak_cliff_and_mean():
    a = run("A", "wifi_rvr", curve(2000, 24) + curve(2000, 27, ch=40))
    b = run("B", "wifi_rvr", curve(1500, 18) + curve(1500, 18, ch=40))
    sc = compare.compare_runs([a, b])["findings"]["scopes"][0]
    base, other = sc["per_run"]
    assert base["peak_median"] == 2000 and base["cliff_median_db"] == 25.5 and base["curves"] == 2          # the curves fall at 24 and 27 dB: median 25.5
    assert other["peak_delta_pct"] == -25.0 and other["cliff_median_db"] == 18.0 and other["cliff_delta_db"] == -7.5


def test_a_curve_that_never_falls_has_no_cliff_and_says_so():
    a = run("A", "wifi_rvr", curve(2000, 24))
    b = run("B", "wifi_rvr", [m("throughput", 1900 - a_, att=a_) for a_ in range(0, 52, 3)])   # slow decline, never below half
    sc = compare.compare_runs([a, b])["findings"]["scopes"][0]
    assert sc["per_run"][1]["cliff_median_db"] is None and "掉到峰值一半以下" in sc["per_run"][1]["cliff_note"]


def test_derived_totals_and_partial_curves_are_not_treated_as_curves():
    a = run("A", "wifi_rvr", curve(2000, 24) + [m("throughput", 5000, d="total", att=45, basis="reported_derived")] + [m("throughput", 10, att=0, ch=99), m("throughput", 9, att=3, ch=99)])
    assert list(findings._rvr_per_run(a).values())[0]["curves"] == 1      # the 2-point stub and the derived total are skipped


def test_focus_narrows_the_scopes_the_model_sees():
    ms_a = [m("throughput", 1000, band="5GHz", d="dl"), m("throughput", 900, band="2.4GHz", bw=20, ch=6, d="dl")]
    ms_b = [m("throughput", 700, band="5GHz", d="dl"), m("throughput", 600, band="2.4GHz", bw=20, ch=6, d="dl")]
    a, b = run("A", "wifi_throughput", ms_a), run("B", "wifi_throughput", ms_b)
    assert len(compare.compare_runs([a, b])["findings"]["scopes"]) == 2
    only = compare.compare_runs([a, b], focus={"band": "5GHz"})["findings"]
    assert [s["scope"] for s in only["scopes"]] == ["5GHz 80MHz 下行"] and only["focus"] == {"band": "5GHz"}
    assert only["available"]["common"] == 2          # the page still offers both, so a focus can be changed


def test_scopes_present_in_only_some_reports_are_listed_not_compared():
    a = run("A", "wifi_throughput", [m("throughput", 1000), m("throughput", 3000, band="6GHz", bw=320, ch=5)])
    b = run("B", "wifi_throughput", [m("throughput", 700)])
    f = compare.compare_runs([a, b])["findings"]
    assert [s["scope"] for s in f["scopes"]] == ["5GHz 80MHz 下行"] and f["scopes_partial"] == ["6GHz 320MHz 下行"]


def test_the_model_sees_findings_not_the_aligned_rows_and_cannot_cite_rows_it_was_not_shown():
    pack = compare.compare_runs([tp_run("A", {36: 1000}), tp_run("B", {36: 700})])
    view = rca.prompt_view(pack)
    assert "diffs" not in view and "coverage" not in view and view["findings"]["scopes"][0]["id"].startswith("P") and view["mode"] == "rca"
    sid = pack["findings"]["scopes"][0]["id"]
    ok = {"summary": "吞吐量中位數由 1000 Mbps 變為 700 Mbps。", "observations": [{"text": "變動 -30%。", "evidence": [sid]}], "hypotheses": [], "unexplained": [], "data_gaps": []}
    assert rca.verify(ok, pack)["ok"]
    ok["observations"][0]["evidence"] = [pack["diffs"][0]["id"]]
    assert any("不存在的證據編號" in v for v in rca.verify(ok, pack)["violations"])


def test_when_several_factors_differ_the_analysis_is_a_description_with_low_confidence_candidates():
    pack = compare.compare_runs([tp_run("A", {36: 1000}), tp_run("B", {36: 700}, fw="2.0", hw="B")])
    assert pack["confounded"] and rca.prompt_view(pack)["mode"] == "describe"
    fid = pack["factors"][0]["id"]
    sid = pack["findings"]["scopes"][0]["id"]
    a = {"summary": "吞吐量中位數由 1000 Mbps 變為 700 Mbps。", "observations": [{"text": "變動 -30%。", "evidence": [sid]}],
         "hypotheses": [{"cause": "韌體差異", "mechanism": "待驗證", "supports": [fid, sid], "against": [], "missing_evidence": ["釋出說明"], "confidence": "medium", "verify_steps": ["同硬體重測"]}],
         "unexplained": [], "data_gaps": ["韌體與硬體同時變動，需要只換一個變因重測"]}
    r = rca.verify(a, pack)
    assert r["ok"] and r["analysis"]["hypotheses"][0]["confidence"] == "low" and any("只做差異描述" in w for w in r["warnings"])


def test_limits_keep_the_answer_short():
    pack = compare.compare_runs([tp_run("A", {36: 1000}), tp_run("B", {36: 700})])
    sid = pack["findings"]["scopes"][0]["id"]
    hyp = {"cause": "c", "mechanism": "m", "supports": [sid], "against": [], "missing_evidence": [], "confidence": "low", "verify_steps": ["v"]}
    a = {"summary": "s", "observations": [{"text": "o", "evidence": [sid]}] * 8, "hypotheses": [hyp] * 5, "unexplained": [], "data_gaps": []}
    r = rca.verify(a, pack)
    assert r["ok"] and len(r["analysis"]["observations"]) == rca.MAX_OBSERVATIONS and len(r["analysis"]["hypotheses"]) == rca.MAX_HYPOTHESES


def test_a_report_type_without_a_reduction_falls_back_to_the_plain_comparison():
    a, b = run("A", "cellular_throughput", [m("throughput", 100)]), run("B", "cellular_throughput", [m("throughput", 50)])
    pack = compare.compare_runs([a, b])
    assert pack["findings"] is None and pack["model_ids"] is None and pack["diffs"] and "diffs" in rca.prompt_view(pack)


def test_the_prompt_is_much_smaller_than_the_raw_rows():
    ms = lambda scale: [m("throughput", scale * (100 + ch), ch=ch, d=d, band=band, bw=bw) for band, bw in (("5GHz", 80), ("5GHz", 160), ("2.4GHz", 20)) for ch in range(1, 30) for d in ("dl", "ul")]
    pack = compare.compare_runs([run("A", "wifi_throughput", ms(1.0)), run("B", "wifi_throughput", ms(0.7))])
    assert len(json.dumps(pack["diffs"], default=str)) > 3 * len(rca.pack_for_prompt(pack)) / 2 and len(pack["findings"]["scopes"]) <= findings.MAX_SCOPES
