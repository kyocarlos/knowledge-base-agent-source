from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "restart_kb.sh"


def _function_body(name: str, next_name: str) -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index(f"{name}() {{")
    end = text.index(f"{next_name}() {{", start)
    return text[start:end]


def test_capture_is_best_effort_read_only_and_redacted():
    body = _function_body("capture_ingress_failure_diagnostics", "check_wp0_contract")
    for required in (
        "docker inspect kb-web",
        "docker inspect kb-nginx",
        "getent hosts web",
        "http://web:8000/health",
        "http://web:8000/api/v1/version",
        '"$BASE_URL/health"',
        '"$BASE_URL/api/v1/version"',
        "docker logs --since 3m kb-nginx",
        "nginx -T",
        '"secrets_included": False',
        '"capture_failure_must_not_block_rollback": True',
        "return 0",
    ):
        assert required in body
    assert "Authorization" in body and "Cookie" in body
    assert "api[_-]?key" in body and "[REDACTED]" in body
    assert "docker rm" not in body
    assert "docker stop" not in body
    assert "docker restart" not in body
    assert "docker compose" not in body
    assert "git " not in body


def test_readiness_failure_captures_before_rollback():
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("if ! run_bounded_deployment_readiness; then", text.index("run_deploy_pinned"))
    end = text.index("fi", start)
    block = text[start:end]
    assert block.index("capture_ingress_failure_diagnostics") < block.index("rollback_deploy")


def test_capture_isolated_contract_does_not_run_production_mutation():
    body = _function_body("capture_ingress_failure_diagnostics", "check_wp0_contract")
    assert "production" not in body.lower()
    assert "synthetic" not in body.lower()
