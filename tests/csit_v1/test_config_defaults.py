from src.csit_integration_v1.config import Settings

def test_shared_identity_service_principal_defaults_without_environment(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("KM_CSIT_"):
            monkeypatch.delenv(key, raising=False)
    settings=Settings.from_env()
    assert settings.service_claim == "principal_type"
    assert settings.service_claim_value == "service"
