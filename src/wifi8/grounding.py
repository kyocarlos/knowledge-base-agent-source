"""Grounding check of a WiFi agent answer against the full text of the chunks it cites.

Plain code, no model judges. For every technical sentence ("claim") of the answer:
* coverage   -- does it carry a [S#] reference (its own or its line's)?
* values     -- numbers, versions, model ids and codes it states; each is looked up in the
                full text of the chunks the claim cites (verified), in other chunks cited by
                the answer (other_source), in anything else the tools returned during the run
                -- document metadata, version lists, overview counts (tool_data) -- or nowhere
                (not_found). The agent may only use tool results, so not_found marks values
                that no evidence supports.
* similarity -- cosine between the claim and the closest sentence of its cited chunks
                (embedding model of the zone). Off by default: on the 2026-10-17 calibration
                (Chinese answers, mostly English sources) it barely separated cited from
                unrelated text, so it is not shown to users.
* assigned numbers -- the short numbers a claim assigns to a label ("2.4G：6", "UHR-4.5.2：25，30，30") are
                not values above (too short to be ids), yet they are what a table answer is made of. For a cited
                claim each must appear in the cited chunks (verified), in another cited chunk (other_source) or it
                is not_in_cited -- the answer states a figure its own citation does not show.
* source names -- a document name such as PF1 / EE1 that the claim (or, for a bare list item, the question) names
                and that is the name of a document seen in this run must be in the title or text of the chunks the
                claim cites; otherwise the claim quotes another document than the one it names.
Plus the authority of the cited sources (WFA, current version).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable

from .excerpt import _SENTENCE
from .lexical import query_terms, text_codes, title_codes, tokens

Encoder = Callable[[list[str]], list[list[float]]]

_REF = re.compile(r"\[(S\d+)\]")
_MARKUP = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}")
_CLAIM_SPLIT = re.compile(r"(?<=[。！？；;])|(?<=[.!?])\s+(?=[A-Z一-鿿])")
# ASCII-only boundaries: in Chinese text ids touch CJK characters ("是BCM6718支援"), where \b fails.
_A, _Z = r"(?<![A-Za-z0-9.])", r"(?![A-Za-z0-9])"
_VALUE = re.compile(
    rf"(?P<unit>{_A}\d+(?:\.\d+)?\s?(?:MHz|GHz|Mbps|Gbps|kbps|dBm|dB|ms|μs|us|%))"
    rf"|(?P<version>{_A}[vV]\d+(?:\.\d+)*[a-z]?{_Z})"
    rf"|(?P<ident>{_A}[A-Z][A-Za-z]*\d[A-Za-z0-9.]*(?:-[A-Za-z0-9.]+)*)"
    rf"|(?P<code>{_A}\d+(?!(?:st|nd|rd|th)(?![A-Za-z]))[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9.]+)*)"  # 4K-QAM, 2xLDPC, 4x4; not 5th
    rf"|(?P<dotted>{_A}\d+(?:\.\d+)+)"
    rf"|(?P<integer>{_A}\d{{3,}}{_Z})"
)
# "2.4G：6"  "UHR-4.5.2: 25、30、30"  "x = 12": numbers right after a label separator, up to a list of them (not dates: 2026/08/03).
_ASSIGNED = re.compile(r"[：:=]\s*\**(?P<n>\d+(?:\.\d+)?(?:\s*[,，、]\s*\d+(?:\.\d+)?)*)(?![\d.]*(?:\s*[A-Za-z%μ]|[-/][A-Za-z0-9]))")
_DASHES = str.maketrans({**{c: "-" for c in "‐‑‒–—−﹣－"}, "×": "x"})


@dataclass(frozen=True)
class GroundingSettings:
    similarity: bool = False         # see module docstring
    similarity_high: float = 0.7      # 99th percentile of unrelated pairs (calibration 2026-10-17)
    similarity_low: float = 0.64      # 90th percentile of unrelated pairs
    candidate_sentences: int = 8      # lexically closest source sentences per claim that get embedded
    max_claims: int = 60
    min_claim_chars: int = 12

    @classmethod
    def from_environment(cls) -> "GroundingSettings":
        return cls(similarity=os.getenv("KM_WIFI8_GROUNDING_SIMILARITY", "0").strip().lower() in {"1", "true", "yes", "on"},
                   similarity_high=float(os.getenv("KM_WIFI8_GROUNDING_SIM_HIGH", str(cls.similarity_high))),
                   similarity_low=float(os.getenv("KM_WIFI8_GROUNDING_SIM_LOW", str(cls.similarity_low))),
                   candidate_sentences=int(os.getenv("KM_WIFI8_GROUNDING_CANDIDATES", str(cls.candidate_sentences))),
                   max_claims=int(os.getenv("KM_WIFI8_GROUNDING_MAX_CLAIMS", str(cls.max_claims))))


def _norm(text: str) -> str:
    """Case- and dash-insensitive, whitespace collapsed (kept, so "2x2 2.4" does not become "2x22.4")."""
    return re.sub(r"\s+", " ", str(text or "").translate(_DASHES)).casefold()


def _value_pattern(key: str) -> str:
    """Regex for a value: optional space/hyphen between a number and a letter ("5 GHz" ~ "5-GHz" ~ "5GHz")."""
    out = []
    for i, ch in enumerate(key):
        if i and (ch.isdigit() != key[i - 1].isdigit()) and (ch.isalnum() or ch in "%μ") and (key[i - 1].isalnum() or key[i - 1] in "%μ"):
            out.append(r"[\s-]?")
        out.append(re.escape(ch))
    return "".join(out)


def _plain(text: str) -> str:
    text = _REF.sub("", text)
    text = re.sub(r"\*\*|__|`", "", text)
    return re.sub(r"\s+", " ", text).strip(" |:：")


_REFUSAL = re.compile(r"尚未查證|無法(?:據此)?(?:回答|確認|確定|判斷)|未(?:列出|提及|提供|包含)|找不到|查無|資料不足|not found|no information", re.I)
_LIST_OR_TABLE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|\|)")


def split_claims(answer: str, min_chars: int = 12) -> list[dict[str, Any]]:
    """Technical sentences of a markdown answer with the refs that support them.

    A sentence without its own [S#] takes its line's refs; list items and table rows also
    take the refs of the introducing line ("支援下列功能：[S2]"). Headings, labels, table
    header rows, fenced code blocks (ASCII diagrams) and statements that something could
    not be verified are not claims.
    """
    claims, intro_refs, block, block_refs, block_kind = [], [], [], [], [""]

    def close_block() -> None:  # a list or table cited only on some items: the others share those refs
        shared = list(dict.fromkeys(block_refs + [ref for claim in block for ref in claim["refs"]]))
        for claim in block:
            if not claim["refs"]:
                claim["refs"] = shared
        block.clear()
        block_refs.clear()
        block_kind[0] = ""

    lines = (answer or "").splitlines()
    fence = ""
    for index, line in enumerate(lines):
        marker = re.match(r"^\s*(```|~~~)", line)
        if fence:  # inside a fenced code block: diagrams and code, not statements
            if marker and marker.group(1) == fence:
                fence = ""
            continue
        if marker:
            fence = marker.group(1)
            close_block()
            continue
        if not line.strip():
            continue
        if re.match(r"^\s*#{1,6}\s", line):
            intro_refs = []
            close_block()
            continue
        if _TABLE_RULE.match(line):
            continue
        listed = bool(_LIST_OR_TABLE.match(line))
        kind = ("table" if line.lstrip().startswith("|") else "list") if listed else ""
        if kind != block_kind[0]:  # a list followed by a table (or prose) is a new block; blank lines are not
            close_block()
            block_kind[0] = kind
        body = _MARKUP.sub("", line)
        if "|" in body.strip(" |"):
            cells = [cell.strip() for cell in body.strip().strip("|").split("|") if cell.strip()]
            body = (cells[0] + "：" + "，".join(cells[1:])) if len(cells) > 1 else "".join(cells)  # one row = one claim
        own_line_refs = list(dict.fromkeys(_REF.findall(body)))
        if listed:
            block_refs.extend(own_line_refs)  # counts even when the line itself is too short to be a claim
        following = next((l for l in lines[index + 1:] if l.strip()), "")
        if kind == "table" and _TABLE_RULE.match(following):
            continue  # header row ("| 條件 | AP 是否必須實作 DBE |"): column names, not a statement
        line_refs = own_line_refs or (intro_refs if listed else [])
        if _REF.sub("", body).rstrip(" *_`").endswith(("：", ":")):
            intro_refs = line_refs
        elif not listed:
            intro_refs = []
        for part in _CLAIM_SPLIT.split(body):
            text = _plain(part)  # note: _plain strips a trailing colon, so labels are detected on the raw part
            short = len(re.sub(r"[\W_]+", "", text)) < min_chars and not extract_values(text)  # short rows with values still count
            # "AP 還必須：" introduces a list; "目前最新的是 v1.5：" still states a value and stays a claim
            label = _REF.sub("", part).rstrip(" *_`").endswith(("：", ":")) and len(text) < 40 and not extract_values(text)
            if short or label or _REFUSAL.search(text):
                continue
            refs = list(dict.fromkeys(_REF.findall(part))) or line_refs
            claims.append({"text": text, "refs": refs, "own_refs": bool(_REF.search(part))})
            if listed:
                block.append(claims[-1])
    close_block()
    return claims


def extract_values(text: str) -> list[str]:
    """Numbers, versions, model ids and codes stated in a claim (longest match wins)."""
    values = []
    for match in _VALUE.finditer(str(text or "").translate(_DASHES)):
        token = match.group(0).strip()
        if match.lastgroup == "ident" and not re.search(r"\d", token):
            continue
        values.append(token)
    return list(dict.fromkeys(values))


def assigned_numbers(text: str) -> list[str]:
    """Numbers a claim assigns to a label ("2.4G：6", "UHR-4.5.2：25，30，30"); units and ids are extract_values' job."""
    found = []
    for match in _ASSIGNED.finditer(str(text or "").translate(_DASHES)):
        found.extend(n.strip() for n in re.split(r"[,，、]", match.group("n")) if n.strip())
    return list(dict.fromkeys(found))


def source_names(text: str) -> set[str]:
    """Short document names (pf1, ee1 ...) in a claim, question or chunk; [S#] references are not names."""
    return text_codes(_REF.sub("", str(text or "")))


def _value_in(token: str, normalized_text: str) -> bool:
    key = re.sub(r"\s+", "", _norm(token))
    # Numbers must not match inside longer numbers ("5ghz" in "15ghz"); ids not inside longer ids.
    head = r"(?<![\d.])" if key[:1].isdigit() else r"(?<![a-z0-9])"
    if re.search(head + _value_pattern(key) + r"(?![\d])", normalized_text):
        return True
    if re.fullmatch(r"v\d+(?:\.\d+)*[a-z]?", key):  # "v1.7" also matches "version 1.7" / "1.7"
        return re.search(r"(?<![\d.])" + re.escape(key[1:]) + r"(?![\d])", normalized_text) is not None
    unit = re.fullmatch(r"(\d+(?:\.\d+)?)([a-zμ%]+)", key)
    if unit:  # "5ghz" also matches "2.4/5/6 GHz" and "5 and 6 GHz"
        number, suffix = map(re.escape, unit.groups())
        return re.search(rf"(?<![\d.]){number}(?:\s*(?:[/,、及和與~-]|and)\s*[\d.]+)*[\s-]?{suffix}", normalized_text) is not None
    return False


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in (m.group(0) for m in _SENTENCE.finditer(text or "")) if len(s.strip()) >= 8]


