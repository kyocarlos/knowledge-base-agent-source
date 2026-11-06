"""A cellular throughput report whose cases repeat a condition (one starred and tested with another UE) is ingested with the cases kept apart."""
import pytest
from openpyxl import Workbook

from src.csit_integration_v1.errors import IntegrationError
from src.csit_integration_v1.report_adapter import ReportAdapter
from src.report_numeric import timescale
from src.report_numeric.parser import Collector, _case_no, _cellular, _separate_cases

SLOT = "DDDSU+UDSUU (4:4)"


def summary(tmp_path, columns, note="*test with Kyocera K5G-C-100A"):
    """columns: [(header, slot, tcp dl)]: one summary block with one column pair per case, as the template lays it out."""
    wb = Workbook()
    ws = wb.active
    ws.title = "3. Test Result Summary"
    ws["A3"] = "Test Case"
    ws["A4"], ws["A5"], ws["A6"], ws["A7"], ws["A8"], ws["B8"] = "Band", "Bandwidth", "WAN Interface", "Time Slot", "TCP\n(Mbps)", "DL"
    for i, (header, slot, dl) in enumerate(columns):
        col = 3 + 2 * i
        ws.cell(3, col, header)
        ws.cell(4, col, "n79_4.85GHz")
        ws.cell(5, col, 100)
        ws.cell(6, col, "Ether-WAN")
        ws.cell(7, col, slot)
        ws.cell(8, col, dl)
    if note:
        ws["J26"] = note
    return wb


def collect(wb):
    out = Collector("TR:X")
    _cellular(wb, out, "SIT-TR-SC-NR-Throughput-X-EV-V1")
    _separate_cases(out)
    return out


def test_a_starred_header_is_a_case_and_remembered():
    assert _case_no(4) == (4, False) and _case_no("4*") == (4, True) and _case_no(" 12 * ") == (12, True) and _case_no("n/a") is None and _case_no(None) is None


def test_two_cases_with_the_same_conditions_get_their_own_ids_and_the_footnote(tmp_path):
    out = collect(summary(tmp_path, [("4*", SLOT, 430), ("6", SLOT, 482), ("7", "DDSUU (3:2)", 509)]))
    by_case = {m["test_case_name"]: m["test_case_id"] for m in out.measurements}
    assert by_case["Test Case 4 (*test with Kyocera K5G-C-100A)"].endswith(f"{SLOT}#case4")
    assert by_case["Test Case 6"].endswith(f"{SLOT}#case6")
    assert by_case["Test Case 7"].endswith("DDSUU (3:2)")                                      # a case with conditions of its own keeps its id
    assert len({m["test_case_id"] for m in out.measurements}) == 3
    assert [i["kind"] for i in out.issues].count("same_conditions") == 1


def test_a_report_without_repeats_is_untouched(tmp_path):
    out = collect(summary(tmp_path, [("1", "DDDSU (4:1)", 705), ("2", "DDSUU (3:2)", 509)], note=""))
    assert [m["test_case_id"] for m in out.measurements] == ["cellular_throughput:n79@4850:100MHz:DDDSU (4:1)", "cellular_throughput:n79@4850:100MHz:DDSUU (3:2)"]
    assert not out.issues


def test_no_two_cells_of_a_report_share_a_measurement_key():
    a = {"test_case_id": "c", "metric_name": "throughput", "source_sheet": "4. Performance Test", "source_cell_range": "B72", "direction": "dl"}
    b = {**a, "source_cell_range": "B118"}
    assert timescale.measurement_key("TR:X", a) != timescale.measurement_key("TR:X", b)
    assert timescale.measurement_key("TR:X", a) == timescale.measurement_key("TR:X", dict(a))


class Conn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("error_name", ["UniqueViolation", "NumericValueOutOfRange", "CheckViolation"])
def test_a_report_the_store_refuses_is_rejected_for_good(monkeypatch, error_name):
    import psycopg
    error = getattr(psycopg.errors, error_name)

    def refuse(*a, **k):
        raise error("refused")
    monkeypatch.setattr(timescale, "write_package", refuse)
    with pytest.raises(IntegrationError) as got:
        ReportAdapter(lambda: Conn(), None, None).write_numeric({})
    assert got.value.code == "REPORT_REJECTED" and got.value.retryable is False and error_name in got.value.message


def test_a_store_that_is_down_is_still_retried(monkeypatch):
    import psycopg

    def down(*a, **k):
        raise psycopg.OperationalError("connection refused")
    monkeypatch.setattr(timescale, "write_package", down)
    with pytest.raises(psycopg.OperationalError):
        ReportAdapter(lambda: Conn(), None, None).write_numeric({})
