"""Webwright：WiFi 工作區「文件處理狀態可見」使用者流程驗收（需求第 1 項；不輸出密碼與 session）。

用法：python scripts/webwright_wifi8_item1.py RUN_DIR ZONE USER PASS_KEY
環境變數見 webwright_wifi8_common.py。數量與預期值都從這個資料區的 API 讀取，不寫死。

檢查項目：
  processing_panel   總覽有「資料處理狀態」：排除數量、文字狀態、檢索單位、匯入失敗、metadata 覆蓋率與 API 一致
  version_relation   文件瀏覽以 Revision ID 查到「取代了舊版」的目前版本，詳情顯示 metadata、版本關係與來源段落
  failure_visible    上傳一個損毀的 .zip：畫面立即顯示驗證失敗原因；「匯入與進度」留有失敗紀錄；目前資料版本不變
測試會留下一筆「驗證失敗」工作紀錄；紀錄的 job_id 寫在 summary.json（rejected_jobs），由呼叫端清除。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webwright_wifi8_common import BASE, Run, login_to_wifi, number, wifi_page  # noqa: E402

BROKEN = {"name": "wifi8-acceptance-broken.zip", "mimeType": "application/zip", "buffer": b"not a zip package"}


def api(pg, path: str):
    return pg.evaluate("(p) => fetch(p, {credentials: 'same-origin'}).then(r => r.json())", path)


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    run_dir, zone, user, pass_key = sys.argv[1:5]
    run = Run(run_dir, zone, user)
    rejected: list[str] = []
    with wifi_page(run) as pg:
        login_to_wifi(pg, zone, user, pass_key)
        overview = api(pg, "/api/wifi8/overview")
        counts, processing = overview["counts"], overview["processing"]
        text = pg.locator("#page-content").inner_text()
        wanted = [f"{reason}：{number(n)} 份" for reason, n in (counts.get("excluded") or {}).items()]
        wanted += [f"{number(n)} 份" for _, n in processing["text_status"]]
        wanted += [f"{number(counts['chunks_ready'])} 個可用"]
        wanted += [f"{round(m['present'] / m['total'] * 100)}%" for m in processing["metadata_coverage"] if m["total"]]
        wanted += [f"{number(m['present'])} / {number(m['total'])}" for m in processing["metadata_coverage"]]
        absent = [w for w in wanted if w not in text]
        run.act(pg, "processing_panel", f"{zone} 總覽「資料處理狀態」：{'資料處理狀態' in text}；預期 {len(wanted)} 項，畫面缺 {absent}",
                "資料處理狀態" in text and not absent and processing["failed_jobs"] >= 0)

        target, page = None, 1
        while target is None:  # the first current document that replaced an older version, wherever it sits in the list
            found = api(pg, f"/api/wifi8/documents?page_size=100&page={page}&include_history=false")
            target = next((d for d in found["documents"] if d.get("supersedes")), None)
            if target is None and page * 100 >= found["total"]:
                raise SystemExit("沒有任何取代舊版的目前版本文件，無法驗證版本關係")
            page += 1
        detail = api(pg, f"/api/wifi8/documents/{target['revision_id']}")
        old_ids = set(target["supersedes"])
        old_labels = [v.get("version_label") or v.get("wfa_revision") or v["revision_id"] for v in detail["versions"] if v["revision_id"] in old_ids]
        pg.goto(BASE + "/wifi8/#/documents")
        pg.wait_for_timeout(2500)
        pg.fill('#document-filters input[name="query"]', target["revision_id"])
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(2500)
        pg.locator("#document-results [data-document]").first.click()
        pg.wait_for_timeout(3000)
        body = pg.locator("#document-dialog-body").inner_text()
        has = {"revision": target["revision_id"] in body, "狀態：目前版本": "目前版本" in body, "版本關係": "版本關係" in body,
               "舊版出現在版本關係": bool(old_labels) and all(label in body for label in old_labels), "來源段落": "來源段落" in body and "#1" in body}
        run.act(pg, "version_relation", f"文件 {target['revision_id']} 取代 {sorted(old_ids)}；詳情顯示 {has}", all(has.values()))
        pg.keyboard.press("Escape")

        before = api(pg, "/api/wifi8/status")["current"]["package_id"]
        known = {j["job_id"] for j in api(pg, "/api/wifi8/jobs?limit=100")["jobs"]}  # records that exist before this upload
        pg.goto(BASE + "/wifi8/#/jobs")
        pg.wait_for_timeout(3000)
        pg.locator('#upload-form input[name="file"]').set_input_files(BROKEN)
        pg.locator("#upload-form button").first.click()
        pg.wait_for_function("() => /匯出包驗證失敗/.test(document.querySelector('#upload-status')?.textContent || '')", timeout=30000)
        shown = pg.locator("#upload-status").inner_text()
        pg.reload()
        pg.wait_for_timeout(3000)
        jobs = api(pg, "/api/wifi8/jobs?limit=100")["jobs"]
        rejected = [j["job_id"] for j in jobs if j["job_id"] not in known and "wifi8-acceptance-broken.zip" in (j.get("message") or "")]
        items = pg.locator(".job-item", has_text=rejected[0]) if rejected else pg.locator(".job-item", has_text="(none)")
        listed = items.first.inner_text() if items.count() else ""
        after = api(pg, "/api/wifi8/status")["current"]["package_id"]
        run.act(pg, "failure_visible",
                f"上傳當下訊息={shown[:60]!r}；新增失敗紀錄 {len(rejected)} 筆，畫面清單={'failed' in items.first.inner_html() if items.count() else False}、"
                f"含原因={'匯出包驗證失敗' in listed}；資料版本 {before} → {after}",
                len(rejected) == 1 and items.count() == 1 and "匯出包驗證失敗" in listed and "failed" in items.first.inner_html() and before == after)
    return run.finish(expected_failures=((422, "POST", "/api/wifi8/packages"),), rejected_jobs=rejected, package_id=before)


if __name__ == "__main__":
    raise SystemExit(main())
