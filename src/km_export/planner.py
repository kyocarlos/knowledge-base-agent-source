"""Turn an assistant answer into an ``ExportSpec`` with the language model.

The model may only reorganise what the answer and its sources already say; the prompt forbids new facts and the result is validated
before anything is written to a file.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable

from pydantic import ValidationError

from .spec import FORMATS, ExportSpec

logger = logging.getLogger(__name__)
Complete = Callable[[list[dict]], str]

SYSTEM = """你是文件整理助理。使用者剛從知識庫助理得到一份回答，現在想把它整理成檔案。
規則：
1. 內容只能來自「回答」與「來源」。不可新增回答裡沒有的事實、數字、規格或結論；數字、單位、型號、版本一律照原文。
2. 依使用者的需求決定結構與詳略（例如頁數、對象、語氣）。沒有特別要求時，簡報每頁 3 到 6 點，文件分章節。
3. 適合用表格的比較或清單用 table（columns 與 rows，每個儲存格都是字串）；其餘用 bullets 或 paragraphs。
4. 每個 section 的 sources 只列「來源」清單裡真的有的項目（可簡寫文件名稱與版本），沒有就留空陣列。
5. 輸出只能是一個 JSON 物件，不要任何說明文字或程式碼框。格式：
{"format": "pptx|docx|xlsx|md|csv|html", "title": "...", "subtitle": "...",
 "sections": [{"heading": "...", "paragraphs": ["..."], "bullets": ["..."],
               "table": {"columns": ["..."], "rows": [["..."]]}, "sources": ["..."]}]}
table 沒有就省略。使用語言與回答一致（通常是繁體中文）。"""


class PlanError(RuntimeError):
    """The model did not return a usable plan."""


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object in the reply")
        text = text[start:end + 1]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("the reply is not a JSON object")
    return value


def build_messages(question: str, answer: str, sources: list[str], request: str, fmt: str | None) -> list[dict]:
    wanted = f"檔案格式：{fmt}（format 欄位必須是 {fmt}）" if fmt else f"檔案格式：使用者沒指定時由你從 {', '.join(FORMATS)} 擇一"
    listing = "\n".join(f"[{i}] {s}" for i, s in enumerate(sources, 1)) or "（沒有列出來源）"
    user = (f"使用者原本的問題：\n{question or '（未提供）'}\n\n回答：\n{answer}\n\n來源：\n{listing}\n\n"
            f"使用者對檔案的需求：\n{request.strip() or '（沒有特別要求，請做出適合閱讀的版本）'}\n\n{wanted}")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def plan(complete: Complete, *, question: str, answer: str, sources: list[str], request: str = "", fmt: str | None = None) -> ExportSpec:
    if fmt is not None and fmt not in FORMATS:
        raise PlanError("unsupported format")
    messages = build_messages(question, answer, sources, request, fmt)
    last = "unknown"
    for attempt in range(2):
        try:
            reply = complete(messages)
        except Exception as exc:  # noqa: BLE001 - the gateway can fail in many ways; the caller shows one clear message
            logger.warning("export plan: model call failed (%s)", type(exc).__name__)
            raise PlanError("llm_unavailable") from exc
        try:
            data = _extract_json(reply)
            if fmt:
                data["format"] = fmt
            return ExportSpec.model_validate(data)
        except (ValueError, ValidationError) as exc:
            last = type(exc).__name__
            messages = [*messages, {"role": "assistant", "content": reply[:4000]},
                        {"role": "user", "content": "上一個輸出不是有效的指定 JSON 格式。請只輸出一個符合格式的 JSON 物件。"}]
    logger.warning("export plan: invalid model output after retry (%s)", last)
    raise PlanError("invalid_plan")
