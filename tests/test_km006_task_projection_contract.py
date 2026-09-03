from pathlib import Path


TASKS_SOURCE = Path(__file__).parents[1].joinpath("src", "web_api", "tasks.py")


def test_search_task_exposes_graph_results_as_sources():
    source = TASKS_SOURCE.read_text(encoding="utf-8")
    assert 'result.get("sources") or result.get("graph_results", [])' in source
    assert '"sources": sources' in source
