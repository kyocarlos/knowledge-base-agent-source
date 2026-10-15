from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from km_credentials.crypto import (
    CredentialCryptoError,
    SourceSecret,
    load_private_keys_from_environment,
    load_public_key_from_environment,
    open_envelope,
    seal,
)


def _write_keys(tmp_path, key_id="k1"):
    private = X25519PrivateKey.generate()
    keys = tmp_path / "private"
    keys.mkdir(exist_ok=True)
    (keys / f"{key_id}.pem").write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public = tmp_path / f"{key_id}.pub.pem"
    public.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return private, keys, public


def test_round_trip_and_no_plaintext_in_envelope(tmp_path):
    private, _, _ = _write_keys(tmp_path)
    envelope = seal(private.public_key(), "k1", "user-a", "jira", SourceSecret("alice", "alice-pass", "basic"))
    assert "alice-pass" not in envelope and "alice" not in envelope
    assert open_envelope({"k1": private}, envelope, "user-a", "jira") == SourceSecret("alice", "alice-pass", "basic")


@pytest.mark.parametrize("user_id,source", [("user-b", "jira"), ("user-a", "confluence")])
def test_envelope_is_bound_to_user_and_source(tmp_path, user_id, source):
    private, _, _ = _write_keys(tmp_path)
    envelope = seal(private.public_key(), "k1", "user-a", "jira", SourceSecret("alice", "alice-pass", "basic"))
    with pytest.raises(CredentialCryptoError):
        open_envelope({"k1": private}, envelope, user_id, source)


def test_tampered_or_unknown_key_is_rejected(tmp_path):
    private, _, _ = _write_keys(tmp_path)
    envelope = seal(private.public_key(), "k1", "u", "jira", SourceSecret("alice", "x", "bearer"))
    with pytest.raises(CredentialCryptoError):
        open_envelope({"k2": private}, envelope.replace(".k1.", ".k2.", 1), "u", "jira")
    with pytest.raises(CredentialCryptoError):
        open_envelope({"k1": X25519PrivateKey.generate()}, envelope, "u", "jira")
    with pytest.raises(CredentialCryptoError):
        open_envelope({"k1": private}, envelope[:-4] + "AAAA", "u", "jira")


def test_environment_loading_and_rotation(tmp_path, monkeypatch):
    old, keys, _ = _write_keys(tmp_path, "k1")
    new, _, new_public = _write_keys(tmp_path, "k2")
    monkeypatch.setenv("KM_SOURCE_CREDENTIAL_KEY_ID", "k2")
    monkeypatch.setenv("KM_SOURCE_CREDENTIAL_PUBLIC_KEY_FILE", str(new_public))
    monkeypatch.setenv("KM_SOURCE_CREDENTIAL_PRIVATE_KEY_DIR", str(keys))
    key_id, public = load_public_key_from_environment()
    private_keys = load_private_keys_from_environment()
    assert key_id == "k2" and set(private_keys) == {"k1", "k2"}
    old_envelope = seal(old.public_key(), "k1", "u", "testrail", SourceSecret("a", "old", "basic"))
    new_envelope = seal(public, key_id, "u", "testrail", SourceSecret("a", "new", "basic"))
    assert open_envelope(private_keys, old_envelope, "u", "testrail").secret == "old"
    assert open_envelope(private_keys, new_envelope, "u", "testrail").secret == "new"


def test_missing_configuration_fails_closed(monkeypatch):
    for name in ("KM_SOURCE_CREDENTIAL_KEY_ID", "KM_SOURCE_CREDENTIAL_PUBLIC_KEY_FILE", "KM_SOURCE_CREDENTIAL_PRIVATE_KEY_DIR"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(CredentialCryptoError):
        load_public_key_from_environment()
    with pytest.raises(CredentialCryptoError):
        load_private_keys_from_environment()
