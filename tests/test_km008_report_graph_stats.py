from pathlib import Path


INGEST_SOURCE = Path(__file__).parents[1] / "src" / "ingest.py"


def test_simple_report_path_assigns_report_graph_stats():
    source = INGEST_SOURCE.read_text(encoding="utf-8")
    call = "graph_stats = write_report_graph("
    assert source.count(call) >= 2
    assert "graph_stats.get(\"sections\", 0)" in source
    assert "report_graph_written = any(" in source
