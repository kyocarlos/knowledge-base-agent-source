from pathlib import Path
from unittest.mock import patch

import pytest

from src.qdrant_readiness import QdrantNotReadyError, check_qdrant_ready
from src.runtime_config import resolve_qdrant_url


ROOT = Path(__file__).resolve().parents[1]


def test_compose_declares_qdrant_and_required_dependencies():
    text = (ROOT / "docker-compose.yml").read_text()
    assert "qdrant/qdrant:v1.13.6" in text
    assert "QDRANT_URL=http://qdrant:6333" in text
    assert "KB_QDRANT_READINESS_REQUIRED=true" in text
    assert "http://127.0.0.1:6333/healthz" in text
    assert text.count("qdrant:\n        condition: service_healthy") >= 3


def test_qdrant_readiness_raises_without_endpoint(monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)
    with pytest.raises(QdrantNotReadyError):
        check_qdrant_ready()


def test_qdrant_readiness_uses_healthz():
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("src.qdrant_readiness.urlopen", return_value=Response()) as open_url:
        assert check_qdrant_ready("http://qdrant:6333") is True
    open_url.assert_called_once_with("http://qdrant:6333/healthz", timeout=2.0)


def test_explicit_qdrant_url_never_falls_back_to_host_endpoint(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://isolated-qdrant:6333")
    assert resolve_qdrant_url() == "http://isolated-qdrant:6333"
