"""Completed.result builder (spec v1.3 section 5).

Rule-derived fields are computed here. Only documentType, summary, keywords, the zone and the technology tag may come from a model, and each is
validated before use. Everything unknown stays null / [] and nothing is guessed (no author, date, model, measurement).
"""
import json,re
from datetime import datetime,timezone
from pathlib import Path
from .doclib_models import DOCUMENT_TYPES,validate_result
from .zones import GIVE_UP,zone_id_for_name,zone_payload

MAX_SUMMARY=600
MAX_KEYWORDS=20
SEMANTIC_INPUT_CHARS=12000
TECHNOLOGY_TAGS=("Wi-Fi","Cellular","Small Cell","PON","Cable")
# CPE documents belong to 行動通訊知識專區 (mapping table row 15). Used only when the model named no zone; the CPE model list CSIT is to provide is not here yet.
CPE_WORDS=re.compile(r"\bCPE\b|路由器|閘道器|用戶端設備|customer premises",re.I)

def detect_language(text):
    sample=text[:20000]
    cjk=len(re.findall(r"[一-鿿]",sample))
    latin=len(re.findall(r"[A-Za-z]",sample))
    if cjk+latin<20:return None
    return "zh" if cjk>=latin*0.3 else "en"

def clean_semantic(raw,text):
    """Validate model output. Anything not provable from the extracted text is dropped."""
    out={"documentType":"Other","summary":None,"keywords":[],"zone_hint":None,"technology":None}
    if not isinstance(raw,dict):return out
    tech=raw.get("technology")
    if tech in TECHNOLOGY_TAGS:out["technology"]=tech
    z=raw.get("zone")
    if isinstance(z,str):out["zone_hint"]=zone_id_for_name(z) # a name that is not one of the zones (or the give-up answer) leaves no hint
    if out["zone_hint"] is None and CPE_WORDS.search(text[:SEMANTIC_INPUT_CHARS]):out["zone_hint"]="mobile"
    dt=raw.get("documentType")
    if isinstance(dt,str) and dt in DOCUMENT_TYPES:out["documentType"]=dt
    summary=raw.get("summary")
    if isinstance(summary,str) and summary.strip():out["summary"]=" ".join(summary.split())[:MAX_SUMMARY]
    lowered=text.lower()
    seen=set()
    for kw in raw.get("keywords") or []:
        if not isinstance(kw,str):continue
        kw=kw.strip()
        if not 1<=len(kw)<=64 or kw.lower() in seen:continue
        # A keyword must occur in the document; this blocks invented terms.
        if kw.lower() not in lowered:continue
        seen.add(kw.lower());out["keywords"].append(kw)
        if len(out["keywords"])>=MAX_KEYWORDS:break
    return out

def _page_count(path,suffix):
    if suffix!=".pdf":return None
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except Exception:return None

def build_result(job,extraction,suffix,source_path,semantic,index_id,chunk_count,indexed_at):
    text=extraction.text
    sem=clean_semantic(semantic,text)
    warnings=[]
    if semantic is None:warnings.append("semantic extraction not available; documentType, summary and keywords left empty")
    expected_ct=job.get("content_type") or ""
    result={
      "metadataSchemaVersion":"1.0",
      "document":{"title":None,"documentType":sem["documentType"],"summary":sem["summary"],"language":detect_language(text),
        "documentDate":None,"authors":[],"department":None,"documentVersionLabel":None,"keywords":sem["keywords"],"tags":[]},
      "technical":{"productNames":[],"modelNumbers":[],"vendorNames":[],"technologies":[],"standards":[],"softwareVersions":[],
        "hardwareVersions":[],"projectNames":[],"testItems":[],"measurements":[],"issueKeys":[],"errorCodes":[]},
      "extraction":{"sourceFormat":suffix.lstrip("."),"method":"Text","pageCount":_page_count(source_path,suffix),
        "sheetNames":[t["name"] for t in extraction.tables] if suffix==".xlsx" else [],
        "extractedCharacterCount":len(text),"ocrUsed":False},
      "indexing":{"status":"Completed","indexId":index_id,"chunkCount":chunk_count,
        "indexedAt":indexed_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
      "warnings":warnings}
    validate_result(result)
    return result

def llm_prompt(text):
    body=text[:SEMANTIC_INPUT_CHARS]
    return ("你是文件分類器。只根據下列文件內容回答，不得臆測；不確定就留空。\n"
        "輸出 JSON 物件，鍵為 documentType、summary、keywords、zone、technology。\n"
        "technology：文件主要談的技術，只能是 "+"、".join(TECHNOLOGY_TAGS)+" 其中之一（CPE 屬於 Cellular）；看不出來或跨多種技術就留空。\n"
        "documentType 只能是："+"、".join(DOCUMENT_TYPES)+"。\n"
        "summary：不超過 "+str(MAX_SUMMARY)+" 字，使用文件原語言。\n"
        "keywords：最多 "+str(MAX_KEYWORDS)+" 個，必須是文件中實際出現的字詞。\n"
        "zone：這份文件該放進哪個知識專區，只能是下列名稱之一，或「"+GIVE_UP+"」。依文件內容的主題判斷，不看檔名。\n"
        "  跨多種技術的文件（例如研討會講義）選內容最接近的專區，不要回「"+GIVE_UP+"」；只有完全看不出主題才回「"+GIVE_UP+"」。\n"
        "  產品驗證專區：測試報告（documentType 為 TestReport 的文件一律填這個，不論它測的是哪種技術）、產品資訊、驗證申請單、測試計畫文件（各技術都放這裡）\n"
        "  WiFi 知識專區：Wi-Fi／802.11 的技術、規範與標準文件（不是測試報告）\n"
        "  行動通訊知識專區：4G／5G／LTE／NR、Small Cell、CPE（路由器、閘道器、用戶端設備）的技術、規範與標準文件（不是測試報告）\n"
        "  固網寬頻知識專區：PON、Cable、DSL 的技術、規範與標準文件（不是測試報告）\n"
        "  認證知識專區：認證與法規、送測流程、認證項目\n"
        "  設備儀器專區：儀器設備資訊、廠商資訊、校驗與使用說明\n"
        "  實驗室管理專區：實驗室規劃、建置、測試環境與管理辦法\n"
        "  Confluence / Jira / TestRail 查詢專區：預留給之後的功能，目前不收文件，不要選這個專區\n"
        "  部門與公司文管專區：Time Report、Weekly Report、部門內部文件、人事行政、採購請款、組織架構等公司內部管理文件\n\n文件內容：\n"+body)

def parse_llm_json(reply):
    if not isinstance(reply,str):return None
    m=re.search(r"\{.*\}",reply,re.S)
    if not m:return None
    try:return json.loads(m.group(0))
    except ValueError:return None

def make_semantic_extractor(complete):
    """complete(prompt)->str is the KM LLM entry point. Any failure yields None so metadata falls back to null/[]."""
    def extract(text):
        if not text.strip():return None
        try:return parse_llm_json(complete(llm_prompt(text)))
        except Exception:return None
    return extract

def zone_fields(source_type,classification_names,semantic,text):
    """The payload fields every point of one document carries: the zone KM decided from the content (see zones.py) and what the zone pages show about
    the document (type, summary, keywords, when it was indexed)."""
    sem=clean_semantic(semantic,text)
    return {**zone_payload(source_type,classification_names,sem["documentType"],sem["zone_hint"]),"document_type":sem["documentType"],"summary":sem["summary"],
            "technology_tag":sem["technology"],"keywords":sem["keywords"],"indexed_at":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
