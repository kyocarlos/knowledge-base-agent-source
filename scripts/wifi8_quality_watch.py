#!/usr/bin/env python3
"""Watch the WiFi zone's data and run the quality check as soon as new data is served.

A quality check that only runs on a schedule finds a bad import up to a day (retrieval) or a week (agent answers) later. This
script is meant to run every few minutes (cron): it reads, per zone, which package the search worker serves (`current.json`,
switched by the importer's publish step) and, when that changed and stayed the same for `settle_polls` consecutive polls,
runs scripts/wifi8_quality_check.py once for the changed zones with `--trigger package_change`. The report names the data
change, compares with the previous run of the same questions, and is sent even when everything passes.

A change is a new package id or the same package published again (`switched_at`): a re-publish can change what is served too.
The first poll only records what is served. State: <quality root>/package-state.json. Silent unless something happens.

The same run sends the daily summary message of each zone whose page asks for it, at the time chosen there
(scripts/wifi8_quality_summary.py; state in <quality root>/summary-state.json).

A zone whose page switch is off (<zone wifi8 root>/auto-check.json, set on the WiFi zone page) is not polled; after it is
switched on again, a change that happened meanwhile is checked then. Every run also writes auto-check-status.json into each
zone, which the page shows (last poll, what is watched, the last check).

Usage: python3 scripts/wifi8_quality_watch.py [--dry-run]
"""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT = Path(os.getenv("KM_WIFI8_QUALITY_ROOT", str(Path.home() / ".km-control/wifi8-quality")))
CONFIG = REPO / "eval/wifi8/quality-config.json"
STATE = ROOT / "package-state.json"
LOCK = ROOT / "quality.lock"  # the same lock as scripts/wifi8_quality_cron.sh: two checks never run at once
DEFAULT_WATCH = {"settle_polls": 2, "max_attempts": 3, "levels": "retrieval,agent,trust", "interval_minutes": 5}
ZONE_ROOT = 'R="${KM_WIFI8_ROOT:-/app/data/wifi8}"'  # where the zone keeps current.json and the page's switch


def marker(current: dict | None) -> tuple | None:
    return (current.get("package_id"), current.get("switched_at")) if current else None


def decide(zone_state: dict | None, current: dict | None, settle_polls: int = 2) -> tuple[dict, bool]:
    """(new state, run the check?) for one zone. A change must be seen `settle_polls` times in a row, so a package that is still
    being published (or flips back) does not start a check."""
    if current is None:
        return zone_state or {}, False
    state = dict(zone_state or {})
    here = {"package_id": current.get("package_id"), "switched_at": current.get("switched_at")}
    if not state.get("checked"):
        state.update(checked=here, pending=None, attempts=0)  # first poll: remember what is served, check nothing
        return state, False
    if marker(state["checked"]) == marker(here):
        state.update(pending=None, attempts=0)
        return state, False
    pending = state.get("pending")
    polls = pending["polls"] + 1 if pending and marker(pending) == marker(here) else 1
    state["pending"] = {**here, "polls": polls}
    return state, polls >= settle_polls


