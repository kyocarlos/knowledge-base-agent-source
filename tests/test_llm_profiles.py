"""Selectable LLM profiles: registry, zone policy, expiry, rate limit, the profile list API, and the keeper route."""
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web_api import keeper_routes, llm_profile_routes, llm_profiles as lp

ENV = {"MODAONE_API_KEY": "test-modaone-key", "KM_LLM_PRIMARY_MODEL": "gpt-test", "KM_LLM_PRIMARY_BASE_URL": "http://gateway.test/v1",
       "KM_LLM_PRIMARY_API_KEY_ENV": "TEST_PRIMARY_KEY", "TEST_PRIMARY_KEY": "primary-test-key"}
FILE = Path(__file__).resolve().parents[1] / "config" / "llm_profiles.json"


def registry(env=None, today=date(2026, 11, 16), clock=None, path=FILE):
    return lp.Registry.load(path, env=dict(ENV if env is None else env), today=lambda: today, **({"clock": clock} if clock else {}))


# ---------------------------------------------------------------- the shipped file

def test_the_shipped_profile_file_is_valid_and_keeps_auto_the_default():
    r = registry()
    assert r.default == "auto" and set(r.profiles) == {"auto", "openai", "modaone-gpt-oss-120b", "modaone-llama-3.3-70b"}
    for p in r.profiles.values():
        assert p.expires_at is None or p.expires_at == date(2026, 12, 8)


def test_without_a_file_only_auto_exists(tmp_path):
    r = lp.Registry.load(tmp_path / "missing.json", env={})
    assert list(r.profiles) == ["auto"] and r.default == "auto"


def test_an_invalid_file_leaves_only_auto_and_is_logged(tmp_path, caplog):
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps({"profiles": [{"id": "x", "source": "custom", "model": "m"}]}))
    with caplog.at_level("ERROR"):
        r = lp.Registry.load(bad, env={})
    assert list(r.profiles) == ["auto"] and "invalid" in caplog.text


def test_unknown_zones_or_purposes_in_a_file_are_rejected(tmp_path):
    for entry in ({"id": "a", "source": "primary", "blocked_zones": ["nowhere"]}, {"id": "a", "source": "primary", "purposes": ["chat"]}, {"id": "bad id!", "source": "primary"}):
        f = tmp_path / "p.json"
        f.write_text(json.dumps({"profiles": [entry]}))
        assert list(lp.Registry.load(f, env={}).profiles) == ["auto"]


def test_auto_cannot_be_redefined(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"default": "auto", "profiles": [{"id": "auto", "source": "custom", "model": "m", "base_url": "http://x", "api_key_env": "K", "external": False}]}))
    assert lp.Registry.load(f, env={"K": "k"}).profiles["auto"].source == "auto"


# ---------------------------------------------------------------- policy

def test_no_profile_or_auto_means_the_callers_own_default_path():
    r = registry()
    assert r.complete_for(None, "mobile", "zone_answer") == (None, lp.AUTO_PROFILE)
    assert r.complete_for("auto", "hub", "keeper")[0] is None and r.check("", "wifi", "wifi_agent").id == "auto"


def test_unknown_profile_is_422():
    with pytest.raises(lp.ProfileError) as e:
        registry().check("gpt-9", "mobile", "zone_answer")
    assert e.value.status == 422 and e.value.code == "unknown_profile"


@pytest.mark.parametrize("zone", ["verification", "csit", "equipment", "integrations", "admin"])
def test_external_models_are_blocked_for_the_sensitive_zones(zone):
    with pytest.raises(lp.ProfileError) as e:
        registry().check("modaone-gpt-oss-120b", zone, "zone_answer")
    assert e.value.status == 403 and e.value.code == "zone_blocked"


@pytest.mark.parametrize("zone", ["mobile", "broadband", "cert", "lab", "hub"])
def test_external_models_are_allowed_for_the_other_zones(zone):
    purpose = "keeper" if zone == "hub" else "zone_answer"
    assert registry().check("modaone-gpt-oss-120b", zone, purpose).id == "modaone-gpt-oss-120b"


def test_the_page_key_csit_is_the_verification_zone():
    assert lp.zone_key("csit") == "verification" and lp.zone_key("Mobile") == "mobile" and lp.zone_key("hub") == "hub"


