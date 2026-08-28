from __future__ import annotations

import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from websocket_crypto_preflight import (  # noqa: E402
    CryptoPreflightError,
    crypto_preflight,
    serialize_connect_payload,
    sign_payload,
    verify_payload,
)


def private_pem(key) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")


class WebSocketCryptoPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = serialize_connect_payload(
            device_id="device", scopes=["operator.read"], timestamp=123,
            token="token", nonce="nonce",
        )

    def test_ed25519_valid_signature_and_negative_matrix(self) -> None:
        key = ed25519.Ed25519PrivateKey.generate()
        result = crypto_preflight(private_pem(key), self.payload)
        self.assertEqual(result["key_type"], "Ed25519")
        self.assertTrue(verify_payload(key.public_key(), "Ed25519", self.payload, result["signature"]))
        self.assertFalse(verify_payload(key.public_key(), "Ed25519", self.payload + b"altered", result["signature"]))
        wrong_key = ed25519.Ed25519PrivateKey.generate().public_key()
        self.assertFalse(verify_payload(wrong_key, "Ed25519", self.payload, result["signature"]))

    def test_rsa_uses_explicit_rsa_path(self) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_type, signature = sign_payload(key, self.payload)
        self.assertEqual(key_type, "RSA")
        self.assertTrue(verify_payload(key.public_key(), key_type, self.payload, signature))

    def test_empty_and_unsupported_key_fail_before_network(self) -> None:
        with self.assertRaisesRegex(CryptoPreflightError, "empty"):
            crypto_preflight("", self.payload)
        unsupported = ec.generate_private_key(ec.SECP256R1())
        with self.assertRaisesRegex(CryptoPreflightError, "unsupported"):
            crypto_preflight(private_pem(unsupported), self.payload)

    def test_payload_serialization_is_deterministic(self) -> None:
        again = serialize_connect_payload(
            device_id="device", scopes=["operator.read"], timestamp=123,
            token="token", nonce="nonce",
        )
        self.assertEqual(self.payload, again)


if __name__ == "__main__":
    unittest.main()
