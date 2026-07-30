#!/usr/bin/env python3
"""Validate, upload, poll and retry canonical KB test reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.test_reports.excel_contract import ReportValidationError, parse_and_validate_report


def _setting(name: str, required: bool = True) -> str:
    value = os.getenv(name, "").strip()
    if required and not value:
        raise RuntimeError(f"缺少環境變數 {name}")
    return value


def _outbox() -> sqlite3.Connection:
    configured = os.getenv("KB_REPORT_OUTBOX", "").strip()
    path = Path(configured) if configured else Path.home() / ".kb-report-uploader" / "outbox.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS pending_reports (
        report_path TEXT PRIMARY KEY, attachments_json TEXT NOT NULL, run_id TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    db.commit()
    return db


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(report: Path, attachments: list[Path]) -> dict:
    return parse_and_validate_report(report, {path.name: _hash(path) for path in attachments})


def _request_config() -> tuple[str, dict, str | bool]:
    base_url = _setting("KB_BASE_URL").rstrip("/")
    headers = {"Authorization": f"Bearer {_setting('KB_INGEST_TOKEN')}", "X-Agent-ID": _setting("KB_AGENT_ID")}
    ca_cert = _setting("KB_CA_CERT", required=False)
    return base_url, headers, ca_cert or True


def upload(report: Path, attachments: list[Path]) -> dict:
    parsed = validate(report, attachments)
    base_url, headers, verify = _request_config()
    headers["Idempotency-Key"] = parsed["manifest"]["run_id"]
    handles = []
    try:
        report_handle = report.open("rb"); handles.append(report_handle)
        files = [("file", (report.name, report_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
        for attachment in attachments:
            handle = attachment.open("rb"); handles.append(handle)
            files.append(("attachments", (attachment.name, handle, "application/octet-stream")))
        response = requests.post(f"{base_url}/api/agent/v1/reports", headers=headers, files=files, verify=verify, timeout=(15, 120))
        if response.status_code >= 400:
            raise requests.HTTPError(f"HTTP {response.status_code}: {response.text[:1000]}", response=response)
        return response.json()
    finally:
        for handle in handles:
            handle.close()


def _queue(report: Path, attachments: list[Path], error: str) -> None:
    run_id = validate(report, attachments)["manifest"]["run_id"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _outbox() as db:
        db.execute("""INSERT INTO pending_reports
            (report_path, attachments_json, run_id, attempts, last_error, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(report_path) DO UPDATE SET attachments_json=excluded.attachments_json,
            attempts=pending_reports.attempts+1, last_error=excluded.last_error, updated_at=excluded.updated_at
        """, (str(report.resolve()), json.dumps([str(path.resolve()) for path in attachments]), run_id, error[:2000], now, now))


def send(report: Path, attachments: list[Path], allow_queue: bool = True) -> int:
    try:
        result = upload(report, attachments)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        with _outbox() as db:
            db.execute("DELETE FROM pending_reports WHERE report_path = ?", (str(report.resolve()),))
        return 0
    except ReportValidationError as exc:
        print(json.dumps({"status": "validation_failed", "errors": exc.errors}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        if allow_queue and (status == 0 or status >= 500):
            _queue(report, attachments, str(exc)); print("伺服器暫時不可用，已放入 outbox", file=sys.stderr); return 3
        print(str(exc), file=sys.stderr); return 4
    except (requests.RequestException, OSError) as exc:
        if allow_queue:
            _queue(report, attachments, str(exc)); print("網路或檔案錯誤，已放入 outbox", file=sys.stderr); return 3
        print(str(exc), file=sys.stderr); return 4


def retry_pending() -> int:
    with _outbox() as db:
        rows = db.execute("SELECT * FROM pending_reports ORDER BY created_at").fetchall()
    failures = 0
    for row in rows:
        failures += send(Path(row["report_path"]), [Path(value) for value in json.loads(row["attachments_json"])]) != 0
    return 0 if failures == 0 else 3


def status(submission_id: str) -> int:
    base_url, headers, verify = _request_config()
    response = requests.get(f"{base_url}/api/agent/v1/reports/{submission_id}", headers=headers, verify=verify, timeout=(15, 30))
    print(response.text)
    return 0 if response.ok else 4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "send"):
        child = commands.add_parser(command); child.add_argument("report", type=Path)
        child.add_argument("--attachment", action="append", default=[], type=Path)
    commands.add_parser("retry")
    status_parser = commands.add_parser("status"); status_parser.add_argument("submission_id")
    args = parser.parse_args()
    if args.command == "validate":
        try:
            print(json.dumps(validate(args.report, args.attachment)["manifest"], ensure_ascii=False, indent=2)); return 0
        except ReportValidationError as exc:
            print(json.dumps({"errors": exc.errors}, ensure_ascii=False, indent=2), file=sys.stderr); return 2
    if args.command == "send": return send(args.report, args.attachment)
    if args.command == "retry": return retry_pending()
    return status(args.submission_id)


if __name__ == "__main__":
    raise SystemExit(main())