def test_a_profile_stops_after_its_expiry_date():
    r = registry(today=date(2026, 12, 9))
    with pytest.raises(lp.ProfileError) as e:
        r.check("modaone-gpt-oss-120b", "mobile", "zone_answer")
    assert e.value.status == 403 and e.value.code == "expired" and "2026-12-08" in e.value.message
    assert registry(today=date(2026, 12, 8)).check("modaone-gpt-oss-120b", "mobile", "zone_answer")
    assert r.check("openai", "mobile", "zone_answer")


def test_a_missing_key_makes_the_profile_unavailable_not_an_error_page():
    r = registry(env={k: v for k, v in ENV.items() if k != "MODAONE_API_KEY"})
    with pytest.raises(lp.ProfileError) as e:
        r.check("modaone-gpt-oss-120b", "mobile", "zone_answer")
    assert e.value.status == 503 and e.value.code == "unavailable"
    listing = {p["id"]: p for p in r.listing("mobile", "zone_answer")["profiles"]}
    assert listing["modaone-gpt-oss-120b"]["available"] is False and listing["auto"]["available"] is True


def test_wifi_agent_only_offers_auto_until_tool_calling_is_verified():
    listing = {p["id"]: p for p in registry().listing("wifi", "wifi_agent")["profiles"]}
    assert listing["auto"]["available"] is True
    assert all(not p["available"] for pid, p in listing.items() if pid != "auto")
    with pytest.raises(lp.ProfileError) as e:
        registry().check("openai", "wifi", "wifi_agent")
    assert e.value.status == 422 and e.value.code == "not_supported"


def test_the_listing_marks_external_experimental_default_and_reasons():
    out = registry().listing("equipment", "zone_answer")
    by = {p["id"]: p for p in out["profiles"]}
    assert out["zone"] == "equipment" and out["default"] == "auto" and by["auto"]["default"] is True
    assert by["modaone-gpt-oss-120b"]["external"] is True and by["modaone-gpt-oss-120b"]["experimental"] is True
    assert by["modaone-gpt-oss-120b"]["available"] is False and by["modaone-gpt-oss-120b"]["reason"]
    assert by["openai"]["available"] is True
    assert "key" not in json.dumps(out).lower() and "base_url" not in json.dumps(out)


def test_per_account_rate_limit_counts_each_use_and_resets_after_an_hour(monkeypatch):
    monkeypatch.setenv("MODAONE_API_KEY", "test-modaone-key")
    clock = {"t": 0.0}
    r = registry(clock=lambda: clock["t"])
    for _ in range(60):
        r.complete_for("modaone-gpt-oss-120b", "mobile", "zone_answer", owner="u1")
    with pytest.raises(lp.ProfileError) as e:
        r.complete_for("modaone-gpt-oss-120b", "mobile", "zone_answer", owner="u1")
    assert e.value.status == 429
    assert r.complete_for("modaone-gpt-oss-120b", "mobile", "zone_answer", owner="u2")[1].id == "modaone-gpt-oss-120b"     # another account is unaffected
    clock["t"] = 3601
    assert r.complete_for("modaone-gpt-oss-120b", "mobile", "zone_answer", owner="u1")


# ---------------------------------------------------------------- the client an explicit profile uses

class Resp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "chosen model answer"}}]}


def test_an_explicit_profile_calls_its_own_endpoint_with_its_own_model_and_no_failover(monkeypatch):
    sent = []
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", lambda url, headers, json, timeout: sent.append((url, headers["Authorization"], json)) or Resp())
    monkeypatch.setenv("MODAONE_API_KEY", "test-modaone-key")
    r = lp.Registry.load(FILE, env={**ENV})
    monkeypatch.setenv("KM_LLM_BACKUP_PROVIDER", "modaone")       # a configured backup must not be used for an explicit choice
    complete, profile = r.complete_for("modaone-gpt-oss-120b", "mobile", "zone_answer", owner="u1")
    assert complete([{"role": "user", "content": "hi"}]) == "chosen model answer"
    url, auth, body = sent[0]
    assert url == "https://modaone-llm-api.dginfra.gov.tw/api/v1/chat/completions" and auth == "Bearer test-modaone-key"
    assert body["model"] == "gpt-oss-120b" and body["reasoning_effort"] == "low" and body["max_tokens"] >= 2048 and body["temperature"] == 0.1


