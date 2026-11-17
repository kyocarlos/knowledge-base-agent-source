from src.report_numeric import compare, findings, noise, rca

FACTORS = ("firmware_version", "hardware_version", "chipset_vendor", "ethernet_type", "npi_stage", "test_date", "report_type", "technology", "dut_model",
           "report_revision", "document_version")


def meas(value, *, channel=36, metric="throughput", direction="dl", band="5GHz", bw=80, att=None):
    return {"test_case_id": "TP", "test_case_name": "tp", "metric_name": metric, "value": value, "unit": "Mbps", "value_basis": "measured", "band": band,
            "bandwidth_mhz": bw, "channel": channel, "direction": direction, "attenuation_db": att, "angle_deg": None, "traffic_mode": None, "protocol": "tcp",
            "statistic": None, "sample_index": None, "wireless_mode": None, "time_slot": None, "source_sheet": "S", "source_cell_range": "A1"}


def run(rid, values, report_type="wifi_throughput", product="P1"):
    r = {"test_run_id": rid, "product_id": product, "dut_model": "M", "report_type": report_type, "document_id": rid, "overall_result": "Pass",
         "quality_status": "clean", "formula_error_count": 0, "error_summary": [], "measurements": values, "results": [], "criteria": [], "conditions": [],
         "technology": "wifi"}
    r.update({f: r.get(f) for f in FACTORS})
    return r


def history_of(values_per_run, **kw):
    return [run(f"H{i}", [meas(v, **kw)]) for i, v in enumerate(values_per_run)]


NOISY = [100, 90, 110, 95, 105, 88, 112]      # wanders by roughly 10 %
STEADY = [100, 101, 99, 100, 100, 101, 99]    # wanders by about 1 %


def test_too_little_history_gives_no_spread():
    assert noise.robust_sigma([1, 2, 3, 4]) is None
    assert noise.relative_pct([1, 2, 3, 4]) is None
    assert noise.relative_pct([0, 0, 0, 0, 0, 0]) is None


def test_relative_spread_and_threshold_only_rises():
    pct = noise.relative_pct(NOISY)
    assert 8 < pct < 16
    assert noise.effective(5.0, None) == 5.0
    assert noise.effective(5.0, 0.5) == 5.0                      # a quiet metric never gets a threshold below the fixed rule
    assert noise.effective(5.0, 4.0) == 12.0


def test_one_real_outlier_does_not_blow_up_the_spread():
    assert noise.relative_pct(STEADY + [60]) < 5


def test_threshold_follows_the_spread():
    t = compare.Thresholds()
    assert t.notable("throughput", 100, 108) is True
    assert t.notable("throughput", 100, 108, noise_pct=4.0) is False   # 8 % < 3 x 4 %
    assert t.notable("throughput", 100, 150, noise_pct=4.0) is True
    assert t.notable("throughput", 100, 108, noise_pct=0.3) is True    # still the fixed 5 % floor


def _pair(a=100, b=108):
    return [run("A", [meas(a)]), run("B", [meas(b)])]


def test_a_difference_inside_the_normal_spread_is_not_notable_but_is_without_history():
    plain = compare.compare_runs(_pair())
    assert plain["counts"]["notable"] == 1
    assert plain["noise"]["applied"] is False and plain["noise"]["history_runs"] == 0
    noisy = compare.compare_runs(_pair(), history=history_of(NOISY))
    assert noisy["counts"]["notable"] == 0 and noisy["counts"]["unchanged"] == 1
    assert noisy["noise"]["applied"] is True and noisy["noise"]["history_runs"] == len(NOISY)


def test_a_difference_far_beyond_the_spread_is_still_notable_and_reports_its_noise():
    pack = compare.compare_runs(_pair(100, 140), history=history_of(STEADY))
    assert pack["counts"]["notable"] == 1
    assert pack["diffs"][0]["noise_pct"] < 3


def test_too_few_history_reports_fall_back_to_the_fixed_threshold_and_say_so():
    pack = compare.compare_runs(_pair(), history=history_of(NOISY[:3]))
    assert pack["counts"]["notable"] == 1
    assert pack["noise"]["applied"] is False and pack["noise"]["history_runs"] == 3
    assert "固定門檻" in pack["noise"]["note"]


def test_findings_scope_uses_the_history_threshold():
    runs = _pair()
    without = findings.build(runs, "wifi_throughput")
    assert without["scopes_notable"] == 1 and without["noise"]["applied"] is False
    with_history = findings.build(runs, "wifi_throughput", history=history_of(NOISY))
    assert with_history["scopes_notable"] == 0 and with_history["noise"]["applied"] is True
    big = findings.build(_pair(100, 150), "wifi_throughput", history=history_of(NOISY))
    scope = big["scopes"][0]
    assert scope["noise"]["history_runs"] == len(NOISY) and scope["noise"]["threshold_pct"] > 5


def _curve(peak, cliff_at, report_type="wifi_rvr"):
    pts = [(0, peak), (10, peak), (20, peak if cliff_at > 20 else peak * 0.4), (30, peak * 0.3)]
    return [meas(v, att=a, channel=36) for a, v in pts]


def test_rvr_scope_uses_peak_and_cliff_spread():
    def rv(rid, peak, cliff_at):
        return run(rid, _curve(peak, cliff_at), report_type="wifi_rvr")
    hist = [rv(f"H{i}", p, 30) for i, p in enumerate(NOISY)]
    a, b = rv("A", 100, 30), rv("B", 108, 30)
    assert findings.build([a, b], "wifi_rvr")["scopes_notable"] == 1
    got = findings.build([a, b], "wifi_rvr", history=hist)
    assert got["scopes_notable"] == 0 and got["noise"]["applied"] is True


def test_the_model_is_shown_the_noise_note():
    pack = compare.compare_runs(_pair(100, 150), history=history_of(NOISY))
    view = rca.prompt_view(pack)
    assert view["noise"]["applied"] is True
    assert view["findings"]["noise"]["applied"] is True
    assert "noise" in rca.SYSTEM_PROMPT


def test_existing_calls_without_history_are_unchanged():
    pack = compare.compare_runs(_pair())
    assert "noise_pct" not in pack["diffs"][0]
    assert findings.build(_pair(), "wifi_throughput")["scopes"][0].get("noise") is None
