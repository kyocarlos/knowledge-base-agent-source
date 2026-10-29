"""Routes CSIT test-report workbooks through the registered report templates (src/report_numeric).

A file whose name matches a registered template is parsed deterministically into a Knowledge Package and written to
km_test (TimescaleDB), Neo4j and Qdrant (ai_km_knowledge_v1). Files with no registered template keep the generic path.
Numbers come only from cell values; nothing is produced by a model.
"""
from pathlib import Path
from .errors import IntegrationError

REPORT_PARSER_VERSION="km-report-numeric-v1"
REPORT_EXTRACTION_VERSION="km-report-package-v1"
# TestReportCommitted means supervisor approval + commit in CSIT, so CSIT is the approval basis.
CSIT_POLICY={"source_system":"CSIT","approval_status":"approved","approval_basis":"csit","publish_status":"published",
    "visibility":"internal","owner_department":"CSIT","access_roles":["CSIT_ENGINEER","CSIT_MANAGER"],"access_departments":["CSIT"]}

class ReportAdapter:
    def __init__(self,connect,graph_driver,qdrant_client,encoder_loader=None):
        self.connect,self.graph_driver,self.qdrant=connect,graph_driver,qdrant_client
        self.encoder_loader=encoder_loader
        self._encoder=None
    def matches(self,job):
        from src.report_numeric.parser import classify_or_none
        return Path(job["file_name"]).suffix.lower()==".xlsx" and classify_or_none(Path(job["file_name"]).name) is not None
    def parse(self,path,job):
        from src.report_numeric.parser import parse_report
        p=job["request_payload"]
        identity={"csit_id":str(p["documentId"]),"source_record_id":str(p["documentId"])+":v"+str(p["version"]),
            "project_id":(p.get("project") or {}).get("number"),"policy":CSIT_POLICY}
        try:return parse_report(path,identity,source_name=Path(job["file_name"]).name)
        except IntegrationError:raise
        except Exception:raise IntegrationError("PARSER_REJECTION","Report template parser rejected workbook") from None
    def write_numeric(self,pkg):
        from src.report_numeric import timescale
        try:
            with self.connect() as conn:
                # Formula-error cells are never stored as numbers; the report is kept and flagged (quality_status).
                return timescale.write_package(conn,pkg,accept_source_errors=True)
        except timescale.ConflictError:
            raise IntegrationError("REPORT_REJECTED","Report rejected by the numeric store validation") from None
    def write_graph(self,pkg):
        from src.report_numeric import graph
        with self.graph_driver.session() as session:return graph.write_graph(session,pkg)
    def write_vectors(self,pkg):
        from src.report_numeric import chunks as chunk_mod,vector
        if self._encoder is None:self._encoder=(self.encoder_loader or vector.load_encoder)()
        model_name,encode,count=self._encoder
        chunks=chunk_mod.build_chunks(pkg,count)
        return {"collection":vector.COLLECTION,"pointCount":vector.write_chunks(self.qdrant,pkg,chunks,encode,vector.doc_sparse,model_name,"v1")}
