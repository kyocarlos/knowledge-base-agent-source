#!/usr/bin/env python3
"""Fail-closed cryptographic preflight for OpenClaw WebSocket runners."""

from __future__ import annotations

import hashlib
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa


class CryptoPreflightError(ValueError):
    """Raised before network activity when runner crypto is unusable."""


def serialize_connect_payload(
    *, device_id: str, scopes: list[str], timestamp: int, token: str,
    nonce: str, platform: str = "linux",
) -> bytes:
    values = [
        "v3", device_id, "cli", "cli", "operator", ",".join(scopes),
        str(timestamp), token, nonce, platform, "",
    ]
    if not device_id or not token or not nonce:
        raise CryptoPreflightError("connect payload requires device_id, token, and nonce")
    return "|".join(values).encode("utf-8")


def load_private_key(private_key_pem: str):
    if not str(private_key_pem or "").strip():
        raise CryptoPreflightError("private key is empty")
    try:
        key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    except (TypeError, ValueError) as exc:
        raise CryptoPreflightError("private key is invalid") from exc
    if not isinstance(key, (ed25519.Ed25519PrivateKey, rsa.RSAPrivateKey)):
        raise CryptoPreflightError(f"unsupported private key type: {type(key).__name__}")
    return key


def sign_payload(private_key, payload: bytes) -> tuple[str, bytes]:
    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        return "Ed25519", private_key.sign(payload)
    if isinstance(private_key, rsa.RSAPrivateKey):
        return "RSA", private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
    raise CryptoPreflightError(f"unsupported private key type: {type(private_key).__name__}")


def verify_payload(public_key, key_type: str, payload: bytes, signature: bytes) -> bool:
    try:
        if key_type == "Ed25519" and isinstance(public_key, ed25519.Ed25519PublicKey):
            public_key.verify(signature, payload)
            return True
        if key_type == "RSA" and isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())
            return True
    except InvalidSignature:
        return False
    return False


def crypto_preflight(private_key_pem: str, payload: bytes) -> dict[str, object]:
    key = load_private_key(private_key_pem)
    key_type, signature = sign_payload(key, payload)
    if not verify_payload(key.public_key(), key_type, payload, signature):
        raise CryptoPreflightError("local signature verification failed")
    return {
        "key_type": key_type,
        "local_sign": "PASS",
        "local_verify": "PASS",
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "signature": signature,
    }


def implementation_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
