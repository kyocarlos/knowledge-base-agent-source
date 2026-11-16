"""The model menu script: content-hash file name, what it may send, where it must not run, and the deploy script's target pages."""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = next((ROOT / "frontend").glob("km-llm-select.*.js"))
TEXT = JS.read_text(encoding="utf-8")


def test_the_file_name_carries_its_content_hash():
    assert re.fullmatch(r"km-llm-select\.[0-9a-f]{12}\.js", JS.name)
    assert hashlib.sha256(JS.read_bytes()).hexdigest()[:12] == JS.name.split(".")[1]


def test_the_script_sends_only_a_profile_id_never_a_model_name_url_or_key():
    assert "body.llm = state.current" in TEXT
    for forbidden in ("api_key", "Authorization", "X-API-KEY", "base_url", "gpt-oss", "modaone"):
        assert forbidden not in TEXT, forbidden
    assert not re.search(r"sk-[A-Za-z0-9]", TEXT)


def test_the_default_model_leaves_the_request_unchanged():
    assert "explicit()" in TEXT and "state.current !== state.defaultId" in TEXT


def test_it_only_runs_on_the_guide_and_zone_pages_and_not_on_wifi_or_demo_admin():
    zone_line = re.findall(r"const zone = .*", TEXT)[0]
    assert "zone === 'admin'" in TEXT and "hub" in zone_line and "zones" in zone_line
    assert "wifi8" not in zone_line and "Not used on /wifi8/" in TEXT


def test_a_blocked_or_expired_choice_falls_back_to_the_default_and_the_error_is_text():
    for code in ("expired", "zone_blocked", "unknown_profile"):
        assert code in TEXT
    assert "detail: detail.message" in TEXT


def test_the_deploy_script_targets_the_pages_and_has_a_rollback():
    script = (ROOT / "scripts" / "deploy_llm_select.sh").read_text(encoding="utf-8")
    for page in ("hub/index.html", "zones/cert/index.html", "zones/csit/index.html", "zones/mobile/index.html"):
        assert page in script
    assert "wifi8/index.html" not in script.split("PAGES=(")[1].split(")")[0] and "zones/admin" not in script.split("PAGES=(")[1].split(")")[0]
    assert "--rollback" in script and "pre-llm-select" in script


def test_usage_is_shown_but_never_claimed_as_the_official_balance():
    assert "pointsRemaining" in TEXT and "pointsUsed" in TEXT
    assert "非官方" in TEXT or "非官方餘額" in TEXT
    assert "p.usage" in TEXT   # the option text and the note both read it from the server's listing


def test_the_menu_reloads_after_an_answer_so_the_usage_figure_stays_current():
    assert TEXT.count("load();") >= 2   # once on a policy error (existing), once after every successful answer (new)
