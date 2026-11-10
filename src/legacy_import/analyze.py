"""One model call per document: classify it into the CSIT taxonomy and extract the v1.2 document / technical metadata.

Nothing the model returns is trusted on its own:
* the classification row must be one of the table's rows, and its evidence must appear in the file path or the text;
* every extracted name, model, version and date must appear in the text, otherwise it is dropped (CSIT v1.2: unknown -> null / []).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from .taxonomy import UNCLASSIFIED, Row, choices

DOCUMENT_TYPES = ("Specification", "Manual", "TestReport", "SOP", "MeetingMinutes", "IssueAnalysis", "Presentation", "Other")
TECHNOLOGIES = ("Wi-Fi", "Cellular", "Small Cell", "PON", "Cable")
LIST_FIELDS = ("authors", "keywords", "tags", "productNames", "modelNumbers", "vendorNames", "technologies", "standards", "softwareVersions",
               "hardwareVersions", "projectNames", "testItems", "issueKeys", "errorCodes")
MIN_CONFIDENCE = 0.6
CLASSIFY_CHARS = 3000
METADATA_CHARS = 8000

SYSTEM = """你是企業知識庫的文件整理員。依「文件路徑」與「文件內容」做兩件事，只輸出一個 JSON 物件，不要任何其他文字。

一、分類：從下列分類表選出最符合的一列（row_id），不可自創。再依該列的第二層、第三層描述，從路徑或內容填入具體名稱（例如機種名稱、認證項目、廠商名稱、設備名稱、實驗室名稱、研討會名稱、組織名稱），找不到就填 null。
  classification.evidence 必須是路徑或內容中「一字不差」的一小段文字，作為判斷依據。信心 confidence 為 0 到 1。
  CPE 相關文件（CPE、路由器、閘道器、用戶端設備）歸入 Cellular（行動通訊）。
  研討會講義若跨多種技術，選內容最接近的那個技術的研討會講義列，不要因為跨技術就放棄分類。
  IEEE 標準目前只對應 IEEE 802.11（Wi-Fi）；802.3（乙太網路）等其他標準不屬於 Wi-Fi 的 IEEE 列。
  人事行政、採購請款、預算、簽呈、費用、Time Report、報價類文件，請選擇對應的列（即使它們看起來像雜項），不要歸入內部雜項。
  xDSL／ADSL／VDSL／DSLAM 文件選 s1；設備預約系統（Project System）文件選 s2；實驗室管理辦法選 s3；IEEE 802.3、ITU-T 等非 802.11 標準選 s4。
  內容明確屬於認證（含 USB-IF、Wi-Fi Alliance 等認證流程）、設備、實驗室或某項技術的文件，優先選該類的列；31 只用於這些都不符合的公司內部事務文件。
  廠商的產品介紹、規格書、操作手冊不是採購請款文件；只有報價單、請購單、訂單、發票、請款單才選採購請款列。
  工作報告、月會簡報若沒有人事資料（薪資、考核、請假、個人評價），不要選人事行政列。

二、中繼資料：只填文件中明示的資訊，不得猜測、不得推算。找不到的欄位用 null 或 []。

分類表（row_id | 第一層 / 第二層 / 第三層 | 條件 | 專區）：
{catalogue}

輸出格式：
{{"classification": {{"row_id": "...", "l2_value": null, "l3_value": null, "technology": null, "confidence": 0.0, "evidence": "..."}},
 "document": {{"title": null, "documentType": "Specification|Manual|TestReport|SOP|MeetingMinutes|IssueAnalysis|Presentation|Other", "summary": null,
   "language": null, "documentDate": null, "authors": [], "department": null, "documentVersionLabel": null, "keywords": [], "tags": []}},
 "technical": {{"productNames": [], "modelNumbers": [], "vendorNames": [], "technologies": [], "standards": [], "softwareVersions": [],
   "hardwareVersions": [], "projectNames": [], "testItems": [], "issueKeys": [], "errorCodes": []}}}}
