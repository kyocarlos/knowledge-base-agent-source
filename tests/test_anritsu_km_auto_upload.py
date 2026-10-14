import json
from pathlib import Path

import pytest

from scripts.anritsu_km_auto_upload import AutoUploadError, _artifact_inputs, _runtime_environment, _write_envelope


def test_runtime_environment_maps_controlled_anritsu_names_without_printing_values():
    env = {
        "KB_INGEST_BASE_URL": "https://km.example",
        "KB_INGEST_API_TOKEN_ANRITSU": "secret-token",
        "KB_INGEST_AGENT_ID_ANRITSU": "anritsu-agent",
    }
    mapped = _runtime_environment(env)
    assert mapped["KB_BASE_URL"] == "https://km.example"
    assert mapped["KB_INGEST_TOKEN"] == "secret-token"
    assert mapped["KB_AGENT_ID"] == "anritsu-agent"


def test_runtime_environment_requires_all_controlled_values():
    with pytest.raises(AutoUploadError, match="token"):
        _runtime_environment({"KB_INGEST_BASE_URL": "https://km.example"})


def test_artifact_inputs_reads_generator_output(tmp_path: Path):
    report = tmp_path / "report.xlsx"
    attachment = tmp_path / "run.log"
    manifest = tmp_path / "result.json"
    report.touch()
    attachment.touch()
    manifest.write_text(json.dumps({"report": str(report), "attachments": [str(attachment)], "run_id": "RUN-1"}))
    assert _artifact_inputs(manifest) == (report.resolve(), [attachment.resolve()], "RUN-1")


def test_artifact_inputs_accepts_windows_utf8_bom(tmp_path: Path):
    manifest = tmp_path / "result.json"
    manifest.write_text(json.dumps({"report": "report.xlsx"}), encoding="utf-8-sig")
    assert _artifact_inputs(manifest)[0].name == "report.xlsx"


def test_artifact_inputs_rejects_missing_report_path(tmp_path: Path):
    manifest = tmp_path / "result.json"
    manifest.write_text("{}")
    with pytest.raises(AutoUploadError, match="no report path"):
        _artifact_inputs(manifest)


def test_write_envelope_contains_no_credentials(tmp_path: Path):
    report = tmp_path / "report.xlsx"
    attachment = tmp_path / "run.log"
    target = _write_envelope(tmp_path / "outbox", report, [attachment], "RUN-1")
    data = json.loads(target.read_text())
    assert data["run_id"] == "RUN-1"
    assert data["secrets_included"] is False
    assert "token" not in target.read_text().lower()
