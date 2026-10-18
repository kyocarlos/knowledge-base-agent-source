import json,uuid,re
from pathlib import Path
from psycopg.types.json import Jsonb
from .pipeline import stable_id, PARSER_VERSION, EXTRACTION_VERSION
from .errors import IntegrationError

class StorageWriter:
    def __init__(self,root):self.root=Path(root)
    def write(self,extraction,lineage,job):
        directory=self.root/str(job["job_id"])
        directory.mkdir(parents=True,exist_ok=True)
        output=directory/"normalized.json"
        temporary=directory/("normalized-"+uuid.uuid4().hex+".tmp")
        data={"lineage":lineage,"parserVersion":PARSER_VERSION,"extractionVersion":EXTRACTION_VERSION,
            "extraction":extraction.model_dump(mode="json")}
        try:
            temporary.write_text(json.dumps(data,ensure_ascii=False,sort_keys=True),encoding="utf-8")
            temporary.replace(output)
        finally:temporary.unlink(missing_ok=True)
        return {"artifact":str(output),"sourceVersion":stable_id(lineage),"parserVersion":PARSER_VERSION,"extractionVersion":EXTRACTION_VERSION}

class QdrantWriter:
    def __init__(self,client,collection,embedder,chunk_size):
        self.client,self.collection,self.embedder,self.chunk_size=client,collection,embedder,chunk_size
    def write(self,text,lineage,job):
        from qdrant_client.models import PointStruct
        chunks=[text[i:i+self.chunk_size] for i in range(0,len(text),self.chunk_size) if text[i:i+self.chunk_size].strip()]
        vectors=self.embedder(chunks)
        if len(vectors)!=len(chunks):raise IntegrationError("EMBEDDING_INVALID","Embedding result shape invalid")
        points=[PointStruct(id=stable_id(lineage["sourceSystem"],lineage["documentId"],lineage["version"],"chunk",i),
            vector=v,payload={"content":t,"lineage":lineage,"metadata":lineage,
                "doc_name":job["file_name"],"source_name":job["file_name"],
                "source_ext":Path(job["file_name"]).suffix.lower(),
                "project_id":lineage["project"]["id"],"project_code":lineage["project"]["number"],"document_id":lineage["documentId"],"document_version":lineage["version"],
                "source_system":lineage["sourceSystem"],"chunk_index":i}) for i,(t,v) in enumerate(zip(chunks,vectors))]
        self.client.upsert(collection_name=self.collection,points=points,wait=True)
        return {"collection":self.collection,"pointIds":[str(p.id) for p in points]}

class Neo4jWriter:
    def __init__(self,driver,database,identifiers=None,required_constraints=None):
        self.driver,self.database=driver,database
        self.identifiers=identifiers or {}
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*",v) for v in self.identifiers.values()):raise ValueError("Unsafe graph schema identifier")
        self.required_constraints=set(required_constraints or ("csit_entity_id_v1","csit_relation_id_v1"))
    def query(self,text):
        for original,replacement in self.identifiers.items():text=text.replace(original,replacement)
        return text
    def write(self,items,lineage,job):
        entities,relations=items
        source=stable_id(lineage["sourceSystem"],lineage["documentId"],lineage["version"])
        ids={e.key:stable_id(source,"entity",e.key) for e in entities}
        encoded=json.dumps(lineage,ensure_ascii=False,sort_keys=True)
        def write(tx):
            # Unique node/relation-identity-node constraints are provisioned by explicit management migration.
            for e in entities:
                tx.run(self.query("""MERGE (e:CsitKnowledgeEntity {id:$id})
                 SET e.kind=$kind,e.name=$name,e.sourceVersion=$source,e.lineage=$lineage"""),
                 id=ids[e.key],kind=e.kind,name=e.name,source=source,lineage=encoded).consume()
            for r in relations:
                key=stable_id(source,"relation",r.source,r.kind,r.target)
                tx.run(self.query("""MATCH (a:CsitKnowledgeEntity {id:$a}),(b:CsitKnowledgeEntity {id:$b})
                 MERGE (r:CsitKnowledgeRelation {id:$id}) SET r.kind=$kind,r.sourceVersion=$source,r.lineage=$lineage
                 MERGE (a)-[:CSIT_RELATION_SOURCE]->(r) MERGE (r)-[:CSIT_RELATION_TARGET]->(b)"""),
                 a=ids[r.source],b=ids[r.target],id=key,kind=r.kind,source=source,lineage=encoded).consume()
        with self.driver.session(database=self.database) as session:
            constraints=list(session.run("SHOW CONSTRAINTS YIELD name RETURN name"))
            names={r["name"] for r in constraints}
            if not self.required_constraints.issubset(names):
                raise IntegrationError("GRAPH_SCHEMA_MISSING","Graph uniqueness migration required")
            session.execute_write(write)
        return {"entityIds":list(ids.values()),"relationCount":len(relations)}

class TimescaleWriter:
    def __init__(self,connect):self.connect=connect
    def write(self,metrics,lineage,job):
        ids=[]
        with self.connect() as c:
            for m in metrics:
                key=stable_id(lineage["sourceSystem"],lineage["documentId"],lineage["version"],m.key,m.metric)
                c.execute("""INSERT INTO km_csit_numeric_points(point_id,source_system,document_id,version,
                    observed_at,metric,value,unit,lineage) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(observed_at,point_id) DO UPDATE SET
                    value=excluded.value,unit=excluded.unit,lineage=excluded.lineage""",
                    (key,lineage["sourceSystem"],lineage["documentId"],lineage["version"],m.timestamp,m.metric,m.value,m.unit,Jsonb(lineage)))
                ids.append(key)
        return {"pointIds":ids,"table":"km_csit_numeric_points"}
