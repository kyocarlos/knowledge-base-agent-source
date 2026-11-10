"""Zone routing of CSIT documents: the nine KM zones, decided by the CSIT L1 name (Test Reports are always 產品驗證專區)."""
import pytest
from src.csit_integration_v1.doclib_pipeline import DocLibQdrantWriter
from src.csit_integration_v1.v2_pipeline import V2QdrantWriter, metadata_payload
from src.csit_integration_v1.writers import QdrantWriter
from src.csit_integration_v1.zones import ZONES, resolve_zone, zone_by_classification, zone_payload

NAMES = ["WiFi 知識專區", "行動通訊知識專區", "固網寬頻知識專區", "認證知識專區", "產品驗證專區", "設備儀器專區", "實驗室管理專區", "Confluence / Jira / TestRail 查詢專區", "部門與公司文管專區"]


def test_there_are_exactly_the_nine_navigation_zones():
    assert [n for _, n in ZONES] == NAMES


@pytest.mark.parametrize("name,zone_id", list(zip(NAMES, ["wifi", "mobile", "broadband", "cert", "verification", "equipment", "lab", "integrations", "admin"])))
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


@pytest.mark.parametrize("l1,l2,l3,zone", [
    ("產品驗證資料", "RTF7907VW-D223", "測試報告", "verification"), ("外部認證資料", "RTF7907VW-D223", "Wi-Fi", "cert"),
    ("設備儀器管理", "設備資訊", "Candela Wi-Fi7 Testbed_12345678", "equipment"), ("設備儀器管理", "廠商資訊", "Keysight", "equipment"),
    ("實驗室內部管理", "實驗室規劃相關", "實驗室介紹", "lab"), ("實驗室內部管理", "測試環境相關", "環境介紹簡報", "lab"),
    ("實驗室內部管理", "測試環境相關", "環境校驗報告", "equipment"), ("實驗室內部管理", "測試計畫文件", "Wi-Fi", "verification"),
    ("部門文管專區", "Time Report", None, "admin"), ("公司官方文件", "人事行政相關", None, "admin"),
    ("技術相關文件", "Wi-Fi", "Wi-Fi7", "wifi"), ("技術相關文件", "技術名稱：Wi-Fi", None, "wifi"), ("技術相關文件", "Cellular", "5G-NR", "mobile"),
    ("技術相關文件", "Small Cell", None, "mobile"), ("技術相關文件", "PON", None, "broadband"), ("技術相關文件", "Cable", None, "broadband"),
    ("國際組織規範", "Wi-Fi Alliance", "SPEC", "wifi"), ("國際組織規範", "IEEE", "SPEC", "wifi"), ("國際組織規範", "3GPP", "SPEC", "mobile"),
])
def test_the_csit_classification_decides_the_zone_as_the_mapping_table_says(l1, l2, l3, zone):
    assert zone_by_classification(l1, l2, l3) == zone
    assert resolve_zone("DocumentLibraryFile", l1, "Specification", "wifi" if zone != "wifi" else "cert", l2, l3)[::2] == (zone, "classification_table")   # before the LLM


@pytest.mark.parametrize("l1,l2", [("技術相關文件", "研討會講義"), ("國際組織規範", "Broadband Forum"), ("技術相關文件", None), ("未知分類", "Wi-Fi"), (None, None)])
def test_where_the_table_does_not_decide_the_document_waits_unclassified_whatever_the_llm_suggests(l1, l2):
    assert zone_by_classification(l1, l2, None) is None
    assert resolve_zone("DocumentLibraryFile", l1, "Presentation", "mobile", l2, None) == ("unclassified", "待分類", "none")


def test_a_test_report_stays_product_verification_whatever_the_classification_says():
    assert resolve_zone("TestReport", "技術相關文件", None, None, "Wi-Fi")[0] == "verification"
    # a document the LLM calls a test report is not one: only CSIT's Test Report source is
    assert resolve_zone("DocumentLibraryFile", "技術相關文件", "TestReport", None, "Cellular")[::2] == ("mobile", "classification_table")
    assert resolve_zone("DocumentLibraryFile", None, "TestReport", None)[:2] == ("unclassified", "待分類")


