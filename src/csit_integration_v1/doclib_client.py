"""KM -> CSIT calls for spec v1.3: document-library download and the two callback endpoints."""
import hashlib
from pathlib import Path
from urllib.parse import quote
import httpx
from .client import CsitIntegrationClient, response_error
from .errors import IntegrationError

DOWNLOAD_PATH="/api/integrations/km/v1/document-library/files/{id}/content"
INGESTION_STATUS_PATH="/api/integrations/km/v1/document-library/ingestion-status"
DELETION_STATUS_PATH="/api/integrations/km/v1/document-deletion-status"
# Spec v1.4 (section 2): callback endpoints by outbox kind.
STATUS_PATHS={"ingestion":INGESTION_STATUS_PATH,"deletion":DELETION_STATUS_PATH,
    "ingestion2":"/api/integrations/km/v2/document-jobs/status",
    "deletion2":"/api/integrations/km/v2/document-deletions/status",
    "change":"/api/integrations/km/v2/document-metadata-changes/status",
    "analysis":"/api/integrations/km/v2/analysis-results"}
CORRELATION_PATH="/api/integrations/km/v2/test-report-correlations/{event_id}"
# Authorised GET by source type; the payload downloadUrl is never followed.
V2_DOWNLOAD_PATHS={"VerificationApplicationAttachment":"/api/integrations/km/v1/documents/{id}/versions/{version}/content",
    "TestReport":"/api/integrations/km/v1/documents/{id}/versions/{version}/content",
    "VendorFile":"/api/integrations/km/v1/vendor-files/{id}/content",
    "EquipmentAttachment":"/api/integrations/km/v1/equipment-documents/{id}/content",
    "DocumentLibraryFile":"/api/integrations/km/v1/document-library/files/{id}/content"}

class DocLibClient(CsitIntegrationClient):
    def download_file(self,job,destination):
        """Stream by documentFileId only (the payload downloadUrl is never followed) and verify size and SHA256."""
        url=self.settings.csit_base_url.rstrip("/")+DOWNLOAD_PATH.format(id=quote(str(job["document_file_id"]),safe=""))
        return self._stream(url,int(job["file_size_bytes"]),job["expected_sha256"],destination)
    def _stream(self,url,expected_size,expected_sha256,destination):
        s=self.settings
        destination=Path(destination);temporary=destination.with_suffix(".part")
        limit=min(s.max_file_size,expected_size) if expected_size else s.max_file_size
        h=hashlib.sha256();size=0
        try:
            with self.http.stream("GET",url,headers=self.auth.headers()) as r:
                if r.status_code!=200:raise response_error(r.status_code,"download")
                length=r.headers.get("content-length")
                if length is not None and (not length.isdigit() or int(length)>s.max_file_size):
                    raise IntegrationError("FILE_TOO_LARGE","Source exceeds configured size")
                destination.parent.mkdir(parents=True,exist_ok=True)
                with temporary.open("wb") as f:
                    for chunk in r.iter_bytes(65536):
                        size+=len(chunk)
                        if size>limit:raise IntegrationError("FILE_TOO_LARGE","Stream exceeds declared or configured size")
                        h.update(chunk);f.write(chunk)
            if size!=expected_size:raise IntegrationError("SIZE_MISMATCH","Source size differs from declared fileSizeBytes")
            digest=h.hexdigest()
            if digest!=expected_sha256:raise IntegrationError("SHA256_MISMATCH","Downloaded content does not match declared sha256")
            temporary.replace(destination)
            return digest
        except IntegrationError:raise
        except httpx.HTTPError:raise IntegrationError("CSIT_NETWORK_ERROR","CSIT download unavailable",True) from None
        finally:temporary.unlink(missing_ok=True)
    def post_status(self,kind,payload):
        path=STATUS_PATHS[kind]
        headers=self.auth.headers()
        if kind not in ("ingestion","deletion"):headers["Idempotency-Key"]=payload["callbackId"] # spec v1.4 3.1; v1 callbacks stay as they were
        try:
            r=self.http.post(self.settings.csit_base_url.rstrip("/")+path,headers=headers,json=payload)
            if r.status_code==409:
                if kind in ("ingestion","deletion"):
                    # v1: CSIT may not have persisted the 202 yet; retry rather than treat as final.
                    raise IntegrationError("CSIT_CALLBACK_CORRELATION_CONFLICT","CSIT callback correlation not accepted",True)
                # Spec v1.4.1 C.4: an id / hash / version / state conflict is not fixed by sending the same thing again. Only the analysis
                # result may be retried, and only while CSIT says the v1 job is not Completed yet.
                if kind=="analysis" and "job_not_completed" in r.text[:500].lower():
                    raise IntegrationError("CSIT_ANALYSIS_JOB_NOT_COMPLETED","CSIT has not recorded the v1 job as Completed yet",True)
                raise IntegrationError("CSIT_CALLBACK_CONFLICT","CSIT answered 409 (conflict); not retried",False)
            if not 200<=r.status_code<300:raise response_error(r.status_code,"callback")
        except httpx.HTTPError:raise IntegrationError("CSIT_CALLBACK_NETWORK_ERROR","CSIT callback unavailable",True) from None
    def download_v2(self,job,destination):
        path=V2_DOWNLOAD_PATHS[job["source_type"]].format(id=quote(str(job["document_id"]),safe=""),version=int(job["version"]))
        return self._stream(self.settings.csit_base_url.rstrip("/")+path,int(job["file_size_bytes"]),job["expected_sha256"],destination)
    def resolve_report(self,event_id,document_id,version,km_job_id):
        """Spec v1.4.1 C.2: the ids a Test Report v1 notice does not carry. Nothing is guessed when this fails."""
        url=self.settings.csit_base_url.rstrip("/")+CORRELATION_PATH.format(event_id=quote(str(event_id),safe=""))
        try:r=self.http.get(url,params={"documentId":str(document_id),"version":int(version),"kmJobId":km_job_id},headers=self.auth.headers())
        except httpx.HTTPError:raise IntegrationError("CSIT_NETWORK_ERROR","CSIT correlation lookup unavailable",True) from None
        if r.status_code==404:raise IntegrationError("CORRELATION_NOT_FOUND","CSIT has no such Test Report outbox entry")
        if r.status_code==409:raise IntegrationError("CORRELATION_MISMATCH","CSIT does not recognise this event / document / version / job combination")
        if r.status_code==410:raise IntegrationError("DOCUMENT_DELETED","The Test Report is being deleted")
        if r.status_code!=200:raise response_error(r.status_code,"correlation lookup")
        try:body=r.json()
        except ValueError:raise IntegrationError("CORRELATION_INVALID","CSIT correlation response is not JSON") from None
        return body
