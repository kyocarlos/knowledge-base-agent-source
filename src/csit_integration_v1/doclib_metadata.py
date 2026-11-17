"""Completed.result builder (spec v1.3 section 5).

Rule-derived fields are computed here. Only documentType, summary, keywords, the zone and the technology tag may come from a model, and each is
validated before use. Everything unknown stays null / [] and nothing is guessed (no author, date, model, measurement).
"""
import json,os,re
from datetime import datetime,timezone
from pathlib import Path
from .doclib_models import DOCUMENT_TYPES,validate_result
from .errors import IntegrationError
from .zones import GIVE_UP,ZONE_BY_ID,zone_id_for_name,zone_payload

MAX_SUMMARY=600
MAX_KEYWORDS=20
MAX_TECHNICAL_ITEMS=40
MAX_MEASUREMENTS=40
MAX_SPECIFICATIONS=30
MAX_LIMITATIONS=20
MAX_CAPABILITY_SUMMARY=400
SEMANTIC_INPUT_CHARS=12000
TECHNOLOGY_TAGS=("Wi-Fi","Cellular","Small Cell","PON","Cable")
# Technical facts kept only when the exact string also occurs in the extracted text (case-insensitive) -- the same rule as keywords below,
# so a model cannot invent a vendor, model number or test item the document never names.
TECHNICAL_LIST_FIELDS=("productNames","modelNumbers","vendorNames","technologies","standards","softwareVersions",
    "hardwareVersions","projectNames","testItems","issueKeys","errorCodes")
PARSE_RETRY_ATTEMPTS=int(os.getenv("KM_CSIT_SEMANTIC_PARSE_RETRIES","2"))
# extract() returns this instead of None when the model's reply never parsed as JSON after retrying: a dict with no field this module
# reads, so clean_semantic() falls through to its empty defaults exactly as it does for a bare {}, while build_result[_v2]() can still
# tell "the model said nothing usable" apart from "no model is configured" and name the real reason in warnings.
PARSE_FAILED_MARKER_KEY="_extraction_parse_failed"
# CPE documents belong to 行動通訊知識專區 (mapping table row 15). Used only when the model named no zone; the CPE model list CSIT is to provide is not here yet.
CPE_WORDS=re.compile(r"\bCPE\b|路由器|閘道器|用戶端設備|customer premises",re.I)

def detect_language(text):
    sample=text[:20000]
    cjk=len(re.findall(r"[一-鿿]",sample))
    latin=len(re.findall(r"[A-Za-z]",sample))
    if cjk+latin<20:return None
    return "zh" if cjk>=latin*0.3 else "en"

def _grounded_strings(items,lowered,limit,max_len=128):
    """Keep each string the model offered only if it also occurs verbatim (case-insensitive) in the document text."""
    out=[];seen=set()
    if not isinstance(items,list):return out
    for item in items:
        if not isinstance(item,str):continue
        item=item.strip()
        if not 1<=len(item)<=max_len or item.lower() in seen:continue
        if item.lower() not in lowered:continue
        seen.add(item.lower());out.append(item)
        if len(out)>=limit:break
    return out

def _grounded_measurements(items,lowered):
    """A measurement/spec value (frequency, band, limit, ...) is kept only when both its metric name and its value occur in the text."""
    out=[]
    if not isinstance(items,list):return out
    for item in items:
        if not isinstance(item,dict):continue
        metric=item.get("metric")
        value=item.get("value")
        if not isinstance(metric,str) or not metric.strip():continue
        if isinstance(value,str):
            value_text=value.strip()
            if not value_text:continue
        elif isinstance(value,(int,float)) and not isinstance(value,bool):value_text=str(value)
        else:continue
        if metric.strip().lower() not in lowered or value_text.lower() not in lowered:continue
        unit=item.get("unit");unit=unit.strip()[:32] if isinstance(unit,str) and unit.strip() else None
        context=item.get("context")
        context=" ".join(context.split())[:200] if isinstance(context,str) and context.strip() else None
        out.append({"metric":metric.strip()[:64],"value":value if isinstance(value,(int,float)) and not isinstance(value,bool) else value_text[:64],
            "unit":unit,"context":context})
        if len(out)>=MAX_MEASUREMENTS:break
    return out

def _free_text_list(items,limit,max_len):
    """A holistic field (a specification sentence, a limitation) the model may phrase in its own words, the same latitude summary already
    has below -- but still only from what the document actually says, never extended with outside knowledge."""
    out=[]
    if not isinstance(items,list):return out
    for item in items:
        if not isinstance(item,str):continue
        item=" ".join(item.split())
        if not item:continue
        out.append(item[:max_len])
        if len(out)>=limit:break
    return out

def clean_semantic(raw,text):
    """Validate model output. Anything not provable from the extracted text is dropped."""
    out={"documentType":"Other","summary":None,"keywords":[],"zone_hint":None,"technology":None,
         **{field:[] for field in TECHNICAL_LIST_FIELDS},"measurements":[],
         "specifications":[],"capabilitySummary":None,"limitations":[]}
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
    for field in TECHNICAL_LIST_FIELDS:
        out[field]=_grounded_strings(raw.get(field),lowered,MAX_TECHNICAL_ITEMS)
    out["measurements"]=_grounded_measurements(raw.get("measurements"),lowered)
    out["specifications"]=_free_text_list(raw.get("specifications"),MAX_SPECIFICATIONS,200)
    out["limitations"]=_free_text_list(raw.get("limitations"),MAX_LIMITATIONS,200)
    cap=raw.get("capabilitySummary")
    if isinstance(cap,str) and cap.strip():out["capabilitySummary"]=" ".join(cap.split())[:MAX_CAPABILITY_SUMMARY]
    return out