技術欄 classification.technology 只能是 Wi-Fi、Cellular、Small Cell、PON、Cable 其中之一或 null。summary 用 100 到 300 字摘要，語言同文件。"""


@dataclass
class Result:
    row: Row
    l2_value: str | None = None
    l3_value: str | None = None
    technology: str | None = None
    confidence: float = 0.0
    evidence: str | None = None
    needs_review: bool = False
    suggested_row: str | None = None
    document: dict = field(default_factory=dict)
    technical: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    skip_reason: str | None = None          # set when a document must not be written to any store (none of the classification rows does this any more)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").casefold()


def _present(value: str, haystack: str) -> bool:
    return bool(value) and _norm(value) in haystack


def _catalogue(rows: list[Row]) -> str:
    return "\n".join(f"{r.id} | {r.label()} | {r.condition} | {r.topic}" for r in rows)


def build_messages(path: str, text: str, rows: list[Row]) -> list[dict]:
    excerpt = text[:METADATA_CHARS]
    return [{"role": "system", "content": SYSTEM.format(catalogue=_catalogue(rows))},
            {"role": "user", "content": f"文件路徑：{path}\n\n文件內容（節錄）：\n{excerpt}"}]


def _json(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        raise ValueError("no JSON object in model output")
    text = match.group(0)
    try:
        return json.loads(text, strict=False)                  # raw tabs / newlines inside strings are common in model output
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", text), strict=False)   # trailing commas


RETRY_NOTE = ("上一次的輸出不是合法 JSON。請重新輸出同樣內容：只輸出一個 JSON 物件；所有字串內不得有換行、Tab 或未跳脫的雙引號；"
              "每個欄位之間都要有逗號；summary 控制在 150 字內。")


def _complete_json(complete: Callable[[list[dict]], str], messages: list[dict]) -> dict:
    """One retry that says what was wrong, with a shorter excerpt: table-like files (asset lists) are what usually breaks the model's JSON."""
    try:
        return _json(complete(messages))
    except (ValueError, json.JSONDecodeError):
        short = [messages[0], {"role": "user", "content": messages[1]["content"][:3000] + "\n\n" + RETRY_NOTE}]
        return _json(complete(short))


def _date_in_text(value: str | None, text: str) -> str | None:
    if not value or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    year, month, day = value.split("-")
    variants = {value, f"{year}/{month}/{day}", f"{year}/{int(month)}/{int(day)}", f"{year}.{month}.{day}", f"{year}年{int(month)}月{int(day)}日",
                f"{year}{month}{day}", f"{year}-{int(month)}-{int(day)}"}
    return value if any(v in text for v in variants) else None


def analyze(complete: Callable[[list[dict]], str], path: str, text: str, rows: list[Row] | None = None) -> Result:
    """complete(messages) -> model text. Raises ValueError when the model output cannot be used at all."""
    rows = rows if rows is not None else choices()
    by_id = {row.id: row for row in rows}
    data = _complete_json(complete, build_messages(path, text, rows))
    cls, doc, tech = data.get("classification") or {}, data.get("document") or {}, data.get("technical") or {}
    full_haystack = _norm(path + "\n" + text)
    result = Result(row=UNCLASSIFIED)
    warnings = result.warnings

    row_id = str(cls.get("row_id") or "")
    try:
        confidence = max(0.0, min(1.0, float(cls.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    evidence = cls.get("evidence")
    if row_id not in by_id:
        warnings.append("classification row not in table")
        confidence = 0.0
    elif not _present(str(evidence or ""), full_haystack):
        warnings.append("classification evidence not found in path or text")
        confidence = min(confidence, 0.4)
    result.confidence = confidence
    result.evidence = evidence if isinstance(evidence, str) else None
    result.suggested_row = row_id if row_id in by_id else None
    if row_id in by_id and confidence >= MIN_CONFIDENCE:
        result.row = by_id[row_id]
    else:
        result.needs_review = True
    for key in ("l2_value", "l3_value"):
        value = cls.get(key)
        setattr(result, key, value if isinstance(value, str) and _present(value, full_haystack) else None)
    technology = cls.get("technology")
    result.technology = technology if technology in TECHNOLOGIES else None

    doc_type = doc.get("documentType")
    result.document = {
        "title": doc.get("title") if isinstance(doc.get("title"), str) and _present(doc["title"], full_haystack) else None,
        "documentType": doc_type if doc_type in DOCUMENT_TYPES else "Other",
        "summary": (doc.get("summary") or None) and str(doc["summary"])[:600],
        "language": doc.get("language") if isinstance(doc.get("language"), str) else None,
        "documentDate": _date_in_text(doc.get("documentDate"), text),
        "department": doc.get("department") if isinstance(doc.get("department"), str) and _present(doc["department"], full_haystack) else None,
        "documentVersionLabel": doc.get("documentVersionLabel") if isinstance(doc.get("documentVersionLabel"), str)
        and _present(doc["documentVersionLabel"], full_haystack) else None,
    }
    merged = {**doc, **tech}
    dropped = 0
    for name in LIST_FIELDS:
        kept = []
        for item in merged.get(name) or []:
            if isinstance(item, str) and (name in ("keywords", "tags") or _present(item, full_haystack)):
                kept.append(item.strip())
            else:
                dropped += 1
        target = result.document if name in ("authors", "keywords", "tags") else result.technical
        target[name] = list(dict.fromkeys(kept))
    if dropped:
        warnings.append(f"{dropped} extracted values were not found in the text and were dropped")
    return result
