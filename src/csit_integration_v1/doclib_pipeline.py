"""Document-library ingestion: download + SHA256 -> parse -> index -> Completed.result (spec v1.3 sections 4 and 5)."""
import hashlib,json,shutil,uuid
from datetime import datetime,timezone
from pathlib import Path
from .errors import IntegrationError,LeaseLost
from .pipeline import FORMAT_MIME,Parser,validate_file,normalize,stable_id
from .doclib_metadata import build_result
from .zones import zone_payload

PARSER_VERSION="km-csit-doclib-parser-v1"

def doclib_dir(root,csit_job_id):
    return Path(root)/"doclib"/str(csit_job_id)

class DocLibQdrantWriter:
    """Chunks go to Qdrant stamped with the exact source identity so a deletion can remove only this document."""
    def __init__(self,client,collection,embedder,chunk_size):
        self.client,self.collection,self.embedder,self.chunk_size=client,collection,embedder,chunk_size
    def ensure_index(self):
        from qdrant_client.models import PayloadSchemaType
        for field in ("document_file_id","csit_job_id","source_type","zone_id","topic_zone"):
            try:self.client.create_payload_index(self.collection,field,field_schema=PayloadSchemaType.KEYWORD)
            except Exception:pass # already present or collection not yet created
    def flt(self,document_file_id):
        from qdrant_client.models import FieldCondition,Filter,MatchValue
        return Filter(must=[FieldCondition(key="document_file_id",match=MatchValue(value=str(document_file_id)))])
    def write(self,text,job):
        from qdrant_client.models import PointStruct
        fid=str(job["document_file_id"])
        chunks=[text[i:i+self.chunk_size] for i in range(0,len(text),self.chunk_size) if text[i:i+self.chunk_size].strip()]
        vectors=self.embedder(chunks)
        if len(vectors)!=len(chunks):raise IntegrationError("EMBEDDING_INVALID","Embedding result shape invalid")
        cls=(job["request_payload"].get("classification") or {})
        names={k:(v or {}).get("name") for k,v in cls.items() if isinstance(v,dict) or v is None}
        # Re-ingest of the same file replaces its points instead of accumulating stale ones.
        self.client.delete(self.collection,points_selector=self.flt(fid),wait=True)
        points=[PointStruct(id=stable_id("CSIT","DocumentLibraryFile",fid,job["expected_sha256"],"chunk",i),vector=v,
            payload={"content":t,"source_system":"CSIT","source_type":"DocumentLibraryFile","document_file_id":fid,
                "csit_job_id":str(job["csit_job_id"]),"doc_name":job["original_file_name"],"source_name":job["original_file_name"],
                "source_ext":Path(job["original_file_name"]).suffix.lower(),"chunk_index":i,"sha256":job["expected_sha256"],
                "classification":names,**zone_payload("DocumentLibraryFile",names)}) for i,(t,v) in enumerate(zip(chunks,vectors))]
        if points:self.client.upsert(collection_name=self.collection,points=points,wait=True)
        return {"collection":self.collection,"pointCount":len(points),"indexId":self.collection+"/"+fid}
    def delete(self,document_file_id):
        self.client.delete(self.collection,points_selector=self.flt(document_file_id),wait=True)

class DocLibPipeline:
    def __init__(self,settings,repository,client,qdrant_writer,parser=None,semantic=None):
        self.settings,self.repo,self.client,self.qdrant=settings,repository,client,qdrant_writer
        self.parser=parser or Parser(settings)
        self.semantic=semantic # text -> dict|None (see doclib_metadata.make_semantic_extractor)
    def run(self,job):
        s=self.settings
        root=doclib_dir(s.storage_root,job["csit_job_id"])
        suffix=Path(job["original_file_name"]).suffix.lower()
        if suffix not in FORMAT_MIME:raise IntegrationError("UNSUPPORTED_DOCUMENT_FORMAT","Document format unsupported")
        path=root/("source-"+str(job["lease_token"])+suffix)
        self.repo.phase(job,"Downloading")
        digest=self.client.download_file(job,path)
        self.repo.set_hash(job,digest)
        self.repo.phase(job,"Validating")
        # CSIT's declared MIME is advisory here; the extension and the file signature decide.
        validate_file(path,{"file_name":job["original_file_name"],"content_type":FORMAT_MIME[suffix]},s)
        self.repo.phase(job,"Parsing")
        extraction=normalize(self.parser.parse(path,suffix),job,())
        if not extraction.text.strip():raise IntegrationError("EMPTY_EXTRACTION","No text could be extracted from the document")
        semantic=None
        if self.semantic:
            self.repo.phase(job,"Extracting")
            semantic=self.semantic(extraction.text)
        self.repo.phase(job,"Storage")
        stored=root/"normalized.json"
        stored.write_text(json.dumps({"documentFileId":str(job["document_file_id"]),"csitJobId":str(job["csit_job_id"]),
            "parserVersion":PARSER_VERSION,"extraction":extraction.model_dump(mode="json")},ensure_ascii=False,sort_keys=True),encoding="utf-8")
        self.repo.phase(job,"Qdrant")
        try:
            indexed=self.qdrant.write(extraction.text,job)
            indexed_at=datetime.now(timezone.utc) # Qdrant upsert used wait=True: the points are durable now.
        except IntegrationError:raise
        except Exception:raise IntegrationError("STORAGE_UNAVAILABLE","Vector index unavailable",True) from None
        self.repo.checkpoint(job,"Qdrant",indexed)
        result=build_result({"content_type":job["content_type"]},extraction,suffix,path,semantic,indexed["indexId"],indexed["pointCount"],indexed_at)
        try:
            self.repo.finish(job,result,{"Storage":{"artifact":str(stored)},"Qdrant":indexed})
        except LeaseLost:
            # Deleted while we worked: leave nothing behind. A superseded lease must not touch the new owner's data.
            if self.repo.file_deleted(job["document_file_id"]):self.discard(job)
            raise
    def discard(self,job):
        try:self.qdrant.delete(job["document_file_id"])
        except Exception:pass
        shutil.rmtree(doclib_dir(self.settings.storage_root,job["csit_job_id"]),ignore_errors=True)