def read_zone_json(worker: str, name: str) -> dict | None:
    done = subprocess.run(["docker", "exec", worker, "sh", "-c", f'{ZONE_ROOT}; cat "$R/{name}"'], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        return None
    try:
        data = json.loads(done.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def read_current(worker: str) -> dict | None:
    data = read_zone_json(worker, "current.json")
    return {k: data.get(k) for k in ("package_id", "switched_at", "previous_package_id", "job_id")} if data else None


def read_enabled(worker: str) -> bool:
    """The page's switch; no file (or an unreadable one) means on."""
    return (read_zone_json(worker, "auto-check.json") or {}).get("enabled") is not False


def write_status(worker: str, status: dict) -> bool:
    done = subprocess.run(["docker", "exec", "-i", worker, "sh", "-c",
                           f'{ZONE_ROOT}; cat > "$R/.auto-check-status.tmp" && mv "$R/.auto-check-status.tmp" "$R/auto-check-status.json"'],
                          input=json.dumps(status, ensure_ascii=False), capture_output=True, text=True, timeout=60)
    return done.returncode == 0


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=ROOT, delete=False) as tmp:
        json.dump(state, tmp, ensure_ascii=False, indent=1)
    os.replace(tmp.name, STATE)


def say(text: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {text}", flush=True)


def notify_text(text: str) -> None:
    spec = importlib.util.spec_from_file_location("wifi8_quality_notify", REPO / "scripts/wifi8_quality_notify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.send(text, module.load_settings())
    except Exception as exc:  # noqa: BLE001 - the log line is the fallback
        say(f"通知失敗：{exc}")


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def send_summaries(config: dict) -> list[str]:
    """Daily summary messages that are due (time chosen on each zone's page). A problem here must never stop the watching."""
    try:
        summary, notify = _module("wifi8_quality_summary"), _module("wifi8_quality_notify")
        sent = summary.send_due(config, lambda zone: read_zone_json(config["zones"][zone]["search_worker"], "summary-notify.json"),
                                datetime.now(timezone.utc), ROOT / "history.jsonl", ROOT / "summary-state.json", ROOT,
                                lambda text: notify.send(text, notify.load_settings()))
        for zone in sent:
            say(f"{zone}：已送出每日摘要")
        return sent
    except Exception as exc:  # noqa: BLE001
        say(f"每日摘要失敗：{exc}")
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report what would run, change nothing")
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    watch = {**DEFAULT_WATCH, **(config.get("watch") or {})}
    if not args.dry_run:
        send_summaries(config)
    state = load_state()
    triggered, statuses = [], {}
    for zone, settings in config["zones"].items():
        current = read_current(settings["search_worker"])
        if current is None:
            say(f"{zone}：讀不到目前資料包（容器 {settings['search_worker']}），略過")
            continue
        enabled = read_enabled(settings["search_worker"])
        statuses[zone] = {"enabled": enabled, "watching": {"package_id": current.get("package_id"), "switched_at": current.get("switched_at")}}
        if not enabled:
            continue  # switched off on the zone's page
        before = (state.get(zone) or {}).get("checked")
        state[zone], run = decide(state.get(zone), current, watch["settle_polls"])
        if run:
            triggered.append({"zone": zone, "before": before, "after": current})
    if args.dry_run:
        say(f"dry-run：需要檢查的區 {[t['zone'] for t in triggered] or '無'}；已關閉的區 {[z for z, s in statuses.items() if not s['enabled']] or '無'}")
        return 0

    def report_status() -> None:
        """Tell each zone's page the watcher is alive and what it last did."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for zone, status in statuses.items():
            last = (state.get(zone) or {}).get("last_check")
            write_status(config["zones"][zone]["search_worker"],
                         {**status, "last_poll_at": now, "interval_minutes": watch["interval_minutes"], "last_check": last})

    if not triggered:
        save_state(state)
        report_status()
        return 0

    ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            save_state(state)
            report_status()
            say("另一個品質驗證正在執行，資料更新的檢查延到下次輪詢")
            return 0
        zones = ",".join(t["zone"] for t in triggered)
        say(f"資料更新：{zones}，開始檢查")
        done = subprocess.run([sys.executable, str(REPO / "scripts/wifi8_quality_check.py"), "--trigger", "package_change",
                               "--zones", zones, "--levels", watch["levels"], "--changes", json.dumps(triggered, ensure_ascii=False)],
                              capture_output=True, text=True, timeout=7200)
        say(f"檢查結束，結束碼 {done.returncode}")
        try:
            report = json.loads((ROOT / "latest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = {}
        for change in triggered:
            zone_state = state[zone := change["zone"]]
            if done.returncode in (0, 1, 3):  # PASS / FAIL / WARN: the check ran and reported
                zone_state.update(checked={k: change["after"][k] for k in ("package_id", "switched_at")}, pending=None, attempts=0,
                                  last_check={"at": report.get("created_utc"), "status": (report.get("zones", {}).get(zone) or {}).get("_status"),
                                              "package_id": change["after"].get("package_id"), "trigger": "package_change"})
            else:
                zone_state["attempts"] = zone_state.get("attempts", 0) + 1
                if zone_state["attempts"] >= watch["max_attempts"]:
                    zone_state.update(checked={k: change["after"][k] for k in ("package_id", "switched_at")}, pending=None, attempts=0)
                    notify_text(f"[KM WiFi 品質驗證] 資料更新後的自動檢查連續 {watch['max_attempts']} 次無法執行（{zone.upper()}）。"
                                f"請手動執行 scripts/wifi8_quality_check.py；錯誤：{(done.stderr or done.stdout).strip()[-200:]}")
        save_state(state)
    report_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
