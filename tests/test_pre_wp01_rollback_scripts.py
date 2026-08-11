from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rollback_requires_explicit_production_confirmation():
    source = (ROOT / "scripts/rollback_pre_wp01.py").read_text()
    assert "PRE_WP01_ROLLBACK" in source
    assert "--confirm-production" in source


def test_rollback_never_deletes_volumes_or_restores_data_implicitly():
    source = (ROOT / "scripts/rollback_pre_wp01.py").read_text()
    assert "volume rm" not in source
    assert "docker volume" not in source
    assert "--force-recreate" in source
    assert "--no-deps" in source


def test_backup_uses_logical_and_online_database_exports():
    source = (ROOT / "scripts/pre_wp01_backup.py").read_text()
    assert "apoc.export.cypher.all" in source
    assert "pg_dump" in source
    assert "/snapshots" in source
    assert "sqlite3" in source


def test_shadow_drill_uses_isolated_names_and_failure_injection():
    source = (ROOT / "scripts/drill_pre_wp01_rollback.py").read_text()
    assert "kb-wp01-shadow" in source
    assert "wp01-candidate-failed" in source
    assert '"--volumes"' in source