def test_zone_fields_use_all_three_classification_levels():
    from src.csit_integration_v1.doclib_metadata import zone_fields
    f = zone_fields("DocumentLibraryFile", {"l1": "技術相關文件", "l2": "PON", "l3": None}, {"documentType": "Manual", "zone": "WiFi 知識專區"}, "t")
    assert (f["zone_id"], f["zone_basis"]) == ("broadband", "classification_table")


def test_a_metadata_change_to_another_classification_moves_the_zone_only_when_the_table_decides():
    from src.csit_integration_v1.v2_pipeline import metadata_payload
    change = {"sourceType": "DocumentLibraryFile", "classification": {"l1": {"id": "1", "name": "外部認證資料"}, "l2": None, "l3": None},
              "attributes": {"tags": [], "keywords": [], "displayName": None, "modelNumbers": [], "vendorReference": None}}
    out = metadata_payload(change)
    assert (out["zone_id"], out["topic_zone"], out["zone_basis"]) == ("cert", "認證知識專區", "classification_table")
    change["classification"] = {"l1": {"id": "1", "name": "技術相關文件"}, "l2": {"id": "2", "name": "研討會講義"}, "l3": None}
    assert "zone_id" not in metadata_payload(change)                       # the zone KM chose from the content stays
    change["sourceType"] = "TestReport"
    change["classification"] = {"l1": {"id": "1", "name": "外部認證資料"}, "l2": None, "l3": None}
    assert "zone_id" not in metadata_payload(change)


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


def test_the_llm_never_sets_the_zone_neither_by_its_zone_nor_by_its_document_type():
    assert resolve_zone("DocumentLibraryFile","WiFi 知識專區","TestReport","mobile")==("wifi","WiFi 知識專區","classification")
    assert resolve_zone("VendorFile",None,"TestReport","verification")[::2]==("equipment","source_default")
    assert resolve_zone("DocumentLibraryFile","WiFi 知識專區","Specification","mobile")[0]=="wifi"       # CSIT's L1 wins over the suggestion
    assert resolve_zone("DocumentLibraryFile",None,"Manual","lab")==("unclassified","待分類","none")        # nothing from CSIT: waits for review


def test_the_rules_that_follow_from_csits_own_data_still_apply():
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


def test_the_prompt_asks_for_the_closest_zone_for_cross_technology_documents_and_a_technology_tag():
    prompt=llm_prompt("內容")
    assert "跨多種技術的文件（例如研討會講義）選內容最接近的專區" in prompt and "technology" in prompt and "測試計畫文件" in prompt
    assert "目前不收文件" in prompt


def test_the_technology_tag_is_kept_only_when_it_is_one_of_the_known_technologies():
    assert clean_semantic({"technology":"Wi-Fi"},"t")["technology"]=="Wi-Fi"
    assert clean_semantic({"technology":"Cellular"},"t")["technology"]=="Cellular"
    assert clean_semantic({"technology":"藍牙"},"t")["technology"] is None and clean_semantic({"technology":5},"t")["technology"] is None
    f=zone_fields("DocumentLibraryFile",{"l1":None},{"documentType":"Other","zone":"產品驗證專區","technology":"PON"},"t")
    assert (f["zone_id"],f["technology_tag"],f["zone_suggestion"])==("unclassified","PON","產品驗證專區")
    assert zone_fields("DocumentLibraryFile",{"l1":None},None,"t")["technology_tag"] is None


def test_a_cpe_document_without_a_zone_from_the_llm_goes_to_mobile():
    assert clean_semantic({"zone":"無法判斷"},"本文件說明 CPE 韌體升級流程")["zone_hint"]=="mobile"
    assert clean_semantic({"documentType":"Manual"},"路由器設定手冊")["zone_hint"]=="mobile"
    assert clean_semantic({"zone":"認證知識專區"},"CPE 認證")["zone_hint"]=="cert"      # the LLM's zone wins; the keywords are only the fallback
    assert clean_semantic({"zone":"無法判斷"},"the specification of a cell")["zone_hint"] is None


