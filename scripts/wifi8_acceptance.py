#!/usr/bin/env python3
"""WiFi 專區驗收包（Patty 需求第 1 項「文件清理 / Normalize / Chunk / Metadata」、第 4 項「Knowledge Search / RAG」）。

每個驗收項目都從「正在服務的資料區」現場取證，不靠人工標記：
  1. 身分：容器與映像、映像對應的 commit、部署程式與 git 該 commit 的逐檔雜湊比對。
  2. 資料區內檢查（src/wifi8/acceptance.py，在各區 search worker 內執行）：排除、chunk、metadata、版本、
     語意＋全文向量、混合檢索對照、引用證據。
  3. 品質報告（scripts/wifi8_quality_check.py）：回答與引用的整體結果；報告資料版本與服務版本不同或超過時限即 STALE。
  4. 使用者流程（Webwright）：畫面能看到處理狀態與失敗；摘要檔以 --ui ZONE=DIR[,DIR] 帶入，缺少即 NOT_RUN。

用法：python scripts/wifi8_acceptance.py --out DIR [--zones test,da40] [--ui test=DIR1,DIR2 --ui da40=DIR3] [--publish-doc FILE]
結束碼：0 全部通過（可含「未啟用」說明）；1 有 FAIL／MISMATCH／STALE；3 有 WARN 或 NOT_RUN（尚未完整驗收）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wifi8_quality_check import CONFIG, REPO, ROOT, sh  # noqa: E402

SPEC_PATH = REPO / "eval/wifi8/acceptance-spec.json"
GOLDEN = REPO / "eval/wifi8/golden-set.v1.jsonl"
CODE_PATHS = ("src/wifi8", "src/web_api/wifi8_routes.py")
STATUS_ORDER = ("FAIL", "MISMATCH", "STALE", "NOT_RUN", "WARN", "NOT_ENABLED", "PASS")
MARK = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "WARN": "⚠️ WARN", "NOT_ENABLED": "⏸ 未啟用", "NOT_RUN": "⬜ 未驗證", "STALE": "🕓 STALE", "MISMATCH": "❌ MISMATCH"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def row(check_id: str, item: str, title: str, status: str, summary: str, **evidence) -> dict:
    return {"id": check_id, "item": item, "title": title, "status": status, "summary": summary, "evidence": evidence}


def git(*args: str) -> str:
    return sh("git", "-C", str(REPO), *args, timeout=60).strip()


# ---- identity -------------------------------------------------------------
def tracked_files(commit: str) -> list[str]:
    names = []
    for path in CODE_PATHS:
        names += [n for n in git("ls-tree", "-r", "--name-only", commit, "--", path).splitlines() if n.endswith(".py")]
    return sorted(names)


def container_hashes(container: str, files: list[str]) -> dict[str, str | None]:
    script = ("import hashlib,json,sys\nout={}\nfor f in json.loads(sys.argv[1]):\n"
              "    try: out[f]=hashlib.sha256(open('/app/'+f,'rb').read()).hexdigest()\n    except OSError: out[f]=None\nprint(json.dumps(out))")
    return json.loads(sh("docker", "exec", container, "python", "-c", script, json.dumps(files), timeout=120))


def identity(zone: str, containers: dict[str, str]) -> tuple[dict, list[dict]]:
    """Which image runs in which container, which commit that image was built from, and whether its code equals that commit."""
    info, mismatches, tags = {}, {}, set()
    for role, name in containers.items():
        image, image_id, started = sh("docker", "inspect", name, "--format", "{{.Config.Image}}|{{.Image}}|{{.State.StartedAt}}", timeout=60).strip().split("|")
        found = re.search(r"-img-([0-9a-f]{7,40})", image)
        info[role] = {"container": name, "image": image, "image_id": image_id[:19], "started_at": started, "image_commit": found.group(1) if found else None}
        tags.add(found.group(1) if found else None)
    commit = next(iter(tags)) if len(tags) == 1 and None not in tags else None
    if commit:
        files = tracked_files(commit)
        expected = {f: hashlib.sha256(subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:{f}"], capture_output=True, check=True).stdout).hexdigest() for f in files}
        for role, name in containers.items():
            actual = container_hashes(name, files)
            # Roles that do not carry a path (e.g. the web image has no worker-only module) are reported as absent, not as different.
            bad = [f for f in files if actual.get(f) is not None and actual[f] != expected[f]]
            info[role]["code_compared"] = sum(1 for f in files if actual.get(f) is not None)
            info[role]["code_different"] = bad
            if bad:
                mismatches[role] = bad[:5]
    head = git("rev-parse", "--short=7", "HEAD")
    behind = []
    if commit:
        behind = [n for n in git("diff", "--name-only", commit, "HEAD", "--", *CODE_PATHS).splitlines() if n.endswith(".py")]
    status = "PASS" if commit and not mismatches and not behind else "MISMATCH"
    summary = (f"映像 commit {commit}；{', '.join(f'{r} 比對 {i.get('code_compared')} 檔' for r, i in info.items())}；"
               f"與 git 該 commit 不同的檔案 {sum(len(v) for v in mismatches.values())} 個；目前 HEAD {head} 之後改過這些程式的檔案 {len(behind)} 個"
               if commit else "容器映像沒有 -img-<commit> 標記或各容器不一致，無法對應到 commit")
    return info, [row("0.1", "0", "部署中的程式 = 已核准的 git commit", status, summary,
                      containers=info, mismatched=mismatches, changed_since_image=behind[:10], head=head)]


# ---- zone-side checks --------------------------------------------------------
def probe(worker: str, out: Path) -> dict:
    remote = f"/tmp/km-acceptance-{uuid.uuid4().hex[:8]}"
    sh("docker", "exec", worker, "mkdir", "-p", f"{remote}/wifi8")
    sh("docker", "cp", str(REPO / "scripts/wifi8_acceptance_probe.py"), f"{worker}:{remote}/")
    sh("docker", "cp", str(REPO / "src/wifi8/acceptance.py"), f"{worker}:{remote}/wifi8/")
    sh("docker", "cp", str(GOLDEN), f"{worker}:{remote}/")
    sh("docker", "cp", str(SPEC_PATH), f"{worker}:{remote}/")
    try:
        sh("docker", "exec", "-w", "/app", worker, "python", f"{remote}/wifi8_acceptance_probe.py", "--cases", f"{remote}/golden-set.v1.jsonl",
           "--spec", f"{remote}/acceptance-spec.json", "--module-dir", f"{remote}/wifi8", "--out", f"{remote}/probe.json", timeout=1800)
        sh("docker", "cp", f"{worker}:{remote}/probe.json", str(out), retries=2)
    finally:
        sh("docker", "exec", worker, "python", "-c", f"import shutil; shutil.rmtree({remote!r}, ignore_errors=True)")
    return json.loads(out.read_text(encoding="utf-8"))


# ---- quality report (answers and citations) ------------------------------------
def answer_rows(zone: str, package_id: str, spec: dict, quality_root: Path) -> list[dict]:
    rule = spec["citation"]
    report = json.loads((quality_root / "latest.json").read_text(encoding="utf-8")) if (quality_root / "latest.json").is_file() else {}
    agent = ((report.get("zones") or {}).get(zone) or {}).get("agent")
    title = "Agent 回答附引用、引用能對到標準來源"
    if not agent:
        return [row("4.5", "4", title, "NOT_RUN", "品質報告沒有此區的 Agent 層結果，請先執行 scripts/wifi8_quality_check.py --levels retrieval,agent")]
    created = datetime.fromisoformat(report["created_utc"])
    age = datetime.now(timezone.utc) - created
    metrics = agent["metrics"]
    if agent.get("package_id") != package_id or age > timedelta(hours=spec["quality_report"]["max_age_hours"]):
        return [row("4.5", "4", title, "STALE", f"品質報告（{report['created_utc']}、資料版本 {agent.get('package_id')}）與目前服務版本 {package_id} 不符或超過 "
                    f"{spec['quality_report']['max_age_hours']} 小時，需重跑", report_created=report["created_utc"])]
    good = (metrics.get("cited_gold") or 0) >= rule["min_cited_gold"] and not metrics.get("forbidden_answers") and not metrics.get("errors")
    return [row("4.5", "4", title, "PASS" if good else "FAIL",
                f"{metrics.get('cases')} 題：回答通過 {metrics.get('answer_pass'):.1%}、引用到標準來源 {metrics.get('cited_gold'):.1%}"
                f"（門檻 ≥{rule['min_cited_gold']:.0%}）、事實涵蓋 {metrics.get('fact_coverage'):.1%}、禁止的回答 {metrics.get('forbidden_answers')}、"
                f"執行錯誤 {metrics.get('errors')}；未通過題 {agent.get('failed_cases')}；報告 {report['created_utc']}（commit {report.get('commit')}）",
                metrics=metrics, failed_cases=agent.get("failed_cases"), report_created=report["created_utc"])]


# ---- user flow evidence (Webwright summaries) ---------------------------------------
UI_CHECKS = (
    ("1.11", "1", "畫面看得到處理狀態：排除、文字狀態、檢索單位、metadata 覆蓋率", "processing_panel"),
    ("1.12", "1", "畫面看得到版本關係、metadata 與來源段落", "version_relation"),
    ("1.13", "1", "失敗狀態可見：驗證失敗立即顯示原因、任務清單留有紀錄、目前版本不受影響", "failure_visible"),
    ("4.6", "4", "使用者流程：混合檢索、AI Agent 附引用回答", ("search_1", "search_2", "search_3", "agent")),
)


def ui_rows(dirs: list[Path], package_id: str) -> list[dict]:
    summaries = []
    for directory in dirs:
        path = directory / "summary.json"
        if path.is_file():
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
    merged: dict[str, bool] = {}
    for summary in summaries:
        merged.update(summary.get("results") or {})
    problems = [s for s in summaries if s.get("console_errors") or s.get("wifi8_api_failures")]
    rows = []
    for check_id, item, title, keys in UI_CHECKS:
        keys = (keys,) if isinstance(keys, str) else keys
        missing = [k for k in keys if k not in merged]
        if missing:
            rows.append(row(check_id, item, title, "NOT_RUN", f"沒有 Webwright 結果：{', '.join(missing)}"))
            continue
        ok = all(merged[k] for k in keys) and not problems
        rows.append(row(check_id, item, title, "PASS" if ok else "FAIL",
                        "；".join(f"{k}={'通過' if merged[k] else '失敗'}" for k in keys) + (f"；console／API 錯誤 {len(problems)} 份摘要" if problems else ""),
                        results={k: merged[k] for k in keys}, dirs=[str(d) for d in dirs]))
    return rows


def cleanup_rejected(container: str, dirs: list[Path]) -> list[str]:
    """Remove the failed-upload records the Webwright flow created on purpose (only validate-phase jobs of its own broken file)."""
    ids = sorted({job for d in dirs if (d / "summary.json").is_file() for job in json.loads((d / "summary.json").read_text(encoding="utf-8")).get("rejected_jobs") or []})
    if not ids:
        return []
    script = ("import json,sys\nfrom src.wifi8.importer import Wifi8Settings\nroot=Wifi8Settings.from_environment().root/'jobs'\nremoved=[]\n"
              "for job_id in json.loads(sys.argv[1]):\n    path=root/(job_id+'.json')\n"
              "    try: job=json.loads(path.read_text(encoding='utf-8'))\n    except OSError: continue\n"
              "    if job.get('status')=='failed' and job.get('phase')=='validate' and 'wifi8-acceptance-broken.zip' in (job.get('message') or ''):\n"
              "        path.unlink(); removed.append(job_id)\nprint(json.dumps(removed))")
    return json.loads(sh("docker", "exec", container, "python", "-c", script, json.dumps(ids), timeout=60).strip().splitlines()[-1])


# ---- report -------------------------------------------------------------------------
def overall(rows: list[dict]) -> str:
    present = {r["status"] for r in rows}
    return next((s for s in STATUS_ORDER if s in present), "PASS")


def render(report: dict, spec: dict) -> str:
    lines = [f"# WiFi 專區驗收報告（Patty 需求第 1、4 項）", "",
             f"- 產生時間：{report['created_utc']}　　程式 commit：{report['commit']}　　題庫：{report['cases_sha256']}",
             f"- 結論：**{MARK.get(report['status'], report['status'])}**（只要任一專區有 FAIL／MISMATCH／STALE 就不是通過；WARN 與未驗證代表尚未完整驗收）", ""]
    zones = report["zones"]
    for item, meta in spec["items"].items():
        lines += [f"## 第 {item} 項：{meta['name']}", "", f"需求：{meta['requirement']}", "",
                  "| 編號 | 驗收項目 | " + " | ".join(z.upper() for z in zones) + " |", "|---|---|" + "---|" * len(zones)]
        ids = [r["id"] for r in next(iter(zones.values()))["rows"] if r["item"] == item]
        for check_id in ids:
            cells = []
            for z in zones.values():
                found = next(r for r in z["rows"] if r["id"] == check_id)
                cells.append(MARK.get(found["status"], found["status"]))
            title = next(r["title"] for r in next(iter(zones.values()))["rows"] if r["id"] == check_id)
            lines.append(f"| {check_id} | {title} | " + " | ".join(cells) + " |")
        lines.append("")
    lines += ["## 證據明細", ""]
    for name, zone in zones.items():
        lines += [f"### {name.upper()}（資料版本 {zone['package_id']}）", ""]
        for r in zone["rows"]:
            lines.append(f"- **{r['id']} {r['title']}**　{MARK.get(r['status'], r['status'])}　{r['summary']}")
        lines.append("")
    notes = [r for z in zones.values() for r in z["rows"] if r["status"] in {"WARN", "NOT_ENABLED", "NOT_RUN", "STALE", "MISMATCH", "FAIL"}]
    if notes:
        lines += ["## 未通過或有保留的項目", ""]
        seen = set()
        for r in notes:
            key = (r["id"], r["status"])
            if key not in seen:
                seen.add(key)
                lines.append(f"- {r['id']} {r['title']}：{MARK.get(r['status'], r['status'])} — {r['summary']}")
        lines.append("")
    lines += ["## 如何重跑", "", "```bash", "python scripts/wifi8_acceptance.py --out DIR --ui test=DIR --ui da40=DIR", "```", "",
              "規格與門檻：`eval/wifi8/acceptance-spec.json`；檢查程式：`src/wifi8/acceptance.py`；畫面流程：`scripts/webwright_wifi8_item1.py`、"
              "`scripts/webwright_wifi8_accept.py`。", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--zones", default="")
    parser.add_argument("--ui", action="append", default=[], help="ZONE=DIR[,DIR]：該區 Webwright 輸出目錄")
    parser.add_argument("--quality-root", type=Path, default=ROOT)
    parser.add_argument("--publish-doc", type=Path)
    parser.add_argument("--keep-rejected", action="store_true", help="不清除 Webwright 故意上傳損毀檔留下的失敗紀錄")
    args = parser.parse_args()
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    ui = {}
    for entry in args.ui:
        zone, _, dirs = entry.partition("=")
        ui[zone] = [Path(d) for d in dirs.split(",") if d]
    wanted = [z for z in (args.zones.split(",") if args.zones else config["zones"]) if z]
    args.out.mkdir(parents=True, exist_ok=True)
    zones = {}
    for zone in wanted:
        settings = config["zones"][zone]
        containers = {"search_worker": settings["search_worker"], **spec["containers"][zone]}
        info, identity_rows = identity(zone, containers)
        result = probe(settings["search_worker"], args.out / f"probe-{zone}.json")
        rows = identity_rows + result["rows"] + answer_rows(zone, result["package_id"], spec, args.quality_root) + ui_rows(ui.get(zone, []), result["package_id"])
        rows.sort(key=lambda r: [int(p) for p in r["id"].split(".")])
        removed = [] if args.keep_rejected else cleanup_rejected(containers["web"], ui.get(zone, []))
        zones[zone] = {"package_id": result["package_id"], "counts": result["counts"], "identity": info, "status": overall(rows), "rows": rows, "removed_test_jobs": removed}
        print(f"{zone}: {zones[zone]['status']}  " + " ".join(f"{r['id']}={r['status']}" for r in rows), flush=True)
    report = {"created_utc": now(), "commit": git("rev-parse", "--short=7", "HEAD"),
              "cases_sha256": hashlib.sha256(GOLDEN.read_bytes()).hexdigest()[:16], "status": overall([r for z in zones.values() for r in z["rows"]]),
              "zones": zones}
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    text = render(report, spec)
    (args.out / "report.md").write_text(text, encoding="utf-8")
    if args.publish_doc:
        args.publish_doc.write_text(text, encoding="utf-8")
    print(f"驗收結論 {report['status']}；報告 {args.out / 'report.md'}")
    return {"PASS": 0, "NOT_ENABLED": 0, "WARN": 3, "NOT_RUN": 3}.get(report["status"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
