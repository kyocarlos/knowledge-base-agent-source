"""Zone routing of CSIT documents: the eight KM zones, decided by the CSIT L1 name (Test Reports are always 產品驗證專區)."""
import pytest
from src.csit_integration_v1.doclib_pipeline import DocLibQdrantWriter
from src.csit_integration_v1.v2_pipeline import V2QdrantWriter, metadata_payload
from src.csit_integration_v1.writers import QdrantWriter
from src.csit_integration_v1.zones import ZONES, resolve_zone, zone_payload

NAMES = ["WiFi 知識專區", "行動通訊知識專區", "固網寬頻知識專區", "認證知識專區", "產品驗證專區", "設備儀器專區", "實驗室管理專區", "Confluence / Jira / TestRail 查詢專區"]


def test_there_are_exactly_the_eight_navigation_zones():
    assert [n for _, n in ZONES] == NAMES


@pytest.mark.parametrize("name,zone_id", list(zip(NAMES, ["wifi", "mobile", "broadband", "cert", "verification", "equipment", "lab", "integrations"])))
def test_l1_names_map_to_their_zone(name, zone_id):
    assert resolve_zone("DocumentLibraryFile", name) == (zone_id, name, "classification")


def test_matching_ignores_case_and_spacing():
    assert resolve_zone("DocumentLibraryFile", "  wifi   知識專區 ")[0] == "wifi"


def test_the_names_the_zones_had_before_the_rename_still_land_correctly():
    assert resolve_zone("DocumentLibraryFile", "4G/5G 知識專區")[0] == "mobile"
    assert resolve_zone("DocumentLibraryFile", "認證與法規知識專區")[0] == "cert"


def test_a_test_report_is_always_product_verification_whatever_its_classification():
    assert resolve_zone("TestReport", None) == ("verification", "產品驗證專區", "source_type")
    assert resolve_zone("TestReport", "WiFi 知識專區")[0] == "verification"


def test_sources_without_a_usable_l1_fall_back_to_their_home_zone():
    assert resolve_zone("VendorFile", None)[:2] == ("equipment", "設備儀器專區")
    assert resolve_zone("EquipmentAttachment", "unknown")[2] == "source_default"
    assert resolve_zone("VerificationApplicationAttachment", None)[0] == "verification"


def test_a_library_file_without_a_zone_is_kept_unclassified_not_guessed():
    assert resolve_zone("DocumentLibraryFile", None) == ("unclassified", "待分類", "none")
    assert resolve_zone("DocumentLibraryFile", "Something else")[0] == "unclassified"


def test_classification_wins_over_the_source_default_except_for_test_reports():
    assert resolve_zone("VendorFile", "WiFi 知識專區")[0] == "wifi"


class Client:
    def __init__(self):self.points=[];self.set=[]
    def delete(self,*a,**k):pass
    def upsert(self,collection_name=None,points=None,wait=True):self.points+=points
    def set_payload(self,*a,**k):self.set.append(k)


def embed(texts):
    return [[0.0]*3 for _ in texts]


def test_library_points_carry_the_zone():
    c=Client()
    DocLibQdrantWriter(c,"km_csit_docs",embed,1000).write("hello world",{"document_file_id":"f1","csit_job_id":"j","original_file_name":"a.txt","expected_sha256":"a"*64,
        "request_payload":{"classification":{"l1":{"id":"20","name":"WiFi 知識專區"},"l2":None,"l3":None}}})
    assert {(p.payload["zone_id"],p.payload["topic_zone"],p.payload["zone_basis"]) for p in c.points}=={("wifi","WiFi 知識專區","classification")}


def test_a_library_file_with_no_classification_is_unclassified():
    c=Client()
    DocLibQdrantWriter(c,"km_csit_docs",embed,1000).write("hello world",{"document_file_id":"f1","csit_job_id":"j","original_file_name":"a.txt","expected_sha256":"a"*64,"request_payload":{}})
    assert c.points[0].payload["zone_id"]=="unclassified"


def v2_job(source_type,l1):
    return {"source_type":source_type,"source_entity_id":"e","document_id":"d","version":1,"csit_job_id":"j","event_id":"ev","original_file_name":"a.txt","expected_sha256":"a"*64,
            "request_payload":{"classification":{"l1":{"id":"1","name":l1} if l1 else None,"l2":None,"l3":None},"source":{}}}


@pytest.mark.parametrize("source,l1,zone",[("VendorFile",None,"equipment"),("VendorFile","認證知識專區","cert"),("VerificationApplicationAttachment","產品驗證專區","verification"),
                                           ("EquipmentAttachment","設備儀器專區","equipment"),("TestReport","WiFi 知識專區","verification")])
def test_v2_points_carry_the_zone(source,l1,zone):
    c=Client()
    V2QdrantWriter(c,"km_csit_docs",embed,1000).write("hello world",v2_job(source,l1))
    assert {p.payload["zone_id"] for p in c.points}=={zone}


def test_a_metadata_change_never_moves_a_document_between_zones():
    p=metadata_payload({"sourceType":"DocumentLibraryFile","classification":{"l1":{"id":"40","name":"行動通訊知識專區"},"l2":None,"l3":None},
                        "attributes":{"tags":[],"keywords":[],"displayName":None,"modelNumbers":[],"vendorReference":None}})
    assert "zone_id" not in p and "topic_zone" not in p and p["classification"]["l1"]=="行動通訊知識專區"


