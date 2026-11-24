"""KM DEV self-test (2026-11-20): runs the REAL v2 ingestion pipeline (parser, ImageReader/Tesseract, vision, semantic extraction, embedding, Qdrant write,
result validation) on local test files. Only the CSIT download and the job-table writes are replaced by stand-ins, so no real CSIT job is touched.
Chunks go to a throw-away Qdrant collection that is dropped at the end. Run inside the worker container: python - < this_file."""
import hashlib, json, os, shutil, sys, time, uuid
from pathlib import Path
sys.path.insert(0, "/app")
from src.csit_integration_v1.config import Settings
from src.csit_integration_v1.errors import IntegrationError
from src.csit_integration_v1.v2_pipeline import V2Pipeline, V2QdrantWriter, v2_dir
from src.csit_integration_v1.image_reader import ImageReader
from src.csit_integration_v1.doclib_metadata import make_semantic_extractor
from src.csit_integration_v1.doclib_llm import complete, describe_image
from src.vector_store import VectorStore

COLL = "km_csit_selftest_" + time.strftime("%Y%m%d%H%M%S")
FILES = [("/tmp/selftest_zh.png", "EquipmentAttachment"), ("/tmp/selftest_diagram.png", "EquipmentAttachment"), ("/tmp/selftest_equipment.xlsx", "EquipmentAttachment")]

class FakeRepo:
    def __init__(self): self.phases, self.result, self.cp = [], None, None
    def phase_job(self, job, phase): self.phases.append(phase)
    def set_hash_job(self, job, digest): pass
    def overrides_job(self, job): return {}
    def checkpoint_job(self, job, name, data): self.cp = (name, data)
    def finish_job(self, job, result, artifacts): self.result = result
    def file_deleted_job(self, job): return False

class FakeClient:
    def __init__(self, src): self.src = src
    def download_v2(self, job, path):
        path.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(self.src, path)
        return hashlib.sha256(Path(self.src).read_bytes()).hexdigest()

s = Settings.from_env(); s.validate()
vector = VectorStore()
assert vector.available and vector.client is not None, "Qdrant unavailable"
dim = len(vector.encode(["x"])[0])
from qdrant_client.models import Distance, VectorParams
vector.client.create_collection(COLL, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
writer = V2QdrantWriter(vector.client, COLL, vector.encode, s.chunk_size); writer.ensure_index()
semantic = make_semantic_extractor(complete)
images = ImageReader(vision=describe_image)
print("test collection:", COLL, "| vector dim:", dim, "| tesseract:", images.tesseract, "| langs:", images.langs, "| vision on:", images.vision is not None)
print("LLM:", os.environ.get("KM_CSIT_LLM_MODEL"), os.environ.get("KM_CSIT_LLM_BASE_URL"))

summary = []
eids = []
try:
    for path, source_type in FILES:
        name = Path(path).name
        eid = str(uuid.uuid4()); eids.append(eid)
        job = {"event_id": eid, "source_type": source_type, "source_entity_id": str(uuid.uuid4()), "document_id": str(uuid.uuid4()), "version": 1,
               "csit_job_id": str(uuid.uuid4()), "document_file_id": None, "original_file_name": name, "file_size_bytes": Path(path).stat().st_size,
               "expected_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "request_payload": {"classification": {}, "source": {}}, "lease_token": "selftest"}
        repo = FakeRepo()
        pipe = V2Pipeline(s, repo, FakeClient(path), writer, semantic=semantic, images=images)
        t0 = time.time()
        print("\n=====", name)
        try:
            pipe.run(job)
        except IntegrationError as e:
            print("FAILED:", e.code, "-", e.message); summary.append((name, "FAILED " + e.code)); continue
        r = repo.result
        ex, doc, tech, idx = r["extraction"], r["document"], r["technical"], r["indexing"]
        print("phases:", " > ".join(repo.phases), f"| {time.time()-t0:.1f}s")
        print("extraction:", json.dumps(ex, ensure_ascii=False))
        stored = json.loads((v2_dir(s.storage_root, eid) / "normalized.json").read_text(encoding="utf-8"))["extraction"]["text"]
        print("extracted text (first 420 chars):\n" + stored[:420])
        print("semantic: type=%s | summary=%s" % (doc["documentType"], (doc["summary"] or "")[:160]))
        print("  keywords:", doc["keywords"][:8], "| models:", tech["modelNumbers"], "| vendors:", tech["vendorNames"], "| tech:", tech["technologies"][:6], "| std:", tech["standards"][:6])
        ss = r.get("sourceSpecific") or {}
        if ss.get("specifications"): print("  specifications:", json.dumps(ss["specifications"], ensure_ascii=False)[:300])
        print("  capability:", str(ss.get("capabilitySummary"))[:200], "| limitations:", str(ss.get("limitations"))[:160])
        print("warnings:", r["warnings"])
        print("indexing:", idx)
        # search the throw-away collection for this document to prove the chunks are really there
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        n = vector.client.count(COLL, count_filter=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=job["document_id"]))]), exact=True).count
        print("points found in Qdrant for this document:", n)
        summary.append((name, f"OK method={ex['method']} ocrUsed={ex['ocrUsed']} chars={ex['extractedCharacterCount']} chunks={idx['chunkCount']} qdrantPoints={n}"))
finally:
    vector.client.delete_collection(COLL)
    for e in eids: shutil.rmtree(v2_dir(s.storage_root, e), ignore_errors=True)   # only this test's own work dirs
    print("\nthrow-away collection dropped:", COLL)
print("\n===== SUMMARY")
for n_, r_ in summary: print(f"{n_}: {r_}")
