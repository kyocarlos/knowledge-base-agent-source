"""Which KM knowledge zone a CSIT document belongs to.

The eight zones are the entries of the KM left navigation. CSIT does not classify documents, so KM decides from the content with the same LLM call that
produces documentType / summary / keywords. The rules, in order:
  1. a Test Report is always 產品驗證專區 (CSIT's Test Report source, or a document the LLM recognises as a test report), whatever its technology;
  2. any other document goes to the zone the LLM named for its content;
  3. when the LLM gave nothing usable (unavailable, or unsure): CSIT's first classification level if it happens to be a zone name;
  4. then the home zone of the attachment sources (verification-application attachment, vendor file, equipment attachment);
  5. otherwise 待分類 — kept, not guessed.
KM stores the result on every point it writes (zone_id, topic_zone, zone_basis); the zone pages filter on topic_zone.
"""
import re

ZONES = (("wifi", "WiFi 知識專區"), ("mobile", "行動通訊知識專區"), ("broadband", "固網寬頻知識專區"), ("cert", "認證知識專區"),
         ("verification", "產品驗證專區"), ("equipment", "設備儀器專區"), ("lab", "實驗室管理專區"), ("integrations", "Confluence / Jira / TestRail 查詢專區"))
ZONE_BY_ID = dict(ZONES)
# The zone page keys of the front end differ for one zone: the page "csit" is 產品驗證專區.
PAGE_KEY = {"verification": "csit"}
UNCLASSIFIED = ("unclassified", "待分類")
# Names the same zones carried before the navigation was renamed (also what the legacy importer wrote); accepted when reading and as a fallback.
ALIASES = {"4g/5g 知識專區": "mobile", "認證與法規知識專區": "cert", "設備預約知識專區": "equipment", "實驗室與測試環境知識專區": "lab", "csit雜項專區": "verification"}
SOURCE_DEFAULT = {"TestReport": "verification", "VerificationApplicationAttachment": "verification", "VendorFile": "equipment", "EquipmentAttachment": "equipment"}
GIVE_UP = "無法判斷"


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


_BY_NAME = {_norm(name): zone_id for zone_id, name in ZONES}
_BY_NAME.update({_norm(k): v for k, v in ALIASES.items()})


def zone_id_for_name(name):
    return _BY_NAME.get(_norm(name)) if name else None


def search_names(zone_id):
    """Every topic_zone value that belongs to a zone: its name now, and the names it had before."""
    return [ZONE_BY_ID[zone_id]] + [k for k, v in ALIASES.items() if v == zone_id and k != _norm(ZONE_BY_ID[zone_id])] if zone_id in ZONE_BY_ID else []


def resolve_zone(source_type, l1_name=None, document_type=None, zone_hint=None):
    """-> (zone_id, topic_zone, basis). basis says why: source_type / document_type (a test report), llm (the content), classification (CSIT's L1),
    source_default, or none."""
    if source_type == "TestReport":
        return "verification", ZONE_BY_ID["verification"], "source_type"
    if document_type == "TestReport":
        return "verification", ZONE_BY_ID["verification"], "document_type"
    if zone_hint in ZONE_BY_ID:
        return zone_hint, ZONE_BY_ID[zone_hint], "llm"
    zone_id = zone_id_for_name(l1_name)
    if zone_id:
        return zone_id, ZONE_BY_ID[zone_id], "classification"
    zone_id = SOURCE_DEFAULT.get(source_type)
    if zone_id:
        return zone_id, ZONE_BY_ID[zone_id], "source_default"
    return UNCLASSIFIED[0], UNCLASSIFIED[1], "none"


def zone_payload(source_type, classification_names=None, document_type=None, zone_hint=None):
    """The three payload fields for a point. classification_names: {"l1": name|None, ...} (names, not ids)."""
    zone_id, topic_zone, basis = resolve_zone(source_type, (classification_names or {}).get("l1"), document_type, zone_hint)
    return {"zone_id": zone_id, "topic_zone": topic_zone, "zone_basis": basis}
