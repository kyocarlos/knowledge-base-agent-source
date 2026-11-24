"""Zone documents are embedded without their page-snapshot / image reference lines; what is stored and cited is unchanged.
Runs under pytest and on its own: python tests/csit_v1/test_embedding_text.py"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.csit_integration_v1.embedding_text import embedding_text  # noqa: E402

COVER = ("## PDF 頁面 1\n- 頁面快照引用：asset://pdf/source-64554fd1/pages/page-001.png\n- 內嵌圖片：\n  - 圖片 1：asset://pdf/source-64554fd1/embedded/page-001/image-000.png\n"
         "  - 圖片 2：asset://pdf/source-64554fd1/embedded/page-001/image-001.jpg\n- 頁面文字：\nProduct Brochure Radio Communication Analyzer MT8821C 30 MHz to 3.8 GHz 3.8 GHz to 6.0 GHz (Option)\n"
         "## PDF 頁面 2\n- 頁面快照引用：asset://pdf/source-64554fd1/pages/page-002.png\n- 頁面文字：\nTomorrow's Wireless Test Capability Today")


def test_reference_lines_are_removed_and_the_page_text_stays():
    out = embedding_text(COVER)
    assert "asset://" not in out and "頁面快照引用" not in out and "內嵌圖片" not in out and "圖片 1" not in out
    assert "30 MHz to 3.8 GHz" in out and "3.8 GHz to 6.0 GHz (Option)" in out and "Tomorrow's Wireless Test Capability Today" in out and "## PDF 頁面 1" in out


def test_a_passage_without_references_is_returned_exactly_as_it_is():
    plain = "Frequency accuracy  ≤ 1 × 10-8   (after 30 min warm-up)\n  Temperature: 5 to 40 °C\n\n頁面文字不是標籤開頭的一般句子。"
    assert embedding_text(plain) == plain and embedding_text("") == ""


def test_a_passage_that_is_only_references_still_gets_its_own_text():
    only = "- 頁面快照引用：asset://pdf/x/pages/page-009.png\n- 內嵌圖片：\n  - 圖片 1：asset://pdf/x/embedded/page-009/image-001.png"
    assert embedding_text(only) == only


def test_a_reference_in_the_middle_of_a_line_is_removed():
    out = embedding_text("see the drawing asset://pdf/x/embedded/page-003/image-002.jpg for the connector layout")
    assert "asset://" not in out and "connector layout" in out and "see the drawing" in out


class FakeClient:
    def __init__(self):
        self.points = []

    def delete(self, *a, **k):
        pass

    def upsert(self, collection_name, points, wait=True):
        self.points += list(points)


def _check_writer(make_writer, job):
    seen = []

    def embedder(texts):
        seen.append(list(texts))
        return [[0.0] * 4 for _ in texts]
    client = FakeClient()
    writer = make_writer(client, embedder)
    writer.write(COVER, job, *([] if "source_type" in job else []))
    assert seen and all("asset://" not in t and "頁面快照引用" not in t for t in seen[0]), seen
    stored = "".join(p.payload["content"] for p in client.points)
    assert stored == COVER and "asset://" in stored                  # the passage that is stored and cited is untouched
    assert len(seen[0]) == len(client.points)


def test_the_document_library_writer_embeds_the_cleaned_text_and_stores_the_original():
    from src.csit_integration_v1.doclib_pipeline import DocLibQdrantWriter
    job = {"document_file_id": "11111111-1111-1111-1111-111111111111", "csit_job_id": "j1", "original_file_name": "a.pdf", "expected_sha256": "0" * 64, "request_payload": {}, "source_type": "DocumentLibraryFile"}
    _check_writer(lambda c, e: DocLibQdrantWriter(c, "km_csit_docs", e, 1200), job)


def test_the_v2_writer_embeds_the_cleaned_text_and_stores_the_original():
    from src.csit_integration_v1.v2_pipeline import V2QdrantWriter
    job = {"source_type": "EquipmentAttachment", "source_entity_id": "A1", "document_id": "22222222-2222-2222-2222-222222222222", "version": 1, "csit_job_id": "j2", "event_id": "e2",
           "original_file_name": "b.pdf", "expected_sha256": "1" * 64, "request_payload": {}}
    _check_writer(lambda c, e: V2QdrantWriter(c, "km_csit_docs", e, 1200), job)


if __name__ == "__main__":
    bad = 0
    for name, fn in sorted((k, v) for k, v in dict(globals()).items() if k.startswith("test_")):
        try:
            fn()
            print("PASS", name)
        except Exception:  # noqa: BLE001
            bad += 1
            print("FAIL", name)
            traceback.print_exc()
    print("OVERALL:", "ALL PASS" if not bad else f"{bad} FAILED")
    sys.exit(1 if bad else 0)
