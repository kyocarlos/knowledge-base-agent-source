"""Sealed envelope for per-user external source credentials.

Control Auth holds only the recipient public key, so it can store a credential
but never read it back.  Only the CrossSearch worker holds the private keys.
Each envelope is bound to (key_id, user_id, source) through AEAD associated
data, so a ciphertext copied to another user or source fails to decrypt.
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SCHEME = "km-src-cred-v1"
SOURCES = frozenset({"confluence", "jira", "testrail"})
AUTH_TYPES = frozenset({"basic", "bearer"})
_KEY_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class CredentialCryptoError(RuntimeError):
    """Raised without secret material; callers map it to a fixed error code."""


@dataclass(frozen=True)
class SourceSecret:
    username: str
    secret: str
    auth_type: str


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _raw(public_key: X25519PublicKey) -> bytes:
    return public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _aad(key_id: str, user_id: str, source: str) -> bytes:
    return "|".join((SCHEME, key_id, user_id, source)).encode("utf-8")


def _derive(shared: bytes, ephemeral: bytes, recipient: bytes, aad: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=ephemeral + recipient, info=aad).derive(shared)


def validate_key_id(key_id: str) -> str:
    if not _KEY_ID.fullmatch(key_id or ""):
        raise CredentialCryptoError("invalid credential key id")
    return key_id


def validate_source(source: str) -> str:
    if source not in SOURCES:
        raise CredentialCryptoError("unknown source")
    return source


def seal(public_key: X25519PublicKey, key_id: str, user_id: str, source: str, value: SourceSecret) -> str:
    validate_key_id(key_id)
    validate_source(source)
    if value.auth_type not in AUTH_TYPES:
        raise CredentialCryptoError("invalid auth type")
    ephemeral = X25519PrivateKey.generate()
    ephemeral_raw = _raw(ephemeral.public_key())
    aad = _aad(key_id, user_id, source)
    key = _derive(ephemeral.exchange(public_key), ephemeral_raw, _raw(public_key), aad)
    nonce = os.urandom(12)
    plaintext = json.dumps({"u": value.username, "s": value.secret, "t": value.auth_type}, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return ".".join((SCHEME, key_id, _b64(ephemeral_raw), _b64(nonce), _b64(ciphertext)))


def envelope_key_id(envelope: str) -> str:
    parts = (envelope or "").split(".")
    if len(parts) != 5 or parts[0] != SCHEME:
        raise CredentialCryptoError("unsupported credential envelope")
    return validate_key_id(parts[1])


def open_envelope(private_keys: dict[str, X25519PrivateKey], envelope: str, user_id: str, source: str) -> SourceSecret:
    key_id = envelope_key_id(envelope)
    private_key = private_keys.get(key_id)
    if private_key is None:
        raise CredentialCryptoError("credential key unavailable")
    _, _, ephemeral_b64, nonce_b64, ciphertext_b64 = envelope.split(".")
    try:
        ephemeral_raw = _unb64(ephemeral_b64)
        aad = _aad(key_id, user_id, source)
        key = _derive(private_key.exchange(X25519PublicKey.from_public_bytes(ephemeral_raw)), ephemeral_raw, _raw(private_key.public_key()), aad)
        payload = json.loads(AESGCM(key).decrypt(_unb64(nonce_b64), _unb64(ciphertext_b64), aad))
        value = SourceSecret(username=str(payload["u"]), secret=str(payload["s"]), auth_type=str(payload["t"]))
    except (InvalidTag, ValueError, KeyError, TypeError) as exc:
        raise CredentialCryptoError("credential envelope rejected") from exc
    if value.auth_type not in AUTH_TYPES:
        raise CredentialCryptoError("credential envelope rejected")
    return value


def load_public_key_from_environment() -> tuple[str, X25519PublicKey]:
    """Return (key_id, public key) or raise when sealing is not configured."""
    key_id = validate_key_id(os.getenv("KM_SOURCE_CREDENTIAL_KEY_ID", "").strip())
    path = os.getenv("KM_SOURCE_CREDENTIAL_PUBLIC_KEY_FILE", "").strip()
    if not path:
        raise CredentialCryptoError("credential public key is not configured")
    try:
        key = serialization.load_pem_public_key(Path(path).read_bytes())
    except (OSError, ValueError) as exc:
        raise CredentialCryptoError("credential public key is unreadable") from exc
    if not isinstance(key, X25519PublicKey):
        raise CredentialCryptoError("credential public key must be X25519")
    return key_id, key


def load_private_keys_from_environment() -> dict[str, X25519PrivateKey]:
    """Load every `<key_id>.pem` in the protected directory; supports rotation."""
    directory = os.getenv("KM_SOURCE_CREDENTIAL_PRIVATE_KEY_DIR", "").strip()
    if not directory:
        raise CredentialCryptoError("credential private keys are not configured")
    keys: dict[str, X25519PrivateKey] = {}
    try:
        entries = sorted(Path(directory).glob("*.pem"))
    except OSError as exc:
        raise CredentialCryptoError("credential private keys are unreadable") from exc
    for entry in entries:
        key_id = entry.stem
        if not _KEY_ID.fullmatch(key_id):
            continue
        try:
            key = serialization.load_pem_private_key(entry.read_bytes(), password=None)
        except (OSError, ValueError) as exc:
            raise CredentialCryptoError("credential private key is unreadable") from exc
        if isinstance(key, X25519PrivateKey):
            keys[key_id] = key
    if not keys:
        raise CredentialCryptoError("credential private keys are not configured")
    return keys
