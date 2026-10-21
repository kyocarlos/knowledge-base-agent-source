import json

from src.wifi8 import overview


def doc(folder, current=True, series=None):
    return {"classification_path": f"{folder}/x/y.pdf" if folder else "", "analysis_eligible": current, "version_series_id": series}


CATEGORIES = [{"folder": "01_WFA", "label": "WFA", "description": "d1"}, {"folder": "02_Std", "label": "標準與學術機構", "description": "d2"},
              {"folder": "03_Empty", "label": "沒有文件的分類", "description": "d3"}]


def test_the_shipped_categories_are_the_eight_chosen_names_in_the_original_order():
    labels = [c["label"] for c in overview.load_categories()]
    assert labels == ["WFA", "標準與學術機構", "晶片與零組件商", "測試與量測廠商", "網路產品品牌商", "媒體與產業研究機構", "內部資料", "其他來源"]
    folders = [c["folder"] for c in overview.load_categories()]
    assert folders == sorted(folders) and folders[0] == "01_WFA" and folders[-1] == "08_Other-Sources"


def test_every_document_counts_history_included_and_the_current_ones_are_shown_next_to_the_total():
    docs = [doc("01_WFA")] * 6 + [doc("01_WFA", current=False)] * 4 + [doc("02_Std")] * 2
    stats = overview.category_stats(docs, CATEGORIES)
    assert stats["total"] == 12
    wfa, std = stats["rows"]
    assert (wfa["total"], wfa["current"], wfa["history"], wfa["share"]) == (10, 6, 4, 83.3)
    assert (std["total"], std["current"], std["history"], std["share"]) == (2, 2, 0, 16.7)
    assert wfa["label"] == "WFA" and wfa["description"] == "d1"


def test_a_category_without_documents_is_left_out_and_the_shares_add_up_to_the_total_of_the_rows():
    stats = overview.category_stats([doc("01_WFA")] * 3 + [doc("02_Std")], CATEGORIES)
    assert [r["folder"] for r in stats["rows"]] == ["01_WFA", "02_Std"]
    assert sum(r["total"] for r in stats["rows"]) == stats["total"] == 4


def test_a_folder_that_is_not_configured_is_still_shown_and_documents_without_a_path_are_unclassified():
    stats = overview.category_stats([doc("01_WFA"), doc("99_New"), doc("99_New"), doc(None)], CATEGORIES)
    assert [(r["folder"], r["label"], r["total"]) for r in stats["rows"]] == [("01_WFA", "WFA", 1), ("99_New", "99_New", 2), ("未分類", "未分類", 1)]
    assert sum(r["total"] for r in stats["rows"]) == stats["total"] == 4  # nothing is dropped


def test_without_the_categories_file_every_folder_is_shown_under_its_own_name(monkeypatch, tmp_path):
    monkeypatch.setenv("KM_WIFI8_CATEGORIES_FILE", str(tmp_path / "missing.json"))
    assert overview.load_categories() == []
    stats = overview.category_stats([doc("01_WFA"), doc("02_Std")])
    assert {r["label"] for r in stats["rows"]} == {"01_WFA", "02_Std"}
    (tmp_path / "broken.json").write_text("{not json")
    monkeypatch.setenv("KM_WIFI8_CATEGORIES_FILE", str(tmp_path / "broken.json"))
    assert overview.load_categories() == []


def test_the_names_can_be_changed_in_a_file_without_touching_the_code(monkeypatch, tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"categories": [{"folder": "01_WFA", "label": "Wi-Fi Alliance", "description": "x"}]}), encoding="utf-8")
    monkeypatch.setenv("KM_WIFI8_CATEGORIES_FILE", str(path))
    assert overview.category_stats([doc("01_WFA")])["rows"][0]["label"] == "Wi-Fi Alliance"


def test_an_empty_package_has_no_rows_and_no_division_by_zero():
    assert overview.category_stats([], CATEGORIES) == {"total": 0, "rows": []}


def test_only_a_series_with_several_current_documents_is_contested():
    docs = [doc("a", True, "s1"), doc("a", True, "s1"), doc("a", True, "s2"), doc("a", False, "s2"), doc("a", True, None), doc("a", True, None)]
    assert overview.contested_series(docs) == 1


def test_nothing_needs_attention_when_everything_is_in_order():
    assert overview.attention_items([doc("a")], {"chunks_pending": 0}, {"failed_jobs": 0}, None, {"enabled": True, "watcher_overdue": False}) == []


def test_each_problem_is_listed_with_where_to_look():
    docs = [doc("a", True, "s1"), doc("a", True, "s1")]
    items = overview.attention_items(docs, {"chunks_pending": 1200}, {"failed_jobs": 2, "latest_failure": {"error": "壞掉的 zip"}},
                                     {"job_id": "j"}, {"enabled": False})
    titles = {i["title"]: i for i in items}
    assert set(titles) == {"匯入失敗紀錄", "匯入進行中", "檢索單位處理中", "版本關係待確認", "資料更新後自動檢查已關閉"}
    assert "2 筆匯入失敗" in titles["匯入失敗紀錄"]["detail"] and "壞掉的 zip" in titles["匯入失敗紀錄"]["detail"] and titles["匯入失敗紀錄"]["route"] == "jobs"
    assert "1,200" in titles["檢索單位處理中"]["detail"] and titles["版本關係待確認"]["level"] == "warning" and titles["版本關係待確認"]["route"] == "documents"
    assert titles["匯入進行中"]["level"] == "info" and titles["資料更新後自動檢查已關閉"]["level"] == "info"


def test_a_watcher_that_stopped_reporting_is_a_warning_only_while_the_check_is_on():
    on = overview.attention_items([], {}, {}, None, {"enabled": True, "watcher_overdue": True})
    off = overview.attention_items([], {}, {}, None, {"enabled": False, "watcher_overdue": True})
    assert [i["title"] for i in on] == ["自動檢查的監看程式沒有回報"] and on[0]["level"] == "warning"
    assert [i["title"] for i in off] == ["資料更新後自動檢查已關閉"]
