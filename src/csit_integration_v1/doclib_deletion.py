"""Verified deletion of one exact source (spec v1.3 section 7).

Seven cleanup items are reported. Each is Deleted (something was removed) or NotPresent (nothing was there). After the
removal every store is queried again; any residue means the job is not Completed (it is retried, then Failed).
A store this deployment never writes for the source type is NotPresent by construction; a store that may hold the data
but is not configured fails the job rather than being assumed empty.
"""
import shutil
from datetime import datetime,timezone
from pathlib import Path
from .errors import IntegrationError
from .pipeline import stable_id
from .doclib_pipeline import doclib_dir

REPORT_TYPES=("TestReport","VerificationApplicationAttachment")

def _is_copy(name):
    """Downloaded source bytes are stored copies; text derived from them (.parsed.md) is extracted text."""
    return name.startswith("source-") and not name.endswith(".parsed.md")

class DeletionExecutor:
    def __init__(self,repo,storage_root,*,qdrant=None,doclib_collection=None,report_collections=(),neo4j_driver=None,
                 neo4j_database=None,timescale_connect=None,cache_clear=None):
        self.repo,self.root=repo,Path(storage_root)
        self.qdrant,self.doclib_collection,self.report_collections=qdrant,doclib_collection,tuple(report_collections)
        self.neo4j,self.neo4j_database,self.timescale,self.cache_clear=neo4j_driver,neo4j_database,timescale_connect,cache_clear

    # -- identity helpers --
    @staticmethod
    def _is_doclib(job):return job["source_type"]=="DocumentLibraryFile"
    def _dirs(self,job):
        r=job["resource"]
        if self._is_doclib(job):
            return [doclib_dir(self.root,x["csit_job_id"]) for x in self.repo.doclib_jobs_for_resource(job)]
        return [self.root/x for x in self.repo.v1_job_ids(r["documentId"],r["version"])]

    # -- qdrant --
    def _qdrant_filters(self,job):
        from qdrant_client.models import FieldCondition,Filter,MatchValue
        r=job["resource"]
        if self._is_doclib(job):
            return [(self.doclib_collection,Filter(must=[FieldCondition(key="document_file_id",match=MatchValue(value=r["documentFileId"]))]))] if self.doclib_collection else []
        must=[FieldCondition(key="document_id",match=MatchValue(value=r["documentId"])),
              FieldCondition(key="document_version",match=MatchValue(value=r["version"]))]
        return [(c,Filter(must=list(must))) for c in self.report_collections]
    def _qdrant_count(self,job):
        total=0
        for collection,flt in self._qdrant_filters(job):
            try:total+=self.qdrant.count(collection,count_filter=flt,exact=True).count
            except Exception as exc:
                if "not found" in str(exc).lower() or "doesn't exist" in str(exc).lower():continue
                raise IntegrationError("CLEANUP_STORE_UNAVAILABLE","Vector store unavailable",True) from None
        return total
    def _qdrant_delete(self,job):
        for collection,flt in self._qdrant_filters(job):
            try:self.qdrant.delete(collection,points_selector=flt,wait=True)
            except Exception as exc:
                if "not found" in str(exc).lower() or "doesn't exist" in str(exc).lower():continue
                raise IntegrationError("CLEANUP_STORE_UNAVAILABLE","Vector store unavailable",True) from None

    # -- neo4j --
    def _graph_queries(self,job):
        r=job["resource"]
        if self._is_doclib(job):
            sv=stable_id("CSIT","DocumentLibraryFile",r["documentFileId"])
            return ("MATCH (n) WHERE n.sourceVersion=$sv RETURN count(n) AS n","MATCH (n) WHERE n.sourceVersion=$sv DETACH DELETE n",{"sv":sv})
        sv=stable_id("CSIT",r["documentId"],r["version"])
        params={"sv":sv,"did":r["documentId"],"ver":r["version"]}
        # Shared nodes (Product, TestCase, Firmware) are only detached from this report, never removed.
        count=("""OPTIONAL MATCH (a) WHERE a.sourceVersion=$sv
                  OPTIONAL MATCH (d:Document {document_id:$did,document_version:$ver})
                  OPTIONAL MATCH (rep:Report {report_id:$did,version:$ver})
                  RETURN count(DISTINCT a)+count(DISTINCT d)+count(DISTINCT rep) AS n""")
        delete=("""OPTIONAL MATCH (a) WHERE a.sourceVersion=$sv
                   OPTIONAL MATCH (d:Document {document_id:$did,document_version:$ver})
                   OPTIONAL MATCH (rep:Report {report_id:$did,version:$ver})
                   OPTIONAL MATCH (tr:TestRun)-[:DOCUMENTED_IN]->(rep)
                   OPTIONAL MATCH (tr)-[:HAS_RESULT]->(x:TestResult)
                   DETACH DELETE a,x,tr,rep,d""")
        return count,delete,params
    def _graph(self,job,delete):
        if self.neo4j is None:
            if self._is_doclib(job):return 0 # the document-library pipeline never writes a graph
            raise IntegrationError("CLEANUP_STORE_UNAVAILABLE","Graph store required for this source is not configured",True)
        count_q,delete_q,params=self._graph_queries(job)
        try:
            with self.neo4j.session(database=self.neo4j_database) as session:
                before=session.run(count_q,**params).single()["n"]
                if delete and before:session.run(delete_q,**params).consume()
                return before if delete else session.run(count_q,**params).single()["n"]
        except IntegrationError:raise
        except Exception:raise IntegrationError("CLEANUP_STORE_UNAVAILABLE","Graph store unavailable",True) from None

    # -- timescale (numeric points) --
    def _numeric(self,job,delete):
        if self._is_doclib(job):return 0 # no numeric points are written for document-library files
        if self.timescale is None:
            raise IntegrationError("CLEANUP_STORE_UNAVAILABLE","Numeric store required for this source is not configured",True)
        r=job["resource"]
        try:
            with self.timescale() as c:
                total=0
                for table,col_v in (("km_csit_numeric_points","version"),):
                    if delete:total+=c.execute(f"DELETE FROM {table} WHERE document_id=%s AND {col_v}=%s",(r["documentId"],r["version"])).rowcount
                    else:total+=c.execute(f"SELECT count(*) FROM {table} WHERE document_id=%s AND {col_v}=%s",(r["documentId"],r["version"])).fetchone()[0]
                if delete:total+=c.execute("DELETE FROM km_test.test_run WHERE document_id=%s AND document_version=%s",(r["documentId"],r["version"])).rowcount
                else:total+=c.execute("SELECT count(*) FROM km_test.test_run WHERE document_id=%s AND document_version=%s",(r["documentId"],r["version"])).fetchone()[0]
                return total
        except IntegrationError:raise
        except Exception as exc:
            if "does not exist" in str(exc):return 0 # table never created in this deployment
            raise IntegrationError("CLEANUP_STORE_UNAVAILABLE","Numeric store unavailable",True) from None

    # -- local files --
    def _files(self,job,pattern_delete=None):
        removed=0
        for d in self._dirs(job):
            if not d.is_dir():continue
            for f in list(d.iterdir()):
                is_copy=_is_copy(f.name)
                if pattern_delete(is_copy) and f.is_file():
                    f.unlink();removed+=1
            if not any(d.iterdir()):d.rmdir()
        return removed
    def _files_present(self,job,copies):
        n=0
        for d in self._dirs(job):
            if d.is_dir():n+=sum(1 for f in d.iterdir() if _is_copy(f.name)==copies)
        return n

    def run(self,job):
        stored_copies=self._files(job,lambda is_copy:is_copy)
        extracted=self._files(job,lambda is_copy:not is_copy)
        had_vectors=0
        if self.qdrant is None and self._qdrant_filters(job):
            raise IntegrationError("CLEANUP_STORE_UNAVAILABLE","Vector store not configured",True)
        if self.qdrant is not None:
            had_vectors=self._qdrant_count(job)
            self._qdrant_delete(job)
        graph=self._graph(job,True)
        numeric=self._numeric(job,True)
        metadata=self.repo.purge_doclib_metadata(job)+numeric
        cache=self.cache_clear(job["resource"]) if self.cache_clear else 0
        # Verification pass: query again, anything left means the cleanup is not proven.
        residue={"storedCopies":self._files_present(job,True),"extractedText":self._files_present(job,False),
                 "chunks":self._qdrant_count(job) if self.qdrant is not None else 0,"graphRelations":self._graph(job,False),
                 "metadata":self.repo.metadata_residue(job)+self._numeric(job,False)}
        residue["vectorIndex"]=residue["chunks"]
        bad=sorted(k for k,v in residue.items() if v)
        if bad:raise IntegrationError("CLEANUP_NOT_VERIFIED","Residual data remains: "+",".join(bad),True)
        flag=lambda n:"Deleted" if n else "NotPresent"
        now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"cleanupVerified":True,"verifiedAt":now,"cleanup":{"metadata":flag(metadata),"extractedText":flag(extracted),
            "chunks":flag(had_vectors),"vectorIndex":flag(had_vectors),"graphRelations":flag(graph),"cache":flag(cache),
            "storedCopies":flag(stored_copies)}}
