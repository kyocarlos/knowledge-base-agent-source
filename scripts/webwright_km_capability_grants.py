"""Webwright：KM Control 管理頁「能力授權」的使用者流程驗收（需要 Control 管理員帳號，不輸出密碼與 session）。

用法：python scripts/webwright_km_capability_grants.py RUN_DIR ADMIN_USER PASS_KEY TARGET_USER ZONE [--end granted|revoked]
環境變數見 webwright_wifi8_common.py（KM_TEST_ACCOUNTS_FILE 內要有 PASS_KEY）。

流程：以管理員登入 → 開啟 /control-admin.html → 找到 TARGET_USER 那一列
  row_has_button   該列有「授權 <ZONE> …摘要通知開關」按鈕（TARGET_USER 在該區有授權，且清單允許該區）
  grant_shows      按下後顯示「能力 <ZONE>：…」徽章，按鈕變成「撤銷」，API 清單帶出這項授權
  revoke_shows     再按「撤銷」後徽章消失，按鈕回到「授權」
  restored         結束時回到指定狀態：預設還原成測試前的狀態；--end granted／revoked 則停在授權／撤銷（供接著驗證專區開關；失敗時也會嘗試）
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webwright_wifi8_common import BASE, Run, secret  # noqa: E402

CAP_LABEL = "排程摘要通知開關"


def main() -> int:
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("run_dir", "admin", "pass_key", "target", "zone"):
        parser.add_argument(name)
    parser.add_argument("--end", choices=("granted", "revoked"))
    args = parser.parse_args()
    run = Run(args.run_dir, args.zone, args.admin)
    zone = args.zone.upper()
    with sync_playwright() as p:
        browser = p.firefox.launch()
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1500, "height": 1000})
        pg = context.new_page()
        pg.on("console", lambda m: m.type == "error" and run.console_errors.append(m.text[:160]))
        pg.on("response", lambda r: r.status >= 400 and run.failed_requests.append((r.status, r.url.split("?")[0].replace(BASE, ""))))
        try:
            pg.goto(BASE + "/login.html")
            pg.fill('input[name="username"]', args.admin)
            pg.fill('input[name="password"]', secret(args.pass_key))
            pg.click('#credentials button[type="submit"]')
            expect(pg.locator("#instances")).to_be_visible(timeout=15000)
            pg.goto(BASE + "/control-admin.html")
            row = pg.locator("#users tr", has=pg.locator("td", has_text=args.target)).first
            row.wait_for(timeout=15000)

            def grants_text():
                return pg.locator("#users tr", has=pg.locator("td", has_text=args.target)).first.locator("td").nth(2).inner_text()

            def button(prefix):
                return pg.locator("#users tr", has=pg.locator("td", has_text=args.target)).first.locator("button", has_text=f"{prefix} {zone} ").filter(has_text=CAP_LABEL)

            held = original = f"能力 {zone}" in grants_text()
            wanted_end = original if args.end is None else (args.end == "granted")
            try:
                run.act(pg, "row_has_button", f"{args.target} 的列：授權按鈕={button('授權').count()}、撤銷按鈕={button('撤銷').count()}（原本{'已' if held else '未'}授權）",
                        (button("撤銷") if held else button("授權")).count() == 1, target=row)
                if held:
                    button("撤銷").click()
                    pg.wait_for_function("t => !document.body.innerText.includes(t)", arg=f"能力 {zone}", timeout=10000)
                    held = False
                button("授權").click()
                pg.wait_for_function("t => document.body.innerText.includes(t)", arg=f"能力 {zone}", timeout=10000)
                run.act(pg, "grant_shows", f"授權後徽章={'有' if f'能力 {zone}' in grants_text() else '無'}，撤銷按鈕={button('撤銷').count()}，授權按鈕={button('授權').count()}",
                        f"能力 {zone}" in grants_text() and button("撤銷").count() == 1 and button("授權").count() == 0,
                        target=pg.locator("#users tr", has=pg.locator("td", has_text=args.target)).first)
                button("撤銷").click()
                pg.wait_for_function("t => !document.body.innerText.includes(t)", arg=f"能力 {zone}", timeout=10000)
                run.act(pg, "revoke_shows", f"撤銷後徽章={'有' if f'能力 {zone}' in grants_text() else '無'}，授權按鈕={button('授權').count()}",
                        f"能力 {zone}" not in grants_text() and button("授權").count() == 1,
                        target=pg.locator("#users tr", has=pg.locator("td", has_text=args.target)).first)
            finally:
                present = f"能力 {zone}" in grants_text()
                if present != wanted_end:
                    (button("撤銷") if present else button("授權")).click()
                    pg.wait_for_timeout(1500)
                run.act(pg, "restored", f"結束時授權={'有' if f'能力 {zone}' in grants_text() else '無'}（目標{'有' if wanted_end else '無'}）", (f"能力 {zone}" in grants_text()) == wanted_end)
        finally:
            try:
                pg.goto(BASE + "/login.html")
                pg.click("#logout", timeout=5000)
            finally:
                browser.close()
    return run.finish()


if __name__ == "__main__":
    raise SystemExit(main())