def test_the_openai_profile_uses_the_primary_settings_only(monkeypatch):
    sent = []
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", lambda url, headers, json, timeout: sent.append((url, json["model"])) or Resp())
    monkeypatch.setenv("TEST_PRIMARY_KEY", "primary-test-key")
    complete, _ = lp.Registry.load(FILE, env={**ENV}).complete_for("openai", "cert", "zone_answer")
    complete([{"role": "user", "content": "hi"}])
    assert sent == [("http://gateway.test/v1/chat/completions", "gpt-test")]


def test_a_failing_explicit_model_raises_instead_of_switching_provider(monkeypatch):
    import requests

    def post(url, headers, json, timeout):
        raise requests.Timeout()
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", post)
    monkeypatch.setenv("MODAONE_API_KEY", "test-modaone-key")
    complete, _ = lp.Registry.load(FILE, env={**ENV}).complete_for("modaone-gpt-oss-120b", "mobile", "zone_answer")
    with pytest.raises(RuntimeError):
        complete([{"role": "user", "content": "hi"}])


def test_audit_log_names_zone_profile_and_user_but_never_the_question_or_key(monkeypatch, caplog):
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", lambda *a, **k: Resp())
    monkeypatch.setenv("MODAONE_API_KEY", "test-modaone-key")
    with caplog.at_level("INFO", logger="km.llm_profiles"):
        complete, _ = lp.Registry.load(FILE, env={**ENV}).complete_for("modaone-gpt-oss-120b", "cert", "zone_answer", owner="alice")
        complete([{"role": "user", "content": "SECRET QUESTION"}])
    assert "zone=cert" in caplog.text and "profile=modaone-gpt-oss-120b" in caplog.text and "user=alice" in caplog.text
    assert "SECRET" not in caplog.text and "test-modaone-key" not in caplog.text


# ---------------------------------------------------------------- HTTP: the profile list and the keeper

@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setattr(lp, "get_registry", lambda: registry())
    app = FastAPI()

    @app.middleware("http")
    async def ident(request, call_next):
        if request.headers.get("x-user") != "none":
            request.state.km_identity = {"sub": request.headers.get("x-user", "u1"), "instance_id": "da40"}
        return await call_next(request)
    app.include_router(llm_profile_routes.router)
    app.include_router(keeper_routes.router)
    return TestClient(app)


def test_profile_list_needs_a_login_and_a_known_zone(api):
    assert api.get("/api/llm/profiles", headers={"x-user": "none"}).status_code == 401
    assert api.get("/api/llm/profiles?zone=nowhere").status_code == 404
    assert api.get("/api/llm/profiles?zone=mobile&purpose=chat").status_code == 422


def test_profile_list_picks_the_purpose_from_the_zone(api):
    assert api.get("/api/llm/profiles").json()["purpose"] == "keeper"
    assert api.get("/api/llm/profiles?zone=mobile").json()["purpose"] == "zone_answer"
    assert api.get("/api/llm/profiles?zone=wifi").json()["purpose"] == "wifi_agent"
    csit = api.get("/api/llm/profiles?zone=csit").json()
    assert csit["zone"] == "verification" and {p["id"]: p["available"] for p in csit["profiles"]}["modaone-gpt-oss-120b"] is False


def test_keeper_uses_the_chosen_model_and_reports_it(api, monkeypatch):
    seen = {}
    monkeypatch.setattr(keeper_routes, "_zones", lambda: [])
    monkeypatch.setattr(keeper_routes.routing, "route", lambda question, complete, zones, stats, entity_zones=None: seen.update(complete=complete) or {"mode": "route", "zones": []})
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", lambda url, headers, json, timeout: seen.update(model=json["model"]) or Resp())
    monkeypatch.setenv("MODAONE_API_KEY", "test-modaone-key")
    r = api.post("/api/keeper/route", json={"question": "Wi-Fi 認證", "llm": "modaone-gpt-oss-120b"})
    assert r.status_code == 200 and r.json()["llm"] == {"profile": "modaone-gpt-oss-120b", "label": "gpt-oss-120b（政府算力平台）"}
    assert seen["complete"]([{"role": "user", "content": "x"}]) == "chosen model answer" and seen["model"] == "gpt-oss-120b"


def test_keeper_without_a_choice_keeps_its_own_default(api, monkeypatch):
    monkeypatch.setattr(keeper_routes, "_zones", lambda: [])
    monkeypatch.setattr(keeper_routes, "_llm_complete", lambda: "the-default-complete")
    seen = {}
    monkeypatch.setattr(keeper_routes.routing, "route", lambda question, complete, zones, stats, entity_zones=None: seen.update(complete=complete) or {"mode": "route"})
    r = api.post("/api/keeper/route", json={"question": "Wi-Fi 認證"})
    assert r.json()["llm"]["profile"] == "auto" and seen["complete"] == "the-default-complete"


