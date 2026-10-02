"""Fail-closed OIDC helpers for the KM Control Auth service."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import jwt
import requests


class OIDCError(RuntimeError):
    pass


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise OIDCError(f"missing {name}")
    return value


def read_client_jwks() -> dict:
    """Read the public client JWKS without requiring an enabled IdP config.

    Shared Identity may need this document while registering the client.  It
    contains public key material only, but still fails closed if the protected
    deployment has not explicitly supplied the JWKS path.
    """
    path = os.getenv("KM_OIDC_CLIENT_JWKS_PATH", "").strip()
    if not path:
        raise OIDCError("missing KM_OIDC_CLIENT_JWKS_PATH")
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OIDCError("OIDC client JWKS is unavailable") from exc
    if not isinstance(value, dict) or not isinstance(value.get("keys"), list):
        raise OIDCError("OIDC client JWKS is invalid")
    return value


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    client_id: str
    redirect_uri: str
    post_logout_redirect_uri: str
    client_auth_method: str
    private_key_path: str
    private_key_kid: str
    scopes: tuple[str, ...]
    id_token_algorithms: tuple[str, ...]
    claim_mapping: dict[str, str]
    end_session_endpoint: str | None

    @classmethod
    def from_environment(cls) -> "OIDCSettings":
        if os.getenv("KM_OIDC_ENABLED", "false").lower() != "true":
            raise OIDCError("OIDC is disabled")
        client_auth_method = os.getenv("KM_OIDC_CLIENT_AUTH_METHOD", "client_secret_basic").strip()
        if client_auth_method not in {"private_key_jwt", "client_secret_basic"}:
            raise OIDCError("unsupported KM_OIDC_CLIENT_AUTH_METHOD")
        try:
            mapping = json.loads(os.getenv("KM_OIDC_CLAIM_MAPPING_JSON") or '{"account":"account","name":"name","email":"email","department":"department"}')
        except json.JSONDecodeError as exc:
            raise OIDCError("invalid KM_OIDC_CLAIM_MAPPING_JSON") from exc
        if not isinstance(mapping, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in mapping.items()):
            raise OIDCError("claim mapping must be a string map")
        allowed_fields = {"account", "name", "email", "email_verified", "department", "team"}
        if not set(mapping).issubset(allowed_fields):
            raise OIDCError("claim mapping contains unsupported profile fields")
        for forbidden in ("department", "team"):
            if forbidden not in mapping:
                mapping[forbidden] = ""
        return cls(
            issuer=_required("KM_OIDC_ISSUER").rstrip("/"),
            authorization_endpoint=_required("KM_OIDC_AUTHORIZATION_ENDPOINT"),
            token_endpoint=_required("KM_OIDC_TOKEN_ENDPOINT"),
            jwks_uri=_required("KM_OIDC_JWKS_URI"),
            client_id=_required("KM_OIDC_CLIENT_ID"),
            redirect_uri=_required("KM_OIDC_REDIRECT_URI"),
            post_logout_redirect_uri=_required("KM_OIDC_POST_LOGOUT_REDIRECT_URI"),
            client_auth_method=client_auth_method,
            private_key_path=os.getenv("KM_OIDC_PRIVATE_KEY_PATH", "").strip(),
            private_key_kid=os.getenv("KM_OIDC_PRIVATE_KEY_KID", "").strip(),
            scopes=tuple(os.getenv("KM_OIDC_SCOPES", "openid profile email").split()),
            id_token_algorithms=tuple(os.getenv("KM_OIDC_ID_TOKEN_ALGORITHMS", "RS256").split()),
            claim_mapping=mapping,
            end_session_endpoint=os.getenv("KM_OIDC_END_SESSION_ENDPOINT", "").strip() or None,
        )

    def authorization_url(self, state: str, nonce: str, verifier: str) -> str:
        challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
        query = urlencode({"response_type": "code", "client_id": self.client_id, "redirect_uri": self.redirect_uri, "scope": " ".join(self.scopes), "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"})
        return f"{self.authorization_endpoint}?{query}"

    def _private_key(self) -> str:
        if self.client_auth_method != "private_key_jwt":
            return ""
        if not self.private_key_path or not self.private_key_kid:
            raise OIDCError("private_key_jwt requires KM_OIDC_PRIVATE_KEY_PATH and KM_OIDC_PRIVATE_KEY_KID")
        try:
            return Path(self.private_key_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise OIDCError("OIDC private key is unavailable") from exc

    def exchange_code(self, code: str, verifier: str) -> dict:
        payload = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri, "client_id": self.client_id, "code_verifier": verifier}
        auth = None
        if self.client_auth_method == "private_key_jwt":
            now = int(time.time())
            assertion = jwt.encode({"iss": self.client_id, "sub": self.client_id, "aud": self.token_endpoint, "iat": now, "exp": now + 60, "jti": _b64(secrets.token_bytes(18))}, self._private_key(), algorithm="RS256", headers={"kid": self.private_key_kid, "typ": "JWT"})
            payload.update({"client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", "client_assertion": assertion})
        else:
            secret = _required("KM_OIDC_CLIENT_SECRET")
            auth = (self.client_id, secret)
        response = requests.post(self.token_endpoint, data=payload, auth=auth, timeout=10)
        if response.status_code != 200:
            raise OIDCError("OIDC token exchange failed")
        try:
            tokens = response.json()
        except ValueError as exc:
            raise OIDCError("OIDC token response is invalid") from exc
        if not isinstance(tokens.get("id_token"), str):
            raise OIDCError("OIDC token response has no id_token")
        return tokens

    def validate_id_token(self, id_token: str, expected_nonce: str) -> dict:
        try:
            client = jwt.PyJWKClient(self.jwks_uri, cache_jwk_set=True, lifespan=300)
            signing_key = client.get_signing_key_from_jwt(id_token)
            claims = jwt.decode(id_token, signing_key.key, algorithms=list(self.id_token_algorithms), audience=self.client_id, issuer=self.issuer, options={"require": ["exp", "iat", "iss", "sub", "aud"]})
        except Exception as exc:
            raise OIDCError("OIDC ID token validation failed") from exc
        if claims.get("nonce") != expected_nonce:
            raise OIDCError("OIDC nonce mismatch")
        return claims

    def profile(self, claims: dict) -> dict:
        return {field: claims.get(claim) if claim else None for field, claim in self.claim_mapping.items()}

    def public_jwks(self) -> dict:
        return read_client_jwks()
