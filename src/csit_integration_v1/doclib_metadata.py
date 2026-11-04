"""Completed.result builder (spec v1.3 section 5).

Rule-derived fields are computed here. Only documentType, summary and keywords may come from a model, and each is
validated before use. Everything unknown stays null / [] and nothing is guessed (no author, date, model, measurement).
"""
import json,re
from datetime import datetime,timezone
from pathlib import Path
from .doclib_models import DOCUMENT_TYPES,validate_result

MAX_SUMMARY=600
MAX_KEYWORDS=20
SEMANTIC_INPUT_CHARS=12000

def detect_language(text):
    sample=text[:20000]
    cjk=len(re.findall(r"[一-鿿]",sample))
    latin=len(re.findall(r"[A-Za-z]",sample))
    if cjk+latin<20:return None
    return "zh" if cjk>=latin*0.3 else "en"

def clean_semantic(raw,text):
    """Validate model output. Anything not provable from the extracted text is dropped."""
    out={"documentType":"Other","summary":None,"keywords":[]}
    if not isinstance(raw,dict):return out
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
        "輸出 JSON 物件，鍵為 documentType、summary、keywords。\n"
        "documentType 只能是："+"、".join(DOCUMENT_TYPES)+"。\n"
        "summary：不超過 "+str(MAX_SUMMARY)+" 字，使用文件原語言。\n"
        "keywords：最多 "+str(MAX_KEYWORDS)+" 個，必須是文件中實際出現的字詞。\n\n文件內容：\n"+body)

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
