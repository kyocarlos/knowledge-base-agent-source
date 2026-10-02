#!/usr/bin/env python3
"""Create a KM private_key_jwt RS256 key pair and public JWKS file.

The output directory must be protected before this script is run. The private
key is never printed and is written with mode 0600.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--kid", default="")
    args = parser.parse_args()
    target = Path(args.output_dir)
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    numbers = private.public_key().public_numbers()
    kid = args.kid or f"km-oidc-{secrets.token_hex(8)}"
    private_path = target / "private-key.pem"
    jwks_path = target / "jwks.json"
    private_path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    os.chmod(private_path, 0o600)
    jwks_path.write_text(json.dumps({"keys": [{"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256", "n": b64(numbers.n.to_bytes((numbers.n.bit_length()+7)//8, "big")), "e": b64(numbers.e.to_bytes((numbers.e.bit_length()+7)//8, "big"))}]}, separators=(",", ":")), encoding="utf-8")
    os.chmod(jwks_path, 0o644)
    print(f"kid={kid}")
    print(f"public_jwks={jwks_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
