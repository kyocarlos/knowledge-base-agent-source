from datetime import timezone

import pytest

from src.timeseries_store import TimeseriesValidationError, _iso, _sample_key


def test_measurement_time_requires_timezone_and_is_normalized():
    value = _iso("2026-09-21T01:00:00+08:00", "observed_at")
    assert value.tzinfo == timezone.utc
    assert value.hour == 17
    with pytest.raises(TimeseriesValidationError, match="timezone"):
        _iso("2026-09-21T01:00:00", "observed_at")


def test_sample_identity_keeps_sequence_and_revision_distinct():
    observed = _iso("2026-09-21T01:00:00Z", "observed_at")
    row = {"case_id": "TC-1", "metric": "throughput", "value": 10, "unit": "Mbps"}
    assert _sample_key("run", "r1", row, observed, "ue-1") != _sample_key("run", "r1", row, observed, "ue-2")
    assert _sample_key("run", "r1", row, observed, "ue-1") != _sample_key("run", "r2", row, observed, "ue-1")
