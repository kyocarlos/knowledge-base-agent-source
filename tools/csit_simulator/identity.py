"""The identity side of the simulated CSIT, for running the simulator against a real KM deployment.

A real KM only accepts bearer tokens signed by the identity authority it is configured to trust, and it fetches that authority's public keys (JWKS)
and asks it for its own outbound token (client credentials). This module plays that authority:

  GET  /.well-known/jwks   the public key
  POST /oauth/token        client_credentials with HTTP Basic (KM's client id + secret) -> a signed service token for the simulator's own routes

  mint_for_km()            the token the simulator sends to KM (principal_type=service, client in KM's allowed list, scope km.ingestion.submit)
  verify_from_km(...)      checks the token KM sends back (signature, issuer, audience, client, scope)

The claim names and scopes mirror what KM validates today (src/csit_integration_v1/auth.py), written independently here. DEV only: the key lives in
the data directory and the client secret comes from a file.
"""
from __future__ import annotations

import base64
import hmac
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs

SUBMIT_SCOPE = "km.ingestion.submit"
OUTBOUND_SCOPES = ("csit.document.read", "csit.ingestion.status.write")
# Spec v1.4 section 3.2 suggests these instead; the simulator issues whichever set KM asks for, from the union.
OUTBOUND_SCOPES_V14 = ("csit.documents.read", "csit.km.status.write", "csit.km.deletion-status.write")
INBOUND_SCOPES_V14 = {"jobs": "km.ingestion.write", "changes": "km.metadata.write", "deletions": "km.deletion.write"}


def _b64u(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Identity:
    def __init__(self, issuer: str, km_audience: str, outbound_audience: str, km_client_id: str, km_client_secret: str,
                 service_client_id: str, data_dir: str | Path | None = None, ttl: int = 600):
        import jwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        self.jwt = jwt
        self.issuer, self.km_audience, self.outbound_audience = issuer, km_audience, outbound_audience
        self.km_client_id, self._secret, self.service_client_id, self.ttl = km_client_id, km_client_secret, service_client_id, ttl
        path = (Path(data_dir) / "identity-key.pem") if data_dir else None
        if path and path.is_file():
            self._key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        else:
            self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self._key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
        nums = self._key.public_key().public_numbers()
        self.kid = "sim-" + _b64u(nums.n)[:16]
        self._jwk = {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": self.kid, "n": _b64u(nums.n), "e": _b64u(nums.e)}
        self.issued: list[dict] = []   # what the simulator handed out, for the traffic view

    def jwks(self) -> dict:
        return {"keys": [self._jwk]}

    def _sign(self, claims: dict) -> str:
        now = int(time.time())
        body = {"iss": self.issuer, "iat": now, "nbf": now - 5, "exp": now + self.ttl, "jti": uuid.uuid4().hex, **claims}
        return self.jwt.encode(body, self._key, algorithm="RS256", headers={"kid": self.kid})

    def mint_for_km(self, scope: str | None = None) -> str:
        """CSIT -> KM calls. scope defaults to the v1.3 scope; v1.4 passes the endpoint-specific one."""
        return self._sign({"aud": self.km_audience, "sub": self.service_client_id, "client_id": self.service_client_id,
                           "principal_type": "service", "scope": scope or SUBMIT_SCOPE})

    def token_endpoint(self, authorization: str, body: bytes) -> tuple[int, dict]:
        """RFC 6749 client_credentials with HTTP Basic, as KM's provider calls it. Never echoes the secret."""
        def err(status, code):
            return status, {"error": code}
        form = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}
        if form.get("grant_type") != "client_credentials":
            return err(400, "unsupported_grant_type")
        try:
            scheme, _, raw = (authorization or "").partition(" ")
            if scheme.lower() != "basic":
                raise ValueError
            client, _, secret = base64.b64decode(raw).decode().partition(":")
        except Exception:  # noqa: BLE001
            return err(401, "invalid_client")
        if client != self.km_client_id or not hmac.compare_digest(secret.encode(), self._secret.encode()):
            return err(401, "invalid_client")
        wanted = set(form.get("scope", "").split()) or set(OUTBOUND_SCOPES)
        allowed = OUTBOUND_SCOPES + OUTBOUND_SCOPES_V14
        if not wanted <= set(allowed):
            return err(400, "invalid_scope")
        scope = " ".join(s for s in allowed if s in wanted)
        token = self._sign({"aud": self.outbound_audience, "sub": client, "client_id": client, "principal_type": "service", "scope": scope})
        self.issued.append({"t": time.time(), "client": client, "scope": scope})
        del self.issued[:-100]
        return 200, {"access_token": token, "token_type": "Bearer", "expires_in": self.ttl, "scope": scope}

    def verify_from_km(self, header: str, scope=None) -> bool:
        """scope: one scope name, or a tuple of names where any one is enough (v1.3 and v1.4 spell them differently)."""
        if not header.startswith("Bearer "):
            return False
        try:
            claims = self.jwt.decode(header[7:], self._key.public_key(), algorithms=["RS256"], issuer=self.issuer, audience=self.outbound_audience,
                                     options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        except Exception:  # noqa: BLE001
            return False
        if claims.get("client_id") != self.km_client_id or claims.get("principal_type") != "service":
            return False
        have = str(claims.get("scope", "")).split()
        return scope is None or any(x in have for x in ((scope,) if isinstance(scope, str) else scope))
