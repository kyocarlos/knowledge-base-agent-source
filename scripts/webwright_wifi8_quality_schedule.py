"""Webwright：WiFi 專區「品質檢查排程」時間（匯入工作頁）的使用者流程驗收（不輸出密碼與 session）。

用法：python scripts/webwright_wifi8_quality_schedule.py RUN_DIR ZONE USER PASS_KEY EXPECT
  EXPECT=granted  這個帳號已由 KM Control 管理員授權：可選時間
  EXPECT=locked   這個帳號未授權：時、分下拉與「儲存時間」反灰、說明原因，直接呼叫 API 也被拒絕
環境變數見 webwright_wifi8_common.py。

檢查項目（granted）：panel_visible、time_is_24h（時選項 00～23、分為 5 分鐘一格、沒有 AM/PM）、time_saves（改時間並儲存：
畫面訊息與 API time 正確、重新載入保留）、time_refused_when_bad（直接送 24:00／9:00／12:60 回 422）、restored（還原原本的時間）
檢查項目（locked）：panel_visible、locked_ui（時、分與儲存鈕 disabled 且有未授權說明）、api_refused（POST 回 403、時間不變）
測試會暫時改變 granted 帳號所在資料區的排程時間，最後一定還原（失敗時也會嘗試還原）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webwright_wifi8_common import BASE, Run, login_to_wifi, wifi_page  # noqa: E402

HOUR, MINUTE, SAVE = "#quality-schedule-hour", "#quality-schedule-minute", "#quality-schedule-save"
GET = "() => fetch('/api/wifi8/quality-schedule', {credentials: 'same-origin'}).then(r => r.json())"
POST = ("(t) => fetch('/api/wifi8/quality-schedule', {method: 'POST', credentials: 'same-origin', "
        "headers: {'Content-Type': 'application/json', 'x-km-wifi8-setting': '1'}, body: JSON.stringify({time: t})}).then(r => r.status)")


def open_jobs(pg) -> None:
    pg.goto(BASE + "/wifi8/#/jobs")
    pg.locator(HOUR).wait_for(timeout=15000)
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
        original = before["time"]
        host = pg.locator("#quality-schedule-host")
        try:
            run.act(pg, "panel_visible", f"面板：目前 {original}，API can_change={before['can_change']}",
                    "品質檢查排程" in pg.locator("#page-content").inner_text() and before["can_change"] is (args.expect == "granted"), target=host)
            if args.expect == "locked":
                disabled = pg.locator(HOUR).is_disabled() and pg.locator(MINUTE).is_disabled() and pg.locator(SAVE).is_disabled()
                notice = pg.locator("#quality-schedule-locked").inner_text() if pg.locator("#quality-schedule-locked").count() else ""
                run.act(pg, "locked_ui", f"時／分／儲存 disabled={disabled}，未授權說明={'有' if '尚未獲得' in notice else '沒有'}", disabled and "尚未獲得" in notice, target=host)
                status = pg.evaluate(POST, "10:00")
                run.act(pg, "api_refused", f"直接 POST 的狀態碼={status}，時間 {original}→{pg.evaluate(GET)['time']}", status == 403 and pg.evaluate(GET)["time"] == original)
            else:
                hours = pg.locator(f"{HOUR} option").all_inner_texts()
                minutes = pg.locator(f"{MINUTE} option").all_inner_texts()
                run.act(pg, "time_is_24h", f"時選項 {hours[0]}～{hours[-1]}（{len(hours)} 個），分選項 {len(minutes)} 個",
                        hours == [f"{h:02d}" for h in range(24)] and len(minutes) >= 12 and "PM" not in " ".join(hours), target=host)
                target = "21:30" if original != "21:30" else "22:45"
                pg.select_option(HOUR, target[:2])
                pg.select_option(MINUTE, target[3:])
                pg.locator(SAVE).click()
                pg.locator("#quality-schedule-message", has_text="已儲存").wait_for(timeout=10000)
                saved = pg.evaluate(GET)
                message = pg.locator("#quality-schedule-message").inner_text()
                pg.reload()
                pg.locator(HOUR).wait_for(timeout=15000)
                shown = f"{pg.locator(HOUR).input_value()}:{pg.locator(MINUTE).input_value()}"
                run.act(pg, "time_saves", f"儲存後 API time={saved['time']}、訊息={message!r}；重新載入後顯示 {shown}",
                        saved["time"] == target and target in message and "Telegram" in message and shown == target and saved.get("changed_by"), target=host)
                codes = [pg.evaluate(POST, bad) for bad in ("24:00", "9:00", "12:60")]
                run.act(pg, "time_refused_when_bad", f"24:00／9:00／12:60 的狀態碼 {codes}，時間仍為 {pg.evaluate(GET)['time']}", codes == [422, 422, 422] and pg.evaluate(GET)["time"] == target)
        finally:
            if args.expect == "granted" and pg.evaluate(GET)["time"] != original:
                pg.evaluate(POST, original)
            run.act(pg, "restored", f"結束時間={pg.evaluate(GET)['time']}（原本 {original}）", pg.evaluate(GET)["time"] == original)
    expected = ((403, "POST", "/api/wifi8/quality-schedule"),) if args.expect == "locked" else ((422, "POST", "/api/wifi8/quality-schedule"),) * 3
    return run.finish(expected_failures=expected)


if __name__ == "__main__":
    raise SystemExit(main())
