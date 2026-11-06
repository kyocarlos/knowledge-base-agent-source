"""The registered Handover template (SIT-SR-SC-NR-Handover): parsing, the metric dictionary, and the chunks."""
import pytest
from openpyxl import Workbook
from src.report_numeric import timescale
from src.report_numeric.chunks import build_chunks
from src.report_numeric.parser import classify_or_none, parse_report
from src.csit_integration_v1.report_adapter import CSIT_POLICY

NAME = "SIT-SR-SC-NR-Handover-SCU2050-EV-V004.xlsx"
IDENT = {"csit_id": "c1", "source_record_id": "c1:v1", "project_id": "P", "policy": CSIT_POLICY}


def put(ws, ref, value):
    ws[ref] = value


def build(path, *, ng_success="Yes", with_example=True):
    wb = Workbook()
    wb.active.title = "Cover"
    put(wb["Cover"], "A24", "NG/Xn Handover Test Report")
    put(wb["Cover"], "A49", "SIT-SR-SC-NR-Handover-SCU2050-EV-V004")
    pre = wb.create_sheet("1. Preface")
    for ref, v in {"A16": "Report Version", "B16": "Date", "C16": "Author", "D16": "Subject", "F16": "Judgement", "A17": "V004", "C17": "Jim", "F17": "PASS",
                   "D17": "SCU2050 handover test of a sample with time slot DDDSU"}.items():
        put(pre, ref, v)
    import datetime
    put(pre, "B17", datetime.datetime(2026, 1, 5))
    intro = wb.create_sheet("2. Introduction")
    rows = {"B7": "Small Cell A Information", "B8": "Model Name :", "E8": "SCU2050", "B9": " Serial Number :", "E9": "SN-SECRET", "B10": "Ether-WAN MAC Address :", "E10": "AA:BB:CC",
            "B11": "Firmware Version :", "E11": "V2.1.0", "B12": "Hardware Version :", "E12": "REV1", "B13": "Band :", "E13": "n78", "B14": "NPI Stage :", "E14": "EV",
            "B16": "Small Cell B Information", "B17": "Model Name :", "E17": "SCE2200", "B18": " Serial Number :", "E18": "SN-B", "B20": "Firmware Version :", "E20": "V2.3.0",
            "B21": "Hardware Version :", "E21": "REV2", "B22": "Band :", "E22": "n78", "B23": "NPI Stage :", "E23": "EV",
            "A26": "2.1  Purpose", "B28": "To verify the handover success rate.", "A40": "2.2  Scope", "B42": "Handover between two small cells."}
    if with_example:
        rows["K8"] = "Example"
    for ref, v in rows.items():
        put(intro, ref, v)
    cfg = wb.create_sheet("2.7 Test Secenarios")
    for ref, v in {"A6": "Small Cell A:", "A7": "Band", "C7": "n78", "A8": "RF Tx Power", "C8": 20, "E8": "Center Frequency", "G8": 3.5, "A9": "Bandwidth", "C9": 100,
                   "E9": "ARFCN", "G9": 633334, "A12": "Time Slot", "C12": "DDDSU (4:1)", "A14": "Neighbor Cell", "A15": "Cell ID", "B15": 201, "C15": "PCI", "D15": 201,
                   "A16": "AbsArfcn", "B16": 633360, "C16": "Xn side", "E16": "Neighbor IP", "G16": "172.16.0.201", "A18": "Small Cell B:", "A19": "Band", "C19": "n78",
                   "A30": "UE SS-RSRP", "A31": "Attenuator", "C31": 0, "E31": 25, "J31": "note", "A32": "Small Cell A", "C32": -60, "E32": -85,
                   "A37": "Time slot", "A38": "DDDSU (4:1)", "A39": "DDSUU (3:2)"}.items():
        put(cfg, ref, v)
    summ = wb.create_sheet("3. Test Result Summary")
    for blk, (title, r0) in enumerate((("3.1  Xn Handover Test Summary", 4), ("3.2  NG Handover Test Summary", 14))):
        put(summ, f"A{r0}", title)
        for ref, v in {f"A{r0+2}": "Latency Test", f"C{r0+2}": "Round trip", f"E{r0+2}": "10 times", f"J{r0+2}": "two",
                       f"A{r0+3}": "Test Result", f"C{r0+3}": "PASS", f"E{r0+3}": "PASS", f"J{r0+3}": 4,
                       f"A{r0+4}": "HO Success Rate", f"C{r0+4}": 1, f"E{r0+4}": 0.9, f"J{r0+4}": 7,
                       f"A{r0+5}": "Max. Tput Variation", f"C{r0+5}": 19, f"E{r0+5}": 30,
                       f"A{r0+6}": "Max. Latency Variation", f"C{r0+6}": 13, f"E{r0+6}": 39,
                       f"A{r0+7}": "Max. Ping Loss Count", f"C{r0+7}": 0, f"E{r0+7}": 1}.items():
            put(summ, ref, v)
    for sheet, title, ok in (("4.1 Xn Handover ", "4.1  Xn Handover Test", "Yes"), ("4.2 NG Handover", "4.2 NG Handover Test", ng_success)):
        ws = wb.create_sheet(sheet)
        put(ws, "A2", title)
        r = 4
        for group, n in ((2, 2), (10, 3)):
            put(ws, f"A{r}", f"Handover {group} times")
            for ref, v in {f"A{r+1}": "No", f"B{r+1}": "Average Latency", f"D{r+1}": "Average Throughput", f"F{r+1}": "Handover Success", f"G{r+1}": "Ping Loss Count",
                           f"B{r+2}": "Before", f"C{r+2}": "After", f"D{r+2}": "Before", f"E{r+2}": "After"}.items():
                put(ws, ref, v)
            if group == 2:
                for ref, v in {f"H{r+2}": "Variation", f"I{r+2}": "Latency", f"J{r+2}": "Tput"}.items():
                    put(ws, ref, v)
            for i in range(1, n + 1):
                rr = r + 2 + i
                for ref, v in {f"A{rr}": i, f"B{rr}": 30 + i, f"C{rr}": 40 + i, f"D{rr}": 600 + i, f"E{rr}": 620 + i, f"F{rr}": ok if i == 1 else "Yes", f"G{rr}": i - 1,
                               f"I{rr}": 10, f"J{rr}": 20 + i, f"L{rr}": 10, f"M{rr}": 20 + i}.items():
                    put(ws, ref, v)
            r += n + 5
        # a page-break repeat of the last block header continues the numbering
        put(ws, f"A{r}", "Handover 10 times")
        put(ws, f"A{r+1}", "No")
        put(ws, f"A{r+3}", 4)
        for ref, v in {f"B{r+3}": 50, f"C{r+3}": 51, f"D{r+3}": 640, f"E{r+3}": 641, f"F{r+3}": "Yes", f"G{r+3}": 0, f"I{r+3}": 1, f"J{r+3}": 1}.items():
            put(ws, ref, v)
    wb.save(path)


