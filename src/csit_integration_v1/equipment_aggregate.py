"""Equipment-level cross-document synthesis against CSIT's real contract (CSIT requirement doc, 2026-11-17; EquipmentAggregateAnalysisContracts.cs).

Input: the Documents CSIT's request names (fileId/version/sha256/kmJobId/analysisResultId). KM never decides which documents belong to an
apparatus -- the manifest CSIT sends does. Output: one EquipmentAggregateAnalysisResult merged from the per-document Completed.result
metadata KM already stored for each (fileId=document_id, version); nothing here parses, chunks, downloads or re-analyses a document.

Each technicalSpecification/testCapability/conflict carries evidenceIds pointing into the evidence list, and each evidence item's
analysisResultId is copied verbatim from the matching source document in CSIT's own request (never minted, never replaced -- CSIT's own
validator checks it against what it already has). A document whose metadata carries no specifications, measurements, capabilities or
limitations contributes nothing (excluded, with a reason); if no document contributes, overview/warnings say so and every list stays
empty -- an empty result is never dressed up as a successful synthesis of something that was not actually there.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Optional, Protocol

from .equipment_aggregate_models import build_equipment_aggregate_result
from .equipment_synthesis import IDENTITY_FIELDS, _key, _sources_of, _text, extract_contribution, normalise_claim

IDENTITY_LABELS = {"productNames": "產品名稱", "modelNumbers": "型號", "vendorNames": "廠牌", "technologies": "技術",
                    "standards": "標準", "softwareVersions": "軟體版本", "hardwareVersions": "硬體版本"}


# How a conflict is told from a multi-valued fact (CSIT's review of 2026-11-23: the old rule reported every field with two different values as a conflict):
#   1. supported capabilities / lists (技術, 標準, 型號, 產品名稱, 軟硬體版本) are several true values at once   -> listed together, never a conflict;
#   2. one document that gives several values for a field (several models compared, base vs. option, 4x4 vs 8x8)  -> listed together, with the condition;
#   3. only when two DIFFERENT documents give values for the same field and condition that share none of them   -> conflict, nothing is chosen.
# Vendor names stay a conflict when they differ: documents of one equipment item that name different makers are a real inconsistency.
LIST_IDENTITY = ("productNames", "modelNumbers", "technologies", "standards", "softwareVersions", "hardwareVersions")
_QUALIFIERS = {"option", "optional", "standard", "typical", "typ", "max", "min", "future", "選配", "選購", "標配", "選項", "未來", "典型", "最大", "最小"}
_QUAL = re.compile(r"^(.*\S)\s*[（(]\s*([^()（）]{1,30}?)\s*[)）]\s*$")


def _split_qualifier(value):
    """"3.8 GHz to 6.0 GHz (Option)" -> ("3.8 GHz to 6.0 GHz", "Option"): a condition the document wrote next to the value, not a different value."""
    if isinstance(value, str):
        m = _QUAL.match(value.strip())
        if m and m.group(2).strip().casefold() in _QUALIFIERS:
            return m.group(1).strip(), m.group(2).strip()
    return value, None


def _shown(cl):
    return cl["value"] + (" " + cl["unit"] if cl["unit"] else "")


def _documents_disagree(claims: dict) -> bool:
    """True when two different documents each state values for the field and the two sets share no value (a document that says more than the other
    does not contradict it)."""
    per_doc: dict = {}
    for key, cl in claims.items():
        for doc in cl["docs"]:
            per_doc.setdefault(doc, set()).add(key)
    sets = list(per_doc.values())
    return any(not (a & b) for i, a in enumerate(sets) for b in sets[i + 1:])


@dataclass(frozen=True)
class DocumentMetadata:
    file_id: str
    version: int
    sha256: str
    km_job_id: str
    result: dict   # the Completed.result (metadataSchemaVersion 2.0) KM stored for (document_id=file_id, version)


class MetadataSource(Protocol):
    def get(self, file_id: str, version: int) -> Optional[DocumentMetadata]: ...


class V2JobMetadataSource:
    """Reads Completed v2 jobs (km_csit_v2_jobs rows) KM already has; nothing is fetched or re-parsed for this request."""

    def __init__(self, rows):
        self._by_key: dict[tuple[str, int], DocumentMetadata] = {}
        for r in rows:
            if r.get("status") != "Completed" or not r.get("result_json"):
                continue
            result = r["result_json"]
            if isinstance(result, str):
                result = json.loads(result)
            key = (str(r["document_id"]).lower(), int(r["version"]))
            self._by_key[key] = DocumentMetadata(key[0], key[1], str(r["expected_sha256"]).lower(), str(r["km_job_id"]), result)

    def get(self, file_id, version):
        return self._by_key.get((str(file_id).lower(), int(version)))


def _collect(request, source: MetadataSource):
    """Every document CSIT's request names, checked against what KM actually has: a mismatched identity (sha256 or kmJobId) is excluded,
    never silently matched to the wrong stored result (spec part 3.3: FileId/Version/Sha256/KmJobId must all be checked)."""
    used, excluded = [], []
    for doc in sorted(request.documents, key=lambda d: (str(d.fileId), d.version)):
        meta = source.get(doc.fileId, doc.version)
        if meta is None:
            excluded.append({"fileId": str(doc.fileId), "version": doc.version, "reason": "metadata_missing"})
            continue
        if meta.sha256 != str(doc.sha256).lower():
            excluded.append({"fileId": str(doc.fileId), "version": doc.version, "reason": "sha256_mismatch"})
            continue
        if meta.km_job_id != doc.kmJobId:
            excluded.append({"fileId": str(doc.fileId), "version": doc.version, "reason": "km_job_id_mismatch"})
            continue
        contribution = extract_contribution(_as_equipment_synthesis_meta(meta, doc))
        if not contribution["substantive"]:
            excluded.append({"fileId": str(doc.fileId), "version": doc.version,
                              "reason": "identity_only" if contribution["identityOnly"] else "no_technical_content"})
            continue
        used.append((doc, meta, contribution))
    return used, excluded


def _as_equipment_synthesis_meta(meta: DocumentMetadata, doc):
    """extract_contribution() (equipment_synthesis.py) reads a DocumentMetadata with the v1-proposal field names; this request's documents
    are keyed by fileId, not documentId, so the value is adapted rather than duplicating that function."""
    from .equipment_synthesis import DocumentMetadata as _Meta
    return _Meta(str(doc.fileId).lower(), doc.version, meta.sha256, "EquipmentAttachment", str(doc.fileId).lower(), meta.km_job_id, meta.result)


def _evidence_id(file_id, index):
    return "ev-" + hashlib.sha256((str(file_id) + ":" + str(index)).encode()).hexdigest()[:16]


def analyze(request, source: MetadataSource) -> dict:
    """-> an EquipmentAggregateAnalysisResult dict (equipment_aggregate_models.build_equipment_aggregate_result's shape)."""
    used, excluded = _collect(request, source)

    specs: dict = {}       # (kind, field_key, context_key) -> {"field":..., "kind":..., "context":..., "claims": {normalised_key: {...}}}
    identity = {f: {} for f in IDENTITY_FIELDS}
    capabilities: dict = {}
    limitations: dict = {}
    evidence_by_source: dict[tuple, dict] = {}   # (fileId, analysisResultId, description) -> evidenceId, reused so one fact cites one evidence item
    evidence_items: list[dict] = []
    summaries = []

    def evidence_for(doc, description):
        key = (str(doc.fileId), str(doc.analysisResultId), description or "")
        if key not in evidence_by_source:
            eid = _evidence_id(doc.fileId, len(evidence_items))
            evidence_by_source[key] = eid
            evidence_items.append({"evidenceId": eid, "fileId": doc.fileId, "analysisResultId": doc.analysisResultId,
                                    "description": description or ("來自 " + (doc.fileName or str(doc.fileId))), "location": description})
        return evidence_by_source[key]

    for doc, meta, c in used:
        for claim in c["claims"]:
            eid = evidence_for(doc, claim.get("evidence"))
            raw_value, qualifier = _split_qualifier(claim["value"]) if claim["kind"] == "specification" and not claim.get("unit") else (claim["value"], None)
            nkey, value, unit = normalise_claim(raw_value, claim.get("unit"))
            context = claim.get("context") if claim["kind"] == "measurement" else qualifier
            group = specs.setdefault((claim["kind"], _key(claim["field"]), _key(context or "")),
                                      {"field": claim["field"], "kind": claim["kind"], "context": context, "claims": {}})
            bucket = group["claims"].setdefault(nkey, {"value": value, "unit": unit, "evidenceIds": [], "docs": set()})
            bucket["docs"].add(str(doc.fileId).lower())
            if eid not in bucket["evidenceIds"]:
                bucket["evidenceIds"].append(eid)
        for text in c["capabilities"]:
            entry = capabilities.setdefault(_key(text), {"value": text, "evidenceIds": []})
            eid = evidence_for(doc, text)
            if eid not in entry["evidenceIds"]:
                entry["evidenceIds"].append(eid)
        for text in c["limitations"]:
            limitations.setdefault(_key(text), text)
        for f in IDENTITY_FIELDS:
            for text in c["identity"][f]:
                entry = identity[f].setdefault(_key(text), {"value": text, "evidenceIds": []})
                eid = evidence_for(doc, IDENTITY_LABELS[f] + "：" + text)
                if eid not in entry["evidenceIds"]:
                    entry["evidenceIds"].append(eid)
        if c["summary"]:
            summaries.append(c["summary"])

    technical_specifications, conflicts, multi_valued, variants = [], [], [], []

    def add_spec(name, value, unit, ids):
        for existing in technical_specifications:                    # the same fact read as a specification and as a measurement is shown once
            if existing["name"] == name and existing["value"] == value and existing["unit"] == unit:
                existing["evidenceIds"] = sorted(set(existing["evidenceIds"]) | set(ids))
                return
        technical_specifications.append({"name": name, "value": value, "unit": unit, "evidenceIds": list(ids)})

    for group in sorted(specs.values(), key=lambda g: (g["kind"], _key(g["field"]), _key(g["context"] or ""))):
        claims = list(group["claims"].values())
        name = group["field"] if not group["context"] else group["field"] + "（" + group["context"] + "）"
        if len(claims) == 1:
            cl = claims[0]
            add_spec(name, cl["value"], cl["unit"], cl["evidenceIds"])
        else:
            all_ids = sorted({e for cl in claims for e in cl["evidenceIds"]})
            values = "；".join(sorted({_shown(cl) for cl in claims}))
            if _documents_disagree(group["claims"]):
                conflicts.append({"field": name, "description": "不同文件對此欄位給出互不相同的值：" + values, "evidenceIds": all_ids})
            else:
                add_spec(name, values, None, all_ids)                # several values of one field (conditions, options, models): all listed, no conflict
                multi_valued.append(name)

    for f in IDENTITY_FIELDS:
        entries = sorted(identity[f].values(), key=lambda e: _key(e["value"]))
        if len(entries) == 1:
            add_spec(IDENTITY_LABELS[f], entries[0]["value"], None, entries[0]["evidenceIds"])
        elif len(entries) > 1:
            all_ids = sorted({e for entry in entries for e in entry["evidenceIds"]})
            values = "；".join(e["value"] for e in entries)
            if f in LIST_IDENTITY:
                add_spec(IDENTITY_LABELS[f], values, None, all_ids)
                if f in ("modelNumbers", "productNames"):
                    variants.append(IDENTITY_LABELS[f] + "：" + values)
            else:
                conflicts.append({"field": IDENTITY_LABELS[f], "description": "不同文件對此欄位給出互不相同的值：" + values, "evidenceIds": all_ids})

    test_capabilities = [{"name": entry["value"], "description": None, "evidenceIds": entry["evidenceIds"]}
                          for entry in sorted(capabilities.values(), key=lambda e: _key(e["value"]))]
    limitations_list = [limitations[k] for k in sorted(limitations)]

    warnings = []
    if conflicts:
        warnings.append("文件對 %d 個欄位的描述不一致，KM 未自行判斷或覆蓋，詳見 conflicts。" % len(conflicts))
    if variants:
        warnings.append("文件提到多個型號或產品名稱（" + "；".join(variants) + "），KM 已全部列出，未判斷哪一個才是這台設備。")
    if excluded:
        warnings.append("%d 份文件因缺少對應的 KM 分析結果、識別資訊不符或沒有可用的技術內容而未納入綜合分析。" % len(excluded))

    if not request.documents:
        overview = "Manifest 未列出任何文件。"
    elif not used:
        overview = "Manifest 列出的文件中，沒有一份有可用的 KM 技術分析結果；本次未產生任何綜合內容。"
    else:
        overview = " ".join(dict.fromkeys(summaries)) if summaries else \
            "整合 %d 份文件的技術分析結果（共 %d 份列於 manifest 中）。" % (len(used), len(request.documents))

    return build_equipment_aggregate_result(overview=overview, technical_specifications=technical_specifications,
        test_capabilities=test_capabilities, limitations=limitations_list, conflicts=conflicts, evidence=evidence_items,
        warnings=warnings)
