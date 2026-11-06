"""Which KM knowledge zone a CSIT document belongs to.

The eight zones are the entries of the KM left navigation. A CSIT document names its zone through the first classification level (L1); a Test Report
always belongs to 產品驗證專區 whatever its classification says. Where CSIT sends no usable L1 the source type decides for the sources that have one home
(verification-application attachments, vendor files, equipment attachments); everything else is kept as 待分類 so it is neither lost nor put in a wrong zone.

KM stores the result on every point it writes (zone_id, topic_zone, zone_basis); the zone pages filter on topic_zone.
"""
import re

ZONES = (("wifi", "WiFi 知識專區"), ("mobile", "行動通訊知識專區"), ("broadband", "固網寬頻知識專區"), ("cert", "認證知識專區"),
         ("verification", "產品驗證專區"), ("equipment", "設備儀器專區"), ("lab", "實驗室管理專區"), ("integrations", "Confluence / Jira / TestRail 查詢專區"))
ZONE_BY_ID = dict(ZONES)
UNCLASSIFIED = ("unclassified", "待分類")
# Names the same zones carried before the navigation was renamed; accepted so an older CSIT classification still lands in the right place.
ALIASES = {"4g/5g 知識專區": "mobile", "認證與法規知識專區": "cert", "設備預約知識專區": "equipment", "實驗室與測試環境知識專區": "lab"}
SOURCE_DEFAULT = {"TestReport": "verification", "VerificationApplicationAttachment": "verification", "VendorFile": "equipment", "EquipmentAttachment": "equipment"}


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


_BY_NAME = {_norm(name): zone_id for zone_id, name in ZONES}
_BY_NAME.update({_norm(k): v for k, v in ALIASES.items() if v})


def resolve_zone(source_type, l1_name):
    """-> (zone_id, topic_zone, basis). basis says why: source_type (Test Report), classification (L1 matched a zone), source_default, or none."""
    if source_type == "TestReport":
        return "verification", ZONE_BY_ID["verification"], "source_type"
    zone_id = _BY_NAME.get(_norm(l1_name)) if l1_name else None
    if zone_id:
        return zone_id, ZONE_BY_ID[zone_id], "classification"
    zone_id = SOURCE_DEFAULT.get(source_type)
    if zone_id:
        return zone_id, ZONE_BY_ID[zone_id], "source_default"
    return UNCLASSIFIED[0], UNCLASSIFIED[1], "none"


def zone_payload(source_type, classification_names):
    """The three payload fields for a point. classification_names: {"l1": name|None, ...} (names, not ids)."""
    zone_id, topic_zone, basis = resolve_zone(source_type, (classification_names or {}).get("l1"))
    return {"zone_id": zone_id, "topic_zone": topic_zone, "zone_basis": basis}
