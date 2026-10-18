"""Secret-free security event accounting for audit/metrics backends."""

from __future__ import annotations

import logging
from collections import Counter

logger = logging.getLogger(__name__)


class AuthAudit:
    def __init__(self) -> None:
        self.metrics: Counter[str] = Counter()

    def record(self, event: str, *, issuer: str | None = None, subject: str | None = None) -> None:
        self.metrics[event] += 1
        # Subject is deliberately not emitted; the pair remains in the control DB only.
        logger.info("km_control_auth event=%s issuer_configured=%s", event, bool(issuer))
