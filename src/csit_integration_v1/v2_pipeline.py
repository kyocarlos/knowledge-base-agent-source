"""Spec v1.4 ingestion: every formally archived file is a job. Download + SHA256 -> parse -> index -> Completed.result (v2).

A file KM cannot read is not skipped: the job ends Failed with a specific code (spec 0, 4.1, 5.3).
"""
import json,re,shutil,zipfile
from datetime import datetime,timezone
from html import unescape
from pathlib import Path
from .errors import IntegrationError,LeaseLost
from .pipeline import FORMAT_MIME,Parser,Extraction,validate_file,check_ooxml,normalize,stable_id
from .doclib_metadata import detect_language,clean_semantic,_page_count
from .v2_models import SOURCE_SPECIFIC_DEFAULTS,validate_result_v2
from .doclib_metadata import zone_fields

PARSER_VERSION="km-csit-v2-parser-v1"
PARSEABLE=tuple(FORMAT_MIME)+(".md",".pptx")
IMAGE_SUFFIXES=(".png",".jpg",".jpeg",".gif",".bmp",".tif",".tiff",".webp")
OLE_MAGIC=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" # password-protected Office files are OLE containers, not zip packages
# Codes of spec 5.3. Anything the v1 validators raise is renamed here so CSIT sees one vocabulary.
CODE_MAP={"UNSUPPORTED_DOCUMENT_FORMAT":"UNSUPPORTED_FORMAT","CORRUPT_DOCUMENT":"CORRUPT_FILE","INVALID_FILE_SIGNATURE":"MALWARE_DETECTED",
          "PARSER_REJECTION":"PARSER_ERROR","SCHEMA_VALIDATION_FAILED":"PARSER_ERROR"}

def v2_dir(root,event_id):
    return Path(root)/"v2"/str(event_id)

def identity_payload(job):
    return {"source_type":job["source_type"],"source_entity_id":str(job["source_entity_id"]),
            "document_id":str(job["document_id"]),"document_version":job["version"]}

def renamed(error):
    code=CODE_MAP.get(error.code,error.code)
    return error if code==error.code else IntegrationError(code,error.message,error.retryable)

class V2Parser(Parser):
    """The v1 parser plus Markdown and PowerPoint (text of the slides, no macros or embedded objects executed)."""
    def parse(self,path,suffix):
        if suffix==".md":
            text=path.read_text(encoding="utf-8-sig",errors="strict")
            if len(text)>self.settings.max_text_chars:raise IntegrationError("PARSER_LIMIT_EXCEEDED","Text parser size limit exceeded")
            return Extraction(text=text)
        if suffix==".pptx":
            try:
                with zipfile.ZipFile(path) as z:
                    slides=sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml",n)),key=lambda n:int(re.findall(r"\d+",n)[0]))
                    parts=[]
                    for n in slides:
                        runs=[unescape(x) for x in re.findall(r"<a:t>([^<]*)</a:t>",z.read(n).decode("utf-8","replace"))]
                        parts.append("\n".join(r for r in runs if r.strip()))
                text="\n\n".join(p for p in parts if p)
            except zipfile.BadZipFile:raise IntegrationError("CORRUPT_DOCUMENT","Office archive invalid") from None
            if len(text)>self.settings.max_text_chars:raise IntegrationError("PARSER_LIMIT_EXCEEDED","Text parser size limit exceeded")
            return Extraction(text=text)
        return super().parse(path,suffix)

