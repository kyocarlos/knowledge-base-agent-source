"""The duplicate-content report: grouping rules, and that it can only read."""
import re

from src.csit_integration_v1 import duplicate_content as dc

S1, S2 = "a" * 64, "b" * 64


def row(job, sha, entity, doc=None, version=1, lane="v2", stype="VendorFile", status="Completed", size=100, index_state=None, created="2026-11-20T01:00:00Z", name="x.png"):
    return {"lane": lane, "km_job_id": job, "source_type": stype, "source_entity_id": entity, "document_id": doc or entity, "version": version, "file_name": name,
            "size_bytes": size, "sha256": sha, "status": status, "index_state": index_state, "created_at": created}


def test_two_records_with_the_same_bytes_are_reported_as_one_group():
    g = dc.group_duplicates([row("KM-ING-1", S1, "e1"), row("KM-ING-2", S1, "e2"), row("KM-ING-3", S2, "e3")])
    assert len(g) == 1 and g[0]["count"] == 2 and g[0]["sha256"] == S1
    assert [m["km_job_id"] for m in g[0]["members"]] == ["KM-ING-1", "KM-ING-2"]


def test_a_retry_of_the_same_document_is_not_a_second_copy():
    # same source, entity, document and version: one CSIT document that happens to have two job rows
    assert dc.group_duplicates([row("KM-ING-1", S1, "e1"), row("KM-ING-9", S1, "e1")]) == []


def test_different_version_of_the_same_document_with_equal_bytes_counts_as_another_document():
    g = dc.group_duplicates([row("KM-ING-1", S1, "e1", version=1), row("KM-ING-2", S1, "e1", version=2)])
    assert len(g) == 1 and g[0]["count"] == 2


def test_failed_deleted_and_superseded_jobs_are_ignored():
    rows = [row("KM-ING-1", S1, "e1"), row("KM-ING-2", S1, "e2", status="Failed"), row("KM-ING-3", S1, "e3", status="Deleted"),
            row("KM-ING-4", S1, "e4", index_state="Superseded")]
    assert dc.group_duplicates(rows) == []


def test_groups_span_the_lanes_and_the_largest_group_comes_first():
    rows = [row("J1", S1, "e1", lane="v1-testreport", stype="TestReport"), row("J2", S1, "e2", lane="v1-doclib", stype="DocumentLibraryFile"),
            row("J3", S2, "e3"), row("J4", S2, "e4"), row("J5", S2, "e5")]
    g = dc.group_duplicates(rows)
    assert [x["count"] for x in g] == [3, 2]
    assert g[1]["source_types"] == ["DocumentLibraryFile", "TestReport"]


def test_sha256_is_compared_without_regard_to_case_and_blank_values_are_skipped():
    g = dc.group_duplicates([row("J1", S1.upper(), "e1"), row("J2", S1, "e2"), row("J3", "", "e3"), row("J4", None, "e4")])
    assert len(g) == 1 and g[0]["count"] == 2


def test_equal_sha256_with_different_sizes_is_flagged_not_hidden():
    g = dc.group_duplicates([row("J1", S1, "e1", size=100), row("J2", S1, "e2", size=101)])
    assert g[0]["size_mismatch"] is True


def test_text_report_says_nothing_was_merged_or_blocked():
    text = dc.render_text(dc.group_duplicates([row("KM-ING-1", S1, "e1"), row("KM-ING-2", S1, "e2")]))
    assert "沒有合併" in text and "KM-ING-1" in text and "KM-ING-2" in text
    assert dc.render_text([]) == "沒有內容相同的重複文件。"


def test_the_module_can_only_read():
    src = open(dc.__file__, encoding="utf-8").read()
    for sql in dc.LANE_SQL.values():
        assert re.match(r"\s*SELECT\b", sql) and not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b", sql, re.I)
    assert "default_transaction_read_only = on" in src
    assert not re.search(r"\.execute\(\s*[\"'](INSERT|UPDATE|DELETE)", src, re.I)
