"""WiFi 專區自動品質驗證：檢索找文件的能力／Agent 整體答得準不準／每則回答可不可信。

用法：python scripts/wifi8_quality_check.py [--zones test,da40] [--levels retrieval,agent,trust]
  retrieval  題庫只評檢索（不呼叫 LLM）：命中@10、MRR、檢索耗時
  agent      題庫完整問答（呼叫 LLM，每區約 34～100 次）：回答通過、事實覆蓋、引用標準來源、耗時、錯誤數
  trust      彙總 search worker 在最近 trust_window_hours 內寫下的 WIFI8_ANSWER_QUALITY 紀錄
             （真實回答的依據檢核：數值找不到比例、沒有依據的句子比例、檢核錯誤、未完成回答、延遲）

設定：eval/wifi8/quality-config.json（各區 worker 容器、門檻、退步容許值）。
輸出：$KM_WIFI8_QUALITY_ROOT（預設 ~/.km-control/wifi8-quality）/<時間>/report.md、report.json 與各層原始結果；
     並更新 latest.md、latest.json，在 history.jsonl 追加一行，供下次比較是否退步。
結束碼：0＝PASS（或資料不足）、3＝WARN、1＝FAIL、2＝參數或執行錯誤。
題庫評測時設定 KM_WIFI8_QUALITY_LOG=0，評測的回答不會混進「真實回答」的統計。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Load src/wifi8/quality.py by path: importing the src package pulls in the KM runtime dependencies,
# which the host (where this runs, next to docker) does not have. quality.py only needs the stdlib.
_spec = importlib.util.spec_from_file_location("wifi8_quality", REPO / "src/wifi8/quality.py")
_quality = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_quality)
agent_metrics, judge, overall_status = _quality.agent_metrics, _quality.judge, _quality.overall_status
parse_quality_lines, retrieval_metrics, summarize_trust = _quality.parse_quality_lines, _quality.retrieval_metrics, _quality.summarize_trust
_spec = importlib.util.spec_from_file_location("wifi8_quality_notify", REPO / "scripts/wifi8_quality_notify.py")
_notify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_notify)

ROOT = Path(os.getenv("KM_WIFI8_QUALITY_ROOT", str(Path.home() / ".km-control/wifi8-quality")))
CONFIG = REPO / "eval/wifi8/quality-config.json"
EVAL_FILES = ["scripts/eval_wifi8_agent.py", "src/wifi8/evaluation.py", "eval/wifi8/golden-set.v1.jsonl"]
LEVELS = ("retrieval", "agent", "trust")
LEVEL_NAMES = {"retrieval": "① 檢索找文件的能力", "agent": "② Agent 整體答得準不準", "trust": "③ 每則回答可不可信"}
EXIT = {"PASS": 0, "WARN": 3, "FAIL": 1}


def sh(*args: str, timeout: int = 3600) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout).stdout


def previous_metrics(zone: str, level: str) -> dict | None:
    history = ROOT / "history.jsonl"
    if not history.is_file():
        return None
    for line in reversed(history.read_text(encoding="utf-8").splitlines()):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("zone") == zone and row.get("level") == level and row.get("status") != "INSUFFICIENT":
            return row.get("metrics")
    return None


def run_golden(worker: str, run_id: str, level: str, out: Path, commit: str) -> dict:
    """Golden-set evaluation inside the zone's search worker; results copied to `out`."""
    remote = f"/tmp/km-quality/{run_id}"
    sh("docker", "exec", worker, "mkdir", "-p", remote)
    for f in EVAL_FILES:
        sh("docker", "cp", str(REPO / f), f"{worker}:{remote}/")
    args = ["docker", "exec", "-w", "/app", "-e", "KM_WIFI8_QUALITY_LOG=0", worker, "python", f"{remote}/eval_wifi8_agent.py",
            "--cases", f"{remote}/golden-set.v1.jsonl", "--out", f"{remote}/{level}", "--source-commit", commit]
    if level == "retrieval":
        args.append("--retrieval-only")
    subprocess.run(args, check=True, capture_output=True, text=True, timeout=7200)
    sh("docker", "cp", f"{worker}:{remote}/{level}", str(out / level))
    sh("docker", "exec", worker, "python", "-c", f"import shutil; shutil.rmtree({remote!r}, ignore_errors=True)")
    return json.loads((out / level / "results.json").read_text(encoding="utf-8"))


