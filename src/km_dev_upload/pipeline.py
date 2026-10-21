import hashlib,json,shutil
from pathlib import Path
from src.csit_integration_v1.pipeline import Pipeline,Entity,Relation,Extraction
from src.csit_integration_v1.errors import IntegrationError

class LocalUpload:
    def __init__(self,root):self.root=Path(root).resolve()
    def source(self,job):
        ref=job["request_payload"]["uploadReference"]
        path=(self.root/ref).resolve()
        if path.parent!=self.root or not path.is_file():raise IntegrationError("UPLOAD_UNAVAILABLE","Test upload artifact unavailable")
        return path
    def download(self,job,destination):
        source=self.source(job);destination.parent.mkdir(parents=True,exist_ok=True)
        digest=hashlib.sha256()
        with source.open("rb") as incoming,destination.open("wb") as output:
            for chunk in iter(lambda:incoming.read(65536),b""):
                digest.update(chunk);output.write(chunk)
        value=digest.hexdigest()
        if value!=job["request_payload"]["uploadSha256"]:
            raise IntegrationError("SOURCE_VERSION_CHANGED","Test upload integrity check failed")
        return value
    def callback(self,*args):raise RuntimeError("CSIT callback is prohibited for DEV uploads")

class TaggedWriter:
    def __init__(self,writer):self.writer=writer
    def write(self,items,lineage,job):
        p=job["request_payload"]
        return self.writer.write(items,{**lineage,"dataZone":p["dataZone"],"testRunId":p["testRunId"]},job)

class DevPipeline:
    def __init__(self,settings,repo,client,writers,rules):
        self.settings,self.repo,self.client=settings,repo,client
        self.writers={k:TaggedWriter(v) for k,v in writers.items()};self.rules=rules
    def run(self,job):
        p=job["request_payload"]
        def typed_metadata(data):
            extraction=Extraction.model_validate(data)
            refs=[("project",p["project"]),("case",p["case"]),("task",p["task"]),
                  ("document",{"name":job["file_name"]})]
            extraction.entities=[Entity(key=k,kind=k,name=v["name"]) for k,v in refs]
            extraction.relations=[Relation(source="project",target="case",kind="HAS_CASE"),
                Relation(source="case",target="task",kind="HAS_TASK"),Relation(source="task",target="document",kind="HAS_DOCUMENT")]
            # Explicit metadata hierarchy, not inferred report semantics or Agent routing.
            return extraction.model_dump()
        Pipeline(self.settings,self.repo,self.client,self.writers,extractor=typed_metadata,numeric_rules=self.rules).run(job)

DEV_GRAPH_IDENTIFIERS={"CsitKnowledgeEntity":"KmDevKnowledgeEntity","CsitKnowledgeRelation":"KmDevKnowledgeRelation","CSIT_RELATION_SOURCE":"KM_DEV_RELATION_SOURCE","CSIT_RELATION_TARGET":"KM_DEV_RELATION_TARGET"}
DEV_GRAPH_CONSTRAINTS=("km_dev_entity_id_v1","km_dev_relation_id_v1")