@pytest.fixture
def pkg(tmp_path):
    f = tmp_path / "upload.xlsx"
    build(f)
    return parse_report(f, IDENT, source_name=NAME)


def test_the_file_name_selects_the_template():
    assert classify_or_none(NAME) == "cellular_handover"
    assert classify_or_none("SIT-SR-SC-NR-Handover-SCU2060-EV-V13.5a.xlsx") == "cellular_handover"
    assert classify_or_none("SIT-SR-SC-NR-Thermal-SCU2050-EV-V1.xlsx") is None
    assert classify_or_none("SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.xlsx") == "cellular_throughput"


def test_identity_dut_and_peer_cell(pkg):
    d, run = pkg["document"], pkg["test_run"]
    assert (d["document_id"], d["document_version"], d["report_type"], d["technology"], d["category"]) == ("SIT-SR-SC-NR-Handover-SCU2050-EV-V004", "V004", "cellular_handover", "NR", "small_cell")
    assert (run["dut_model"], run["product_id"], run["npi_stage"], run["firmware_version"], run["hardware_version"], run["overall_result"], run["test_date"]) == \
        ("SCU2050", "SCU2050", "EV", "V2.1.0", "REV1", "pass", "2026-01-05")
    assert pkg["dut"]["peer_cell"] == {"model": "SCE2200", "fw_version": "V2.3.0", "hw_version": "REV2", "band": "n78", "npi_stage": "EV"}
    assert "SN-SECRET" not in str(pkg) and "SN-B" not in str(pkg) and "AA:BB:CC" not in str(pkg)  # serial numbers and MAC addresses are deliberately not read
    assert pkg["dut"]["model"] == "SCU2050"  # Small Cell B must not leak into A's fields


