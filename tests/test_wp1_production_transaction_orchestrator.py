from pathlib import Path
import json
import os
import signal
import subprocess
import textwrap
import time

import pytest


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


def _isolated_fixture(tmp_path, runner_exit=0, sleep_runner=False):
    prod = tmp_path / "prod"
    (prod / "scripts").mkdir(parents=True)
    (prod / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(prod), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(prod), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(prod), "config", "user.name", "isolated-test"], check=True)
    subprocess.run(["git", "-C", str(prod), "add", "."], check=True)
    subprocess.run(["git", "-C", str(prod), "commit", "-qm", "fixture"], check=True)
    head = subprocess.check_output(["git", "-C", str(prod), "rev-parse", "HEAD"], text=True).strip()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "docker-state"
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        set -u
        state="${MOCK_STATE:?}"
        web_target="${MOCK_WEB_TARGET:-kb-web}"
        ingest_target="${MOCK_INGEST_TARGET:-kb-celery-ingest}"
        search_target="${MOCK_SEARCH_TARGET:-kb-celery-search}"
        beat_target="${MOCK_BEAT_TARGET:-kb-celery-beat}"
        if [ "${1:-}" = inspect ]; then
          service="${2:-}"
          mode=$(sed -n 's/^mode=//p' "$state")
          if [ "$service" = "$web_target" ]; then
            printf 'KB_E2E_WRITE_MODE_ENABLED=%s\\n' "$mode"
            if [ "$mode" = true ]; then
              printf '%s\\n' KB_E2E_AGENT_TOKEN_HASHES_JSON KB_E2E_REVIEWER_TOKEN_HASHES_JSON KB_E2E_CLEANUP_ENABLED KB_E2E_CLEANUP_TOKEN_HASHES_JSON KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX
            fi
          elif [ "$service" = "$ingest_target" ]; then
            printf '%s\\n' KB_E2E_AGENT_TOKEN_HASHES_JSON KB_E2E_REVIEWER_TOKEN_HASHES_JSON KB_E2E_CLEANUP_ENABLED KB_E2E_CLEANUP_TOKEN_HASHES_JSON KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX
          fi
          exit 0
        fi
        if [ "${1:-}" = compose ]; then
          has_overlay=0
          for arg in "$@"; do [ "$arg" = "${MOCK_OVERLAY:-}" ] && has_overlay=1; done
          case " $* " in
            *" config --quiet "*) exit 0 ;;
            *" up "*)
              if [ "$has_overlay" -eq 0 ] && [ "${MOCK_RESTORE_FAIL:-0}" = 1 ]; then exit 9; fi
              printf 'recreate=web\\n' >> "$state"
              if [ "$has_overlay" -eq 1 ]; then sed -i 's/^mode=.*/mode=true/' "$state"; else sed -i 's/^mode=.*/mode=false/' "$state"; fi
              exit 0 ;;
          esac
        fi
        exit 0
    """), encoding="utf-8")
    fake_docker.chmod(0o755)

    fake_python = bin_dir / "python3"
    fake_python.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        set -u
        args="$*"
        if [[ "$args" == *wp1_negative_e2e_probe.py* ]]; then
          out=""
          prev=""
          for arg in "$@"; do [ "$prev" = --evidence-out ] && out="$arg"; prev="$arg"; done
          printf '{"status":%s,"secrets_included":false}\\n' "${MOCK_PROBE_STATUS:-404}" > "$out"
          exit 0
        fi
        if [[ "$args" == *run_wp1_production_acceptance.py* && -n "${MOCK_RUNNER_ARGS_FILE:-}" ]]; then
          printf '%s\n' "$@" > "$MOCK_RUNNER_ARGS_FILE"
        fi
        if [[ "$args" == *wp1_maintenance_entrypoint.py* ]]; then
          [ "${MOCK_SLEEP_RUNNER:-0}" = 1 ] && sleep 30
          exit "${MOCK_RUNNER_EXIT:-0}"
        fi
        exec /usr/bin/python3 "$@"
    """), encoding="utf-8")
    fake_python.chmod(0o755)

    fake_curl = bin_dir / "curl"
    fake_curl.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        set -u
        calls_file="${MOCK_CURL_CALLS:?}"
        calls=0
        [ -f "$calls_file" ] && calls=$(cat "$calls_file")
        calls=$((calls + 1))
        printf '%s\n' "$calls" > "$calls_file"
        code=200
        if [ "${MOCK_READINESS_ALWAYS_FAIL:-0}" = 1 ]; then
          code=503
        elif [ "$calls" -lt "${MOCK_READINESS_READY_AFTER_CALLS:-1}" ]; then
          code=503
        fi
        printf '%s' "$code"
    """), encoding="utf-8")
    fake_curl.chmod(0o755)

    overlay = tmp_path / "overlay.env"
    overlay.write_text("\n".join([
        "KB_E2E_WRITE_MODE_ENABLED=true", "KB_E2E_AGENT_TOKEN_HASHES_JSON=redacted",
        "KB_E2E_REVIEWER_TOKEN_HASHES_JSON=redacted", "KB_E2E_CLEANUP_ENABLED=true",
        "KB_E2E_CLEANUP_TOKEN_HASHES_JSON=redacted", "KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX=TR-E2E-WP1-ISO",
    ]) + "\n", encoding="utf-8")
    overlay.chmod(0o600)
    base_env = tmp_path / "base.env"
    base_env.write_text("BASE=1\n", encoding="utf-8")
    for path in (tmp_path / "credentials.env", tmp_path / "fixture.xlsx", tmp_path / "pinned.yml"):
        path.write_text("isolated\n", encoding="utf-8")
    state.write_text("mode=false\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{env['PATH']}", "MOCK_STATE": str(state), "MOCK_OVERLAY": str(overlay),
        "MOCK_CURL_CALLS": str(tmp_path / "curl-calls.txt"), "MOCK_READINESS_READY_AFTER_CALLS": "1",
        "MOCK_RUNNER_ARGS_FILE": str(tmp_path / "runner-args.txt"),
        "MOCK_RUNNER_EXIT": str(runner_exit), "MOCK_SLEEP_RUNNER": "1" if sleep_runner else "0",
        "WP1_EXECUTION_MODE": "isolated", "WP1_COMPOSE_PROJECT": "wp1-isolated-test",
        "WP1_COMPOSE_FILE": str(prod / "docker-compose.yml"), "WP1_ISOLATED_BASE_URL": "http://127.0.0.1:13030",
        "WP1_ISOLATED_DATA_ROOT": str(tmp_path / "data"), "WP1_ISOLATED_CONFIG_ROOT": str(tmp_path / "config"),
        "WP1_ISOLATED_LEDGER_PATH": str(tmp_path / "data" / "job-ledger.sqlite3"),
        "WP1_ISOLATED_CONTAINER_PREFIX": "wp1iso-", "WP1_ISOLATED_PORTS": "13030:443",
        "WP1_WEB_TARGET": "wp1iso-web", "WP1_INGEST_TARGET": "wp1iso-ingest",
        "WP1_SEARCH_TARGET": "wp1iso-search", "WP1_BEAT_TARGET": "wp1iso-beat",
        "MOCK_WEB_TARGET": "wp1iso-web", "MOCK_INGEST_TARGET": "wp1iso-ingest",
        "WP1_RUN_ID": "TR-E2E-WP1-PROD-ISOLATED-20260830-0001",
        "WP1_PROD": str(prod), "WP1_EVIDENCE_ROOT": str(evidence), "WP1_BASE_ENV": str(base_env),
        "WP1_OVERLAY": str(overlay), "WP1_PINNED_OVERRIDE": str(tmp_path / "pinned.yml"),
        "WP1_CREDENTIALS_ENV": str(tmp_path / "credentials.env"), "WP1_FIXTURE": str(tmp_path / "fixture.xlsx"),
        "WP1_ATTACHMENT": str(tmp_path / "fixture.xlsx"), "WP1_EXPECTED_GIT_HEAD": head,
        "WP1_EXPECTED_RUNNER_SHA": "runner", "WP1_EXPECTED_CRYPTO_SHA": "crypto",
        "WP1_EXPECTED_COMMIT": "commit", "WP1_EXPECTED_RELEASE_ID": "release",
        "WP1_EXPECTED_IMAGE_ID": "image", "WP1_EXPECTED_BUILD_TIMESTAMP": "timestamp",
        "WP1_READINESS_INTERVAL_SECONDS": "0", "WP1_READINESS_TIMEOUT_SECONDS": "1",
    })
    return env, evidence, state


def _run_isolated(tmp_path, runner_exit=0, sleep_runner=False):
    env, evidence, state = _isolated_fixture(tmp_path, runner_exit, sleep_runner)
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)
    tx = evidence / env["WP1_RUN_ID"]
    return result, tx, state


def test_isolated_success_recreates_only_web_and_restores(tmp_path):
    result, tx, state = _run_isolated(tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads((tx / "transaction-result.json").read_text())
    assert payload["transaction_result"] == "PASS"
    assert state.read_text().splitlines().count("recreate=web") == 2
    assert "restoration_verified" in (tx / "orchestration.jsonl").read_text()


def test_isolated_runner_failure_stays_fail_closed_and_restores(tmp_path):
    result, tx, state = _run_isolated(tmp_path, runner_exit=7)
    assert result.returncode == 7
    payload = json.loads((tx / "transaction-result.json").read_text())
    assert payload["acceptance_result"] == "FAIL_CLOSED"
    assert payload["transaction_result"] == "FAIL_CLOSED"
    assert state.read_text().splitlines().count("recreate=web") == 2


@pytest.mark.parametrize("sig,expected", [(signal.SIGINT, 130), (signal.SIGTERM, 143), (signal.SIGHUP, 129)])
def test_isolated_signal_restores_and_stays_fail_closed(tmp_path, sig, expected):
    env, evidence, state = _isolated_fixture(tmp_path, sleep_runner=True)
    proc = subprocess.Popen(
        ["bash", str(SCRIPT)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.25)
    os.killpg(proc.pid, sig)
    proc.communicate(timeout=10)
    tx = evidence / env["WP1_RUN_ID"]
    payload = json.loads((tx / "transaction-result.json").read_text())
    assert proc.returncode == expected
    assert payload["transaction_result"] == "FAIL_CLOSED"
    assert state.read_text().splitlines().count("recreate=web") == 2


def test_isolated_restoration_failure_stays_fail_closed(tmp_path):
    env, evidence, state = _isolated_fixture(tmp_path)
    env["MOCK_RESTORE_FAIL"] = "1"
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)
    tx = evidence / env["WP1_RUN_ID"]
    payload = json.loads((tx / "transaction-result.json").read_text())
    assert result.returncode != 0
    assert payload["restoration_result"] == "FAIL_CLOSED"
    assert payload["transaction_result"] == "FAIL_CLOSED"
    assert state.read_text().splitlines().count("recreate=web") == 1


def test_isolated_precondition_failure_does_not_recreate(tmp_path):
    env, evidence, state = _isolated_fixture(tmp_path)
    state.write_text("mode=unexpected\n", encoding="utf-8")
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "recreate=web" not in state.read_text()
    assert not (evidence / env["WP1_RUN_ID"] / "transaction-result.json").exists()


def test_production_profile_rejects_isolated_inputs(tmp_path):
    env, evidence, state = _isolated_fixture(tmp_path)
    env["WP1_EXECUTION_MODE"] = "production"
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "isolated input is not allowed in production mode" in result.stderr
    assert "recreate=web" not in state.read_text()


def test_isolated_runner_command_omits_production_flag(tmp_path):
    result, tx, _ = _run_isolated(tmp_path)
    assert result.returncode == 0, result.stderr
    args = (tmp_path / "runner-args.txt").read_text().splitlines()
    assert "--production" not in args
    assert "--base-url" in args
    assert "http://127.0.0.1:13030" in args


def test_delayed_readiness_is_bounded_and_runner_starts_after_pass(tmp_path):
    env, evidence, state = _isolated_fixture(tmp_path)
    env["MOCK_READINESS_READY_AFTER_CALLS"] = "3"
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    tx = evidence / env["WP1_RUN_ID"]
    log = (tx / "orchestration.jsonl").read_text()
    assert '"event":"post_enable_readiness_passed"' in log
    assert '"event":"post_restore_readiness_passed"' in log
    assert log.index('"event":"post_enable_readiness_passed"') < log.index('"event":"runner_launch"')


def test_never_ready_fails_closed_without_runner(tmp_path):
    env, evidence, state = _isolated_fixture(tmp_path)
    env["MOCK_READINESS_ALWAYS_FAIL"] = "1"
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    tx = evidence / env["WP1_RUN_ID"]
    log = (tx / "orchestration.jsonl").read_text()
    assert '"event":"post_enable_readiness_failed"' in log
    assert '"event":"runner_launch"' not in log
    assert state.read_text().splitlines().count("recreate=web") == 2


def test_production_runner_command_includes_production_flag(tmp_path):
    env, evidence, state = _isolated_fixture(tmp_path)
    for key in (
        "WP1_COMPOSE_PROJECT", "WP1_COMPOSE_FILE", "WP1_ISOLATED_BASE_URL",
        "WP1_ISOLATED_DATA_ROOT", "WP1_ISOLATED_CONFIG_ROOT", "WP1_ISOLATED_LEDGER_PATH",
        "WP1_ISOLATED_CONTAINER_PREFIX", "WP1_ISOLATED_PORTS", "WP1_WEB_TARGET",
        "WP1_INGEST_TARGET", "WP1_SEARCH_TARGET", "WP1_BEAT_TARGET",
    ):
        env.pop(key, None)
    env["WP1_EXECUTION_MODE"] = "production"
    env["MOCK_WEB_TARGET"] = "kb-web"
    env["MOCK_INGEST_TARGET"] = "kb-celery-ingest"
    env["MOCK_SEARCH_TARGET"] = "kb-celery-search"
    env["MOCK_RUNNER_EXIT"] = "0"
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    args = (tmp_path / "runner-args.txt").read_text().splitlines()
    assert "--production" in args
    assert "--base-url" in args
    assert "https://127.0.0.1:3030" in args