def _page_count(path,suffix):
    if suffix!=".pdf":return None
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except Exception:return None

def semantic_warning(semantic):
    """None when nothing is wrong. extract() (below) returns None when no model is configured, or a dict carrying
    PARSE_FAILED_MARKER_KEY when a model answered but never produced parseable JSON after retrying -- two different situations that must
    not share one vague warning, so a Completed.result with empty technical fields always says which one happened."""
    if semantic is None:return "semantic extraction not available; documentType, summary and keywords left empty"
    if isinstance(semantic,dict) and semantic.get(PARSE_FAILED_MARKER_KEY):
        return "semantic extraction attempted but the model's reply could not be parsed as JSON after retrying; technical fields left empty"
    return None

def build_result(job,extraction,suffix,source_path,semantic,index_id,chunk_count,indexed_at):
    text=extraction.text
    sem=clean_semantic(semantic,text)
    warnings=[]
    warning=semantic_warning(semantic)
    if warning:warnings.append(warning)
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

def llm_prompt(text,*,retry=False):
    body=text[:SEMANTIC_INPUT_CHARS]
    retry_note="\n（上一次回覆不是合法 JSON，這次請只回傳一個 JSON 物件，不要加其他文字或說明。）" if retry else ""
    return ("你是文件分類與技術擷取器。只根據下列文件內容回答，不得臆測；文件沒有明確提到的欄位一律留空或空陣列。"+retry_note+"\n"
        "輸出一個 JSON 物件，鍵為 documentType、summary、keywords、zone、technology、"
        "productNames、modelNumbers、vendorNames、technologies、standards、softwareVersions、hardwareVersions、"
        "projectNames、testItems、measurements、issueKeys、errorCodes、specifications、capabilitySummary、limitations。\n"
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
        "  部門與公司文管專區：Time Report、Weekly Report、部門內部文件、人事行政、採購請款、組織架構等公司內部管理文件\n\n"
        "以下欄位只填文件中實際出現的詞語或數據，不得翻譯、改寫或推論：\n"
        "productNames：設備／產品名稱。modelNumbers：型號。vendorNames：廠牌／供應商名稱。\n"
        "technologies：使用的技術（例如 Wi-Fi 6、NR）。standards：技術標準（例如 IEEE 802.11ax）。\n"
        "softwareVersions：韌體／軟體版本字串。hardwareVersions：硬體版本字串。projectNames：專案名稱。\n"
        "testItems：文件中列出的可執行測試項目名稱。issueKeys：問題追蹤編號。errorCodes：錯誤代碼。\n"
        "measurements：量測數據、頻段／頻率等技術規格，每筆為 {metric, value, unit, context} 物件；metric 與 value 都必須是文件中出現的字詞。\n"
        "以下欄位可以用你自己的話摘要，但內容必須完全根據文件，不得延伸或補充文件沒有的資訊：\n"
        "specifications：條列式的技術規格摘要，每項一句話。\n"
        "capabilitySummary：這份文件描述的設備可執行哪些測試或具備哪些能力，一段話摘要；文件沒有提到就留 null。\n"
        "limitations：文件中提到的限制條件、注意事項或已知問題；沒有就留空陣列。\n\n文件內容：\n"+body)

def parse_llm_json(reply):
    if not isinstance(reply,str):return None
    m=re.search(r"\{.*\}",reply,re.S)
    if not m:return None
    try:return json.loads(m.group(0))
    except ValueError:return None

def make_semantic_extractor(complete):
    """complete(prompt)->str is the KM LLM entry point.

    A call that fails after doclib_llm's own retry budget (HTTP 429/5xx/timeout/connection/invalid-body) is never swallowed here: it is
    re-raised as an IntegrationError so the caller's existing job-retry machinery runs, carrying the same code and retryable flag doclib_llm
    classified it with. That is the fix for "a necessary technical analysis failure silently became an empty array reported as a complete
    success" -- an infra failure must look like a failure, not like a document with nothing technical in it.

    A reply that is simply never valid JSON is a different thing: the input will not change on a later job attempt, so after
    PARSE_RETRY_ATTEMPTS extra tries (with a corrective note appended to the prompt) this degrades to the PARSE_FAILED_MARKER_KEY marker
    instead of raising -- still never silent, since semantic_warning() turns that marker into its own specific warning text, but it does
    not loop the whole document job forever on a model that keeps answering with prose."""
    from .doclib_llm import LlmCallError
    def extract(text):
        if not text.strip():return None
        for attempt in range(PARSE_RETRY_ATTEMPTS+1):
            try:
                reply=complete(llm_prompt(text,retry=attempt>0))
            except LlmCallError as exc:
                raise IntegrationError(exc.code,"semantic extraction: "+exc.message,exc.retryable) from exc
            except Exception as exc:
                # complete() did not go through doclib_llm's own retry/classification (a test double, or a future caller with its own
                # client): still never silently None -- default to retryable, the same safe default ingest_one() falls back to elsewhere.
                raise IntegrationError("LLM_CALL_FAILED","semantic extraction: "+str(exc),True) from exc
            parsed=parse_llm_json(reply)
            if parsed is not None:return parsed
        return {PARSE_FAILED_MARKER_KEY:True}
    return extract

def zone_fields(source_type,classification_names,semantic,text):
    """The payload fields every point of one document carries: the zone KM decided from the content (see zones.py) and what the zone pages show about
    the document (type, summary, keywords, when it was indexed)."""
    sem=clean_semantic(semantic,text)
    return {**zone_payload(source_type,classification_names,sem["documentType"],sem["zone_hint"]),"document_type":sem["documentType"],"summary":sem["summary"],
            "zone_suggestion":ZONE_BY_ID.get(sem["zone_hint"]),"technology_tag":sem["technology"],"keywords":sem["keywords"],"indexed_at":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