def test_v1_test_report_points_are_product_verification():
    c=Client()
    lineage={"sourceSystem":"CSIT","documentId":"d","version":1,"project":{"id":"p","number":"PRJ"}}
    QdrantWriter(c,"knowledge_base",embed,1000).write("report text",lineage,{"file_name":"r.pdf"})
    assert c.points[0].payload["topic_zone"]=="產品驗證專區" and c.points[0].payload["zone_id"]=="verification"


def test_registered_template_reports_and_their_graph_document_are_product_verification():
    from src.report_numeric.vector import payload
    from src.report_numeric.graph import _zone
    pkg={"schema_version":"1.0","document":{"document_id":"D","document_version":"V1","title":"t","report_type":"cellular_handover"},
         "test_run":{"test_run_id":"TR:D","product_id":"P","dut_model":"P"},"policy":{"source_system":"CSIT","approval_status":"approved","approval_basis":"csit","publish_status":"published",
         "visibility":"internal","owner_department":"CSIT","access_roles":[],"access_departments":[]}}
    chunk={"chunk_id":"c","chunk_index":0,"chunk_hash":"h","text":"x","content_type":"measurement_rows"}
    assert payload(pkg,chunk,"m","v1")["topic_zone"]=="產品驗證專區" and _zone("CSIT")=="產品驗證專區"
    pkg["policy"]["source_system"]="ManualUpload"
    assert "topic_zone" not in payload(pkg,chunk,"m","v1") and _zone("ManualUpload") is None


# ---------- the content decides (CSIT does not classify): the LLM names the zone ----------
from src.csit_integration_v1.doclib_metadata import clean_semantic, llm_prompt, zone_fields


def test_a_document_the_llm_recognises_as_a_test_report_is_product_verification_whatever_its_technology_or_source():
    assert resolve_zone("DocumentLibraryFile","WiFi 知識專區","TestReport","wifi")==("verification","產品驗證專區","document_type")
    assert resolve_zone("VendorFile",None,"TestReport","equipment")[0]=="verification"


def test_other_documents_go_to_the_zone_the_llm_named_even_against_the_csit_l1():
    assert resolve_zone("DocumentLibraryFile","WiFi 知識專區","Specification","mobile")==("mobile","行動通訊知識專區","llm")
    assert resolve_zone("VendorFile",None,"Manual","lab")[0]=="lab"


def test_without_a_usable_hint_the_old_rules_apply():
    assert resolve_zone("DocumentLibraryFile","認證知識專區","SOP",None)[2]=="classification"
    assert resolve_zone("VendorFile",None,"SOP","nonsense")[2]=="source_default"
    assert resolve_zone("DocumentLibraryFile",None,"SOP",None)[2]=="none"


def test_clean_semantic_turns_the_llm_zone_into_an_id_and_drops_anything_else():
    assert clean_semantic({"zone":"固網寬頻知識專區"},"t")["zone_hint"]=="broadband"
    assert clean_semantic({"zone":"4G/5G 知識專區"},"t")["zone_hint"]=="mobile"
    assert clean_semantic({"zone":"無法判斷"},"t")["zone_hint"] is None
    assert clean_semantic({"zone":"某個不存在的專區"},"t")["zone_hint"] is None
    assert clean_semantic({"zone":5},"t")["zone_hint"] is None and clean_semantic(None,"t")["zone_hint"] is None


def test_the_prompt_lists_every_zone_and_the_test_report_rule():
    prompt=llm_prompt("內容")
    assert all(name in prompt for _,name in ZONES) and "無法判斷" in prompt and "TestReport" in prompt and "不看檔名" in prompt


def test_zone_fields_combine_the_documents_type_and_the_llms_zone():
    assert zone_fields("DocumentLibraryFile",{"l1":None},{"documentType":"TestReport","zone":"WiFi 知識專區"},"t")["zone_id"]=="verification"
    assert zone_fields("DocumentLibraryFile",{"l1":None},{"documentType":"Manual","zone":"認證知識專區"},"t")=={"zone_id":"cert","topic_zone":"認證知識專區","zone_basis":"llm"}
    assert zone_fields("DocumentLibraryFile",{"l1":None},None,"t")["zone_id"]=="unclassified"


def test_library_points_follow_the_llm_zone_not_the_csit_l1():
    c=Client()
    DocLibQdrantWriter(c,"km_csit_docs",embed,1000).write("hello world",{"document_file_id":"f1","csit_job_id":"j","original_file_name":"a.txt","expected_sha256":"a"*64,
        "request_payload":{"classification":{"l1":{"id":"20","name":"WiFi 知識專區"},"l2":None,"l3":None}}},{"documentType":"Manual","zone":"行動通訊知識專區"})
    assert {(p.payload["zone_id"],p.payload["zone_basis"]) for p in c.points}=={("mobile","llm")}


def test_v2_points_of_a_recognised_test_report_are_product_verification():
    c=Client()
    V2QdrantWriter(c,"km_csit_docs",embed,1000).write("hello world",v2_job("VendorFile",None),None,{"documentType":"TestReport","zone":"設備儀器專區"})
    assert {(p.payload["zone_id"],p.payload["zone_basis"]) for p in c.points}=={("verification","document_type")}


def test_search_names_include_the_names_a_zone_had_before():
    from src.csit_integration_v1.zones import search_names
    assert "4g/5g 知識專區" in search_names("mobile") and search_names("mobile")[0]=="行動通訊知識專區"
    assert "csit雜項專區" in search_names("verification")
