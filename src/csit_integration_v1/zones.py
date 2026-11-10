"""Which KM knowledge zone a CSIT document belongs to.

The nine zones are the entries of the KM left navigation. CSIT owns the official classification (CSIT reply of 2026-11-10: KM may not override it with keywords or an
AI guess, and a document that cannot be mapped goes to 待分類, not to an arbitrary zone), so only rules that follow from CSIT's own data assign a zone, in order:
  1. a Test Report is always 產品驗證專區 (CSIT's Test Report source), whatever its technology;
  2. the zone CSIT's classification maps to (zone_by_classification: e.g. 外部認證資料 -> 認證, 部門文管專區 -> 文管, 技術相關文件／Wi-Fi -> WiFi);
  3. CSIT's first classification level if it happens to be a zone name;
  4. the home zone of the attachment sources (verification-application attachment, vendor file, equipment attachment);
  5. otherwise 待分類 — kept for review, not guessed.
The zone the LLM would pick is only stored as a suggestion (zone_suggestion) next to the document, for the person who reviews 待分類; it never sets topic_zone.
KM stores the result on every point it writes (zone_id, topic_zone, zone_basis); the zone pages filter on topic_zone.
"""
import re

ZONES = (("wifi", "WiFi 知識專區"), ("mobile", "行動通訊知識專區"), ("broadband", "固網寬頻知識專區"), ("cert", "認證知識專區"),
         ("verification", "產品驗證專區"), ("equipment", "設備儀器專區"), ("lab", "實驗室管理專區"), ("integrations", "Confluence / Jira / TestRail 查詢專區"),
         ("admin", "部門與公司文管專區"))
ZONE_BY_ID = dict(ZONES)
# The zone page keys of the front end differ for one zone: the page "csit" is 產品驗證專區.
PAGE_KEY = {"verification": "csit"}
UNCLASSIFIED = ("unclassified", "待分類")
# Names the same zones carried before the navigation was renamed (also what the legacy importer wrote); accepted when reading and as a fallback.
ALIASES = {"4G/5G 知識專區": "mobile", "認證與法規知識專區": "cert", "設備預約知識專區": "equipment", "實驗室與測試環境知識專區": "lab", "CSIT雜項專區": "verification"}
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
    return [ZONE_BY_ID[zone_id]] + [k for k, v in ALIASES.items() if v == zone_id and k != ZONE_BY_ID[zone_id]] if zone_id in ZONE_BY_ID else []


# CSIT's own classification (the document-centre table, 第一層／第二層／第三層) decides the zone when the table says so (mapping table 2026-11-10).
L1_ZONE = {"產品驗證資料": "verification", "外部認證資料": "cert", "設備儀器管理": "equipment", "實驗室內部管理": "lab", "部門文管專區": "admin", "公司官方文件": "admin"}
# Under 技術相關文件 and 國際組織規範 the second level names the technology / organisation. Research seminars and Broadband Forum documents are not here:
# the content decides (seminars of several technologies, TR-398 versus PON).
_TECH_ZONE = (("wifi", re.compile(r"wi-?fi|802\.11|ieee")), ("mobile", re.compile(r"cellular|lte|5g|\bnr\b|ntn|redcap|6g|small ?cell|3gpp|\bcpe\b")),
              ("broadband", re.compile(r"(?<![a-z])pon(?![a-z])|\bcable\b|docsis|xdsl|dsl")))


def zone_by_classification(l1=None, l2=None, l3=None):
    """The zone CSIT's classification names, or None when it does not decide (or the names are not those of the table)."""
    l1, l2, l3 = (str(x or "").strip() for x in (l1, l2, l3))
    if l1 == "實驗室內部管理":                              # two rows leave the lab: test plans are product verification, calibration reports belong to the instrument
        if "測試計畫" in l2:
            return "verification"
        if "環境校驗" in l3:
            return "equipment"
    if l1 in L1_ZONE:
        return L1_ZONE[l1]
    if l1 in ("技術相關文件", "國際組織規範") and l2 and "研討會" not in l2 and not (l1 == "國際組織規範" and "broadband forum" in l2.casefold()):
        text = l2.casefold()
        return next((zone for zone, pattern in _TECH_ZONE if pattern.search(text)), None)
    return None


def resolve_zone(source_type, l1_name=None, document_type=None, zone_hint=None, l2_name=None, l3_name=None):
    """-> (zone_id, topic_zone, basis). basis says why: source_type / document_type (a test report), classification_table (CSIT's classification as the table
    maps it), llm (the content), classification (CSIT's L1 is itself a zone name), source_default, or none."""
    if source_type == "TestReport":
        return "verification", ZONE_BY_ID["verification"], "source_type"
    zone_id = zone_by_classification(l1_name, l2_name, l3_name)
    if zone_id:
        return zone_id, ZONE_BY_ID[zone_id], "classification_table"
    zone_id = zone_id_for_name(l1_name)
    if zone_id:
        return zone_id, ZONE_BY_ID[zone_id], "classification"
    zone_id = SOURCE_DEFAULT.get(source_type)
    if zone_id:
        return zone_id, ZONE_BY_ID[zone_id], "source_default"
    return UNCLASSIFIED[0], UNCLASSIFIED[1], "none"


def zone_payload(source_type, classification_names=None, document_type=None, zone_hint=None):
    """The three payload fields for a point. classification_names: {"l1": name|None, ...} (names, not ids)."""
    names = classification_names or {}
    zone_id, topic_zone, basis = resolve_zone(source_type, names.get("l1"), document_type, zone_hint, names.get("l2"), names.get("l3"))
    return {"zone_id": zone_id, "topic_zone": topic_zone, "zone_basis": basis}