def test_zone_fields_keep_the_llm_zone_only_as_a_suggestion():
    f=zone_fields("DocumentLibraryFile",{"l1":None},{"documentType":"TestReport","zone":"WiFi 知識專區"},"t")
    assert (f["zone_id"],f["zone_basis"],f["zone_suggestion"])==("unclassified","none","WiFi 知識專區")
    f=zone_fields("DocumentLibraryFile",{"l1":None},{"documentType":"Manual","zone":"認證知識專區","summary":"摘要","keywords":["t"]},"t")
    assert (f["zone_id"],f["topic_zone"],f["zone_basis"],f["zone_suggestion"],f["document_type"],f["summary"],f["keywords"])==("unclassified","待分類","none","認證知識專區","Manual","摘要",["t"]) and f["indexed_at"].endswith("Z")
    f=zone_fields("DocumentLibraryFile",{"l1":None},None,"t")
    assert f["zone_id"]=="unclassified" and f["zone_suggestion"] is None
    assert zone_fields("DocumentLibraryFile",{"l1":"外部認證資料"},{"zone":"WiFi 知識專區"},"t")["zone_id"]=="cert"


def test_library_points_follow_the_csit_l1_not_the_llm_zone():
    c=Client()
    DocLibQdrantWriter(c,"km_csit_docs",embed,1000).write("hello world",{"document_file_id":"f1","csit_job_id":"j","original_file_name":"a.txt","expected_sha256":"a"*64,
        "request_payload":{"classification":{"l1":{"id":"20","name":"WiFi 知識專區"},"l2":None,"l3":None}}},{"documentType":"Manual","zone":"行動通訊知識專區"})
    assert {(p.payload["zone_id"],p.payload["zone_basis"],p.payload["zone_suggestion"]) for p in c.points}=={("wifi","classification","行動通訊知識專區")}


def test_v2_points_of_a_vendor_file_the_llm_calls_a_test_report_stay_in_the_vendor_home_zone():
    c=Client()
    V2QdrantWriter(c,"km_csit_docs",embed,1000).write("hello world",v2_job("VendorFile",None),None,{"documentType":"TestReport","zone":"產品驗證專區"})
    assert {(p.payload["zone_id"],p.payload["zone_basis"]) for p in c.points}=={("equipment","source_default")}


def test_search_names_include_the_names_a_zone_had_before():
    from src.csit_integration_v1.zones import search_names
    assert "4G/5G 知識專區" in search_names("mobile") and search_names("mobile")[0]=="行動通訊知識專區"
    assert "CSIT雜項專區" in search_names("verification")


def test_points_carry_what_the_zone_pages_show():
    c=Client()
    V2QdrantWriter(c,"km_csit_docs",embed,1000).write("hello world",v2_job("VendorFile",None),None,{"documentType":"Manual","summary":"一份手冊","keywords":["hello"],"zone":"設備儀器專區"})
    p=c.points[0].payload
    assert (p["document_type"],p["summary"],p["keywords"],p["topic_zone"])==("Manual","一份手冊",["hello"],"設備儀器專區") and p["indexed_at"].endswith("Z")


def test_a_v1_test_report_point_has_a_type_and_a_time():
    c=Client()
    QdrantWriter(c,"knowledge_base",embed,1000).write("report text",{"sourceSystem":"CSIT","documentId":"d","version":1,"project":{"id":"p","number":"PRJ"}},{"file_name":"r.pdf"})
    assert c.points[0].payload["document_type"]=="TestReport" and c.points[0].payload["indexed_at"].endswith("Z")


def test_superseding_a_version_records_when():
    calls=[]
    class C2(Client):
        def set_payload(self,*a,**k):calls.append(k.get("payload") or a[1] if len(a)>1 else k.get("payload"))
    w=V2QdrantWriter(C2(),"km_csit_docs",embed,1000,extra_collections=("knowledge_base",))
    w.set_state("d",1,"a"*64,"Superseded")
    assert calls and all(c["index_state"]=="Superseded" and c["superseded_at"].endswith("Z") for c in calls)
    calls.clear();w.set_state("d",1,"a"*64,"Active")
    assert all("superseded_at" not in c for c in calls)
