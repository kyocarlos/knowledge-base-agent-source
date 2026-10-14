"""Fail-closed OIDC authorization-code flow primitives for KM Control Auth."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import OIDCSettings

logger = logging.getLogger(__name__)


class OIDCError(ValueError):
    """A safe, user-facing authentication failure."""


@dataclass(frozen=True, slots=True)
class PendingAuthorization:
    state: str
    nonce: str
    verifier: str
    expires_at: float


class AuthorizationStore:
    """Single-use, in-memory store; production replicas must replace this with shared storage."""
    def __init__(self) -> None:
        self._entries: dict[str, PendingAuthorization] = {}

    def create(self, ttl_seconds: int) -> PendingAuthorization:
        entry = PendingAuthorization(secrets.token_urlsafe(32), secrets.token_urlsafe(32),
                                     secrets.token_urlsafe(64), time.time() + ttl_seconds)
        self._entries[entry.state] = entry
        return entry

    def consume(self, state: str) -> PendingAuthorization:
        entry = self._entries.pop(state, None)
        if entry is None or entry.expires_at < time.time():
            raise OIDCError("OIDC state is invalid or expired")
        return entry


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


class OIDCClient:
    def __init__(self, settings: OIDCSettings, store: AuthorizationStore | None = None) -> None:
        self.settings, self.store = settings, store or AuthorizationStore()

    def authorization_redirect(self) -> str:
        if not self.settings.enabled:
            raise OIDCError("OIDC is not enabled")
        pending = self.store.create(self.settings.session_ttl_seconds)
        params = {
            "client_id": self.settings.client_id, "response_type": "code",
            "redirect_uri": self.settings.redirect_uri, "scope": " ".join(self.settings.scopes),
            "state": pending.state, "nonce": pending.nonce, "code_challenge": pkce_challenge(pending.verifier),
            "code_challenge_method": "S256",
        }
        return f"{self.settings.issuer}/authorize?{urlencode(params)}"

    def exchange_and_validate(self, *, code: str, state: str) -> dict[str, Any]:
        if not code:
            raise OIDCError("authorization code is missing")
        pending = self.store.consume(state)
        discovery = self._get_json(f"{self.settings.issuer}/.well-known/openid-configuration")
        endpoint = discovery.get("token_endpoint")
        jwks_uri = discovery.get("jwks_uri")
        if not isinstance(endpoint, str) or not isinstance(jwks_uri, str):
            raise OIDCError("provider discovery is incomplete")
        try:
            response = httpx.post(endpoint, data={"grant_type": "authorization_code", "code": code,
                "redirect_uri": self.settings.redirect_uri, "code_verifier": pending.verifier},
                auth=(self.settings.client_id or "", self.settings.client_secret or ""), timeout=10)
            response.raise_for_status()
            id_token = response.json().get("id_token")
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("oidc_token_exchange_failed error=%s", type(exc).__name__)
            raise OIDCError("authorization-code exchange failed") from exc
        if not isinstance(id_token, str):
            raise OIDCError("token response did not include an ID token")
        return self.validate_id_token(id_token, jwks_uri, pending.nonce)

    def validate_id_token(self, token: str, jwks_uri: str, expected_nonce: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}:
                raise OIDCError("unsupported ID token algorithm")
            key = PyJWKClient(jwks_uri).get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=[header["alg"]], audience=self.settings.client_id,
                issuer=self.settings.issuer, leeway=self.settings.clock_skew_seconds,
                options={"require": ["exp", "iss", "sub", "aud", "nonce"]})
        except OIDCError:
            raise
        except Exception as exc:
            logger.warning("oidc_token_validation_failed error=%s", type(exc).__name__)
            raise OIDCError("ID token validation failed") from exc
        if not secrets.compare_digest(str(claims.get("nonce", "")), expected_nonce):
            raise OIDCError("ID token nonce mismatch")
        return claims

    @staticmethod
    def _get_json(url: str) -> dict[str, Any]:
        try:
            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError("provider discovery failed") from exc
        if not isinstance(payload, dict):
            raise OIDCError("provider discovery is invalid")
        return payload


def map_claims(claims: dict[str, Any], mapping: tuple[tuple[str, str], ...]) -> dict[str, str]:
    """Only configured scalar claims become KM identity attributes."""
    resolved: dict[str, str] = {}
    for target, source in mapping:
        value = claims.get(source)
        if isinstance(value, (str, int, float, bool)):
            resolved[target] = str(value)
    if not resolved.get("user_id"):
        raise OIDCError("configured claim mapping did not resolve user_id")
    return resolved
