"""Concept extraction for the WiFi zone graph: windows of chunk text -> LLM -> validated concepts/relations -> aggregated graph rows.

Decision (2026-10-22): relations extracted by the LLM are written without human review (an explicit exception to KM v2.6 for this zone). What keeps
them honest is code, not review: every relation must quote a passage that really occurs in the window it came from, both ends must be named in
that window, and the relation type must be one of a fixed list. Every row keeps its evidence, model and run so a wrong edge can be traced and removed.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

CONCEPT_TYPES = ("Feature", "Mechanism", "Field", "Parameter", "Metric", "Standard", "TestItem")
RELATION_TYPES = ("PART_OF", "DEPENDS_ON", "ENABLES", "IMPROVES", "COMPARED_WITH", "USES", "TESTED_BY", "INTRODUCED_IN", "LIMITED_TO", "RELATED_TO")
MAX_EVIDENCE_CHARS = 200
MAX_CONCEPTS, MAX_RELATIONS = 25, 30

PROMPT = """你是 Wi-Fi 技術知識圖譜的抽取器。只根據下面「文件內容」抽取，輸出單一 JSON 物件，不要任何其他文字。
目標：找出文件中明確提到的技術概念，以及概念之間的關係。
概念（concepts）：具名的 Wi-Fi 功能、機制、欄位、參數、量測指標、標準版本、測試項目；一般詞彙（例如 data、device、network）不要抽。不要抽組織、公司、會議、工作小組、委員會與流程（例如 TTG、MTG、BoD、Wi-Fi Alliance、廠商名稱）；不要抽「Security」「MRD」「test cases」這類過於籠統的詞，要抽就抽具體名稱（例如 WPA3-Enterprise、Control frame protection）。名稱用文件裡的英文原文，不可被截斷（括號要成對）；縮寫與全名都出現時，name 一律用文件中最常用的寫法（通常是縮寫，例如 DRU、ELR、NPCA），全名放 aliases。type 只能是：%s。
關係（relations）：source 與 target 必須是你列在 concepts 的名稱。type 只能是下列之一，方向如下：
- PART_OF：source 是 target 的一部分或子功能、欄位
- DEPENDS_ON：source 需要 target 才能運作，或「若實作／啟用 source，則必須實作 target」。條件式要求（「If X is implemented, Y shall be implemented」）一律用 DEPENDS_ON，source 是 X、target 是 Y，不要用 ENABLES
- ENABLES：source 使 target 得以實現（target 是能力或結果）
- IMPROVES：source 改善 target（效能、可靠度、延遲…）
- COMPARED_WITH：source 與 target 被明確比較或互相替代
- USES：source 使用 target（欄位、機制、參數）
- TESTED_BY：source 是被測的功能或欄位，target 是測試項目或測試案例（方向不可相反）
- INTRODUCED_IN：文件明確寫出 source 由 target（標準、版本或認證計畫，例如 "defined in the Wi-Fi 8 program"）定義或引入。只是參考文獻清單或章節標題，沒有寫出功能與版本的關係，就不要輸出
- LIMITED_TO：source 僅限、僅定義或僅適用於 target 的範圍（方向如 uplink／downlink、頻段、頻寬、模式、認證計畫範圍），例如「ELR is only defined for UL operation」「DSO is only applicable to 5 GHz and 6 GHz」
- RELATED_TO：確定有關但不屬於上述任何一種；盡量不用，使用時 evidence 必須同時提到 source 與 target
每個關係必須附 evidence：從文件內容中逐字複製的一小段（不超過 %d 字元，不要改寫、不要翻譯、不要用「…」省略、不要在字詞中間截斷），這段文字必須同時支持這個關係及其方向。找不到逐字依據的關係不要輸出。confidence 為 0 到 1 的數字。
請盡量完整：文件中每一項明確的需求、限制、適用範圍、條件、欄位組成、測試步驟與所述的效益，只要有逐字證據，都要有對應的關係，不要只挑最重要的幾條。至多 %d 個概念、%d 個關係；沒有就輸出空陣列。已知名稱（若文件談到同一個東西請沿用這些名稱）：%s
輸出格式：{"concepts":[{"name":str,"type":str,"aliases":[str]}],"relations":[{"source":str,"type":str,"target":str,"evidence":str,"confidence":number}]}
文件標題：%s
文件內容：
%s"""


def build_prompt(title: str, text: str, known: Iterable[str], scope: str = "") -> str:
    """scope: optional extra instruction (e.g. the Wi-Fi relevance limit for papers), inserted before the output-format line."""
    prompt = PROMPT % ("、".join(CONCEPT_TYPES), MAX_EVIDENCE_CHARS, MAX_CONCEPTS, MAX_RELATIONS, "、".join(list(known)[:60]) or "（無）", title, text)
    return prompt.replace("輸出格式：", scope + "輸出格式：", 1) if scope else prompt


def norm(text: str) -> str:
    """Comparison form: case-insensitive, whitespace collapsed, typographic dashes/quotes unified."""
    text = text.translate({0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x00A0: " "})
    return re.sub(r"\s+", " ", text).strip().casefold()


def norm_keep_case(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate({0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x00A0: " "})).strip()


def cut_mid_word(text_keep: str, text_norm: str, quote_norm: str) -> bool:
    """True when the quote stops inside a word of the source (lower-case letter followed by lower-case letter, or digit by digit). A lower->Upper or
    letter->digit change is a table-cell boundary in flattened tables ("...transmissionUHR DL OFDMA"), which is a complete quote."""
    i = text_norm.find(quote_norm)
    end = i + len(quote_norm)
    if i < 0 or end >= len(text_norm) or len(text_keep) != len(text_norm):
        return False
    prev, nxt = text_keep[end - 1], text_keep[end]
    return (prev.islower() and nxt.islower()) or (prev.isdigit() and nxt.isdigit())


def _singular(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and len(token) >= 5 and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


@dataclass
class Rules:
    never: set[str] = field(default_factory=set)
    organizations: set[str] = field(default_factory=set)
    no_related_to: set[str] = field(default_factory=set)
    both_endpoints: set[str] = field(default_factory=set)
    target_types: dict[str, set[str]] = field(default_factory=dict)  # relation type -> concept types its target may have
    strip_suffix: set[str] = field(default_factory=set)
    min_evidence: int = 12
    weak_threshold: int = 2
    relevance: dict[str, Any] = field(default_factory=dict)  # see concept_rules.json "relevance"
    merge: dict[str, Any] = field(default_factory=dict)      # see concept_rules.json "merge"
    alias_key: dict[str, str] = field(default_factory=dict)   # normalised key -> canonical key
    canonical_name: dict[str, str] = field(default_factory=dict)  # canonical key -> display name


def concept_key(name: str, rules: Rules | None = None) -> str:
    """Identity of a concept name: tokens lower-cased, plural folded, trailing field/element/frame words dropped, then alias-mapped."""
    tokens = [_singular(t) for t in re.findall(r"[0-9a-z\u4e00-\u9fff]+", norm(name).replace("+", " plus "))]
    if rules:
        while len(tokens) > 1 and tokens[-1] in rules.strip_suffix:
            tokens.pop()
    key = "".join(tokens)
    return rules.alias_key.get(key, key) if rules else key


def load_rules(path: str | Path | None = None, merges: str | Path | None = None) -> Rules:
    """merges: optional JSON file {canonical name: [aliases]} of approved cross-document merges (same shape as "aliases"); it only adds to the rules."""
    data = json.loads(Path(path or Path(__file__).with_name("concept_rules.json")).read_text("utf-8"))
    if merges and Path(merges).exists():
        extra = json.loads(Path(merges).read_text("utf-8"))
        data["aliases"] = {**(data.get("aliases") or {}), **{k: sorted(set(v) | set((data.get("aliases") or {}).get(k, []))) for k, v in extra.items()}}
    r = Rules(relevance=data.get("relevance") or {}, merge=data.get("merge") or {}, min_evidence=int(data.get("min_evidence_chars", 12)), weak_threshold=int(data.get("weak_support_threshold", 2)),
              both_endpoints=set(data.get("evidence_mentions_both", [])), target_types={k: set(v) for k, v in (data.get("relation_target_types") or {}).items()}, strip_suffix={_singular(t.lower()) for t in data.get("strip_suffix_tokens", [])})
    for name, aliases in (data.get("aliases") or {}).items():
        canonical = concept_key(name, r)
        r.canonical_name[canonical] = name
        for a in [name, *aliases]:
            r.alias_key[concept_key(a, r)] = canonical
    r.never = {concept_key(n, r) for n in data.get("never_concepts", [])}
    r.organizations = {concept_key(n, r) for n in data.get("organization_names", [])}
    r.no_related_to = {concept_key(n, r) for n in data.get("no_related_to", [])}
    return r


def relevance_applies(role: str | None, rules: Rules) -> bool:
    return bool(rules.relevance) and (role or "") in set(rules.relevance.get("roles") or [])


def relevance_hits(text: str, rules: Rules) -> int:
    pattern = rules.relevance.get("pattern")
    return len(re.findall(pattern, text, re.I)) if pattern else 0


def document_relevance(title: str, text: str, rules: Rules) -> dict[str, Any]:
    """Density of Wi-Fi vocabulary per 1000 characters (or a Wi-Fi word in the title) decides whether a document of a filtered role is processed."""
    density = relevance_hits(text, rules) / max(1, len(text)) * 1000
    by_title = bool(rules.relevance.get("title_pattern")) and re.search(rules.relevance["title_pattern"], title or "", re.I) is not None
    return {"density": round(density, 2), "title_match": by_title, "relevant": by_title or density >= float(rules.relevance.get("min_doc_density", 2.0))}


def window_relevant(text: str, rules: Rules) -> bool:
    return relevance_hits(text, rules) >= int(rules.relevance.get("min_window_hits", 2))


def build_windows(chunks: list[dict[str, Any]], max_chars: int = 6000) -> list[dict[str, Any]]:
    """Consecutive chunks of one document grouped up to ``max_chars`` (a single longer chunk is its own window)."""
    windows, current, size = [], [], 0
    for chunk in sorted(chunks, key=lambda c: c["chunk_index"]):
        text = chunk.get("content") or ""
        if current and size + len(text) > max_chars:
            windows.append(current)
            current, size = [], 0
        current.append(chunk)
        size += len(text) + 2
    if current:
        windows.append(current)
    out = []
    for i, group in enumerate(windows):
        out.append({"window_id": f"{group[0]['revision_id']}#{group[0]['chunk_index']}-{group[-1]['chunk_index']}", "revision_id": group[0]["revision_id"],
                    "title": group[0].get("source_name") or group[0].get("doc_name") or "", "chunk_indexes": [c["chunk_index"] for c in group],
                    "text": "\n\n".join(c.get("content") or "" for c in group), "index": i})
    return out


def parse_json(raw: str) -> dict[str, Any] | None:
    try:
        match = re.search(r"\{.*\}", raw or "", re.S)
        data = json.loads(match.group(0)) if match else None
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


@dataclass
class Validated:
    concepts: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    dropped: Counter = field(default_factory=Counter)


def alnum(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _balanced(name: str) -> bool:
    return name.count("(") == name.count(")") and name.count("[") == name.count("]")


def validate(data: dict[str, Any] | None, window_text: str, rules: Rules | None = None) -> Validated:
    """Keep only what the window text itself supports. Reasons for every drop are counted (this is the hallucination rate)."""
    rules = rules or load_rules()
    out = Validated()
    if data is None:
        out.dropped["invalid_json"] += 1
        return out
    text_norm = norm(window_text)
    text_keep = norm_keep_case(window_text)
    text_alnum = alnum(text_norm)
    text_key = concept_key(window_text)
    names: dict[str, str] = {}  # concept key (incl. aliases) -> canonical name
    types: dict[str, str] = {}  # canonical name -> concept type, for the relation target-type rule
    spellings: dict[str, list[str]] = {}  # canonical name -> every spelling the model gave (for "does the quote mention it")
    for item in (data.get("concepts") or [])[:MAX_CONCEPTS]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            out.dropped["concept_malformed"] += 1
            continue
        name, kind = item["name"].strip(), item.get("type")
        aliases = [a.strip() for a in item.get("aliases") or [] if isinstance(a, str) and a.strip()]
        if kind not in CONCEPT_TYPES:
            out.dropped["concept_bad_type"] += 1
        elif not _balanced(name):
            out.dropped["concept_truncated_name"] += 1
        elif concept_key(name, rules) in rules.never or concept_key(name, rules) in rules.organizations:
            out.dropped["concept_generic_or_org"] += 1
        # A concept the text never mentions (by name or alias) is the model's own knowledge, not the document's.
        elif not any(norm(n) in text_norm or concept_key(n) in text_key for n in [name, *aliases]):
            out.dropped["concept_not_in_text"] += 1
        else:
            canonical = rules.canonical_name.get(concept_key(name, rules)) or name
            out.concepts.append({"name": canonical, "type": kind, "aliases": sorted({a for a in aliases + ([name] if name != canonical else []) if concept_key(a, rules) != concept_key(canonical, rules) or a != canonical})})
            types.setdefault(canonical, kind)
            spellings.setdefault(canonical, []).extend([name, *aliases, canonical])
            for n in [name, *aliases, canonical]:
                names.setdefault(concept_key(n, rules), canonical)

    def mentioned(quote_norm: str, canonical: str) -> bool:
        return any(norm(n) in quote_norm for n in spellings.get(canonical, [canonical]))

    for item in (data.get("relations") or [])[:MAX_RELATIONS]:
        if not isinstance(item, dict):
            out.dropped["relation_malformed"] += 1
            continue
        src, dst, kind, quote = item.get("source"), item.get("target"), item.get("type"), item.get("evidence")
        if not all(isinstance(v, str) and v.strip() for v in (src, dst, kind, quote)):
            out.dropped["relation_malformed"] += 1
            continue
        s_name, d_name = names.get(concept_key(src, rules)), names.get(concept_key(dst, rules))
        q = quote.strip(" .…")
        qn = norm(q)
        if kind not in RELATION_TYPES:
            out.dropped["relation_bad_type"] += 1
        elif not s_name or not d_name or s_name == d_name:
            out.dropped["relation_endpoint_unknown"] += 1
        elif len(quote.strip()) > MAX_EVIDENCE_CHARS + 40:
            out.dropped["evidence_too_long"] += 1
        elif qn not in text_norm and not (len(alnum(qn)) >= 20 and alnum(qn) in text_alnum):
            # Verbatim up to punctuation, spacing and hyphenation (PDF text has "re-\nliability", ligatures, split formulas) is accepted; a rewording is not.
            out.dropped["evidence_not_in_text"] += 1
        elif len(qn) < rules.min_evidence:
            out.dropped["evidence_too_short"] += 1
        elif cut_mid_word(text_keep, text_norm, qn):
            out.dropped["evidence_cut_mid_word"] += 1
        elif concept_key(q, rules) == concept_key(s_name, rules) or \
                (concept_key(q, rules) == concept_key(d_name, rules) and not (kind == "TESTED_BY" and mentioned(qn, s_name))) or \
                len(concept_key(q, rules).replace(concept_key(s_name, rules), "").replace(concept_key(d_name, rules), "")) <= 1 and mentioned(qn, s_name) and mentioned(qn, d_name):
            # A test item whose own name states what it tests ("5.5 STAUT transmits and receives LDPC codes ...") is evidence for TESTED_BY; for other types
            # a quote that is just one of the two names is a heading, not a statement.
            out.dropped["evidence_is_heading_echo"] += 1  # the "evidence" is just the two names, e.g. a table heading
        elif kind == "RELATED_TO" and (concept_key(s_name, rules) in rules.no_related_to or concept_key(d_name, rules) in rules.no_related_to):
            out.dropped["relation_generic_endpoint"] += 1
        elif kind in rules.target_types and types.get(d_name) not in rules.target_types[kind]:
            out.dropped["relation_target_type"] += 1  # e.g. TESTED_BY must end at a test item
        elif kind in rules.both_endpoints and not (mentioned(qn, s_name) and mentioned(qn, d_name)):
            out.dropped["evidence_missing_endpoint"] += 1  # e.g. a bibliography line that names the standard but not the feature
        else:
            try:
                confidence = max(0.0, min(1.0, float(item.get("confidence", 0.5))))
            except (TypeError, ValueError):
                confidence = 0.5
            out.relations.append({"source": s_name, "type": kind, "target": d_name, "evidence": quote.strip()[:MAX_EVIDENCE_CHARS], "confidence": confidence})
    return out


def aggregate(records: list[dict[str, Any]], rules: Rules | None = None) -> dict[str, Any]:
    """Merge validated windows into graph rows. records: {"revision_id", "window_id", "chunk_indexes", "concepts", "relations"}."""
    rules = rules or load_rules()
    concepts: dict[str, dict[str, Any]] = {}
    names_to_key: dict[str, str] = {}
    for rec in records:  # first pass: concepts, and alias -> one identity
        for c in rec["concepts"]:
            keys = {concept_key(n, rules) for n in [c["name"], *c["aliases"]]}
            known = next((names_to_key[k] for k in keys if k in names_to_key), None)
            key = known or concept_key(c["name"], rules)
            entry = concepts.setdefault(key, {"names": Counter(), "types": Counter(), "aliases": set(), "docs": set(), "windows": set(), "mentions": defaultdict(set), "runs": set()})
            entry["runs"].add(rec.get("run") or "")
            entry["names"][c["name"]] += 1
            entry["types"][c["type"]] += 1
            entry["aliases"].update(c["aliases"])
            entry["docs"].add(rec["revision_id"])
            entry["windows"].add(rec["window_id"])
            entry["mentions"][rec["revision_id"]].update(rec["chunk_indexes"])
            for k in keys:
                names_to_key.setdefault(k, key)
    relations: dict[tuple[str, str, str], dict[str, Any]] = {}
    for rec in records:
        for r in rec["relations"]:
            s, d = names_to_key.get(concept_key(r["source"], rules)), names_to_key.get(concept_key(r["target"], rules))
            if not s or not d or s == d:
                continue
            row = relations.setdefault((s, r["type"], d), {"windows": set(), "docs": set(), "confidence": [], "evidence": [], "runs": set()})
            row["runs"].add(rec.get("run") or "")
            row["windows"].add(rec["window_id"])
            row["docs"].add(rec["revision_id"])
            row["confidence"].append(r["confidence"])
            if len(row["evidence"]) < 3 and all(e["quote"] != r["evidence"] for e in row["evidence"]):
                row["evidence"].append({"quote": r["evidence"], "revision_id": rec["revision_id"], "window_id": rec["window_id"]})
    out_concepts = []
    for key, e in concepts.items():
        name = rules.canonical_name.get(key) or e["names"].most_common(1)[0][0]
        out_concepts.append({"concept_id": "C:" + hashlib.sha1(key.encode()).hexdigest()[:16], "key": key, "name": name, "type": e["types"].most_common(1)[0][0],
                             "aliases": sorted((e["aliases"] | set(e["names"])) - {name})[:12], "doc_count": len(e["docs"]),
                             "window_count": len(e["windows"]), "runs": sorted(e["runs"] - {""}), "mentions": {d: sorted(ix) for d, ix in e["mentions"].items()}})
    ids = {c["key"]: c["concept_id"] for c in out_concepts}
    out_relations = [{"source": ids[s], "type": t, "target": ids[d], "support_windows": len(v["windows"]), "support_docs": len(v["docs"]),
                      "confidence": round(sum(v["confidence"]) / len(v["confidence"]), 3), "evidence": v["evidence"], "runs": sorted(v["runs"] - {""}),
                      # A relation seen once and only "related to" is kept but flagged: the answer layer shows weak relations only on request.
                      "weak": t == "RELATED_TO" and len(v["windows"]) < rules.weak_threshold} for (s, t, d), v in relations.items()]
    return {"concepts": out_concepts, "relations": out_relations}
