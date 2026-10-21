import copy
import json
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from src.csit_integration_v1.callbacks import build_callback_payload
from src.csit_integration_v1.errors import IntegrationError
from src.csit_integration_v1.models import IngestionRequest

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/csit-km-integration-v1"
FIXTURE = ROOT / "tests/csit_v1/fixtures/canonical-ingestion-request.json"

def validator(name):
    schema=json.loads((CONTRACTS/name).read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())

def test_canonical_ingestion_producer_fixture_schema_and_km_consumer():
    payload=json.loads(FIXTURE.read_text())
    validator("ingestion-request.schema.json").validate(payload)
    request=IngestionRequest.model_validate(payload)
    dumped=request.model_dump(mode="json")
    assert dumped==payload
    for field in ("eventId","documentId","project","case","task"):
        if field in ("eventId","documentId"):
            assert isinstance(getattr(request,field),UUID)
        else:
            assert isinstance(getattr(request,field).id,UUID)
    assert all("number" in payload[key] and "code" not in payload[key] for key in ("project","case","task"))

@pytest.mark.parametrize("status,schema_name",[
    ("Processing","callback-processing.schema.json"),
    ("Completed","callback-completed.schema.json"),
    ("Failed","callback-failed.schema.json"),
])
def test_production_callback_builder_matches_canonical_schema(repo,payload,status,schema_name):
    repo.submit(IngestionRequest.model_validate(payload))
    job=repo.claim("canonical-contract-test",60)
    error=None
    if status=="Completed":
        repo.finish(job,{},"test-parser","test-extraction")
        job=repo.get(job["job_id"])
    elif status=="Failed":
        error=IntegrationError("SOURCE_ERROR","Canonical failure fixture")
        repo.fail(job,error,())
        job=repo.get(job["job_id"])
    callback=build_callback_payload(job,status,error)
    validator(schema_name).validate(callback)
    if status=="Failed":
        assert callback["timestamps"]["failedAt"]==job["last_error_at"].isoformat()

@pytest.mark.parametrize("status,schema_name,required",[
    ("Processing","callback-processing.schema.json","startedAt"),
    ("Completed","callback-completed.schema.json","completedAt"),
    ("Failed","callback-failed.schema.json","failedAt"),
])
def test_required_transition_timestamp_is_enforced(repo,payload,status,schema_name,required):
    repo.submit(IngestionRequest.model_validate(payload));job=repo.claim("negative-contract-test",60)
    error=None
    if status=="Completed":
        repo.finish(job,{},"test-parser","test-extraction");job=repo.get(job["job_id"])
    elif status=="Failed":
        error=IntegrationError("SOURCE_ERROR","Canonical failure fixture")
        repo.fail(job,error,());job=repo.get(job["job_id"])
    invalid=build_callback_payload(job,status,error)
    del invalid["timestamps"][required]
    assert not validator(schema_name).is_valid(invalid)

@pytest.mark.parametrize("field,value",[("code","PROJECT-17"),("code","CASE-42"),("code","TASK-9")])
def test_legacy_code_alias_cannot_replace_wire_number(payload,field,value):
    validator("ingestion-request.schema.json").validate(payload)
    invalid=copy.deepcopy(payload)
    ref={"PROJECT-17":"project","CASE-42":"case","TASK-9":"task"}[value]
    invalid[ref][field]=invalid[ref].pop("number")
    assert not validator("ingestion-request.schema.json").is_valid(invalid)
    with pytest.raises(ValidationError):
        IngestionRequest.model_validate(invalid)

@pytest.mark.parametrize("location",["eventId","documentId","project.id","case.id","task.id"])
def test_invalid_uuid_rejected_by_canonical_schema_and_consumer(payload,location):
    invalid=copy.deepcopy(payload)
    target=invalid
    for part in location.split(".")[:-1]:target=target[part]
    target[location.split(".")[-1]]="not-a-uuid"
    assert not validator("ingestion-request.schema.json").is_valid(invalid)
    with pytest.raises(ValidationError):IngestionRequest.model_validate(invalid)

def test_invalid_required_timestamp_rejected(payload):
    invalid=copy.deepcopy(payload);invalid["committedAt"]="not-a-date-time"
    assert not validator("ingestion-request.schema.json").is_valid(invalid)
    with pytest.raises(ValidationError):IngestionRequest.model_validate(invalid)

@pytest.mark.parametrize("missing",["code","message"])
def test_failed_callback_requires_nonblank_error_fields(repo,payload,missing):
    repo.submit(IngestionRequest.model_validate(payload));job=repo.claim("negative-failed-contract",60)
    error=IntegrationError("SOURCE_ERROR","Canonical failure fixture")
    repo.fail(job,error,());job=repo.get(job["job_id"])
    invalid=build_callback_payload(job,"Failed",error)
    del invalid["error"][missing]
    assert not validator("callback-failed.schema.json").is_valid(invalid)

@pytest.mark.parametrize("ref",["project","case","task"])
def test_nullable_reference_properties_are_required_and_allow_null(payload,ref):
    payload[ref]["number"]=None;payload[ref]["name"]=None
    validator("ingestion-request.schema.json").validate(payload)
    IngestionRequest.model_validate(payload)
    del payload[ref]["number"]
    assert not validator("ingestion-request.schema.json").is_valid(payload)

@pytest.mark.parametrize("size",[0,-1])
def test_document_size_must_be_positive(payload,size):
    payload["document"]["sizeBytes"]=size
    assert not validator("ingestion-request.schema.json").is_valid(payload)
    with pytest.raises(ValidationError):IngestionRequest.model_validate(payload)

@pytest.mark.parametrize("field",["code","message"])
@pytest.mark.parametrize("invalid_value",["","   "])
def test_failed_callback_error_must_be_nonblank(repo,payload,field,invalid_value):
    repo.submit(IngestionRequest.model_validate(payload));job=repo.claim("negative-error-contract",60)
    error=IntegrationError("SOURCE_ERROR","Canonical failure fixture")
    repo.fail(job,error,());job=repo.get(job["job_id"])
    invalid=build_callback_payload(job,"Failed",error)
    invalid["error"][field]=invalid_value
    assert not validator("callback-failed.schema.json").is_valid(invalid)

@pytest.mark.parametrize("field",["code","message"])
@pytest.mark.parametrize("invalid_value",["","   "])
def test_production_builder_rejects_blank_failed_error(repo,payload,field,invalid_value):
    from jsonschema import ValidationError as SchemaValidationError
    repo.submit(IngestionRequest.model_validate(payload));job=repo.claim("builder-error-gate",60)
    error=IntegrationError("SOURCE_ERROR","Canonical failure fixture")
    repo.fail(job,error,());job=repo.get(job["job_id"])
    setattr(error,field,invalid_value)
    with pytest.raises(SchemaValidationError):build_callback_payload(job,"Failed",error)
