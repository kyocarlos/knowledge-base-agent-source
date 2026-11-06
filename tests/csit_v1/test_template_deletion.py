"""Deleting a Test Report written through a registered report template: the template rows are keyed by the report's own name, not by the CSIT ids."""
import pytest
from src.csit_integration_v1.doclib_deletion import DeletionExecutor
from src.csit_integration_v1.errors import IntegrationError

DOC,VER="90a22f5a-f94d-4a7d-a1a6-ad4cba322607",1
SR=f"{DOC}:v{VER}"
NAME,NVER="SIT-TR-SC-NR-Throughput-X-EV-V10","V10"

class Repo:
    def v1_job_ids(self,d,v):return []
    def doclib_jobs_for_resource(self,job):return []
    def v2_jobs_for_resource(self,job):return []
    def purge_doclib_metadata(self,job):return 0
    def metadata_residue(self,job):return 0

class UndefinedTable(Exception):
    sqlstate="42P01"

class Cursor:
    def __init__(self,rows=(),n=0):self.rows,self.rowcount=list(rows),n
    def fetchall(self):return self.rows
    def fetchone(self):return self.rows[0]

class Timescale:
    def __init__(self):self.runs={"TR:X":(NAME,NVER,SR)};self.packages={"TR:X"}
    def __call__(self):return self
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def execute(self,sql,params=()):
        if "FROM km_test.test_run WHERE source_record_id" in sql and sql.startswith("SELECT test_run_id"):
            return Cursor([(k,v[0],v[1]) for k,v in self.runs.items() if v[2]==params[0]])
        if sql.startswith("SELECT count(*) FROM km_test.test_run WHERE source_record_id"):return Cursor([(sum(1 for v in self.runs.values() if v[2]==params[0]),)])
        if sql.startswith("SELECT count(*) FROM km_test.test_run"):return Cursor([(0,)]) # document_id/version of the CSIT ids: no match, as in production
        if sql.startswith("DELETE FROM km_test.report_package"):self.packages.discard(params[0]);return Cursor(n=1)
        if sql.startswith("DELETE FROM km_test.test_run WHERE test_run_id"):return Cursor(n=1 if self.runs.pop(params[0],None) else 0)
        if sql.startswith("DELETE FROM km_test.test_run"):return Cursor(n=0)
        if "km_csit_numeric_points" in sql:raise UndefinedTable()
        raise AssertionError(sql)

class Qdrant:
    def __init__(self):self.points=6
    def _matches(self,flt):return any(c.key=="source_record_id" and c.match.value==SR for c in flt.must)
    def count(self,collection,count_filter=None,exact=True):
        return type("C",(),{"count":self.points if self._matches(count_filter) else 0})()
    def delete(self,collection,points_selector=None,wait=True):
        if self._matches(points_selector):self.points=0

class Neo4j:
    def __init__(self):self.nodes=5
    def session(self,database=None):return self
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def run(self,q,**p):
        self.last=(q,p);return self
    def single(self):
        q,p=self.last
        return {"n":self.nodes if p["did"]==NAME and p["ver"]==NVER else 0}
    def consume(self):
        if self.last[1]["did"]==NAME:self.nodes=0

def job(source="TestReport"):
    return {"source_type":source,"resource":{"sourceType":source,"documentId":DOC,"version":VER,"sourceEntityId":DOC}}

@pytest.fixture
def stores(tmp_path):
    t,q,n=Timescale(),Qdrant(),Neo4j()
    return t,q,n,DeletionExecutor(Repo(),tmp_path,qdrant=q,doclib_collection="km_csit_docs",report_collections=("knowledge_base","ai_km_knowledge_v1"),
        neo4j_driver=n,neo4j_database="neo4j",timescale_connect=t)

def test_template_rows_are_found_by_the_csit_identity_and_removed(stores):
    t,q,n,ex=stores
    res=ex.run(job())
    assert res["cleanupVerified"] and t.runs=={} and not t.packages and q.points==0 and n.nodes==0
    assert res["cleanup"]["metadata"]=="Deleted" and res["cleanup"]["chunks"]=="Deleted" and res["cleanup"]["graphRelations"]=="Deleted"

def test_a_report_without_template_rows_still_verifies(stores):
    t,q,n,ex=stores
    t.runs.clear();q.points=0;n.nodes=0
    res=ex.run(job())
    assert res["cleanupVerified"] and res["cleanup"]["chunks"]=="NotPresent" and res["cleanup"]["graphRelations"]=="NotPresent"

def test_another_reports_template_rows_are_left_alone(stores):
    t,q,n,ex=stores
    t.runs["TR:OTHER"]=("OTHER","V1","other-doc:v1")
    ex.run(job())
    assert "TR:OTHER" in t.runs

def test_a_leftover_is_never_reported_as_verified(stores):
    t,q,n,ex=stores
    q.delete=lambda *a,**k:None # the vector store silently keeps the points
    with pytest.raises(IntegrationError) as e:ex.run(job())
    assert e.value.code=="CLEANUP_NOT_VERIFIED"
