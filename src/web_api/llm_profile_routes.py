"""GET /api/llm/profiles: the models an asker may choose for one assistant (the page uses it to fill its model menu)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from . import llm_profiles

router = APIRouter(prefix="/api/llm", tags=["LLM profiles"])
DEFAULT_PURPOSE = {"hub": "keeper", "wifi": "wifi_agent"}      # every other zone asks the zone assistant


@router.get("/profiles")
async def list_profiles(request: Request, zone: str = Query(default="hub", min_length=1, max_length=40), purpose: str | None = Query(default=None, max_length=20)):
    if not getattr(request.state, "km_identity", None):
        raise HTTPException(status_code=401, detail="KM login required")
    zone_id = llm_profiles.zone_key(zone)
    if zone_id not in llm_profiles.KNOWN_ZONES:
        raise HTTPException(status_code=404, detail="no such zone")
    purpose = purpose or DEFAULT_PURPOSE.get(zone_id, "zone_answer")
    if purpose not in llm_profiles.PURPOSES:
        raise HTTPException(status_code=422, detail="unknown purpose")
    return llm_profiles.get_registry().listing(zone_id, purpose)
