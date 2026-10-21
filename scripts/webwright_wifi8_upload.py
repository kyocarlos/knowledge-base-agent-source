"""Webwright：從 WiFi 工作區「匯入與進度」頁上傳 Wi-Fi8 匯出包（不輸出密碼與 session）。

用法：python scripts/webwright_wifi8_upload.py RUN_DIR ZONE USER PASS_KEY --package ZIP [--dry-run]
  --dry-run  只驗證到上傳表單可用並選好檔案，不送出（不會建立匯入工作）。

送出時檢查 POST /api/wifi8/packages 回 202、狀態 queued、submitted_by 為登入帳號，
並記錄 job_id 供後續追蹤。帳號需有匯入權限（KM_WIFI8_IMPORT_USERS）。
環境變數見 webwright_wifi8_common.py（KM_BASE_URL、KM_TEST_ACCOUNTS_FILE）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webwright_wifi8_common import BASE, Run, login_to_wifi, wifi_page  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir")
    parser.add_argument("zone")
    parser.add_argument("user")
    parser.add_argument("pass_key")
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.package.is_file():
        parser.error(f"package not found: {args.package}")
    run = Run(args.run_dir, args.zone, args.user)
    posted = {}
    with wifi_page(run) as pg:
        def on_response(response):
            if response.request.method == "POST" and "/api/wifi8/packages" in response.url:
                posted.update(status=response.status, body=response.json())
        pg.on("response", on_response)
        login_to_wifi(pg, args.zone, args.user, args.pass_key)
        run.act(pg, "before", f"{args.zone} 上傳前總覽：{pg.locator('#page-content').inner_text()[:80]!r}", True)

        pg.goto(BASE + "/wifi8/#/jobs")
        pg.wait_for_timeout(3000)
        form = pg.locator("#upload-form")
        run.act(pg, "jobs_page", f"開啟「匯入與進度」，上傳表單可見={form.is_visible()}", form.is_visible())
        pg.locator('#upload-form input[name="file"]').set_input_files(str(args.package))
        chosen = pg.locator('#upload-form input[name="file"]').evaluate("el => el.files.length ? el.files[0].name : ''")
        run.act(pg, "file_selected", f"選擇匯出包：{chosen}", chosen == args.package.name)
        if not args.dry_run:
            pg.locator("#upload-form button").first.click()
            for _ in range(240):
                if posted:
                    break
                pg.wait_for_timeout(500)
            body = posted.get("body") or {}
            run.act(pg, "uploaded",
                    f"POST /api/wifi8/packages → {posted.get('status')} status={body.get('status')} package_id={body.get('package_id')} "
                    f"job_id={body.get('job_id')} submitted_by={body.get('submitted_by')}",
                    posted.get("status") == 202 and body.get("status") == "queued" and body.get("submitted_by") == args.user)
    return run.finish(dry_run=args.dry_run, package=args.package.name, job=(posted.get("body") or {}).get("job_id"))


if __name__ == "__main__":
    raise SystemExit(main())
