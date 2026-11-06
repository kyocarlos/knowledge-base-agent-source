"""Which template a workbook gets: the registered file-name prefixes first, otherwise the sheets (only for SIT- document numbers, only when they say one thing)."""
import pytest
from openpyxl import Workbook

from src.csit_integration_v1.report_adapter import ReportAdapter
from src.report_numeric.parser import classify_content, classify_or_none

LAYOUTS = {
    "cellular_throughput": ["Cover", "2. Introduction", "3. Test Result Summary", "4. Performance Test", "5. Reference"],
    "cellular_handover": ["Cover", "3. Test Result Summary", "4.1 Xn Handover", "4.2 NG Handover"],
    "wifi_rvr": ["Cover", "3. Test Result Summary", "3.1 RvR_2.4G-20M", "3.2 RvR_5G-80M"],
    "wifi_throughput": ["Cover", "3.Test Result Summary", "4. Criteria", "4.1 2.4GHz Test", "4.2 5GHz Test", "4.3 Concurrent Test"],
}


def book(tmp_path, sheets, name="w.xlsx"):
    wb = Workbook()
    wb.active.title = sheets[0]
    for title in sheets[1:]:
        wb.create_sheet(title)
    path = tmp_path / name
    wb.save(path)
    return path


@pytest.mark.parametrize("kind", sorted(LAYOUTS))
def test_the_sheets_show_the_type_of_a_file_whose_name_is_not_a_registered_prefix(tmp_path, kind):
    path = book(tmp_path, LAYOUTS[kind])
    assert classify_content(path) == kind
    assert classify_or_none("SIT-TR-NR-Throughput-X-EV-V10.xlsx" if kind == "cellular_throughput" else "SIT-ZZ-QQ-Other-X-EV-V1.xlsx", path) == kind


def test_a_registered_prefix_is_still_decided_by_the_name_alone(tmp_path):
    assert classify_or_none("SIT-TR-WL-RvR-X-D1-DV-V10.xlsx") == "wifi_rvr"
    assert classify_or_none("SIT-TR-WL-RvR-X-D1-DV-V10.xlsx", book(tmp_path, ["Cover"])) == "wifi_rvr"     # its sheets are not consulted
    assert classify_or_none("SIT-TR-NR-Throughput-X-EV-V10.xlsx") is None                                 # no path: the name alone does not register a variant


def test_a_layout_with_no_registered_template_keeps_the_generic_path(tmp_path):
    en_dc = book(tmp_path, ["Cover", "3.Test Result Summary", "4.1 5GNR_Eth", "4.2 EN-DC_Eth", "4.3 EN-DC_WiFi2.4G"], "endc.xlsx")
    assert classify_content(en_dc) is None and classify_or_none("SIT-TR-NR-Throughput-NCQ2200B2V-EV-V10.xlsx", en_dc) is None


def test_sheets_that_show_two_types_decide_nothing(tmp_path):
    both = book(tmp_path, LAYOUTS["wifi_rvr"] + ["4.1 Xn Handover"], "both.xlsx")
    assert classify_content(both) is None and classify_or_none("SIT-TR-XX-Mixed-X-EV-V1.xlsx", both) is None


def test_only_a_document_number_name_is_looked_into(tmp_path):
    path = book(tmp_path, LAYOUTS["wifi_rvr"])
    assert classify_or_none("budget-2026.xlsx", path) is None
    assert classify_or_none("SIT-TR-XX-Other-X-EV-V1.pdf", path) is None
    assert classify_content(tmp_path / "missing.xlsx") is None


def test_the_adapter_uses_the_path_when_the_pipeline_gives_it(tmp_path):
    adapter = ReportAdapter(None, None, None)
    job = {"file_name": "SIT-TR-NR-Throughput-X-EV-V10.xlsx"}
    assert not adapter.matches(job)
    assert adapter.matches(job, book(tmp_path, LAYOUTS["cellular_throughput"]))
    assert not adapter.matches(job, book(tmp_path, ["Cover", "Notes"], "plain.xlsx"))