def validate_v2_file(path,suffix,name,settings):
    """Format gate. Executable content, broken containers and password-protected documents get their own codes."""
    if path.stat().st_size==0:raise IntegrationError("CORRUPT_FILE","Empty source document")
    with path.open("rb") as f:head=f.read(16)
    if head.startswith((b"MZ",b"\x7fELF")):raise IntegrationError("MALWARE_DETECTED","Executable content rejected")
    if suffix in (".docx",".xlsx",".pptx") and head.startswith(OLE_MAGIC):
        raise IntegrationError("ENCRYPTED_DOCUMENT","The document is password protected")
    if suffix==".pdf":
        if not head.startswith(b"%PDF-"):raise IntegrationError("CORRUPT_FILE","PDF signature invalid")
        try:from pypdf import PdfReader
        except ImportError:PdfReader=None # without pypdf the encryption check is skipped and the parser decides
        if PdfReader is not None:
            try:
                if PdfReader(str(path)).is_encrypted:raise IntegrationError("ENCRYPTED_DOCUMENT","The document is password protected")
            except IntegrationError:raise
            except Exception:raise IntegrationError("CORRUPT_FILE","PDF cannot be read") from None
    if suffix==".pptx":check_ooxml(path,"ppt/presentation.xml",settings)
    elif suffix in FORMAT_MIME:
        validate_file(path,{"file_name":name,"content_type":FORMAT_MIME[suffix]},settings) # MIME is advisory; extension and signature decide
    elif suffix==".md":
        try:path.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError:raise IntegrationError("CORRUPT_FILE","Markdown is not valid UTF-8") from None

def source_specific(job,extraction,suffix):
    out=dict(SOURCE_SPECIFIC_DEFAULTS.get(job["source_type"],{}))
    sheets=[t["name"] for t in extraction.tables] if suffix==".xlsx" else []
    if "sheetNames" in out:out["sheetNames"]=sheets
    return out