def test_configuration_becomes_conditions_and_tags_every_measurement(pkg):
    cond = {c["name"]: c for c in pkg["conditions"]}
    assert cond["cell_a.band"]["text"] == "n78" and cond["cell_a.bandwidth"]["value"] == 100 and cond["cell_a.bandwidth"]["unit"] == "MHz"
    assert cond["cell_a.neighbor.neighbor_ip"]["text"] == "172.16.0.201" and cond["cell_a.neighbor.cell_id"]["value"] == 201
    assert cond["ue.attenuator.near"]["value"] == 0 and cond["ue.attenuator.far"]["value"] == 25 and cond["ue.ss_rsrp_cell_a.far"]["value"] == -85
    assert "cell_b.band" in cond
    assert not any(c["name"].startswith("cell_a.neighbor") and "time" in c["name"] for c in pkg["conditions"])  # the time-slot catalogue is not configuration
    m = pkg["measurements"][0]
    assert (m["band"], m["bandwidth_mhz"], m["center_freq_mhz"], m["time_slot"]) == ("n78", 100, 3500, "DDDSU (4:1)")


def test_every_handover_is_a_row_with_before_after_and_the_printed_variation(pkg):
    cases = {m["test_case_id"] for m in pkg["measurements"]}
    assert cases == {f"cellular_handover:{mode}:{g}" for mode in ("xn", "ng") for g in (2, 10)}
    one = {m["metric_name"]: m for m in pkg["measurements"] if m["test_case_id"] == "cellular_handover:xn:2" and m.get("sample_index") == 2}
    assert one["latency_rtt_before_ho"]["value"] == 32 and one["latency_rtt_after_ho"]["value"] == 42 and one["latency_rtt_after_ho"]["unit"] == "ms"
    assert one["throughput_before_ho"]["value"] == 602 and one["throughput_after_ho"]["value"] == 622 and one["throughput_after_ho"]["direction"] == "dl"
    assert one["ho_success"]["value"] == 1 and one["ping_loss_count"]["value"] == 1
    assert one["throughput_variation"]["value"] == 22 and one["throughput_variation"]["value_basis"] == "reported_derived"
    assert one["latency_rtt_before_ho"]["source_sheet"] == "4.1 Xn Handover" and one["latency_rtt_before_ho"]["source_cell_range"] == "B8"


def test_a_block_header_repeated_on_a_new_page_continues_the_block(pkg):
    ten = [m for m in pkg["measurements"] if m["test_case_id"] == "cellular_handover:xn:10" and m["metric_name"] == "ho_success"]
    assert sorted(m["sample_index"] for m in ten) == [1, 2, 3, 4]
    four = next(m for m in pkg["measurements"] if m["test_case_id"] == "cellular_handover:xn:10" and m["sample_index"] == 4 and m["metric_name"] == "latency_rtt_after_ho")
    assert four["value"] == 51  # a continuation row has no sub-header, so the columns of the first header are reused


def test_summary_gives_the_verdict_and_maxima_per_block_and_ignores_the_example_columns(pkg):
    res = {r["test_case_id"]: r["result"] for r in pkg["results"]}
    assert res == {f"cellular_handover:{m}:{g}": "pass" for m in ("xn", "ng") for g in (2, 10)}
    s = {(m["test_case_id"], m["metric_name"]): m for m in pkg["measurements"] if m.get("sample_index") is None}
    assert s[("cellular_handover:xn:2", "ho_success_rate")]["value"] == 1 and s[("cellular_handover:xn:10", "ho_success_rate")]["value"] == 0.9
    assert s[("cellular_handover:ng:10", "max_latency_variation")]["value"] == 39 and s[("cellular_handover:ng:10", "max_latency_variation")]["statistic"] == "max"
    assert not any(m["source_cell_range"].startswith("J") for m in pkg["measurements"] if m["source_sheet"].startswith("3."))


