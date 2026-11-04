"""Root-cause narrative over a comparison pack: the model proposes, code checks.

The model never sees the database and never computes a number. It gets the evidence pack from compare.py and must answer in a fixed JSON shape in which
every observation and hypothesis cites evidence ids. The result is verified before anyone sees it: unknown ids, uncited claims, numbers that are not in
the evidence, overconfident attribution when several factors changed at once. A failed check sends the model one correction round; if it still fails
the analysis is rejected instead of shown. Hypotheses are candidates to verify, never conclusions.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable

CONFIDENCE = ("low", "medium", "high")
MAX_HYPOTHESES = 5
FREE_INTEGERS = range(0, 11)  # "2 項", "第 3" and similar counting words are not data
SYSTEM_PROMPT = """你是 CSIT 測試報告的根因分析（RCA）助理。你只會拿到一份由程式整理好的「差異證據包」，不能查資料庫，也不能計算。
規則：
1. 只能根據證據包回答。每一條觀察與每一個假設都要在 evidence / supports 欄位列出證據編號（F#、D#、R#、C#、Q#、T#），只能使用證據包裡存在的編號。
2. 數值、單位、版本、通道、頻段一律原樣照抄證據包；不要自行計算、換算、四捨五入或估計，沒有出現在證據包的數字不要寫。
3. 先陳述事實（observations），再提出假設（hypotheses）。假設只是「待驗證的候選原因」，不是結論；每個假設要寫機制（mechanism）、支持與反對的證據、缺少什麼證據、信心等級（low/medium/high），以及具體的驗證步驟（verify_steps）。
4. confounded 為 true 時，代表韌體、硬體、晶片或乙太網路類型同時變動，無法歸因到單一因素：信心不得高於 medium，並在 data_gaps 說明需要如何拆開變因（例如只換一個變因重測）。
5. 沒有證據支持的機制只能是 low，且 supports 可以只引用觀察到的差異；不要把一般工程常識當成證據，也不要為它編造引用。
6. 指標的 higher_is_better 未定義時（assessment 為 changed），只描述差異，不要使用「較佳、較差、進步、退步、劣化」。
7. 證據包沒有解釋到的差異放進 unexplained；資料品質問題（Q#）、涵蓋缺口與單位不符放進 data_gaps，不要略過。
8. 以繁體中文回答，輸出單一 JSON 物件，不要加說明文字或程式碼區塊。格式：
{"summary": "...", "observations": [{"text": "...", "evidence": ["D1"]}],
 "hypotheses": [{"cause": "...", "mechanism": "...", "supports": ["F1","D1"], "against": [], "missing_evidence": ["..."], "confidence": "low", "verify_steps": ["..."]}],
 "unexplained": [{"text": "...", "evidence": ["D3"]}], "data_gaps": ["..."]}"""
BAN_WORDS_WHEN_UNDEFINED = ("較佳", "較差", "進步", "退步", "劣化", "變好", "變差")


class RcaError(RuntimeError):
    pass


def _norm(x: float) -> str:
    return f"{x:g}"


def allowed_numbers(evidence: dict[str, dict], extra_text: str = "") -> set[str]:
    """Every number the model may quote: those in the evidence (plus common roundings and magnitudes) and in the user's own question."""
    out: set[str] = set()

    def walk(v: Any) -> None:
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            for r in (v, round(v, 1), round(v, 2), round(v, 0)):
                out.add(_norm(float(r))); out.add(_norm(abs(float(r))))
        elif isinstance(v, str):
            for m in re.findall(r"-?\d+(?:\.\d+)?", v):
                out.add(_norm(float(m))); out.add(_norm(abs(float(m))))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
    walk(evidence)
    for m in re.findall(r"-?\d+(?:\.\d+)?", extra_text):
        out.add(_norm(float(m)))
    return out


def _strings(analysis: dict) -> list[str]:
    out = [str(analysis.get("summary") or "")]
    out += [str(o.get("text") or "") for o in analysis.get("observations", []) if isinstance(o, dict)]
    for h in analysis.get("hypotheses", []):
        if isinstance(h, dict):
            out += [str(h.get("cause") or ""), str(h.get("mechanism") or "")] + [str(x) for x in (h.get("missing_evidence") or []) + (h.get("verify_steps") or [])]
    out += [str(u.get("text") or "") for u in analysis.get("unexplained", []) if isinstance(u, dict)]
    out += [str(x) for x in analysis.get("data_gaps", [])]
    return out


