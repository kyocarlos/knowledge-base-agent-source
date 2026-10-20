"""WiFi 專區品質驗證的通知（Telegram 或 LINE Messaging API）。

設定檔（預設 ~/.km-control/notify/wifi8-quality.env，可用 KM_WIFI8_NOTIFY_ENV 指定；權限須為 0600，不進 git）：
  KM_NOTIFY_CHANNEL=telegram            # telegram 或 line；兩者都寫則用逗號分隔
  TELEGRAM_BOT_TOKEN=...                # @BotFather 建立的 bot token
  TELEGRAM_CHAT_ID=...                  # 個人或群組 chat_id
  LINE_CHANNEL_ACCESS_TOKEN=...         # LINE Developers > Messaging API channel access token（LINE Notify 已停止服務）
  LINE_TO=...                           # 推送對象的 userId 或 groupId

用法：
  python scripts/wifi8_quality_notify.py --test          # 送一則測試訊息，確認設定可用
  python scripts/wifi8_quality_notify.py --text "..."    # 送自訂訊息（排程失敗時由 wifi8_quality_cron.sh 使用）
wifi8_quality_check.py 在結果為 WARN／FAIL 時會呼叫 notify_report()。
訊息只含狀態、區、層、未通過指標與數值、報告路徑；不含題目、回答或文件內容。token 不會輸出到畫面或紀錄。
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = Path(os.getenv("KM_WIFI8_NOTIFY_ENV", str(Path.home() / ".km-control/notify/wifi8-quality.env")))
LEVEL_NAMES = {"retrieval": "①檢索", "agent": "②Agent", "trust": "③可信度"}
MAX_CHARS = 3500  # Telegram allows 4096, LINE text 5000


def load_settings(path: Path = ENV_FILE) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"通知設定檔不存在：{path}")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError(f"通知設定檔權限必須是 0600：{path}")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _failed_cases(data: dict, names: dict) -> list[str]:
    """Which questions failed, by kind: the question ids are not sensitive, and the kind tells a developer where to look."""
    lines = []
    for kind, ids in (data.get("failure_classes") or {}).items():
        lines.append(f"　{names.get(kind, kind)}：{'、'.join(ids)}")
    if data.get("retried"):
        lines.append(f"　已自動重試（LLM 逾時）：{'、'.join(data['retried'])}" + ("，重試仍失敗" if data.get("retry_failed") else ""))
    return lines


def build_message(report: dict, report_path: str = "", always: bool = False) -> str:
    """WARN/FAIL levels with their failing metrics and questions; with ``always`` (a data change) every level, so a passing
    check of new data is reported too."""
    lines = [f"[KM WiFi 品質驗證] {report.get('status')}", f"時間 {report.get('created_utc')}・程式 {report.get('commit')}"]
    if report.get("changes"):
        lines.append("資料更新：" + "；".join(report["changes"]))
    names = report.get("failure_class_names") or {}
    for zone, levels in (report.get("zones") or {}).items():
        for level, data in levels.items():
            if level.startswith("_"):
                continue
            flagged = data.get("status") in ("WARN", "FAIL")
            if not flagged and not (always and data.get("status")):
                continue
            lines.append(f"{zone.upper()} {LEVEL_NAMES.get(level, level)}：{data['status']}")
            for c in [c for c in data.get("checks") or [] if c.get("status") in ("WARN", "FAIL")]:
                lines.append(f"・{c['metric']}={c.get('value')}（上次 {c.get('previous')}）{c.get('reason') or ''}")
            lines += _failed_cases(data, names)
    if report_path:
        lines.append(f"報告：{report_path}")
    text = "\n".join(lines)
    return text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 20] + "\n…（完整內容見報告）"


def _post(url: str, payload: dict, headers: dict | None = None) -> None:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status >= 300:
            raise RuntimeError(f"HTTP {response.status}")


def send(text: str, settings: dict[str, str]) -> list[str]:
    """Send to every configured channel; returns the channels that succeeded (errors never reveal tokens)."""
    sent, errors = [], []
    for channel in [c.strip().lower() for c in settings.get("KM_NOTIFY_CHANNEL", "").split(",") if c.strip()]:
        try:
            if channel == "telegram":
                _post(f"https://api.telegram.org/bot{settings['TELEGRAM_BOT_TOKEN']}/sendMessage",
                      {"chat_id": settings["TELEGRAM_CHAT_ID"], "text": text, "disable_web_page_preview": True})
            elif channel == "line":
                _post("https://api.line.me/v2/bot/message/push",
                      {"to": settings["LINE_TO"], "messages": [{"type": "text", "text": text}]},
                      {"Authorization": f"Bearer {settings['LINE_CHANNEL_ACCESS_TOKEN']}"})
            else:
                raise ValueError("不支援的通知管道")
            sent.append(channel)
        except KeyError as exc:
            errors.append(f"{channel}: 設定缺少 {exc.args[0]}")
        except urllib.error.HTTPError as exc:
            errors.append(f"{channel}: HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001 - report the type only; messages may contain the URL with the token
            errors.append(f"{channel}: {type(exc).__name__}")
    if errors:
        raise RuntimeError("；".join(errors) + (f"（已送出：{','.join(sent)}）" if sent else ""))
    if not sent:
        raise RuntimeError("KM_NOTIFY_CHANNEL 未設定任何通知管道")
    return sent


def notify_report(report: dict, report_path: str, notify_on: list[str], always: bool = False) -> str:
    """Called by wifi8_quality_check.py; never raises (the check result must still be written). ``always``: notify whatever the
    status is (a data change is worth a message even when everything passes). The daily summary is separate
    (scripts/wifi8_quality_summary.py, sent by the watcher at the time the zone's page asks for)."""
    if not always and report.get("status") not in notify_on:
        return "未達通知條件"
    try:
        return "已通知：" + ",".join(send(build_message(report, report_path, always), load_settings()))
    except Exception as exc:  # noqa: BLE001
        return f"通知失敗：{exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test", action="store_true")
    group.add_argument("--text")
    args = parser.parse_args()
    text = "[KM WiFi 品質驗證] 通知測試：設定可用。" if args.test else args.text
    try:
        print("已送出：" + ",".join(send(text, load_settings())))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"通知失敗：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
