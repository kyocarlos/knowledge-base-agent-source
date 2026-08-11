"""Security contract placeholder; WP0 does not invent an identity provider."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SecurityContext:
    subject: str | None = None
    authenticated: bool = False


ANONYMOUS_CONTEXT = SecurityContext()
