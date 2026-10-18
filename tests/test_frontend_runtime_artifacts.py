from pathlib import Path

import pytest

from scripts.validate_frontend_runtime_artifacts import validate


def test_runtime_artifact_requires_legacy_chat_page(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("index", encoding="utf-8")
    with pytest.raises(ValueError, match="chat.html"):
        validate(tmp_path)


def test_runtime_artifact_contract_records_hashes(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("index", encoding="utf-8")
    (tmp_path / "chat.html").write_text("chat", encoding="utf-8")
    result = validate(tmp_path)
    assert result["legacy_chat_contract"] == "PASS"
    assert result["secrets_included"] is False
    assert result["required_files"]["chat.html"]["size"] == 4
