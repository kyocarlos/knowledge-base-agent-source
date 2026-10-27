"""Extension layer of a WiFi zone answer: related knowledge, general knowledge (labelled) and follow-up questions.

Off by default (KM_WIFI8_AGENT_EXTENSION). The grounding check only ever sees the main answer; the extension is split off in code, never trusted to the model.
"""
from __future__ import annotations

import re
from typing import Any

HEADING = re.compile(r"^\s{0,3}#{1,4}\s*延伸知識\s*$", re.M)
SUB_HEADING = re.compile(r"^\s{0,3}#{2,5}\s*(.+?)\s*$", re.M)
DISCLAIMER = "以下為模型的一般知識，未經專區文件驗證"
RULE7_ORIGINAL = "7. 資料不足或找不到時，只說明已確認什麼、缺什麼；不要補上一般常識、可能原因或建議（例如「費用通常取決於…」「建議向…詢價」）。"
RULE7_EXTENDED = ("7. 主體回答（延伸知識之前）資料不足或找不到時，只說明已確認什麼、缺什麼；不要在主體補上一般常識、可能原因或建議。"
                  "一般知識只能放在最後的「延伸知識」區塊。")

EXTENSION_RULES = """
延伸知識（本次已啟用）：主體回答照上述規則寫完後，另起一段，標題固定為「## 延伸知識」，內含以下小節（沒有內容的小節整段省略，不要硬湊）：
- 「### 相關主題與文件」：用 graph_related／graph_timeline 取得的相關主題、相關文件、版本沿革，句末標註 [G#]；若引用文件段落內容則標註 [S#]。只列工具回傳的內容。
- 「### 一般知識補充」：第一行固定寫「（%s）」，接著補充背景、原理、與其他技術的關係、實務上的考量。這一節不要標註 [S#]、[G#]，不要寫出專區文件裡的數值、版本、日期、文件名稱，也不要宣稱專區文件說過什麼；沒有把握的內容不要寫。最多 6 句。
- 「### 你可能還想問」：2 到 3 個與使用者問題相關、專區文件可能回答得了的後續問題，每題一行，以「- 」開頭。
延伸知識的總長度不超過主體回答的一半。資料不足而拒答時，不要寫延伸知識。""" % DISCLAIMER


def extended_prompt(base_prompt: str) -> str:
    """The base prompt with rule 7 narrowed to the main answer, plus the extension rules."""
    return base_prompt.replace(RULE7_ORIGINAL, RULE7_EXTENDED) + EXTENSION_RULES


def split_answer(answer: str) -> tuple[str, dict[str, Any] | None]:
    """(main answer, extension) -- extension is None when the model wrote none. Never raises."""
    match = HEADING.search(answer or "")
    if not match:
        return (answer or "").strip(), None
    main, rest = answer[:match.start()].rstrip(), answer[match.end():]
    sections: dict[str, str] = {}
    marks = list(SUB_HEADING.finditer(rest))
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(rest)
        sections[mark.group(1)] = rest[mark.end():end].strip()
    related = next((v for k, v in sections.items() if "相關" in k), "")
    general = next((v for k, v in sections.items() if "一般知識" in k), "")
    followups = [re.sub(r"^[-*•\d.)\s]+", "", line).strip() for line in next((v for k, v in sections.items() if "還想問" in k), "").splitlines()
                 if line.strip()][:3]
    warnings = []
    if re.search(r"\[[SG]\d+\]", general):
        warnings.append("general_knowledge_has_citation")
    if general and DISCLAIMER not in general:
        general = f"（{DISCLAIMER}）\n" + general  # the label is guaranteed by code, not left to the model
    extension = {"related": related, "general": general, "followups": [f for f in followups if f], "warnings": warnings}
    if not any((related, general, extension["followups"])):
        return main, None
    return main, extension
