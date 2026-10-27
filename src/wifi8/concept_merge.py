"""Cross-document concept merging: code proposes candidate pairs, the LLM judges them, approved pairs become aliases (a data file, no code change).

Candidates come from three cheap signals (similar key, acronym of the other name, similar embedding). Pairs that differ in a distinguishing token
(UL/DL, band, bandwidth, a number) are never candidates: "UL OFDMA" and "DL OFDMA" are different concepts however similar they look.
"""
from __future__ import annotations

import difflib
import json
import re
from typing import Any, Callable, Iterable

from .concepts import Rules, concept_key, norm, parse_json

JUDGE_PROMPT = """判斷下面兩個名稱在 Wi-Fi 技術文件中是否指同一個概念（同一功能、機制、欄位、參數或標準），只輸出 JSON：{"same": true|false, "canonical": "較好的名稱", "reason": "一句話"}。
規則：只是縮寫與全名、單複數、寫法或連字號不同才算相同；方向（UL／DL）、頻段、頻寬、版本、階段不同，或一個是另一個的子功能／上位概念，就不是同一個。拿不準就回 false。
A：%s（類型 %s；別名 %s）
  出現位置與依據：%s
B：%s（類型 %s；別名 %s）
  出現位置與依據：%s"""


def tokens(name: str) -> set[str]:
    return set(re.findall(r"[0-9a-z.]+", norm(name)))


def acronym(name: str) -> str:
    words = re.findall(r"[0-9a-zA-Z]+", re.sub(r"\([^)]*\)", " ", name))
    return "".join(w[0] for w in words).lower() if len(words) >= 2 else ""


def differs_in_distinguishing_token(a: str, b: str, rules: Rules) -> bool:
    dist = {t.lower() for t in rules.merge.get("distinguishing_tokens", [])}
    return (tokens(a) ^ tokens(b)) & dist != set()


def candidates(concepts: list[dict[str, Any]], rules: Rules, encode: Callable[[list[str]], Iterable[Iterable[float]]] | None = None) -> list[dict[str, Any]]:
    """concepts: aggregate()["concepts"]. Returns [{"a": concept_id, "b": concept_id, "signals": [...], "score": float}] best first, capped."""
    cfg = rules.merge
    ratio_min, vec_min, cap = float(cfg.get("name_ratio", 0.88)), float(cfg.get("vector_similarity", 0.9)), int(cfg.get("max_candidates", 300))
    out: dict[tuple[str, str], dict[str, Any]] = {}

    def add(x: dict, y: dict, signal: str, score: float) -> None:
        if differs_in_distinguishing_token(x["name"], y["name"], rules):
            return
        k = tuple(sorted((x["concept_id"], y["concept_id"])))
        e = out.setdefault(k, {"a": k[0], "b": k[1], "signals": [], "score": 0.0})
        e["signals"].append(signal)
        e["score"] = max(e["score"], score)

    n = len(concepts)
    keys = [concept_key(c["name"], rules) for c in concepts]
    acr = [{acronym(c["name"]), *[acronym(a) for a in c.get("aliases", [])]} - {""} for c in concepts]
    for i in range(n):
        sm = difflib.SequenceMatcher(None)
        sm.set_seq2(keys[i])  # seq2 is indexed once; the cheap upper bounds skip most pairs before the full ratio
        for j in range(i + 1, n):
            ci, cj = concepts[i], concepts[j]
            if keys[i] == keys[j]:
                continue
            if abs(len(keys[i]) - len(keys[j])) <= 6:
                sm.set_seq1(keys[j])
                if sm.real_quick_ratio() >= ratio_min and sm.quick_ratio() >= ratio_min:
                    r = sm.ratio()
                    if r >= ratio_min:
                        add(ci, cj, "name", r)
            if keys[j] in acr[i] or keys[i] in acr[j]:
                add(ci, cj, "acronym", 0.95)
    if encode is not None and n > 1:
        import numpy as np
        vecs = np.asarray([list(map(float, v)) for v in encode([c["name"] for c in concepts])], dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1)
        vecs = vecs / np.where(norms == 0, 1.0, norms)[:, None]
        step = 512
        for lo in range(0, n, step):  # blocked matrix product: only the upper triangle is read
            sims = vecs[lo:lo + step] @ vecs.T
            rows, cols = np.nonzero(sims >= vec_min)
            for r, c in zip(rows.tolist(), cols.tolist()):
                i = lo + r
                if c > i and keys[i] != keys[c]:
                    add(concepts[i], concepts[c], "vector", float(sims[r, c]))
    return sorted(out.values(), key=lambda e: (-len(e["signals"]), -e["score"]))[:cap]


def describe(concept: dict[str, Any], evidence_for: dict[str, str]) -> tuple:
    return concept["name"], concept["type"], "、".join(concept.get("aliases", [])[:6]) or "（無）", evidence_for.get(concept["concept_id"], "（無）")


def judge_prompt(a: dict, b: dict, evidence_for: dict[str, str]) -> str:
    return JUDGE_PROMPT % (*describe(a, evidence_for), *describe(b, evidence_for))


def parse_decision(raw: str) -> dict[str, Any] | None:
    data = parse_json(raw)
    if not data or not isinstance(data.get("same"), bool):
        return None
    return {"same": data["same"], "canonical": str(data.get("canonical") or ""), "reason": str(data.get("reason") or "")[:200]}


def merges_file(decisions: Iterable[dict[str, Any]], concepts_by_id: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Approved decisions -> {canonical name: [alias names]} (the shape load_rules() accepts). Chains (A=B, B=C) end up under one canonical name."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    approved = [d for d in decisions if d.get("same") and d["a"] in concepts_by_id and d["b"] in concepts_by_id]
    for d in approved:
        parent[find(d["b"])] = find(d["a"])
    groups: dict[str, set[str]] = {}
    for d in approved:
        for cid in (d["a"], d["b"]):
            groups.setdefault(find(cid), set()).add(cid)
    wanted = {find(d["a"]): d["canonical"] for d in approved if d.get("canonical")}
    out: dict[str, list[str]] = {}
    for root, members in groups.items():
        names = {concepts_by_id[m]["name"]: concepts_by_id[m].get("doc_count", 0) for m in members}
        canonical = wanted.get(root) if wanted.get(root) in names else max(names, key=lambda n: (names[n], -len(n)))
        out[canonical] = sorted(set(names) - {canonical})
    return out
