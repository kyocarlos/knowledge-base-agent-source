from pathlib import Path


def test_runtime_image_includes_operator_owned_timeseries_migrations():
    """The migration runner resolves /app/migrations/timeseries at runtime."""
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY migrations/ ./migrations/" in dockerfile