def test_a_failed_handover_is_recorded_as_zero(tmp_path):
    f = tmp_path / "x.xlsx"
    build(f, ng_success="No")
    p = parse_report(f, IDENT, source_name=NAME)
    ng = [m for m in p["measurements"] if m["test_case_id"] == "cellular_handover:ng:2" and m["metric_name"] == "ho_success"]
    assert sorted((m["sample_index"], m["value"]) for m in ng) == [(1, 0), (2, 1)]


def test_every_metric_is_in_the_dictionary_with_its_unit(pkg):
    allowed = {(m["metric_name"], m["unit"]) for m in timescale.load_dictionary()}
    assert timescale.validate(pkg, allowed) == []


def test_the_rows_do_not_collide_on_the_measurement_key(pkg):
    dims = timescale.DIMS
    keys = [(m["test_case_id"], m["metric_name"], *[m.get(d) for d in dims]) for m in pkg["measurements"]]
    assert len(keys) == len(set(keys))


def test_chunks_carry_the_words_and_each_handover_line(pkg):
    chunks = build_chunks(pkg)
    text = "\n".join(c["text"] for c in chunks)
    assert "換手（Xn／NG Handover）測試報告" in text and "對向小型基站 SCE2200" in text
    assert "第 2 次：延遲 32→42 ms（差 10）；下行吞吐量 602→622 Mbps（差 22）；換手成功；ping 遺失 1" in text
    assert "報告判定 Pass" in text and "換手成功率 0.9" in text
    assert any(c["content_type"] == "section_text" and "To verify the handover success rate." in c["text"] for c in chunks)
    assert all(c["test_case_id"].startswith("cellular_handover:") for c in chunks if c["content_type"] == "measurement_rows")


def test_every_block_gets_a_summary_computed_from_its_rows_and_one_passage_compares_them(pkg):
    chunks = build_chunks(pkg)
    xn10 = next(c for c in chunks if c["content_type"] == "test_results" and c.get("test_case_id") == "cellular_handover:xn:10" and "依逐次數據彙總" in c["text"])
    assert "共 4 次" in xn10["text"] and "換手成功 4／4 次" in xn10["text"]
    assert "換手後延遲平均 44.2" in xn10["text"] and "最小 41、最大 51" in xn10["text"] and "ping 遺失合計 3（單次最大 2）" in xn10["text"]
    both = next(c for c in chunks if c["content_type"] == "test_results" and "比較" in c["text"] and c.get("test_case_id") is None)
    assert "Xn Handover 10 times" in both["text"] and "NG Handover 10 times" in both["text"]


def test_a_failed_handover_lowers_the_computed_success_count(tmp_path):
    f = tmp_path / "failed.xlsx"
    build(f, ng_success="No")
    chunks = build_chunks(parse_report(f, IDENT, source_name=NAME))
    ng10 = next(c for c in chunks if c.get("test_case_id") == "cellular_handover:ng:10" and "依逐次數據彙總" in c["text"])
    assert "換手成功 3／4 次" in ng10["text"]


def test_a_throughput_report_is_parsed_exactly_as_before():
    # SIT-TR-SC-NR-Throughput keeps its own parser; the handover work only widened the document-number and band-label rules
    from src.report_numeric import parser
    assert parser.DOC_NUMBER.match("SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001")
    assert parser.DOC_NUMBER.match("SIT-SR-SC-NR-Handover-SCU2060-EV-V13.5a")
    assert not parser.DOC_NUMBER.match("SIT-XX-SC-NR-Handover-SCU2060-EV-V1")
    assert parser._model_from_number("SIT-SR-SC-NR-Handover-SCU2060-EV-V13.5a") == "SCU2060"
    assert parser._model_from_number("SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001") == "SCU5050-n78L"