def test_keeper_refuses_an_unknown_or_expired_model_with_a_clear_code(api, monkeypatch):
    monkeypatch.setattr(lp, "get_registry", lambda: registry(today=date(2026, 12, 9)))
    r = api.post("/api/keeper/route", json={"question": "x", "llm": "modaone-gpt-oss-120b"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "expired"
    assert api.post("/api/keeper/route", json={"question": "x", "llm": "nope"}).status_code == 422


def test_full_width_evidence_markers_are_turned_into_the_ascii_form_the_zone_answer_reads(monkeypatch):
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", lambda *a, **k: types_resp("審查約 4 週【S1】，需要報告［S2］。[S3]"))
    monkeypatch.setenv("MODAONE_API_KEY", "test-modaone-key")
    complete, _ = lp.Registry.load(FILE, env={**ENV}).complete_for("modaone-gpt-oss-120b", "cert", "zone_answer")
    assert complete([{"role": "user", "content": "x"}]) == "審查約 4 週[S1]，需要報告[S2]。[S3]"
    assert lp.normalise_citations("【S12】 和 【 S3 】 但不改 【附註】") == "[S12] 和 [S3] 但不改 【附註】"


def types_resp(text):
    r = Resp()
    r.json = lambda: {"choices": [{"message": {"content": text}}]}
    return r


# ---------------------------------------------------------------- a chosen model that fails is visible, and recovery clears it

def _failing_post(monkeypatch, fail):
    import requests

    def post(url, headers, json, timeout):
        if fail["on"]:
            raise requests.Timeout()
        return Resp()
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", post)


def test_a_profile_whose_last_call_failed_is_marked_degraded_until_it_works_again(monkeypatch):
    fail = {"on": True}
    clock = {"t": 0.0}
    monkeypatch.setenv("MODAONE_API_KEY", "test-modaone-key")
    _failing_post(monkeypatch, fail)
    r = lp.Registry.load(FILE, env={**ENV}, clock=lambda: clock["t"])
    flag = lambda: {p["id"]: p["degraded"] for p in r.listing("mobile", "zone_answer")["profiles"]}
    assert not any(flag().values())
    complete, _ = r.complete_for("modaone-gpt-oss-120b", "mobile", "zone_answer", owner="u1")
    with pytest.raises(RuntimeError):
        complete([{"role": "user", "content": "x"}])
    assert complete.state["failed"] is True and flag()["modaone-gpt-oss-120b"] is True and flag()["auto"] is False
    clock["t"] = 901
    assert flag()["modaone-gpt-oss-120b"] is False                      # an old failure is forgotten
    fail["on"] = False
    complete2, _ = r.complete_for("modaone-gpt-oss-120b", "mobile", "zone_answer", owner="u1")
    assert complete2([{"role": "user", "content": "x"}]) == "chosen model answer" and complete2.state["failed"] is False
    assert flag()["modaone-gpt-oss-120b"] is False


def test_keeper_says_when_the_chosen_model_did_not_answer(api, monkeypatch):
    import requests
    monkeypatch.setattr(keeper_routes, "_zones", lambda: [])

    def route(question, complete, zones, stats, entity_zones=None):
        try:
            complete([{"role": "user", "content": question}])
        except Exception:  # noqa: BLE001 - the real router answers by keywords when the model fails
            pass
        return {"mode": "keywords", "zones": []}
    monkeypatch.setattr(keeper_routes.routing, "route", route)
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", lambda *a, **k: (_ for _ in ()).throw(requests.Timeout()))
    monkeypatch.setenv("MODAONE_API_KEY", "test-modaone-key")
    out = api.post("/api/keeper/route", json={"question": "Wi-Fi 認證", "llm": "modaone-gpt-oss-120b"}).json()
    assert out["llm"]["profile"] == "modaone-gpt-oss-120b" and out["llm"]["failed"] is True
    monkeypatch.setattr("src.web_api.openai_compatible_client.requests.post", lambda *a, **k: Resp())
    assert "failed" not in api.post("/api/keeper/route", json={"question": "Wi-Fi 認證", "llm": "modaone-gpt-oss-120b"}).json()["llm"]
