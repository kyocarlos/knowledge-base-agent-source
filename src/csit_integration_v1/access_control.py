"""Document-level read permission, as CSIT sends it (accessControl) and as KM stores it on every point of the document.

CSIT owns the permission; KM keeps a copy next to the passages and enforces it when somebody asks. The copy is made by KM's code from the document's
permission, nobody reviews passages. A point carries:
  acl_mode            "Public" | "Restricted"
  acl_version         CSIT's version of the permission (only ever goes up)
  allowed_principals  normalised principal keys (see principal_key); empty for Public
A point without acl_mode is unlabeled and, while enforcement is on, readable by nobody (fail closed).
"""
from typing import Any, Optional


def normalize_unit(code: Any) -> str:
    """One spelling of a unit code: CSIT's list, the document permissions and KM's user-unit table all compare through this."""
    return str(code if code is not None else "").strip().casefold()


def principal_key(kind: str, issuer: Optional[str], ident: str) -> str:
    """One spelling for 'this user/group/unit'. Users and groups: the identity provider's immutable id (OIDC sub, AD objectGUID) at that provider.
    A unit is named by CSIT's unit code alone (no provider): the code list is CSIT's, and KM imports it."""
    kind = str(kind).strip().lower()
    if kind == "unit":
        return f"unit:|{normalize_unit(ident)}"
    return f"{kind}:{(issuer or '').strip().rstrip('/').lower()}|{str(ident).strip().lower()}"


def acl_payload(request_payload: Optional[dict]) -> dict[str, Any]:
    """The index payload for a request (or a metadata change) that carries accessControl; {} when it does not (the stored permission is left alone)."""
    ac = (request_payload or {}).get("accessControl")
    if not ac:
        return {}
    restricted = ac.get("mode") == "Restricted"
    keys = sorted({principal_key(p.get("type"), p.get("issuer"), p.get("id")) for p in (ac.get("allowedPrincipals") or [])}) if restricted else []
    return {"acl_mode": "Restricted" if restricted else "Public", "acl_version": int(ac.get("version") or 1), "allowed_principals": keys}
