import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "restart_kb.sh"


class RestartKbScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=ROOT,
            env={**os.environ, "PATH": os.environ.get("PATH", "")},
            check=False,
            capture_output=True,
            text=True,
        )

    def test_shell_syntax_and_executable_mode(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], check=False, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_default_is_read_only_status_and_help_documents_modes(self):
        self.assertIn('MODE="status"', self.source)
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--status", result.stdout)
        self.assertIn("--restart", result.stdout)
        self.assertIn("--deploy", result.stdout)

    def test_deploy_requires_confirmation_before_preflight(self):
        result = self.run_script("--deploy")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--confirm-deploy DEPLOY_WP01", result.stderr)
        self.assertNotIn("Configuration preflight", result.stdout)

    def test_unknown_argument_fails_before_runtime_actions(self):
        result = self.run_script("--not-a-real-option")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown argument", result.stderr)
        self.assertNotIn("docker compose", result.stdout)

    def test_restart_never_removes_or_rebuilds_data_services(self):
        self.assertNotIn("docker rm -f", self.source)
        start = self.source.index("run_restart()")
        end = self.source.index("check_deploy_source()")
        restart_body = self.source[start:end]
        self.assertIn("compose_preflight", restart_body)
        self.assertIn("require_idle_tasks", restart_body)
        self.assertIn('restart "${APP_SERVICES[@]}"', restart_body)
        self.assertNotIn(" build ", restart_body)
        for service in ("redis", "neo4j", "qdrant", "report_registry"):
            self.assertNotIn(f" restart {service}", restart_body)

    def test_deploy_has_checkpoint_candidate_gate_and_rollback(self):
        start = self.source.index("run_deploy()")
        deploy_body = self.source[start:]
        self.assertIn("prepare_checkpoint", deploy_body)
        self.assertIn("kb-wp01-candidate:", deploy_body)
        self.assertIn("run_acceptance_gates", deploy_body)
        self.assertGreaterEqual(deploy_body.count("rollback_deploy"), 2)
        self.assertIn("restore_frontend", deploy_body)

    def test_wp0_wp1_acceptance_contracts_are_explicit(self):
        for endpoint in (
            "/health",
            "/api/v1/health/live",
            "/api/v1/health/ready",
            "/api/v1/version",
            "/api/agent/v1/health",
        ):
            self.assertIn(endpoint, self.source)
        self.assertIn("WP0 error/trace envelope", self.source)
        self.assertIn("active_queues", self.source)
        self.assertIn("JobConfig", self.source)
        self.assertIn("Beat scheduler", self.source)

    def test_paths_and_external_url_are_configurable(self):
        self.assertIn('dirname -- "${BASH_SOURCE[0]}"', self.source)
        self.assertIn("KB_INTERNAL_BASE_URL", self.source)
        self.assertIn("KB_EXTERNAL_URL", self.source)
        self.assertNotIn("61.216.9.52", self.source)
        self.assertNotIn('ROOT_DIR="/home/', self.source)


if __name__ == "__main__":
    unittest.main()
