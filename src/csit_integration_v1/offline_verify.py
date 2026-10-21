"""Deterministic, network-free verification of the installed Integration v1 code."""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

from .callbacks import build_callback_payload
from .errors import IntegrationError
from .models import IngestionRequest

ROOT=Path(__file__).resolve().parents[2]
CONTRACTS=ROOT/"contracts/csit-km-integration-v1"
FIXTURE=ROOT/"fixtures/canonical-ingestion-request.json"


def verify():
    pin=json.loads((CONTRACTS/"UPSTREAM.json").read_text())
    if pin["commit"]!="3a9ae52f04625aeee5fd01e7a3565f5972fc9122":
        raise ValueError("unexpected canonical commit")
    validators={}
    for name,digest in pin["schemas"].items():
        data=(CONTRACTS/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=digest:
            raise ValueError("vendored schema hash mismatch: "+name)
        validators[name]=Draft202012Validator(json.loads(data),format_checker=FormatChecker())
    ingestion=json.loads(FIXTURE.read_text())
    validators["ingestion-request.schema.json"].validate(ingestion)
    model=IngestionRequest.model_validate(ingestion)
    if model.model_dump(mode="json")!=ingestion:
        raise ValueError("ingestion consumer changed canonical JSON values")
    for field in ("eventId","documentId"):
        if not isinstance(getattr(model,field),UUID):
            raise ValueError("consumer did not validate UUID: "+field)
    at=datetime(2026,10,14,6,0,tzinfo=timezone.utc)
    job={"job_id":UUID("da725d21-9574-47e1-8660-76e2c49ce377"),"source_system":"CSIT",
         "document_id":ingestion["documentId"],"version":ingestion["version"],
         "updated_at":at,"completed_at":at,"last_error_at":at}
    status_schemas={"Processing":"callback-processing.schema.json","Completed":"callback-completed.schema.json","Failed":"callback-failed.schema.json"}
    for status,name in status_schemas.items():
        error=IntegrationError("SOURCE_ERROR","Offline fixture error") if status=="Failed" else None
        payload=build_callback_payload(job,status,error)
        validators[name].validate(payload)
    return {"result":"PASS","canonicalCommit":pin["commit"],"callbacks":list(status_schemas)}

if __name__=="__main__":
    if "--require-disabled" in sys.argv and os.environ.get("KM_CSIT_ENABLED","").lower()!="false":
        raise SystemExit("integration is not disabled")
    print(json.dumps(verify(),sort_keys=True))
