from pathlib import Path

import pytest

from src.timeseries_store import TimeSeriesStore


ROOT = Path(__file__).resolve().parents[1]


def test_compose_declares_independent_timescaledb_dependency():
    text = (ROOT / "docker-compose.yml").read_text()
    assert "timescale/timescaledb:2.17.2-pg16" in text
    assert "TIMESCALEDB_URL=postgresql://kb_timeseries:" in text
    assert "timescaledb_data:" in text
    assert "timescaledb:\n        condition: service_healthy" in text


def test_timeseries_store_requires_explicit_endpoint(monkeypatch):
    monkeypatch.delenv("TIMESCALEDB_URL", raising=False)
    with pytest.raises(RuntimeError, match="TIMESCALEDB_URL is required"):
        TimeSeriesStore()
