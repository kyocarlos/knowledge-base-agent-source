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

class DocLibClient(CsitIntegrationClient):
    def download_file(self,job,destination):
        """Stream by documentFileId only (the payload downloadUrl is never followed) and verify size and SHA256."""
        s=self.settings
        url=s.csit_base_url.rstrip("/")+DOWNLOAD_PATH.format(id=quote(str(job["document_file_id"]),safe=""))
        destination=Path(destination);temporary=destination.with_suffix(".part")
        expected_size=int(job["file_size_bytes"]);limit=min(s.max_file_size,expected_size) if expected_size else s.max_file_size
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
            if digest!=job["expected_sha256"]:raise IntegrationError("SHA256_MISMATCH","Downloaded content does not match declared sha256")
            temporary.replace(destination)
            return digest
        except IntegrationError:raise
        except httpx.HTTPError:raise IntegrationError("CSIT_NETWORK_ERROR","CSIT download unavailable",True) from None
        finally:temporary.unlink(missing_ok=True)
    def post_status(self,kind,payload):
        path=INGESTION_STATUS_PATH if kind=="ingestion" else DELETION_STATUS_PATH
        try:
            r=self.http.post(self.settings.csit_base_url.rstrip("/")+path,headers=self.auth.headers(),json=payload)
            if r.status_code==409:
                # CSIT may not have persisted the 202 yet; retry rather than treat as final.
                raise IntegrationError("CSIT_CALLBACK_CORRELATION_CONFLICT","CSIT callback correlation not accepted",True)
            if not 200<=r.status_code<300:raise response_error(r.status_code,"callback")
        except httpx.HTTPError:raise IntegrationError("CSIT_CALLBACK_NETWORK_ERROR","CSIT callback unavailable",True) from None
