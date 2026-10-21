"""What the WiFi zone overview shows besides the plain counts: the classification statistics and the things that need attention.

The classification statistics mirror the overview of the original Wi-Fi8 KM System: documents grouped by the top folder of their
``classification_path`` (the publishing organisation's category), with a Chinese name, a description, the count and its share of
all documents. All documents count (history versions included), and the current versions are shown next to the total. The names
come from ``categories.json`` (``KM_WIFI8_CATEGORIES_FILE`` overrides the path); a folder that is not listed there is still
shown under its folder name, so nothing is dropped silently.

The attention list is computed from what the import and the zone's switches say; it never invents a problem and is empty when
everything is in order.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

CATEGORIES_FILE_ENV = "KM_WIFI8_CATEGORIES_FILE"
DEFAULT_CATEGORIES_FILE = Path(__file__).with_name("categories.json")
UNCLASSIFIED = "未分類"


def load_categories() -> list[dict[str, str]]:
    path = Path(os.getenv(CATEGORIES_FILE_ENV) or DEFAULT_CATEGORIES_FILE)
    try:
        items = json.loads(path.read_text(encoding="utf-8"))["categories"]
        return [{"folder": str(i["folder"]), "label": str(i.get("label") or i["folder"]), "description": str(i.get("description") or "")} for i in items]
    except (OSError, ValueError, KeyError, TypeError):
        return []  # without the file every folder is shown under its own name


def category_folder(document: dict[str, Any]) -> str:
    return str(document.get("classification_path") or "").split("/")[0] or UNCLASSIFIED


def category_stats(documents: list[dict[str, Any]], categories: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """{total, rows: [{folder, label, description, total, current, history, share}]} in the configured order, unlisted folders after."""
    categories = load_categories() if categories is None else categories
    total, current = Counter(), Counter()
    for document in documents:
        folder = category_folder(document)
        total[folder] += 1
        current[folder] += 1 if document.get("analysis_eligible") else 0
    listed = {c["folder"] for c in categories}
    rows = [{**c, "total": total[c["folder"]], "current": current[c["folder"]]} for c in categories if total[c["folder"]]]
    rows += [{"folder": f, "label": f, "description": "尚未設定分類名稱的資料夾", "total": n, "current": current[f]} for f, n in total.most_common() if f not in listed]
    grand = sum(total.values())
    for row in rows:
        row["history"] = row["total"] - row["current"]
        row["share"] = round(row["total"] / grand * 100, 1) if grand else 0.0
    return {"total": grand, "rows": rows}


def contested_series(documents: list[dict[str, Any]]) -> int:
    """Version series that have more than one current document: the source has not said which one replaces the other."""
    series = Counter(d.get("version_series_id") for d in documents if d.get("analysis_eligible") and d.get("version_series_id"))
    return sum(1 for n in series.values() if n > 1)


def attention_items(documents: list[dict[str, Any]], counts: dict[str, Any], processing: dict[str, Any], active_job: dict[str, Any] | None,
                    auto_check: dict[str, Any]) -> list[dict[str, str]]:
    """[{level: warning|info, title, detail, route}] — route is a page of the zone SPA."""
    items: list[dict[str, str]] = []
    if processing.get("failed_jobs"):
        latest = (processing.get("latest_failure") or {}).get("error") or ""
        items.append({"level": "warning", "title": "匯入失敗紀錄", "route": "jobs",
                      "detail": f"{processing['failed_jobs']} 筆匯入失敗，目前資料版本不受影響。" + (f"最近一筆：{latest[:80]}" if latest else "")})
    if active_job:
        items.append({"level": "info", "title": "匯入進行中", "route": "jobs", "detail": "匯入完成前不會切換目前版本。"})
    if counts.get("chunks_pending"):
        items.append({"level": "info", "title": "檢索單位處理中", "route": "overview", "detail": f"{counts['chunks_pending']:,} 個檢索單位尚在處理，完成後才能被搜尋到。"})
    contested = contested_series(documents)
    if contested:
        items.append({"level": "warning", "title": "版本關係待確認", "route": "documents",
                      "detail": f"{contested} 組版本系列同時有多份「目前版本」，來源端尚未判定誰取代誰，請向來源確認。"})
    if auto_check.get("enabled") is False:
        items.append({"level": "info", "title": "資料更新後自動檢查已關閉", "route": "jobs", "detail": "資料更新後不會自動做品質檢查；可在「匯入與進度」頁重新開啟。"})
    elif auto_check.get("watcher_overdue"):
        items.append({"level": "warning", "title": "自動檢查的監看程式沒有回報", "route": "jobs", "detail": "超過預期時間沒有輪詢，資料更新後可能不會自動檢查，請通知開發者。"})
    return items