def build_result_v2(job,extraction,suffix,source_path,semantic,index_id,chunk_count,indexed_at,warnings=()):
    text=extraction.text
    sem=clean_semantic(semantic,text)
    warnings=list(warnings)
    if semantic is None:warnings.append("semantic extraction not available; documentType, summary and keywords left empty")
    result={
      "metadataSchemaVersion":"2.0",
      "document":{"title":None,"documentType":sem["documentType"],"summary":sem["summary"],"language":detect_language(text),
        "documentDate":None,"authors":[],"department":None,"documentVersionLabel":None,"keywords":sem["keywords"],"tags":[]},
      "technical":{"productNames":[],"modelNumbers":[],"vendorNames":[],"technologies":[],"standards":[],"softwareVersions":[],
        "hardwareVersions":[],"projectNames":[],"testItems":[],"measurements":[],"issueKeys":[],"errorCodes":[]},
      "extraction":{"sourceFormat":suffix.lstrip("."),"method":"Text","pageCount":_page_count(source_path,suffix),
        "sheetNames":[t["name"] for t in extraction.tables] if suffix==".xlsx" else [],
        "extractedCharacterCount":len(text),"ocrUsed":False},
      "indexing":{"status":"Completed","indexId":index_id,"chunkCount":chunk_count,
        "indexedAt":indexed_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
      "warnings":warnings,
      "sourceSpecific":source_specific(job,extraction,suffix)}
    validate_result_v2(result)
    return result

def metadata_payload(change_payload):
    """The index payload a metadata change produces. Complete new values: an empty list clears the old one."""
    cls=change_payload["classification"]
    a=change_payload["attributes"]
    names={k:(cls.get(k) or {}).get("name") for k in ("l1","l2","l3")}
    return {"classification":names, # the zone stays: KM decided it from the content, CSIT's classification is not the zone
            "tags":a["tags"],"keywords":a["keywords"],"display_name":a["displayName"],
            "model_numbers":a["modelNumbers"],"vendor_reference":a["vendorReference"]}

class V2QdrantWriter:
    """Chunks go to the document-library collection stamped with the exact source identity (source, entity, document, version)."""
    FIELDS=("source_entity_id","document_id","document_version","source_type","csit_job_id","document_file_id")
    def __init__(self,client,collection,embedder,chunk_size,extra_collections=()):
        self.client,self.collection,self.embedder,self.chunk_size=client,collection,embedder,chunk_size
        self.extra_collections=tuple(extra_collections) # Test Report v1 vectors live in the report collections
    def ensure_index(self):
        from qdrant_client.models import PayloadSchemaType
        for field in self.FIELDS+("zone_id","topic_zone"):
            try:self.client.create_payload_index(self.collection,field,field_schema=PayloadSchemaType.INTEGER if field=="document_version" else PayloadSchemaType.KEYWORD)
            except Exception:pass
    @staticmethod
    def flt(source_entity_id,document_id,version):
        from qdrant_client.models import FieldCondition,Filter,MatchValue
        return Filter(must=[FieldCondition(key="source_entity_id",match=MatchValue(value=str(source_entity_id))),
                            FieldCondition(key="document_id",match=MatchValue(value=str(document_id))),
                            FieldCondition(key="document_version",match=MatchValue(value=int(version)))])
    def write(self,text,job,overrides=None,semantic=None):
        from qdrant_client.models import PointStruct
        ident=identity_payload(job)
        chunks=[text[i:i+self.chunk_size] for i in range(0,len(text),self.chunk_size) if text[i:i+self.chunk_size].strip()]
        vectors=self.embedder(chunks) if chunks else []
        if len(vectors)!=len(chunks):raise IntegrationError("EMBEDDING_INVALID","Embedding result shape invalid")
        req=job["request_payload"]
        cls={k:(v or {}).get("name") for k,v in (req.get("classification") or {}).items() if isinstance(v,dict) or v is None}
        src=req.get("source") or {}
        extra={"classification":cls,**zone_fields(job["source_type"],cls,semantic,text),**(overrides or {})}
        # A re-ingest of the same version replaces its points instead of accumulating stale ones.
        self.client.delete(self.collection,points_selector=self.flt(job["source_entity_id"],job["document_id"],job["version"]),wait=True)
        points=[PointStruct(id=stable_id("CSIT",job["source_type"],str(job["source_entity_id"]),str(job["document_id"]),job["version"],job["expected_sha256"],"chunk",i),
            vector=v,payload={"content":t,"source_system":"CSIT",**ident,"csit_job_id":str(job["csit_job_id"]),"event_id":str(job["event_id"]),
                "doc_name":job["original_file_name"],"source_name":job["original_file_name"],"source_ext":Path(job["original_file_name"]).suffix.lower(),
                "chunk_index":i,"sha256":job["expected_sha256"],"index_state":"Active",
                "application_id":src.get("applicationId"),"vendor_id":src.get("vendorId"),"equipment_id":src.get("equipmentId"),**extra})
            for i,(t,v) in enumerate(zip(chunks,vectors))]
        if points:self.client.upsert(collection_name=self.collection,points=points,wait=True)
        return {"collection":self.collection,"pointCount":len(points),"indexId":self.collection+"/"+str(job["event_id"])}
    def delete(self,job):
        self.client.delete(self.collection,points_selector=self.flt(job["source_entity_id"],job["document_id"],job["version"]),wait=True)
    def set_state(self,document_id,version,sha256,state):
        """Mark the points of an older document version (a replacement completed). Not searchable as current once Superseded."""
        from qdrant_client.models import FieldCondition,Filter,MatchValue
        must=[FieldCondition(key="document_id",match=MatchValue(value=str(document_id))),
              FieldCondition(key="document_version",match=MatchValue(value=int(version))),
              FieldCondition(key="sha256",match=MatchValue(value=sha256))]
        payload={"index_state":state,**({"superseded_at":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")} if state=="Superseded" else {})}
        self.client.set_payload(self.collection,payload=payload,points=Filter(must=must),wait=True)
        # A Test Report written through v1 carries document_id / document_version only (no sha256 in its points).
        for collection in self.extra_collections:
            try:self.client.set_payload(collection,payload=payload,wait=True,points=Filter(must=must[:2]))
            except Exception as exc:
                if "not found" not in str(exc).lower():raise
        # A version-less document-library file replaced through v2 is addressed by its file id.
        self.client.set_payload(self.collection,payload=payload,wait=True,
            points=Filter(must=[FieldCondition(key="document_file_id",match=MatchValue(value=str(document_id)))]))
    def apply_metadata(self,flt,payload):
        self.client.set_payload(self.collection,payload=payload,points=flt,wait=True)

class V2Pipeline:
    def __init__(self,settings,repository,client,qdrant_writer,parser=None,semantic=None):
        self.settings,self.repo,self.client,self.qdrant=settings,repository,client,qdrant_writer
        self.parser=parser or V2Parser(settings)
        self.semantic=semantic
    def run(self,job):
        try:self._run(job)
        except IntegrationError as e:raise renamed(e) from None
    def _run(self,job):
        s=self.settings
        suffix=Path(job["original_file_name"]).suffix.lower()
        if job["file_size_bytes"]>s.max_file_size:raise IntegrationError("FILE_TOO_LARGE","File exceeds the size KM accepts ("+str(s.max_file_size)+" bytes)")
        if suffix in IMAGE_SUFFIXES:raise IntegrationError("UNSUPPORTED_FORMAT","Image content cannot be analysed: OCR and vision are not enabled in this KM")
        if suffix not in PARSEABLE:raise IntegrationError("UNSUPPORTED_FORMAT","File format "+(suffix or "(no extension)")+" cannot be analysed")
        root=v2_dir(s.storage_root,job["event_id"])
        path=root/("source-"+str(job["lease_token"])+suffix)
        self.repo.phase_job(job,"Downloading")
        digest=self.client.download_v2(job,path)
        self.repo.set_hash_job(job,digest)
        self.repo.phase_job(job,"Validating")
        validate_v2_file(path,suffix,job["original_file_name"],s)
        self.repo.phase_job(job,"Parsing")
        extraction=normalize(self.parser.parse(path,suffix),job,())
        # Spec v1.4.1 C.4: Completed means something was parsed and indexed. A file with no extractable text (a scan, an empty sheet) is not.
        if not extraction.text.strip():raise IntegrationError("EMPTY_EXTRACTION","No text could be extracted from the document; nothing was indexed")
        semantic=None
        if self.semantic and extraction.text.strip():
            self.repo.phase_job(job,"Extracting")
            semantic=self.semantic(extraction.text)
        self.repo.phase_job(job,"Storage")
        stored=root/"normalized.json"
        stored.write_text(json.dumps({"documentId":str(job["document_id"]),"eventId":str(job["event_id"]),"parserVersion":PARSER_VERSION,
            "extraction":extraction.model_dump(mode="json")},ensure_ascii=False,sort_keys=True),encoding="utf-8")
        self.repo.phase_job(job,"Qdrant")
        try:
            indexed=self.qdrant.write(extraction.text,job,self.repo.overrides_job(job),semantic)
            indexed_at=datetime.now(timezone.utc) # the upsert used wait=True: the points are durable now
        except IntegrationError:raise
        except Exception:raise IntegrationError("STORAGE_UNAVAILABLE","Vector index unavailable",True) from None
        self.repo.checkpoint_job(job,"Qdrant",indexed)
        result=build_result_v2(job,extraction,suffix,path,semantic,indexed["indexId"],indexed["pointCount"],indexed_at)
        try:self.repo.finish_job(job,result,{"Storage":{"artifact":str(stored)},"Qdrant":indexed})
        except LeaseLost:
            # Deleted while we worked: leave nothing behind. A superseded lease must not touch the new owner's data.
            if self.repo.file_deleted_job(job):self.discard(job)
            raise
    def discard(self,job):
        try:self.qdrant.delete(job)
        except Exception:pass
        shutil.rmtree(v2_dir(self.settings.storage_root,job["event_id"]),ignore_errors=True)
    def reconcile_supersede(self):
        """After a replacement is Completed (never before): retire the older version's index. Idempotent, retried until done."""
        job=self.repo.next_supersede()
        if not job:return False
        old=job["request_payload"]["supersedes"]
        self.qdrant.set_state(old["oldDocumentId"],old["oldVersion"],old["oldSha256"],"Superseded")
        self.repo.retire_old(job)
        self.repo.supersede_done(job)
        return True