def verify(analysis: Any, pack: dict, texts: dict[str, dict] | None = None, question: str = "") -> dict:
    """{'ok': bool, 'violations': [...], 'warnings': [...], 'analysis': cleaned} -- never raises on model output."""
    violations: list[str] = []
    warnings: list[str] = []
    evidence = {**pack.get("evidence", {}), **(texts or {})}
    if not isinstance(analysis, dict):
        return {"ok": False, "violations": ["輸出不是 JSON 物件"], "warnings": [], "analysis": None}
    analysis = copy.deepcopy(analysis)  # the caller's object is never edited
    for key in ("summary", "observations", "hypotheses", "unexplained", "data_gaps"):
        if key not in analysis:
            violations.append(f"缺少欄位 {key}")
    if violations:
        return {"ok": False, "violations": violations, "warnings": [], "analysis": None}
    cited: set[str] = set()

    def check_ids(ids: Any, where: str, *, required: bool) -> list[str]:
        ids = ids if isinstance(ids, list) else []
        if required and not ids:
            violations.append(f"{where} 沒有引用任何證據")
        good = []
        for i in ids:
            if i in evidence:
                good.append(i); cited.add(i)
            else:
                violations.append(f"{where} 引用了不存在的證據編號 {i}")
        return good

    for n, o in enumerate(analysis["observations"], 1):
        if not isinstance(o, dict) or not str(o.get("text") or "").strip():
            violations.append(f"observations[{n}] 格式不正確"); continue
        o["evidence"] = check_ids(o.get("evidence"), f"observations[{n}]", required=True)
    hyps = analysis["hypotheses"] if isinstance(analysis["hypotheses"], list) else []
    if len(hyps) > MAX_HYPOTHESES:
        warnings.append(f"假設超過 {MAX_HYPOTHESES} 個，只保留前 {MAX_HYPOTHESES} 個"); hyps = hyps[:MAX_HYPOTHESES]
    for n, h in enumerate(hyps, 1):
        if not isinstance(h, dict) or not str(h.get("cause") or "").strip():
            violations.append(f"hypotheses[{n}] 格式不正確"); continue
        h["supports"] = check_ids(h.get("supports"), f"hypotheses[{n}].supports", required=True)
        h["against"] = check_ids(h.get("against"), f"hypotheses[{n}].against", required=False)
        for k in ("missing_evidence", "verify_steps"):
            h[k] = [str(x) for x in (h.get(k) or []) if str(x).strip()]
        if not h["verify_steps"]:
            violations.append(f"hypotheses[{n}] 沒有驗證步驟")
        conf = h.get("confidence")
        if conf not in CONFIDENCE:
            violations.append(f"hypotheses[{n}].confidence 必須是 {CONFIDENCE}"); continue
        kinds = {evidence[i].get("kind") for i in h["supports"] if i in evidence}
        if conf == "high" and (len(h["supports"]) < 2 or not ({"factor", "condition"} & kinds) or not ({"measurement", "result"} & kinds)):
            h["confidence"] = "medium"; warnings.append(f"hypotheses[{n}] 的信心由 high 降為 medium：需要同時有變因與量測兩類證據")
        if pack.get("confounded") and h["confidence"] == "high":
            h["confidence"] = "medium"; warnings.append(f"hypotheses[{n}] 的信心由 high 降為 medium：多個變因同時變動，無法歸因")
    analysis["hypotheses"] = hyps
    for n, u in enumerate(analysis["unexplained"], 1):
        if isinstance(u, dict):
            u["evidence"] = check_ids(u.get("evidence"), f"unexplained[{n}]", required=False)
    if pack.get("confounded") and not any(("變因" in str(g) or "拆開" in str(g) or "重測" in str(g)) for g in analysis["data_gaps"]):
        violations.append("多個變因同時變動，data_gaps 必須說明如何拆開變因")
    if pack.get("quality") and not any("品質" in str(g) or "公式" in str(g) or "錯誤" in str(g) for g in analysis["data_gaps"]):
        warnings.append("證據包有資料品質旗標，但 data_gaps 沒有提到")
    allowed = allowed_numbers(evidence, question)
    stray = sorted({m for s in _strings(analysis) for m in re.findall(r"(?<![A-Za-z#\[])-?\d+(?:\.\d+)?", re.sub(r"\[[A-Z]\d+\]", "", s))
                    if _norm(float(m)) not in allowed and not (float(m).is_integer() and int(float(m)) in FREE_INTEGERS)})
    if stray:
        violations.append("出現證據包以外的數字：" + "、".join(stray[:8]))
    if not pack.get("directions_defined"):
        text = "\n".join(_strings(analysis))
        banned = [w for w in BAN_WORDS_WHEN_UNDEFINED if w in text]
        if banned:
            violations.append("指標好壞方向尚未定義，不可使用：" + "、".join(banned))
    analysis["cited"] = sorted(cited)
    return {"ok": not violations, "violations": violations, "warnings": warnings, "analysis": analysis if not violations else None}


def pack_for_prompt(pack: dict, texts: dict[str, dict] | None = None) -> str:
    """The evidence the model sees: findings with ids, not the raw rows. Text evidence (T#) from the knowledge base is appended when supplied."""
    view = {k: pack[k] for k in ("runs", "factors", "confounded", "confounded_note", "counts", "diffs", "coverage", "result_changes", "criteria_changes", "quality", "directions_defined")
            if k in pack}
    for d in view.get("diffs", []):
        d.pop("key", None)
    if texts:
        view["knowledge_texts"] = list(texts.values())
    return json.dumps(view, ensure_ascii=False, default=str)


def run_rca(pack: dict, llm: Callable[[list[dict]], str], *, texts: dict[str, dict] | None = None, question: str = "", retries: int = 1) -> dict:
    """llm(messages) -> str. Returns {'status': 'ok'|'rejected', 'analysis', 'violations', 'warnings', 'attempts'}."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": (f"使用者關心：{question}\n" if question else "") + "證據包：\n" + pack_for_prompt(pack, texts)}]
    violations: list[str] = []
    result: dict = {"ok": False, "violations": ["未取得回答"], "warnings": [], "analysis": None}
    for attempt in range(1, retries + 2):
        reply = llm(messages)
        try:
            raw = json.loads(re.search(r"\{.*\}", reply or "", re.S).group(0))
        except (AttributeError, ValueError):
            raw = None
        result = verify(raw, pack, texts, question)
        if result["ok"]:
            return {"status": "ok", "analysis": result["analysis"], "violations": [], "warnings": result["warnings"], "attempts": attempt}
        violations = result["violations"]
        messages += [{"role": "assistant", "content": (reply or "")[:4000]},
                     {"role": "user", "content": "你的輸出未通過檢查，請只修正下列問題後重新輸出完整 JSON：\n- " + "\n- ".join(violations[:10])}]
    return {"status": "rejected", "analysis": None, "violations": violations, "warnings": result["warnings"], "attempts": retries + 1}
