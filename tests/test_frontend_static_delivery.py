import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "validate_frontend_static_delivery.py"
SPEC = importlib.util.spec_from_file_location("validate_frontend_static_delivery", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _write_valid_frontend(root: Path) -> None:
    (root / "index.html").write_text("<!doctype html><script src='app.js'></script>", encoding="utf-8")
    (root / "chat.html").write_text("<!doctype html><title>Chat</title>", encoding="utf-8")
    (root / "app.js").write_text("console.log('isolated');", encoding="utf-8")


def test_valid_frontend_generates_manifest(tmp_path: Path) -> None:
    _write_valid_frontend(tmp_path)

    evidence = MODULE.validate(tmp_path, allow_temporary=True)

    assert evidence["result"] == "PASS"
    assert evidence["file_count"] == 3
    assert evidence["asset_count"] == 1
    assert len(evidence["manifest"]["app.js"]) == 64


def test_empty_or_incomplete_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="required frontend files missing"):
        MODULE.validate(tmp_path, allow_temporary=True)


def test_production_validation_rejects_temporary_path(tmp_path: Path) -> None:
    _write_valid_frontend(tmp_path)

    with pytest.raises(ValueError, match="must not use temporary path"):
        MODULE.validate(Path("/tmp") / tmp_path.name)


def test_isolated_validation_can_explicitly_allow_temporary_path(tmp_path: Path) -> None:
    _write_valid_frontend(tmp_path)

    evidence = MODULE.validate(tmp_path, allow_temporary=True)

    assert evidence["result"] == "PASS"
