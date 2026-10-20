"""Webwright：WiFi 專區「排程摘要通知」開關（匯入工作頁）的使用者流程驗收（不輸出密碼與 session）。

用法：python scripts/webwright_wifi8_summary_notify.py RUN_DIR ZONE USER PASS_KEY EXPECT
  EXPECT=granted  這個帳號已由 KM Control 管理員授權：開關可操作
  EXPECT=locked   這個帳號未授權：開關反灰、說明原因，直接呼叫 API 也被拒絕
環境變數見 webwright_wifi8_common.py。

檢查項目（granted）：panel_visible、time_is_24h（時選項 00～23、分為 5 分鐘一格）、toggle_saves（畫面與 API 都更新、記錄變更者）、toggle_persists、time_saves（改時間並儲存：畫面訊息與 API time 正確、重新載入保留）、time_refused_when_bad（直接送 24:00／9:00 回 422）、restored（含還原原本的時間）
檢查項目（locked）：panel_visible、locked_ui（開關、時、分 disabled 且有未授權說明）、api_refused（POST 回 403、狀態不變）、click_no_effect
測試會暫時改變 granted 帳號所在資料區的開關，最後一定還原（失敗時也會嘗試還原）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webwright_wifi8_common import BASE, Run, login_to_wifi, wifi_page  # noqa: E402

TOGGLE = "#summary-notify-toggle"
GET = "() => fetch('/api/wifi8/summary-notify', {credentials: 'same-origin'}).then(r => r.json())"
POST = ("(enabled) => fetch('/api/wifi8/summary-notify', {method: 'POST', credentials: 'same-origin', "
        "headers: {'Content-Type': 'application/json', 'x-km-wifi8-setting': '1'}, body: JSON.stringify({enabled})}).then(r => r.status)")


def open_jobs(pg) -> None:
    pg.goto(BASE + "/wifi8/#/jobs")
    pg.locator(TOGGLE).wait_for(timeout=15000)
    pg.wait_for_timeout(500)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("run_dir", "zone", "user", "pass_key"):
        parser.add_argument(name)
    parser.add_argument("expect", choices=("granted", "locked"))
    args = parser.parse_args()
    run = Run(args.run_dir, args.zone, args.user)
    with wifi_page(run) as pg:
        login_to_wifi(pg, args.zone, args.user, args.pass_key)
        open_jobs(pg)
        before = pg.evaluate(GET)
        original = before["enabled"]
        original_time = before["time"]
        host = pg.locator("#summary-notify-host")
        try:
            run.act(pg, "panel_visible", f"面板：role={pg.locator(TOGGLE).get_attribute('role')}，狀態={'開' if original else '關'}，API can_change={before['can_change']}",
                    "排程摘要通知" in pg.locator("#page-content").inner_text() and pg.locator(TOGGLE).get_attribute("role") == "switch"
                    and before["can_change"] is (args.expect == "granted"), target=host)
            if args.expect == "locked":
                disabled = pg.locator(TOGGLE).is_disabled() and pg.locator("#summary-notify-hour").is_disabled() and pg.locator("#summary-notify-minute").is_disabled()
                notice = pg.locator("#summary-notify-locked").inner_text() if pg.locator("#summary-notify-locked").count() else ""
                run.act(pg, "locked_ui", f"開關 disabled={disabled}，未授權說明={'有' if '尚未獲得' in notice else '沒有'}", disabled and "尚未獲得" in notice, target=host)
                status = pg.evaluate(POST, not original)
                after = pg.evaluate(GET)
                run.act(pg, "api_refused", f"直接 POST 的狀態碼={status}，開關狀態 {original}→{after['enabled']}", status == 403 and after["enabled"] is original)
                pg.locator(TOGGLE).click(force=True)
                pg.wait_for_timeout(800)
                run.act(pg, "click_no_effect", f"強制點擊後 checked={pg.locator(TOGGLE).is_checked()}（應維持 {original}），API enabled={pg.evaluate(GET)['enabled']}",
                        pg.locator(TOGGLE).is_checked() is original and pg.evaluate(GET)["enabled"] is original, target=host)
            else:
                pg.locator(TOGGLE).click(force=True)
                pg.locator("#summary-notify-message", has_text="排程摘要通知。").wait_for(timeout=10000)
                after = pg.evaluate(GET)
                label = pg.locator("#summary-notify-state").inner_text()
                message = pg.locator("#summary-notify-message").inner_text()
                run.act(pg, "toggle_saves", f"切換後：標籤={label!r}、訊息={message!r}；API enabled={after['enabled']}、變更者={after.get('changed_by')!r}",
                        after["enabled"] is (not original) and label == ("已開啟" if after["enabled"] else "已關閉") and after.get("changed_by")
                        and message == ("已開啟排程摘要通知。" if after["enabled"] else "已關閉排程摘要通知。"), target=host)
                pg.reload()
                pg.locator(TOGGLE).wait_for(timeout=15000)
                run.act(pg, "toggle_persists", f"重新載入後開關={'開' if pg.locator(TOGGLE).is_checked() else '關'}（應為 {'開' if after['enabled'] else '關'}）",
                        pg.locator(TOGGLE).is_checked() is after["enabled"], target=host)
                hours = pg.locator("#summary-notify-hour option").all_inner_texts()
                minutes = pg.locator("#summary-notify-minute option").all_inner_texts()
                run.act(pg, "time_is_24h", f"時選項 {hours[0]}～{hours[-1]}（{len(hours)} 個），分選項 {len(minutes)} 個", hours == [f"{h:02d}" for h in range(24)] and len(minutes) >= 12 and "PM" not in " ".join(hours),
                        target=host)
                pg.select_option("#summary-notify-hour", "21")
                pg.select_option("#summary-notify-minute", "30")
                pg.locator("#summary-notify-save-time").click()
                pg.locator("#summary-notify-message", has_text="已儲存").wait_for(timeout=10000)
                saved = pg.evaluate(GET)
                message = pg.locator("#summary-notify-message").inner_text()
                pg.reload()
                pg.locator(TOGGLE).wait_for(timeout=15000)
                shown = f"{pg.locator('#summary-notify-hour').input_value()}:{pg.locator('#summary-notify-minute').input_value()}"
                run.act(pg, "time_saves", f"儲存後 API time={saved['time']}、訊息={message!r}；重新載入後顯示 {shown}", saved["time"] == "21:30" and "21:30" in message and shown == "21:30", target=host)
                codes = [pg.evaluate("(t) => fetch('/api/wifi8/summary-notify', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'x-km-wifi8-setting': '1'}, body: JSON.stringify({enabled: false, time: t})}).then(r => r.status)", bad)
                         for bad in ("24:00", "9:00", "12:60")]
                run.act(pg, "time_refused_when_bad", f"24:00／9:00／12:60 的狀態碼 {codes}，時間仍為 {pg.evaluate(GET)['time']}", codes == [422, 422, 422] and pg.evaluate(GET)["time"] == "21:30")
        finally:
            if args.expect == "granted" and (pg.evaluate(GET)["enabled"] is not original or pg.evaluate(GET)["time"] != original_time):
                pg.evaluate("([enabled, time]) => fetch('/api/wifi8/summary-notify', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'x-km-wifi8-setting': '1'}, body: JSON.stringify({enabled, time})}).then(r => r.status)", [original, original_time])
            run.act(pg, "restored", f"結束狀態 enabled={pg.evaluate(GET)['enabled']}、time={pg.evaluate(GET)['time']}（原本 {original}、{original_time}）",
                    pg.evaluate(GET)["enabled"] is original and pg.evaluate(GET)["time"] == original_time)
    expected = ((403, "POST", "/api/wifi8/summary-notify"),) if args.expect == "locked" else ((422, "POST", "/api/wifi8/summary-notify"),) * 3
    return run.finish(expected_failures=expected)


if __name__ == "__main__":
    raise SystemExit(main())
