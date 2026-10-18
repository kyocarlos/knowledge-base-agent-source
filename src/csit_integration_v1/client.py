import hashlib
from pathlib import Path
from urllib.parse import quote
from email.message import Message
from email.utils import collapse_rfc2231_value
import httpx
from .errors import IntegrationError
from .models import safe_filename

def response_error(status,operation):
    if status in (401,403):return IntegrationError("CSIT_AUTH_FORBIDDEN","CSIT service authorization rejected")
    if status==404:return IntegrationError("CSIT_DOCUMENT_NOT_FOUND","Committed source version not found")
    return IntegrationError("CSIT_HTTP_ERROR","CSIT "+operation+" HTTP failure",status==429 or status>=500)

class CsitIntegrationClient:
    def __init__(self, settings, auth_provider, transport=None):
        self.settings=settings
        self.auth=auth_provider
        self.http=httpx.Client(timeout=settings.timeout,verify=True,follow_redirects=False,transport=transport)
    def download(self,job,destination):
        s=self.settings
        path="/api/integrations/km/v1/documents/"+quote(job["document_id"],safe="")+"/versions/"+str(job["version"])+"/content"
        destination=Path(destination)
        temporary=destination.with_suffix(".part")
        h=hashlib.sha256();size=0
        try:
            with self.http.stream("GET",s.csit_base_url.rstrip("/")+path,headers=self.auth.headers()) as r:
                if r.status_code!=200:raise response_error(r.status_code,"download")
                mime=r.headers.get("content-type","").split(";")[0].strip().lower()
                if mime!=job["content_type"].lower():raise IntegrationError("CONTENT_TYPE_MISMATCH","Source MIME type differs from committed metadata")
                message=Message();message["Content-Disposition"]=r.headers.get("content-disposition","")
                filename=message.get_param("filename",header="content-disposition")
                if isinstance(filename,tuple):filename=collapse_rfc2231_value(filename)
                try: filename=safe_filename(str(filename or ""))
                except ValueError:raise IntegrationError("UNSAFE_FILENAME","Source response filename unsafe") from None
                if filename!=job["file_name"]:raise IntegrationError("FILENAME_MISMATCH","Source filename differs from committed metadata")
                length=r.headers.get("content-length")
                if length is not None and (not length.isdigit() or int(length)>s.max_file_size):
                    raise IntegrationError("FILE_TOO_LARGE","Source exceeds configured size")
                destination.parent.mkdir(parents=True,exist_ok=True)
                with temporary.open("wb") as f:
                    for chunk in r.iter_bytes(65536):
                        size+=len(chunk)
                        if size>s.max_file_size or size>job["size_bytes"]:
                            raise IntegrationError("FILE_TOO_LARGE","Stream exceeds configured or committed size")
                        h.update(chunk);f.write(chunk)
            if size!=job["size_bytes"]:raise IntegrationError("SIZE_MISMATCH","Source size differs from committed metadata")
            temporary.replace(destination)
            return h.hexdigest()
        except IntegrationError:raise
        except httpx.HTTPError:raise IntegrationError("CSIT_NETWORK_ERROR","CSIT download unavailable",True) from None
        finally:
            temporary.unlink(missing_ok=True)
    def callback(self,payload):
        try:
            r=self.http.post(self.settings.csit_base_url.rstrip("/")+"/api/integrations/km/v1/ingestion-status",
                headers=self.auth.headers(),json=payload)
            if r.status_code==409:
                # CSIT may still be persisting the 202 jobId when the first callback arrives.
                raise IntegrationError("CSIT_CALLBACK_CORRELATION_CONFLICT","CSIT callback correlation not accepted",True)
            if not 200<=r.status_code<300:raise response_error(r.status_code,"callback")
        except httpx.HTTPError:raise IntegrationError("CSIT_CALLBACK_NETWORK_ERROR","CSIT callback unavailable",True) from None
    def close(self):self.http.close()
