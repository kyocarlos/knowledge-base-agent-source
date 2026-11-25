"""Who is asking, as document permissions see them (KM zone pages). Nothing here reads the request body: the viewer comes from the signed-in session.

KM_ZONE_ACL_ENFORCE       off (default) = zone pages behave exactly as before document permissions existed.
KM_ZONE_ACL_ADMIN_SEES_ALL  off (default) = even a KM admin only sees what the permission lists allow (least privilege).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from ..csit_integration_v1.access_control import principal_key


def _on(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def enforce_enabled() -> bool:
    return _on("KM_ZONE_ACL_ENFORCE")


@dataclass(frozen=True)
class Viewer:
    principals: frozenset[str]
    is_admin: bool = False

    def cache_key(self) -> tuple:
        return ("*admin*",) if self.is_admin else tuple(sorted(self.principals))


# lookup(user_id) -> iterable of principal keys that user holds (the bound external identity, its groups ...). Stage B plugs the KM Control lookup in here.
Lookup = Callable[[str], Iterable[str]]


_default_lookup: Optional[Lookup] = None


def set_default_lookup(lookup: Optional[Lookup]) -> None:
    """The resolver the zone routes use (stage B: the bound external identity and groups from KM Control; tests: a fixture)."""
    global _default_lookup
    _default_lookup = lookup


def control_lookup(user_id: str) -> Iterable[str]:
    """The signed-in KM account's units, read from KM Control on every call (the unit list is CSIT's, membership is set by a KM admin)."""
    from ..km_control import ControlRegistry
    return ControlRegistry.from_environment().unit_keys_for(user_id)


def control_zone_lookup(user_id: str) -> Iterable[str]:
    """The zones the signed-in KM account may enter, read from KM Control on every call."""
    from ..km_control import ControlRegistry
    return ControlRegistry.from_environment().zones_for(user_id)


def zones_for(identity: dict[str, Any], lookup: Optional[Lookup] = None) -> Optional[frozenset[str]]:
    """The zone ids the account may enter. None while enforcement is off (every zone, as before). With enforcement on: an account whose zones cannot be
    resolved holds none (fail closed), and a KM admin sees all zones only when KM_ZONE_ACL_ADMIN_SEES_ALL is on."""
    if not enforce_enabled():
        return None
    from ..csit_integration_v1.zones import ZONES
    if _on("KM_ZONE_ACL_ADMIN_SEES_ALL") and identity.get("role") == "admin":
        return frozenset(z for z, _ in ZONES)
    try:
        return frozenset(str(z) for z in (lookup or control_zone_lookup)(str(identity.get("sub"))))
    except Exception:  # noqa: BLE001 - a failed lookup must narrow access, never widen it
        return frozenset()


def viewer_for(identity: dict[str, Any], lookup: Optional[Lookup] = None) -> Optional[Viewer]:
    """None while enforcement is off. With enforcement on a viewer is always returned: an account whose permissions cannot be resolved holds none (sees Public only)."""
    if not enforce_enabled():
        return None
    keys: set[str] = set()
    lookup = lookup or _default_lookup
    try:
        if lookup is not None:
            keys.update(lookup(str(identity.get("sub"))))
    except Exception:  # noqa: BLE001 - a failed lookup must narrow access, never widen it
        keys = set()
    for g in identity.get("groups") or ():         # only when the signed session itself carries groups
        keys.add(principal_key("group", identity.get("issuer"), g))
    admin = _on("KM_ZONE_ACL_ADMIN_SEES_ALL") and identity.get("role") == "admin"
    return Viewer(frozenset(keys), is_admin=admin)


def condition(viewer: Optional[Viewer]):
    """The Qdrant condition a passage must meet to be readable by this viewer; None = no restriction (enforcement off, or an admin who sees all)."""
    if viewer is None or viewer.is_admin:
        return None
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
    should = [FieldCondition(key="acl_mode", match=MatchValue(value="Public"))]
    if viewer.principals:
        should.append(FieldCondition(key="allowed_principals", match=MatchAny(any=sorted(viewer.principals))))
    return Filter(should=should)


def visible(viewer: Optional[Viewer], payload: dict[str, Any]) -> bool:
    """The same rule as condition(), for a payload already in hand."""
    if viewer is None or viewer.is_admin:
        return True
    if payload.get("acl_mode") == "Public":
        return True
    return payload.get("acl_mode") == "Restricted" and bool(viewer.principals & set(payload.get("allowed_principals") or ()))
