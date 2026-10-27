"""Relation questions over the concept graph: which tests cover X, what X depends on, how A and B are connected.

Read-only and bounded like the other graph tools. The graph is LLM-extracted from part of the zone's documents; every relation carries a verbatim evidence
sentence from the document it came from, and those sentences are registered as ordinary [S#] citations so the grounding check sees them. Off by default
(KM_WIFI8_CONCEPTS); without Neo4j or without loaded concepts the tools answer with an error and nothing else changes.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

RELATION_TYPES = ("USES", "PART_OF", "IMPROVES", "RELATED_TO", "ENABLES", "TESTED_BY", "LIMITED_TO", "DEPENDS_ON", "COMPARED_WITH", "INTRODUCED_IN")
DIRECTIONS = ("out", "in", "both")
MAX_PER_RELATION = 8
MAX_CANDIDATES = 5
COVERAGE_NOTE = ("概念圖譜由 LLM 從部分文件（MRD、認證測試案例與測試計畫、會議紀錄、過濾後的論文）自動抽取，未涵蓋專區全部文件；"
                 "圖譜沒有的關係不代表文件沒寫。關係的依據是下列原文句子（有 ref），回答時只引用有 ref 的句子，並註明來源是概念圖譜。")

CONCEPT_TOOLS = [
    {"type": "function", "function": {
        "name": "concept_relations",
        "description": "概念圖譜：某個功能、機制、欄位或測項的關係。用於「X 有哪些測項」「X 依賴／使用什麼」「X 屬於哪個功能」「X 改善什麼」這類關係型問題。"
                       "每筆關係附原文證據句與 [S#] 編號。圖譜只涵蓋部分文件，結論要與 search_wifi 的結果互相印證。",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "概念名稱或縮寫，技術名詞用英文原文，例如 NPCA、DSO、EMLSR"},
            "relation_type": {"type": "string", "enum": list(RELATION_TYPES), "description": "只看某一種關係；省略則列出全部。TESTED_BY＝被哪些測項測試，DEPENDS_ON＝依賴，PART_OF＝屬於"},
            "direction": {"type": "string", "enum": list(DIRECTIONS), "description": "out＝此概念指向其他概念（X 使用／依賴／被測試於…），in＝其他概念指向此概念，預設 both"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "concept_compare",
        "description": "概念圖譜：比較兩個概念的連結——兩者直接的關係、共同提到它們的文件、共同關聯的其他概念。用於「A 和 B 有什麼關係／差異」「兩者共同出現在哪些文件」。",
        "parameters": {"type": "object", "properties": {
            "a": {"type": "string", "description": "第一個概念名稱，例如 NPCA"},
            "b": {"type": "string", "description": "第二個概念名稱，例如 DSO"}}, "required": ["a", "b"]}}},
]

CONCEPT_PROMPT = """
關係型問題（本次已啟用概念圖譜）：問題在問測項、依賴、組成、改善、兩個功能之間的關係時，先用 concept_relations 或 concept_compare 取得關係與原文證據句，再用 search_wifi 查證重要結論；回答時：
- 只使用工具回傳、有 [S#] 編號的證據句，句末標註；圖譜沒有找到時，明說「概念圖譜未找到」，不要用常識補。
- 註明這類關係來自概念圖譜（LLM 自動抽取、僅涵蓋部分文件），圖譜與文件檢索不一致時以文件段落為準，並說明差異。
- 關係的方向要照工具回傳的 direction 表達（out：此概念 → 對方；in：對方 → 此概念）。"""


def key(name: str) -> str:
    """Identity of a name for lookup: lower case, punctuation dropped, plural folded."""
    tokens = [t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t for t in re.findall(r"[0-9a-z一-鿿]+", str(name).lower().replace("+", " plus "))]
    return "".join(tokens)


def resolve(index: list[dict[str, Any]], name: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """(best concept, other candidates). Exact name/alias key wins; otherwise a longer name that contains the query. The most documented concept comes first."""
    q = key(name)
    if len(q) < 2:
        return None, []
    exact = [c for c in index if q in {key(n) for n in [c["name"], *(c.get("aliases") or [])]}]
    pool = exact or ([c for c in index if q in key(c["name"])] if len(q) >= 4 else [])
    pool = sorted(pool, key=lambda c: (-int(c.get("doc_count") or 0), len(c["name"]), c["name"]))
    return (pool[0], pool[1:1 + MAX_CANDIDATES]) if pool else (None, [])


class ConceptTools:
    """Handlers bound to one WifiTools instance (its graph, document store and citation registry)."""

    def __init__(self, tools: Any) -> None:
        self.tools = tools

    # -- helpers ---------------------------------------------------------
    def _docs(self) -> dict[str, dict[str, Any]]:
        return {d["revision_id"]: d for d in self.tools.store.documents()}

    def _cite(self, evidence: str, docs: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        """evidence is "<revision_id>: <quote>" as the loader wrote it."""
        rid, _, quote = str(evidence).partition(": ")
        quote = quote.strip()
        doc = docs.get(rid)
        if not rid or not quote or doc is None:
            return None
        ref = self.tools.citations.add({
            "revision_id": rid, "point_id": f"concept:{rid}:{hashlib.sha1(quote.encode()).hexdigest()[:12]}", "source": doc.get("title"), "content": quote,
            "location_label": "概念圖譜證據句", "wfa_document_id": doc.get("wfa_document_id"), "wfa_revision": doc.get("wfa_revision"),
            "document_role": doc.get("document_role"), "publisher": doc.get("publisher"), "document_date": doc.get("document_date"),
            "analysis_eligible": doc.get("analysis_eligible")})
        return {"ref": ref, "title": doc.get("title"), "quote": quote[:400], "current_version": doc.get("analysis_eligible")}

    def _concept(self, name: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        graph = self.tools.graph
        if graph is None:
            return None, {"error": "知識圖譜目前不可用"}
        index = graph.concept_index()
        if not index:
            return None, {"error": "概念圖譜尚未載入此專區"}
        best, others = resolve(index, name)
        if best is None:
            near = [c["name"] for c in index if key(name)[:4] and key(name)[:4] in key(c["name"])][:5]
            return None, {"error": f"概念圖譜找不到「{name}」", **({"similar_names": near} if near else {}), "note": COVERAGE_NOTE}
        best = {**best, "_others": [c["name"] for c in others]}
        return best, None

    # -- tools ------------------------------------------------------------
    def concept_relations(self, name: str, relation_type: str = "", direction: str = "both"):
        relation_type = str(relation_type or "").upper()
        if relation_type and relation_type not in RELATION_TYPES:
            return {"error": f"relation_type 必須是 {', '.join(RELATION_TYPES)} 其中之一"}
        direction = direction if direction in DIRECTIONS else "both"
        concept, error = self._concept(name)
        if error:
            return error
        graph, docs = self.tools.graph, self._docs()
        rows = graph.concept_relations(concept["concept_id"], relation_type)
        wanted = [r for r in rows if direction == "both" or r["direction"] == direction]
        # The model often picks the wrong direction (tests of X hang off X as "out", but "in" reads naturally): an empty filter falls back to both.
        fallback = bool(rows) and not wanted
        rows = rows if fallback else wanted
        rows.sort(key=lambda r: (-(r.get("support_docs") or 0), -(r.get("confidence") or 0), r["other"]))
        grouped: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            bucket = grouped.setdefault(f"{r['direction']}:{r['relation']}", [])
            if len(bucket) >= MAX_PER_RELATION:
                continue
            evidence = [e for e in (self._cite(x, docs) for x in (r.get("evidence") or [])[:2]) if e]
            bucket.append({"other": r["other"], "other_type": r["other_type"], "support_docs": r.get("support_docs"),
                           **({"weak": True} if r.get("weak") else {}), "evidence": evidence})
        documents = graph.concept_documents(concept["concept_id"], 10)
        return {"concept": {"name": concept["name"], "type": concept["type"], "aliases": (concept.get("aliases") or [])[:6], "documents": concept.get("doc_count")},
                **({"other_matches": concept["_others"]} if concept["_others"] else {}),
                **({"direction_note": f"指定方向（{direction}）沒有結果，已列出另一個方向；請依各筆的 direction／meaning 表達方向"} if fallback else {}),
                "relations": [{"direction": k.split(":")[0], "relation": k.split(":")[1], "meaning": f"{concept['name']} → 對方" if k.startswith("out") else f"對方 → {concept['name']}",
                               "total": sum(1 for r in rows if f"{r['direction']}:{r['relation']}" == k), "items": v} for k, v in grouped.items()],
                "mentioned_in": [{"title": d["title"], "document_role": d.get("document_role"), "revision_id": d["revision_id"]} for d in documents],
                "note": COVERAGE_NOTE}

    def concept_compare(self, a: str, b: str):
        first, error = self._concept(a)
        if error:
            return error
        second, error = self._concept(b)
        if error:
            return error
        if first["concept_id"] == second["concept_id"]:
            return {"error": "兩個名稱是同一個概念", "concept": first["name"]}
        graph, docs = self.tools.graph, self._docs()
        direct = [r for r in graph.concept_relations(first["concept_id"]) if r["other_id"] == second["concept_id"]]
        shared = graph.concept_shared_documents(first["concept_id"], second["concept_id"])
        common = graph.concept_common(first["concept_id"], second["concept_id"])
        return {"a": {"name": first["name"], "type": first["type"], "documents": first.get("doc_count")},
                "b": {"name": second["name"], "type": second["type"], "documents": second.get("doc_count")},
                "direct_relations": [{"direction": r["direction"], "relation": r["relation"], "support_docs": r.get("support_docs"),
                                      "meaning": f"{first['name']} → {second['name']}" if r["direction"] == "out" else f"{second['name']} → {first['name']}",
                                      "evidence": [e for e in (self._cite(x, docs) for x in (r.get("evidence") or [])[:2]) if e]} for r in direct],
                "shared_documents": [{"title": d["title"], "document_role": d.get("document_role"), "revision_id": d["revision_id"]} for d in shared],
                "shared_documents_count": len(shared),
                "common_concepts": [{"name": c["name"], "type": c["type"], "with_a": c["with_a"], "with_b": c["with_b"]} for c in common],
                "note": COVERAGE_NOTE}
