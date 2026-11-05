"""Spec v1.4 work loops: v2 ingestion, metadata changes, version replacement and Test Report analysis results."""
import json,logging,re,uuid
from datetime import timezone
from pathlib import Path
from qdrant_client.models import FieldCondition,Filter,MatchValue
from .errors import IntegrationError,LeaseLost
from .doclib_worker import _Heartbeat
from .v2_pipeline import metadata_payload,V2QdrantWriter
from .v2_models import SOURCE_SPECIFIC_DEFAULTS,validate_result_v2

logger=logging.getLogger("km.csit.v2")

class V2Processor:
    def __init__(self,settings,repo,pipeline,qdrant,report_collections=(),client=None):
        self.settings,self.repo,self.pipeline,self.qdrant=settings,repo,pipeline,qdrant
        self.client=client # DocLibClient: the Correlation Resolver call of the analysis-results flow
        self.report_collections=tuple(report_collections)
        self.id=uuid.uuid4().hex
    def steps(self):
        out=[(self.ingest_one,"v2-ingest"),(self.change_one,"v2-change"),(self.supersede_one,"v2-supersede")]
        if self.settings.analysis_results_enabled:out.append((self.analysis_one,"v2-analysis"))
        return out

    def ingest_one(self):
        s=self.settings
        job=self.repo.claim_job(self.id,s.lease_seconds)
        if not job:return False
        try:
            with _Heartbeat(lambda:self.repo.renew_job(job,s.lease_seconds),s.lease_seconds):
                self.pipeline.run(job)
        except LeaseLost:pass
        except Exception as e:
            error=e if isinstance(e,IntegrationError) else IntegrationError("PROCESSING_FAILED","KM processing unavailable",True)
            try:self.repo.fail_job(job,error,s.retry_delays)
            except LeaseLost:pass
        logger.info(json.dumps({"kmJobId":job["km_job_id"],"attempt":job["attempt_count"]}))
        return True

    def supersede_one(self):
        return self.pipeline.reconcile_supersede()

    # -- spec 6.2: index metadata only, no download and no re-extraction --
    def change_one(self):
        s=self.settings
        change=self.repo.claim_change(self.id,s.lease_seconds)
        if not change:return False
        try:
            with _Heartbeat(lambda:self.repo.renew_change(change,s.lease_seconds),s.lease_seconds):
                overrides_for=self.apply_change(change)
            self.repo.finish_change(change,overrides_for)
        except LeaseLost:pass
        except Exception as e:
            error=e if isinstance(e,IntegrationError) else IntegrationError("METADATA_UPDATE_FAILED","Index metadata update unavailable",True)
            try:self.repo.fail_change(change,error,s.retry_delays)
            except LeaseLost:pass
        logger.info(json.dumps({"kmChangeJobId":change["km_change_job_id"],"attempt":change["attempt_count"]}))
        return True
    def apply_change(self,change):
        target=self.repo.change_target(change)
        if not target:raise IntegrationError("TARGET_NOT_INDEXED","The document has no completed index to update")
        kind,row=target
        payload=metadata_payload(change["request_payload"])
        payload["source_revision"]=change["source_revision"]
        try:
            if kind=="v2":
                self.qdrant.apply_metadata(V2QdrantWriter.flt(row["source_entity_id"],row["document_id"],row["version"]),payload)
                return {"event_id":row["event_id"],"overrides":payload}
            if kind=="doclib":
                self.qdrant.apply_metadata(Filter(must=[FieldCondition(key="document_file_id",match=MatchValue(value=str(row["document_file_id"])))]),payload)
            else:
                flt=Filter(must=[FieldCondition(key="document_id",match=MatchValue(value=str(change["document_id"]))),
                                 FieldCondition(key="document_version",match=MatchValue(value=int(change["version"])))])
                for collection in self.report_collections:
                    try:self.qdrant.client.set_payload(collection,payload=payload,points=flt,wait=True)
                    except Exception as exc:
                        if "not found" not in str(exc).lower():raise
        except IntegrationError:raise
        except Exception:raise IntegrationError("STORAGE_UNAVAILABLE","Vector index unavailable",True) from None
        return None

    # -- spec 5.4 + v1.4.1 C.2: full AI result for a Test Report whose v1 status CSIT already acknowledged --
    UUID_RE=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
    def analysis_one(self):
        job=self.repo.next_unreported_report()
        if not job:return False
        try:
            corr=self.client.resolve_report(job["event_id"],job["document_id"],job["version"],str(job["job_id"]))
            self.check_correlation(job,corr)
            built=self.analysis_fields(job,corr)
        except IntegrationError as e:
            if e.retryable:self.repo.retry_analysis(job,e.code,self.settings.callback_retry_delays)
            else:
                logger.warning(json.dumps({"analysisSkipped":e.code,"jobId":str(job["job_id"]),"eventId":str(job["event_id"]),"documentId":str(job["document_id"]),"version":job["version"]}))
                self.repo.skip_analysis(job,e.code)
            return True
        fields,result,analyzed_at=built
        self.repo.queue_analysis(job,fields,result,analyzed_at)
        return True
    def check_correlation(self,job,c):
        """The Resolver answer must repeat what was asked and carry the ids only CSIT knows. A guess or a mismatch is never sent on."""
        bad=lambda why:IntegrationError("CORRELATION_INVALID","CSIT correlation response rejected: "+why)
        if not isinstance(c,dict):raise bad("not an object")
        want={"schemaVersion":"2.0","sourceSystem":"CSIT","sourceType":"TestReport","status":"Completed","eventId":str(job["event_id"]).lower(),
              "documentId":str(job["document_id"]).lower(),"version":job["version"],"kmJobId":str(job["job_id"])}
        for k,v in want.items():
            got=c.get(k)
            if (got.lower() if isinstance(got,str) and k in ("eventId","documentId") else got)!=v:raise bad(k+" differs from the request")
        for k in ("sourceEntityId","csitJobId"):
            if not (isinstance(c.get(k),str) and self.UUID_RE.match(c[k])):raise bad(k+" is not a UUID")
        sha=c.get("sourceSha256")
        if not (isinstance(sha,str) and re.fullmatch(r"[0-9a-f]{64}",sha)):raise bad("sourceSha256 is not 64 lowercase hex")
        if job["content_sha256"] and sha!=job["content_sha256"]:
            raise IntegrationError("SHA256_MISMATCH","The source hash CSIT reports differs from the file KM downloaded")
    def analysis_fields(self,job,corr):
        try:
            refs=job["storage_references"] or {}
            artifact=Path((refs.get("Storage") or {})["artifact"])
            text=json.loads(artifact.read_text(encoding="utf-8"))["extraction"]["text"]
        except Exception:
            raise IntegrationError("NO_EXTRACTION","No readable extraction for this Test Report; nothing to report") from None
        points=(refs.get("Qdrant") or {}).get("pointIds") or []
        suffix=Path(job["file_name"]).suffix.lower()
        done=job["updated_at"].astimezone(timezone.utc)
        result={"metadataSchemaVersion":"2.0",
          "document":{"title":None,"documentType":"TestReport","summary":None,"language":None,"documentDate":None,"authors":[],
            "department":None,"documentVersionLabel":None,"keywords":[],"tags":[]},
          "technical":{k:[] for k in ("productNames","modelNumbers","vendorNames","technologies","standards","softwareVersions",
            "hardwareVersions","projectNames","testItems","measurements","issueKeys","errorCodes")},
          "extraction":{"sourceFormat":suffix.lstrip("."),"method":"Text","pageCount":None,"sheetNames":[],
            "extractedCharacterCount":len(text),"ocrUsed":False},
          "indexing":{"status":"Completed","indexId":"km-test-report/"+str(job["job_id"]),"chunkCount":len(points),
            "indexedAt":done.strftime("%Y-%m-%dT%H:%M:%SZ")},
          "warnings":["semantic extraction not available; fields left empty"],
          "sourceSpecific":dict(SOURCE_SPECIFIC_DEFAULTS["TestReport"])}
        if not points or not text.strip():raise IntegrationError("NO_EXTRACTION","The Test Report was not indexed as text; nothing to report")
        validate_result_v2(result)
        fields={"source_entity_id":corr["sourceEntityId"],"document_id":job["document_id"],"version":job["version"],
                "csit_job_id":corr["csitJobId"],"km_job_id":str(job["job_id"]),"source_sha256":corr["sourceSha256"]}
        return fields,result,done
