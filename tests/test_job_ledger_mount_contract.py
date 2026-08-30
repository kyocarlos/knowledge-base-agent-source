import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/validate_job_ledger_mount_contract.py"
SPEC = importlib.util.spec_from_file_location("ledger_mount_contract", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _container(source: Path, logical: str) -> dict:
    return {
        "Name": "/isolated",
        "Config": {"Env": [f"KB_JOB_LEDGER_PATH={logical}"]},
        "Mounts": [{"Source": str(source), "Destination": "/data"}],
    }


def test_validate_requires_same_physical_identity(tmp_path, monkeypatch):
    logical = "/data/job-ledger.sqlite3"
    ledger = tmp_path / "job-ledger.sqlite3"
    ledger.write_bytes(b"shared-ledger")
    monkeypatch.setattr(MODULE, "docker_inspect", lambda _: _container(tmp_path, logical))
    result = MODULE.validate(["web", "worker"], logical)
    assert result["result"] == "PASS"
    assert result["physical_identity_count"] == 1
    assert result["read_only"] is True


def test_validate_rejects_different_sources(tmp_path, monkeypatch):
    logical = "/data/job-ledger.sqlite3"
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "job-ledger.sqlite3").write_bytes(b"a")
    (second / "job-ledger.sqlite3").write_bytes(b"b")
    containers = {"web": _container(first, logical), "worker": _container(second, logical)}
    monkeypatch.setattr(MODULE, "docker_inspect", containers.__getitem__)
    result = MODULE.validate(["web", "worker"], logical)
    assert result["result"] == "FAIL"
    assert result["physical_identity_count"] == 2