def _closest_by_terms(claim: str, sentences: list[str], limit: int) -> list[str]:
    terms = set(query_terms(claim))
    if not terms:
        return sentences[:limit]
    scored = sorted(sentences, key=lambda s: -len(terms & set(tokens(s))))
    return scored[:limit]


def check_answer(answer: str, sources: dict[str, dict[str, Any]], *, context: str = "", encoder: Encoder | None = None,
                 settings: GroundingSettings | None = None, question: str = "") -> dict[str, Any]:
    """`sources` maps ref -> {"text": full chunk text, "source": title, "publisher", "analysis_eligible", ...};
    `context` is everything else the agent saw (question and tool results); `question` is the user's question."""
    settings = settings or GroundingSettings()
    claims = split_claims(answer, settings.min_claim_chars)[: settings.max_claims]
    normalized = {ref: _norm(src.get("text") or "") for ref, src in sources.items()}
    tool_data = _norm(context)
    all_cited = list(dict.fromkeys(ref for c in claims for ref in c["refs"] if ref in sources))
    seen_names = set().union(*(title_codes(src.get("source")) for src in sources.values())) if sources else set()
    question_names = source_names(question) & seen_names

    for claim in claims:
        claim["refs"] = [ref for ref in claim["refs"] if ref in sources]
        own = " ".join(normalized[ref] for ref in claim["refs"])
        other = " ".join(normalized[ref] for ref in all_cited if ref not in claim["refs"])
        claim["values"] = [{"value": v, "status": "verified" if own and _value_in(v, own)
                            else "other_source" if other and _value_in(v, other)
                            else "tool_data" if tool_data and _value_in(v, tool_data) else "not_found"}
                           for v in extract_values(claim["text"])]
        # Uncited statements whose every value is in the evidence (e.g. a version table built from
        # list_versions) are supported by tool data rather than unsupported.
        if claim["refs"]:  # the short numbers of a table-like answer must be in what the claim cites
            known = [v["value"] for v in claim["values"]]
            for number in assigned_numbers(claim["text"]):
                if any(k.startswith(number) for k in known):
                    continue
                claim["values"].append({"value": number, "status": "verified" if _value_in(number, own)
                                        else "other_source" if other and _value_in(number, other) else "not_in_cited"})
        cited_text = " ".join(f"{sources[ref].get('source') or ''} {sources[ref].get('text') or ''}" for ref in claim["refs"])
        # A name in the claim, else the single document name the question asks about (a list item rarely repeats it).
        named = (source_names(claim["text"]) & seen_names) or (question_names if len(question_names) == 1 else set())
        claim["names_missing"] = sorted(n.upper() for n in named - source_names(cited_text)) if claim["refs"] else []
        claim["support"] = ("citation" if claim["refs"] else
                            "tool_data" if claim["values"] and all(v["status"] != "not_found" for v in claim["values"]) else "none")

    if encoder is not None and settings.similarity:
        _similarities(claims, sources, encoder, settings)
    for claim in claims:
        sim = claim.get("similarity")
        claim["similarity_level"] = ("none" if not claim["refs"] else "unknown" if sim is None
                                     else "high" if sim >= settings.similarity_high
                                     else "medium" if sim >= settings.similarity_low else "low")

    values = [v for c in claims for v in c["values"]]
    cited_sources = [sources[ref] for ref in all_cited]
    levels = [c["similarity_level"] for c in claims]
    summary = {
        "claims": len(claims),
        "claims_cited": sum(1 for c in claims if c["refs"]),
        "claims_tool_data": sum(1 for c in claims if c["support"] == "tool_data"),
        "values": len(values),
        "values_verified": sum(v["status"] == "verified" for v in values),
        "values_other_source": sum(v["status"] == "other_source" for v in values),
        "values_tool_data": sum(v["status"] == "tool_data" for v in values),
        "values_not_in_cited": sum(v["status"] == "not_in_cited" for v in values),
        "claims_source_mismatch": sum(1 for c in claims if c["names_missing"]),
        "values_not_found": sum(v["status"] == "not_found" for v in values),
        "similarity": {level: levels.count(level) for level in ("high", "medium", "low", "none", "unknown") if level in levels},
        "sources": {"total": len(cited_sources),
                    "wfa": sum(1 for s in cited_sources if s.get("publisher") == "WFA"),
                    "current": sum(1 for s in cited_sources if s.get("analysis_eligible"))},
        "similarity_enabled": bool(encoder is not None and settings.similarity),
        "thresholds": {"high": settings.similarity_high, "low": settings.similarity_low},
    }
    flagged = [{"text": c["text"][:240], "refs": c["refs"],
                "reasons": [r for r, hit in (("no_source", c["support"] == "none"),
                                             ("value_not_found", any(v["status"] == "not_found" for v in c["values"])),
                                             ("value_not_in_cited", any(v["status"] == "not_in_cited" for v in c["values"])),
                                             ("source_name_mismatch", bool(c["names_missing"])),
                                             ("low_similarity", c["similarity_level"] == "low")) if hit],
                "values": [v for v in c["values"] if v["status"] in ("not_found", "not_in_cited")],
                "names": c["names_missing"],
                "similarity": c.get("similarity")}
               for c in claims]
    return {"summary": summary, "flagged": [f for f in flagged if f["reasons"]],
            "claims": [{"text": c["text"][:240], "refs": c["refs"], "support": c["support"], "similarity": c.get("similarity"),
                        "similarity_level": c["similarity_level"], "values": c["values"]} for c in claims]}


def _similarities(claims: list[dict[str, Any]], sources: dict[str, dict[str, Any]], encoder: Encoder,
                  settings: GroundingSettings) -> None:
    per_ref = {ref: _sentences(src.get("text") or "") for ref, src in sources.items()}
    jobs, texts = [], {}
    for index, claim in enumerate(claims):
        if not claim["refs"]:
            continue
        pool = list(dict.fromkeys(s for ref in claim["refs"] for s in per_ref.get(ref, [])))
        candidates = _closest_by_terms(claim["text"], pool, settings.candidate_sentences)
        if not candidates:
            continue
        jobs.append((index, candidates))
        texts.setdefault(claim["text"], None)
        for sentence in candidates:
            texts.setdefault(sentence, None)
    if not jobs:
        return
    order = list(texts)
    vectors = dict(zip(order, encoder(order)))
    for index, candidates in jobs:
        claim_vector = vectors[claims[index]["text"]]
        claims[index]["similarity"] = round(max(sum(a * b for a, b in zip(claim_vector, vectors[s])) for s in candidates), 4)
