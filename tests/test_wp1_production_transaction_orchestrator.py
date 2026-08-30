from pathlib import Path
import subprocess


SCRIPT = Path(__file__).parents[1] / "scripts/wp1_production_transaction_orchestrator.sh"


def test_orchestrator_shell_syntax():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_orchestrator_has_required_fail_closed_controls():
    text = SCRIPT.read_text(encoding="utf-8")
    for marker in (
        "trap on_exit EXIT",
        "trap 'exit 130' INT",
        "trap 'exit 143' TERM",
        "trap 'exit 129' HUP",
        "--no-build",
        "--no-deps",
        "--force-recreate web",
        "wp1_maintenance_entrypoint.py",
        "run_wp1_production_acceptance.py",
        "wp1_negative_e2e_probe.py",
        'secrets_included":false',
    ):
        assert marker in text


def test_orchestrator_does_not_directly_call_runner_without_entrypoint():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "run_wp1_production_acceptance.py" in text
    assert "wp1_maintenance_entrypoint.py" in text
    assert "--production" in text
