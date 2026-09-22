from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "scripts" / "preflight_timeseries_preprod.py"
    spec = importlib.util.spec_from_file_location("timeseries_preflight", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_preflight_fails_closed_when_required_secret_names_are_missing(monkeypatch, capsys):
    module = _load()
    for name in module.REQUIRED:
        monkeypatch.delenv(name, raising=False)
    assert module.main() == 2
    assert "missing=" in capsys.readouterr().out


def test_preflight_rejects_enabled_receiver_without_test_scope(monkeypatch, capsys):
    module = _load()
    for name in module.REQUIRED:
        monkeypatch.setenv(name, "present")
    monkeypatch.setenv("KM_PGADMIN_PORT", "0")
    monkeypatch.setenv("KM_TIMESERIES_MIN_FREE_BYTES", "0")
    monkeypatch.setenv("KM_CSIT_NOTIFICATION_ENABLED", "true")
    monkeypatch.setenv("KM_CSIT_NOTIFICATION_ELIGIBILITY", "disabled")
    monkeypatch.delenv("KM_CSIT_NOTIFICATION_AUTH_TOKEN", raising=False)
    assert module.main() == 2
    assert "receiver_not_test_scoped" in capsys.readouterr().out