def trust_level(worker: str, hours: float, out: Path) -> tuple[dict, list[dict]]:
    logs = subprocess.run(["docker", "logs", "--since", f"{hours}h", worker], capture_output=True, text=True, timeout=600)
    records = parse_quality_lines((logs.stdout + logs.stderr).splitlines())
    (out / "trust").mkdir(parents=True, exist_ok=True)
    (out / "trust" / "records.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return summarize_trust(records), records


RATE_SUFFIXES = ("hit_at_10", "answer_pass", "fact_coverage", "cited_gold", "_rate", "_share")


def fmt(value, metric: str = "") -> str:
    """Rates as percentages, scores such as MRR as decimals, counts and milliseconds as integers."""
    if value is None:
        return "—"
    if metric.endswith(RATE_SUFFIXES):
        return f"{value * 100:.1f}%"
    if isinstance(value, float):
        return f"{value:.3f}" if value < 10 else f"{value:,.0f}"
    return f"{value:,}" if isinstance(value, int) else str(value)


def render(report: dict) -> str:
    lines = [f"# WiFi 專區品質驗證報告", "", f"- 時間：{report['created_utc']}；程式版本：`{report['commit']}`；總結：**{report['status']}**", ""]
    for zone, levels in report["zones"].items():
        lines += [f"## {zone.upper()}（{levels.get('_status', '')}）", ""]
        for level in LEVELS:
            if level not in levels:
                continue
            data = levels[level]
            extra = f"；匯入版本 `{data.get('package_id')}`" if data.get("package_id") else ""
            if level == "trust":
                extra += f"；最近 {report['trust_window_hours']} 小時 {data['metrics'].get('answers', 0)} 則回答"
            lines += [f"### {LEVEL_NAMES[level]}：{data['status']}{extra}", "", "| 指標 | 數值 | 上次 | 門檻（警示／失敗） | 結果 |", "|---|---|---|---|---|"]
            for c in data["checks"]:
                arrow = "≥" if c["direction"] == "higher" else "≤"
                m = c["metric"]
                lines.append(f"| {m} | {fmt(c['value'], m)} | {fmt(c['previous'], m)} | {arrow} {fmt(c['warn'], m)}／{fmt(c['fail'], m)} | "
                             f"{c['status']}{('：' + c['reason']) if c.get('reason') else ''} |")
            if data.get("failed_cases"):
                label = "檢索前 10 筆沒有標準來源的題目" if level == "retrieval" else "回答未通過或出錯的題目"
                lines += ["", f"{label}：" + "、".join(data["failed_cases"])]
            lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zones", default=",".join(config["zones"]))
    parser.add_argument("--levels", default=",".join(LEVELS))
    parser.add_argument("--no-notify", action="store_true", help="do not send WARN/FAIL notifications")
    args = parser.parse_args()
    zones = [z for z in args.zones.split(",") if z]
    levels = [l for l in args.levels.split(",") if l]
    unknown = [z for z in zones if z not in config["zones"]] + [l for l in levels if l not in LEVELS]
    if unknown:
        parser.error(f"unknown zone/level: {unknown}")

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / run_id
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    report = {"created_utc": now.isoformat(timespec="seconds"), "commit": commit, "zones": {},
              "trust_window_hours": config["trust_window_hours"], "levels": levels}
    history_rows = []
    for zone in zones:
        worker = config["zones"][zone]["search_worker"]
        out = run_dir / zone
        out.mkdir(parents=True, exist_ok=True)
        report["zones"][zone] = {}
        for level in levels:
            entry = {}
            try:
                if level == "trust":
                    metrics, _ = trust_level(worker, config["trust_window_hours"], out)
                    if metrics["answers"] < config["trust_min_answers"]:
                        checks = [{"metric": "trust.answers", "value": metrics["answers"], "direction": "higher", "warn": config["trust_min_answers"],
                                   "fail": None, "previous": None, "status": "INSUFFICIENT", "reason": "回答數不足，不判定"}]
                    else:
                        checks = judge("trust", metrics, config["thresholds"], previous_metrics(zone, level))
                else:
                    result = run_golden(worker, f"{run_id}-{zone}", level, out, commit)
                    metrics = (retrieval_metrics if level == "retrieval" else agent_metrics)(result["summary"])
                    checks = judge(level, metrics, config["thresholds"], previous_metrics(zone, level))
                    entry["package_id"] = result.get("package_id")
                    # Each level lists its own failures: retrieval misses for ①, wrong or failed answers for ②.
                    if level == "retrieval":
                        failed = [c["id"] for c in result["cases"] if c.get("error") or (c.get("retrieval") or {}).get("hit") is False]
                    else:
                        failed = [c["id"] for c in result["cases"] if c.get("error") or (c.get("answer") or {}).get("passed") is False]
                    entry["failed_cases"] = failed
            except (subprocess.SubprocessError, OSError, KeyError, json.JSONDecodeError) as exc:
                metrics, checks = {}, [{"metric": f"{level}.run", "value": None, "direction": "higher", "warn": None, "fail": None,
                                        "previous": None, "status": "FAIL", "reason": f"執行失敗：{type(exc).__name__}: {str(exc)[:200]}"}]
            status = "INSUFFICIENT" if checks and all(c["status"] == "INSUFFICIENT" for c in checks) else overall_status(checks)
            entry.update({"status": status, "metrics": metrics, "checks": checks})
            report["zones"][zone][level] = entry
            history_rows.append({"ts": report["created_utc"], "run": run_id, "zone": zone, "level": level, "status": status,
                                 "metrics": {k: v for k, v in metrics.items() if not isinstance(v, dict)}, "commit": commit})
        report["zones"][zone]["_status"] = overall_status([c for lv in levels for c in report["zones"][zone][lv]["checks"]])
    report["status"] = overall_status([c for z in report["zones"].values() for lv in levels for c in z[lv]["checks"]])

    notify_on = (config.get("notify") or {}).get("on") or []
    report["notification"] = ("未通知（--no-notify）" if args.no_notify
                              else _notify.notify_report(report, str(run_dir / "report.md"), notify_on))
    text = render(report) + f"\n- 通知：{report['notification']}\n"
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "report.md").write_text(text, encoding="utf-8")
    for name, content in (("latest.json", json.dumps(report, ensure_ascii=False, indent=1)), ("latest.md", text)):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=ROOT, delete=False) as tmp:
            tmp.write(content)
        os.replace(tmp.name, ROOT / name)
    with (ROOT / "history.jsonl").open("a", encoding="utf-8") as history:
        for row in history_rows:
            history.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(text)
    print(f"報告：{run_dir / 'report.md'}")
    return EXIT[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
