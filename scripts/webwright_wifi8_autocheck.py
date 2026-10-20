"""Webwright：WiFi 工作區「資料更新後自動檢查」開關（匯入工作頁）的使用者流程驗收（不輸出密碼與 session）。

用法：python scripts/webwright_wifi8_autocheck.py RUN_DIR ZONE USER PASS_KEY [EXPECT]
  EXPECT=granted（預設）這個帳號已由 KM Control 管理員授權「自動檢查開關」；EXPECT=locked 未授權：開關反灰、說明原因、直接 POST 回 403
環境變數見 webwright_wifi8_common.py。

檢查項目：
  panel_visible     匯入工作頁有「資料更新後自動檢查」面板，開關是 role=switch，並顯示最近輪詢與目前監看的資料版本
  toggle_saves      點擊開關：畫面狀態改變、顯示「已關閉／已開啟自動檢查」、API 回傳新狀態與變更者
  toggle_persists   重新載入頁面後，開關仍是剛設定的狀態（設定存在這個資料區）
  keyboard          以鍵盤（Tab 聚焦、空白鍵）也能切換
  restored          結束時還原成測試前的狀態
測試會暫時改變這個資料區的開關，最後一定還原（失敗時也會嘗試還原）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webwright_wifi8_common import BASE, Run, login_to_wifi, wifi_page  # noqa: E402


def state(pg) -> bool:
    return pg.locator("#auto-check-toggle").is_checked()


def api_state(pg) -> dict:
    return pg.evaluate("() => fetch('/api/wifi8/auto-check', {credentials: 'same-origin'}).then(r => r.json())")


def open_jobs(pg) -> None:
    pg.goto(BASE + "/wifi8/#/jobs")
    pg.locator("#auto-check-toggle").wait_for(timeout=15000)
    pg.wait_for_timeout(500)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("run_dir", "zone", "user", "pass_key"):
        parser.add_argument(name)
    parser.add_argument("expect", nargs="?", choices=("granted", "locked"), default="granted")
    args = parser.parse_args()
    run = Run(args.run_dir, args.zone, args.user)
    with wifi_page(run) as pg:
        login_to_wifi(pg, args.zone, args.user, args.pass_key)
        open_jobs(pg)
        original = state(pg)
        if args.expect == "locked":
            can = api_state(pg).get("can_change")
            disabled = pg.locator("#auto-check-toggle").is_disabled()
            notice = "尚未獲得" in (pg.locator("#auto-check-locked").inner_text() if pg.locator("#auto-check-locked").count() else "")
            run.act(pg, "locked_ui", f"can_change={can}、開關 disabled={disabled}、未授權說明={'有' if notice else '沒有'}", can is False and disabled and notice, target=pg.locator("#auto-check-host"))
            status = pg.evaluate("(enabled) => fetch('/api/wifi8/auto-check', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'x-km-wifi8-setting': '1'}, body: JSON.stringify({enabled})}).then(r => r.status)", not original)
            run.act(pg, "api_refused", f"直接 POST 狀態碼={status}，開關狀態 {original}→{api_state(pg).get('enabled')}", status == 403 and api_state(pg).get("enabled") is original)
            return run.finish(expected_failures=((403, "POST", "/api/wifi8/auto-check"),))
        try:
            text = pg.locator("#auto-check-host").inner_text()
            role = pg.locator("#auto-check-toggle").get_attribute("role")
            run.act(pg, "panel_visible", f"面板：開關 role={role}，狀態={'開' if original else '關'}；含最近輪詢={('最近輪詢' in text)}、監看版本={('目前監看的資料版本' in text)}",
                    "資料更新後自動檢查" in pg.locator("#page-content").inner_text() and role == "switch" and "最近輪詢" in text and "目前監看的資料版本" in text,
                    target=pg.locator("#auto-check-host"))

            pg.locator("#auto-check-toggle").click(force=True)
            pg.locator("#auto-check-message", has_text="自動檢查。").wait_for(timeout=10000)
            after = state(pg)
            message = pg.locator("#auto-check-message").inner_text()
            label = pg.locator("#auto-check-state").inner_text()
            info = api_state(pg)
            run.act(pg, "toggle_saves", f"切換後：畫面={'開' if after else '關'}、標籤={label!r}、訊息={message!r}；API enabled={info.get('enabled')}、變更者={info.get('changed_by')!r}",
                    after != original and info.get("enabled") is after and label == ("已開啟" if after else "已關閉")
                    and message == ("已開啟自動檢查。" if after else "已關閉自動檢查。") and info.get("changed_by"),
                    target=pg.locator("#auto-check-host"))

            open_jobs(pg)
            pg.reload()
            pg.locator("#auto-check-toggle").wait_for(timeout=15000)
            run.act(pg, "toggle_persists", f"重新載入後開關={'開' if state(pg) else '關'}（應為 {'開' if after else '關'}）", state(pg) is after,
                    target=pg.locator("#auto-check-host"))

            pg.locator("#auto-check-toggle").focus()
            focused = pg.evaluate("document.activeElement && document.activeElement.id")
            pg.keyboard.press("Space")
            pg.locator("#auto-check-message", has_text="自動檢查。").wait_for(timeout=10000)
            back = state(pg)
            run.act(pg, "keyboard", f"聚焦元素={focused!r}，空白鍵後開關={'開' if back else '關'}（應回到 {'開' if original else '關'}）",
                    focused == "auto-check-toggle" and back is original, target=pg.locator("#auto-check-host"))
        finally:
            if api_state(pg).get("enabled") is not original:
                pg.evaluate("(enabled) => fetch('/api/wifi8/auto-check', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'x-km-wifi8-setting': '1'}, body: JSON.stringify({enabled})})", original)
            run.act(pg, "restored", f"結束狀態 enabled={api_state(pg).get('enabled')}（原本 {original}）", api_state(pg).get("enabled") is original)
    return run.finish()


if __name__ == "__main__":
    raise SystemExit(main())
