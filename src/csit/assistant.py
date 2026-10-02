"""Natural-language, read-only CSIT lookup used by the KM assistant.

The assistant deliberately orchestrates only the approved GET chain.  It does
not expose CSIT credentials or call CSIT write endpoints from the browser.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from .client import CsitReadOnlyClient
from ..test_reports.auth import create_csit_download_ticket


_CSIT_HINTS = re.compile(
    r"csit|project|record|module|case|task|file|report|測試報告|附件|專案|案件|任務|模組",
    re.IGNORECASE,
)
_STOP_WORDS = {
    "csit", "system", "查詢", "請問", "請查", "幫我", "找", "取得", "顯示", "列出",
    "project", "record", "module", "case", "task", "file", "report", "測試報告", "附件",
    "專案", "案件", "任務", "模組", "的", "中", "下", "有", "哪些", "資料",
}


def is_csit_query(query: str) -> bool:
    """Return whether the user explicitly asks for CSIT data."""

    text = str(query or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return "csit" in lowered or bool(
        re.search(r"(?:project|record|case|task|file|report).*(?:csit|附件|測試報告)", lowered, re.IGNORECASE)
    )


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "data", "results", "records", "cases", "tasks", "files", "modules"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = _items(value)
                if nested:
                    return nested
        return [payload]
    return []


def _id(item: Mapping[str, Any]) -> str:
    for key in ("id", "recordId", "caseId", "taskId", "fileId", "guid", "uuid"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _label(item: Mapping[str, Any], fallback: str) -> str:
    for key in ("name", "title", "code", "moduleCode", "recordNo", "caseNo", "taskNo", "fileName", "filename"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return fallback


def _blob(item: Mapping[str, Any]) -> str:
    return " ".join(str(value) for value in item.values() if isinstance(value, (str, int, float, bool))).lower()


def _terms(query: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_.:-]{2,}|[\u4e00-\u9fff]{2,}", str(query or "").lower())
    return [word for word in words if word not in _STOP_WORDS]


def _match(items: list[dict[str, Any]], query: str, limit: int = 5) -> list[dict[str, Any]]:
    terms = _terms(query)
    if not terms:
        return items[:limit]
    scored = []
    for index, item in enumerate(items):
        blob = _blob(item)
        score = sum(1 for term in terms if term in blob)
        if score:
            scored.append((score, -index, item))
    scored.sort(reverse=True, key=lambda row: (row[0], row[1]))
    return [item for _, _, item in scored[:limit]]


def _module_code(item: Mapping[str, Any]) -> str:
    return str(item.get("moduleCode") or item.get("code") or item.get("id") or "").strip()


def _file_name(item: Mapping[str, Any]) -> str:
    for key in ("fileName", "filename", "name", "title"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return _label(item, "未命名附件")


def _download_link(file_id: str, filename: str = "") -> str:
    path = f"/api/csit/files/{quote(file_id, safe='')}/download"
    ticket = create_csit_download_ticket(file_id, filename)
    if ticket:
        return f"[下載報告]({path}?ticket={quote(ticket, safe='')})"
    return f"`{path}`"


def _line(item: Mapping[str, Any], fallback: str) -> str:
    label = _label(item, fallback)
    identifier = _id(item)
    return f"- {label}" + (f"（ID: `{identifier}`）" if identifier else "")


def _detail_lines(detail: Any) -> list[str]:
    """Render safe scalar fields without dumping arbitrary nested payloads."""
    if not isinstance(detail, dict):
        return []
    values = []
    for key, value in detail.items():
        if isinstance(value, (str, int, float, bool)) and str(value).strip():
            values.append(f"{key}: {value}")
    return values[:12]


def answer_csit_query(client: CsitReadOnlyClient, query: str) -> str:
    """Run a bounded Module → Record → Case → Task → File lookup."""

    modules = _items(client.get("/api/modules/enabled"))
    if not modules:
        return "CSIT 目前沒有回傳啟用中的 Module。"

    query_terms = _terms(query)
    selected_modules = _match(modules, query, limit=3)
    if not selected_modules:
        selected_modules = modules[:3]

    lines = ["### CSIT 唯讀查詢結果", "", "**啟用中的 Module**"]
    lines.extend(_line(item, "未命名 Module") for item in selected_modules)

    if not query_terms:
        lines.extend(["", "請再補充 Project／Record、Case 或 Task 名稱／編號，我才能繼續查詢下層資料。"])
        lines.extend(["", "資料來源：CSIT Stage REST API；本次操作僅使用 GET，未修改 CSIT 資料。"])
        return "\n".join(lines)

    resolved = False
    for module in selected_modules:
        code = _module_code(module)
        if not code:
            continue
        records = _items(client.get("/api/modules/{moduleCode}/records", path_params={"moduleCode": code}, query={"page": 1, "pageSize": 50}))
        matched_records = _match(records, query, limit=5) or records[:5]
        # A keyword may match a valid Record that has no Case yet. Keep a
        # bounded fallback set so a generic CSIT question can still discover
        # the first populated branch without scanning the whole system.
        seen_record_ids = {_id(item) for item in matched_records}
        for item in records:
            if len(matched_records) >= 5:
                break
            if _id(item) not in seen_record_ids:
                matched_records.append(item)
                seen_record_ids.add(_id(item))
        lines.extend(["", f"**Project / Record（{_label(module, code)}）**"])
        lines.extend(_line(item, "未命名 Record") for item in matched_records)
        for record in matched_records:
            record_id = _id(record)
            if not record_id:
                continue
            record_detail = client.get("/api/records/{id}", path_params={"id": record_id})
            detail = _detail_lines(record_detail)
            if detail:
                lines.extend(["  詳細："] + [f"  - {value}" for value in detail])
            cases = _items(client.get("/api/records/{recordId}/cases", path_params={"recordId": record_id}, query={"page": 1, "pageSize": 50}))
            matched_cases = _match(cases, query, limit=5) or cases[:5]
            lines.extend(["", f"**Case（Record `{record_id}`）**"])
            lines.extend(_line(item, "未命名 Case") for item in matched_cases)
            for case in matched_cases:
                case_id = _id(case)
                if not case_id:
                    continue
                case_detail = client.get("/api/cases/{id}", path_params={"id": case_id})
                detail = _detail_lines(case_detail)
                if detail:
                    lines.extend(["  詳細："] + [f"  - {value}" for value in detail])
                case_files = _items(client.get("/api/cases/{caseId}/files", path_params={"caseId": case_id}))
                if case_files:
                    lines.append("  Case 附件：" + ", ".join(_file_name(item) for item in case_files[:10]))
                tasks = _items(client.get("/api/cases/{caseId}/tasks", path_params={"caseId": case_id}, query={"page": 1, "pageSize": 50}))
                matched_tasks = _match(tasks, query, limit=5) or tasks[:5]
                lines.extend(["", f"**Task（Case `{case_id}`）**"])
                lines.extend(_line(item, "未命名 Task") for item in matched_tasks)
                for task in matched_tasks:
                    task_id = _id(task)
                    if not task_id:
                        continue
                    task_detail = client.get("/api/tasks/{id}", path_params={"id": task_id})
                    detail = _detail_lines(task_detail)
                    if detail:
                        lines.extend(["  詳細："] + [f"  - {value}" for value in detail])
                    files = _items(client.get("/api/tasks/{taskId}/files", path_params={"taskId": task_id}))
                    lines.extend(["", f"**附件／測試報告（Task `{task_id}`）**"])
                    if files:
                        for file_item in files[:10]:
                            file_id = _id(file_item)
                            suffix = f"（{_download_link(file_id, _file_name(file_item))}）" if file_id else ""
                            lines.append(f"- {_file_name(file_item)}" + suffix)
                    else:
                        lines.append("- 此 Task 沒有附件")
                    resolved = True

    if not resolved:
        lines.extend(["", "尚未依查詢文字定位到具體 Case／Task；以上為目前可讀取的 Module 與 Record。請補充 Project、Case 或 Task 名稱／編號。"])
    lines.extend(["", "資料來源：CSIT Stage REST API；本次操作僅使用 GET，未修改 CSIT 資料。"])
    return "\n".join(lines)
