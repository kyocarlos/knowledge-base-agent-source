"""Equipment-level cross-document synthesis (CSIT DEV request).

Input: a manifest CSIT sends for one equipment item (CSIT's own string equipment id, a manifest hash and revision, and the valid documents with
id / version / SHA-256). Output: one synthesis of what the per-document analyses already say. Nothing here parses, chunks or indexes a document:
it only reads the Completed.result metadata KM stored for each (documentId, version) and merges it, so an unchanged document costs no new
analysis. KM never decides which documents belong to an equipment item; the manifest does.

Rules this module enforces (the numbers match the request):
 2. Only fields the documents actually carry are merged. Identical values (after unit normalisation) are merged with all their sources.
 3. Different values for the same field are reported as a conflict with every claim and its source; no value is picked or overwritten.
 4. A new manifest (revision) is re-synthesised from stored metadata; unchanged documents reuse their cached contribution.
 5. Every result carries an analysis version, the manifest hash/revision and per-item sources. The same inputs give the same
    analysisResultId (idempotent); a result for an older manifest revision never replaces a newer one.
 6. Nothing is written to CSIT and the single-document v2 contract is untouched.

Honesty rule: a document whose metadata has no specifications, measurements, capabilities or limitations contributes nothing. If no document
contributes, the status is InsufficientEvidence, never Completed, so empty single-document metadata cannot be merged into a "successful" analysis.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal, Optional, Protocol

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

ALGORITHM_VERSION = "equipment-synthesis/1"
SCHEMA_VERSION = "1.0-proposal"
SOURCE_TYPES = ("VerificationApplicationAttachment", "VendorFile", "EquipmentAttachment", "TestReport", "DocumentLibraryFile")
STATUSES = ("Completed", "Partial", "InsufficientEvidence", "NoDocuments")
IDENTITY_FIELDS = ("productNames", "modelNumbers", "vendorNames", "technologies", "standards", "softwareVersions", "hardwareVersions")
_NAMESPACE = uuid.UUID("6f1d0c1e-3a55-4b0e-9d8a-5d0b7e2c9a11")


# ------------------------------------------------------------------ wire models (PROPOSAL: not yet agreed with CSIT)

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManifestDocument(_Strict):
    documentId: str = Field(min_length=1, max_length=64)
    version: StrictInt = Field(ge=1, le=2147483647)
    sha256: str
    sourceType: Literal["VerificationApplicationAttachment", "VendorFile", "EquipmentAttachment", "TestReport", "DocumentLibraryFile"]
    sourceEntityId: str = Field(min_length=1, max_length=64)
    analysisResultId: Optional[str] = Field(default=None, max_length=128)   # CSIT's identifier of the per-document analysis result, echoed back
    fileName: Optional[str] = Field(default=None, max_length=255)

    @field_validator("documentId", "sourceEntityId")
    @classmethod
    def _id(cls, value):
        return value.strip().lower()

    @field_validator("sha256")
    @classmethod
    def _sha(cls, value):
        value = value.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("sha256 must be 64 hex characters")
        return value


class EquipmentManifest(_Strict):
    schemaVersion: Literal["1.0"]
    equipmentId: str = Field(min_length=1, max_length=128)     # CSIT's existing string identifier; never parsed as a UUID
    manifestHash: str = Field(min_length=8, max_length=128)
    manifestRevision: StrictInt = Field(ge=1, le=2147483647)   # increases by one or more with every manifest CSIT issues for this equipment
    generatedAt: datetime
    documents: list[ManifestDocument] = Field(default_factory=list, max_length=500)

    @field_validator("equipmentId")
    @classmethod
    def _eq(cls, value):
        value = value.strip()
        if not value or re.search(r"[\x00-\x1f]", value):
            raise ValueError("equipmentId must be a non-empty printable string")
        return value

    @field_validator("generatedAt")
    @classmethod
    def _tz(cls, value):
        if value.tzinfo is None:
            raise ValueError("timestamp timezone required")
        return value

    @model_validator(mode="after")
    def _one_version_per_document(self):
        seen = set()
        for d in self.documents:
            if d.documentId in seen:
                raise ValueError("a manifest lists one version per documentId")
            seen.add(d.documentId)
        return self


# ------------------------------------------------------------------ per-document metadata (read from what KM already stored)

@dataclass(frozen=True)
class DocumentMetadata:
    documentId: str
    version: int
    sha256: str
    sourceType: str
    sourceEntityId: str
    kmJobId: str
    result: dict   # the Completed.result (metadataSchemaVersion 2.0) KM sent for that document


class MetadataSource(Protocol):
    def get(self, document_id: str, version: int) -> Optional[DocumentMetadata]: ...


class JobRowsSource:
    """Reads Completed v2 jobs (rows of km_csit_v2_jobs). A row that is not Completed, or has no result, does not exist for this purpose."""

    def __init__(self, rows):
        self._by_key: dict[tuple[str, int], DocumentMetadata] = {}
        for r in sorted(rows, key=lambda r: str(r.get("completed_at") or "")):
            if r.get("status") != "Completed" or not r.get("result_json"):
                continue
            result = r["result_json"]
            if isinstance(result, str):
                result = json.loads(result)
            key = (str(r["document_id"]).lower(), int(r["version"]))
            self._by_key[key] = DocumentMetadata(key[0], key[1], str(r["expected_sha256"]).lower(), r["source_type"], str(r["source_entity_id"]).lower(),
                                                 r["km_job_id"], result)

    def get(self, document_id, version):
        return self._by_key.get((document_id, version))


# ------------------------------------------------------------------ normalisation

def _text(value) -> str:
    return " ".join(str(value).split())


def _key(value) -> str:
    return _text(value).casefold()


_SI = {"G": 1e9, "M": 1e6, "k": 1e3, "K": 1e3, "m": 1e-3, "u": 1e-6, "µ": 1e-6, "": 1.0}
_BASES = {"hz": "Hz", "bps": "bps", "w": "W", "v": "V", "a": "A", "s": "s", "m": "m"}
_FREE = {"dbm": "dBm", "db": "dB", "dbi": "dBi", "%": "%", "°c": "°C", "c": "°C"}
_KNOWN = set(_BASES.values()) | set(_FREE.values())
_NUMBER = re.compile(r"^\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*(.*?)\s*$")


def _unit(unit: str):
    """(scale, base) for a unit with an SI prefix (MHz, mW, Gbps), else (1, the unit as written); None for no unit."""
    u = _text(unit or "")
    if not u:
        return None
    if u.lower() in _FREE:
        return 1.0, _FREE[u.lower()]
    u = u.replace("bit/s", "bps").replace("b/s", "bps")
    for prefix in ("G", "M", "k", "K", "m", "u", "µ"):
        rest = u[len(prefix):] if u.startswith(prefix) else None
        if rest and rest.lower() in _BASES:
            if prefix == "m" and rest.lower() in ("bps", "hz"):    # "mbps"/"mhz" is written for mega, never milli
                return 1e6, _BASES[rest.lower()]
            return _SI[prefix], _BASES[rest.lower()]
    if u.lower() in _BASES:
        return 1.0, _BASES[u.lower()]
    return 1.0, u


def _split(value, unit):
    """A value like "23 dBm" with no separate unit is split; anything else is left as written."""
    if unit in (None, "") and isinstance(value, str):
        m = _NUMBER.match(value)
        if m and m.group(2) and _unit(m.group(2))[1] in _KNOWN:     # "23 dBm" splits; "10GbE SFP+" is text and stays whole
            return m.group(1), m.group(2)
    return value, unit


def normalise_claim(value, unit):
    """(comparison key, display value, display unit). Numbers with comparable units compare equal across prefixes (1.2 Gbps == 1200 Mbps)."""
    value, unit = _split(value, unit)
    display_value = _text(value) if value is not None else ""
    display_unit = _text(unit) if unit else None
    number = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    elif isinstance(value, str):
        m = _NUMBER.fullmatch(value.strip())
        if m:
            number = float(m.group(1).replace(",", ""))
    scale_base = _unit(unit)
    if number is not None:
        scale, base = scale_base if scale_base else (1.0, None)
        return ("num", float(f"{number * scale:.9g}"), base), display_value, display_unit
    return ("txt", _key(display_value), _key(display_unit or "")), display_value, display_unit


# ------------------------------------------------------------------ one document's contribution

def _sources_of(meta: DocumentMetadata, evidence=None) -> dict:
    return {"documentId": meta.documentId, "version": meta.version, "sha256": meta.sha256, "sourceType": meta.sourceType,
            "sourceEntityId": meta.sourceEntityId, "kmJobId": meta.kmJobId, "evidence": _text(evidence) if evidence else None}


def _strings(values):
    return [_text(v) for v in (values or []) if isinstance(v, (str, int, float)) and _text(v)]


def extract_contribution(meta: DocumentMetadata) -> dict:
    """The claims one document makes, in a fixed shape. Empty lists when the metadata is empty: nothing is inferred."""
    result = meta.result if isinstance(meta.result, dict) else {}
    technical = result.get("technical") if isinstance(result.get("technical"), dict) else {}
    specific = result.get("sourceSpecific") if isinstance(result.get("sourceSpecific"), dict) else {}
    document = result.get("document") if isinstance(result.get("document"), dict) else {}
    claims = []
    for spec in specific.get("specifications") or []:
        if isinstance(spec, dict) and _text(spec.get("field") or "") and spec.get("value") not in (None, ""):
            claims.append({"kind": "specification", "field": _text(spec["field"]), "value": spec["value"], "unit": spec.get("unit"), "evidence": spec.get("evidence")})
    for m in technical.get("measurements") or []:
        if isinstance(m, dict) and _text(m.get("metric") or "") and m.get("value") not in (None, ""):
            claims.append({"kind": "measurement", "field": _text(m["metric"]), "value": m["value"], "unit": m.get("unit"), "evidence": m.get("context"), "context": m.get("context")})
    capabilities = _strings([specific.get("capabilitySummary")]) + _strings(technical.get("testItems")) + _strings(specific.get("testItems"))
    limitations = _strings(specific.get("limitations"))
    identity = {f: _strings(technical.get(f)) for f in IDENTITY_FIELDS}
    summary = _text(document.get("summary") or "") or None
    substantive = bool(claims or capabilities or limitations)
    contribution = {"claims": claims, "capabilities": capabilities, "limitations": limitations, "identity": identity, "summary": summary,
                    "substantive": substantive, "identityOnly": (not substantive) and any(identity.values())}
    contribution["fingerprint"] = hashlib.sha256(json.dumps(contribution, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return contribution


# ------------------------------------------------------------------ store (in memory; the SQL store keeps the same rules)

class StaleManifest(Exception):
    """The manifest is older than the one already analysed: nothing is written."""

    def __init__(self, latest):
        super().__init__("manifest revision is older than the latest analysed revision")
        self.latest = latest


class ManifestConflict(Exception):
    """Same equipment and revision, different manifest hash: CSIT must issue a new revision."""


class EquipmentSynthesisStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._results: dict[str, list[dict]] = {}
        self._contributions: dict[tuple, dict] = {}

    def latest(self, equipment_id):
        with self._lock:
            history = self._results.get(equipment_id)
            return history[-1] if history else None

    def history(self, equipment_id):
        with self._lock:
            return list(self._results.get(equipment_id, []))

    def find(self, equipment_id, analysis_result_id):
        with self._lock:
            return next((r for r in self._results.get(equipment_id, []) if r["analysisResultId"] == analysis_result_id), None)

    def commit(self, result: dict):
        """Compare-and-set under one lock: a result for an older manifest revision than the stored latest is refused (StaleManifest), the same
        result again returns the stored one, anything else becomes the next analysisVersion."""
        with self._lock:
            history = self._results.setdefault(result["equipmentId"], [])
            existing = next((r for r in history if r["analysisResultId"] == result["analysisResultId"]), None)
            if existing:
                return existing, False
            latest = history[-1] if history else None
            if latest and result["manifestRevision"] < latest["manifestRevision"]:
                raise StaleManifest(latest)
            if latest and result["manifestRevision"] == latest["manifestRevision"] and result["manifestHash"] != latest["manifestHash"]:
                raise ManifestConflict("manifestRevision %d already analysed with a different manifestHash" % latest["manifestRevision"])
            stored = {**result, "analysisVersion": (latest["analysisVersion"] if latest else 0) + 1,
                      "supersedesAnalysisResultId": latest["analysisResultId"] if latest else None}
            history.append(stored)
            return stored, True

    def contribution(self, key, build):
        with self._lock:
            if key not in self._contributions:
                self._contributions[key] = build()
                self.extractions += 1
            return self._contributions[key]

    extractions = 0


# ------------------------------------------------------------------ the synthesis

@dataclass
class Outcome:
    kind: Literal["Created", "Duplicate"]
    result: dict


def _add(bucket: dict, key, label, source):
    entry = bucket.setdefault(key, {"value": label, "sources": []})
    if source not in entry["sources"]:
        entry["sources"].append(source)


def _sorted_sources(sources):
    return sorted(sources, key=lambda s: (s["documentId"], s["version"], s["evidence"] or ""))


class EquipmentSynthesizer:
    def __init__(self, source: MetadataSource, store: EquipmentSynthesisStore, *, clock: Callable[[], datetime] | None = None,
                 summarizer: Callable[[dict], str | None] | None = None):
        self.source, self.store = source, store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.summarizer = summarizer   # optional: turns the merged result into prose; None leaves summary.text null (extractive summary only)

    def analyze(self, manifest: EquipmentManifest) -> Outcome:
        latest = self.store.latest(manifest.equipmentId)
        if latest and manifest.manifestRevision < latest["manifestRevision"]:
            raise StaleManifest(latest)
        if latest and manifest.manifestRevision == latest["manifestRevision"] and manifest.manifestHash != latest["manifestHash"]:
            raise ManifestConflict("manifestRevision %d already analysed with a different manifestHash" % latest["manifestRevision"])
        result = self._synthesise(manifest, latest)
        existing = self.store.find(manifest.equipmentId, result["analysisResultId"])
        if existing:
            return Outcome("Duplicate", existing)
        stored, created = self.store.commit(result)
        validate_result(stored)
        return Outcome("Created" if created else "Duplicate", stored)

    # -- pieces
    def _collect(self, manifest):
        used, excluded = [], []
        for doc in sorted(manifest.documents, key=lambda d: (d.documentId, d.version)):
            meta = self.source.get(doc.documentId, doc.version)
            if meta is None:
                excluded.append({"documentId": doc.documentId, "version": doc.version, "reason": "metadata_missing", "hasDocumentSummary": False})
                continue
            if meta.sha256 != doc.sha256:
                excluded.append({"documentId": doc.documentId, "version": doc.version, "reason": "metadata_sha_mismatch", "hasDocumentSummary": False})
                continue
            raw = hashlib.sha256(json.dumps(meta.result, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
            contribution = self.store.contribution((doc.documentId, doc.version, doc.sha256, raw), lambda m=meta: extract_contribution(m))
            if not contribution["substantive"]:
                excluded.append({"documentId": doc.documentId, "version": doc.version, "reason": "identity_only" if contribution["identityOnly"] else "no_technical_content",
                                 "hasDocumentSummary": bool(contribution["summary"]), "contributionFingerprint": contribution["fingerprint"]})
                continue
            used.append((doc, meta, contribution))
        return used, excluded

    def _synthesise(self, manifest, latest):
        used, excluded = self._collect(manifest)
        specs: dict = {}
        capabilities: dict = {}
        limitations: dict = {}
        identity = {f: {} for f in IDENTITY_FIELDS}
        summaries = []
        for doc, meta, c in used:
            for claim in c["claims"]:
                src = _sources_of(meta, claim.get("evidence"))
                nkey, value, unit = normalise_claim(claim["value"], claim.get("unit"))
                group = specs.setdefault((claim["kind"], _key(claim["field"]), _key(claim.get("context") or "") if claim["kind"] == "measurement" else ""),
                                         {"field": claim["field"], "kind": claim["kind"], "context": claim.get("context"), "claims": {}})
                bucket = group["claims"].setdefault(nkey, {"value": value, "unit": unit, "sources": []})
                if src not in bucket["sources"]:
                    bucket["sources"].append(src)
            for text in c["capabilities"]:
                _add(capabilities, _key(text), text, _sources_of(meta))
            for text in c["limitations"]:
                _add(limitations, _key(text), text, _sources_of(meta))
            for f in IDENTITY_FIELDS:
                for text in c["identity"][f]:
                    _add(identity[f], _key(text), text, _sources_of(meta))
            if c["summary"]:
                summaries.append({"text": c["summary"], "sources": [_sources_of(meta)]})

        merged_specs, merged_measurements, conflicts = [], [], []
        for group in sorted(specs.values(), key=lambda g: (g["kind"], _key(g["field"]), _key(g["context"] or ""))):
            claims = list(group["claims"].values())
            for cl in claims:
                cl["sources"] = _sorted_sources(cl["sources"])
            if len(claims) == 1:
                item = {"field": group["field"], "value": claims[0]["value"], "unit": claims[0]["unit"], "sources": claims[0]["sources"],
                        "agreement": "agreed" if len({s["documentId"] for s in claims[0]["sources"]}) > 1 else "single"}
                if group["kind"] == "measurement":
                    item["context"] = group["context"]
                    merged_measurements.append(item)
                else:
                    merged_specs.append(item)
            else:
                conflicts.append({"field": group["field"], "kind": group["kind"], "context": group["context"], "resolution": "none",
                                  "claims": sorted(({"value": c_["value"], "unit": c_["unit"], "sources": c_["sources"]} for c_ in claims),
                                                   key=lambda c_: (c_["sources"][0]["documentId"], str(c_["value"])))})

        def listing(bucket):
            return [{"value": e["value"], "sources": _sorted_sources(e["sources"])} for _, e in sorted(bucket.items())]

        ident = {f: listing(identity[f]) for f in IDENTITY_FIELDS}
        warnings = []
        for f in ("modelNumbers", "productNames"):
            if len(ident[f]) > 1:
                warnings.append({"code": "IDENTITY_VARIANTS", "field": f, "values": [e["value"] for e in ident[f]],
                                 "message": "The documents name this equipment differently; KM did not choose one."})
        if conflicts:
            warnings.append({"code": "SPEC_CONFLICTS", "count": len(conflicts), "message": "Documents disagree on %d field(s); see conflicts." % len(conflicts)})

        if not manifest.documents:
            status, reason = "NoDocuments", "The manifest lists no documents."
        elif not used:
            status, reason = "InsufficientEvidence", "No listed document has extracted specifications, measurements, capabilities or limitations; nothing was merged."
        elif excluded:
            status, reason = "Partial", "%d of %d documents contributed; the others are listed under coverage.excluded." % (len(used), len(manifest.documents))
        else:
            status, reason = "Completed", None

        previous_all = {(d["documentId"], d["version"], d["sha256"]) for d in (latest or {}).get("manifestDocuments", [])}
        now = {(d.documentId, d.version, d.sha256) for d in manifest.documents}
        prev_ids = {k[0]: k for k in previous_all}
        changes = {"basedOn": latest["analysisResultId"] if latest else None,
                   "added": sorted(k[0] for k in now if k[0] not in prev_ids),
                   "replaced": sorted(k[0] for k in now if k[0] in prev_ids and prev_ids[k[0]] != k),
                   "removed": sorted(i for i in prev_ids if i not in {k[0] for k in now}),
                   "unchanged": sorted(k[0] for k in now if k in previous_all)} if latest else {"basedOn": None, "added": sorted(k[0] for k in now), "replaced": [], "removed": [], "unchanged": []}

        fingerprint = hashlib.sha256(json.dumps(
            {"used": [[d.documentId, d.version, d.sha256, c["fingerprint"]] for d, _, c in used],
             "excluded": [[e["documentId"], e["version"], e["reason"], e.get("contributionFingerprint")] for e in excluded]},
            sort_keys=True).encode()).hexdigest()
        result_id = str(uuid.uuid5(_NAMESPACE, "|".join([manifest.equipmentId, manifest.manifestHash, ALGORITHM_VERSION, fingerprint])))
        result = {
            "schemaVersion": SCHEMA_VERSION, "analysisResultId": result_id, "equipmentId": manifest.equipmentId,
            "manifestHash": manifest.manifestHash, "manifestRevision": manifest.manifestRevision,
            "algorithmVersion": ALGORITHM_VERSION, "inputsFingerprint": fingerprint,
            "status": status, "statusReason": reason, "analyzedAt": self.clock().isoformat().replace("+00:00", "Z"),
            "coverage": {"manifestDocuments": len(manifest.documents), "usedDocuments": len(used), "excluded": excluded},
            "summary": {"text": None, "documentSummaries": summaries},
            "identity": ident, "specifications": merged_specs, "measurements": merged_measurements,
            "capabilities": listing(capabilities), "limitations": listing(limitations),
            "conflicts": conflicts, "warnings": warnings, "changes": changes,
            "documents": [{"documentId": d.documentId, "version": d.version, "sha256": d.sha256, "sourceType": d.sourceType, "kmJobId": m.kmJobId,
                           "analysisResultId": d.analysisResultId, "contributionFingerprint": c["fingerprint"]} for d, m, c in used],
            "manifestDocuments": [{"documentId": d.documentId, "version": d.version, "sha256": d.sha256} for d in manifest.documents],
        }
        if self.summarizer and used:
            result["summary"]["text"] = self.summarizer(result)
        return result


# ------------------------------------------------------------------ result schema (PROPOSAL)

def _arr(item):
    return {"type": "array", "items": item}


_SOURCE = {"type": "object", "required": ["documentId", "version", "sha256", "sourceType", "sourceEntityId", "kmJobId", "evidence"]}
_RESULT = {
    "type": "object",
    "required": ["schemaVersion", "analysisResultId", "equipmentId", "manifestHash", "manifestRevision", "analysisVersion", "algorithmVersion",
                 "inputsFingerprint", "status", "statusReason", "analyzedAt", "coverage", "summary", "identity", "specifications", "measurements",
                 "capabilities", "limitations", "conflicts", "warnings", "changes", "documents", "supersedesAnalysisResultId"],
    "properties": {
        "schemaVersion": {"const": SCHEMA_VERSION},
        "status": {"enum": list(STATUSES)},
        "analysisVersion": {"type": "integer", "minimum": 1},
        "manifestRevision": {"type": "integer", "minimum": 1},
        "specifications": _arr({"type": "object", "required": ["field", "value", "unit", "sources", "agreement"],
                                "properties": {"sources": {"type": "array", "minItems": 1, "items": _SOURCE}}}),
        "conflicts": _arr({"type": "object", "required": ["field", "claims", "resolution"],
                           "properties": {"resolution": {"const": "none"}, "claims": {"type": "array", "minItems": 2}}}),
        "capabilities": _arr({"type": "object", "required": ["value", "sources"], "properties": {"sources": {"type": "array", "minItems": 1, "items": _SOURCE}}}),
        "limitations": _arr({"type": "object", "required": ["value", "sources"], "properties": {"sources": {"type": "array", "minItems": 1, "items": _SOURCE}}}),
    },
}
_VALIDATOR = Draft202012Validator(_RESULT)


def validate_result(result: dict) -> None:
    errors = sorted(_VALIDATOR.iter_errors(result), key=lambda e: list(e.path))
    if errors:
        e = errors[0]
        raise ValueError("equipment synthesis result invalid at " + ".".join(str(p) for p in e.path) + ": " + e.message[:120])
    if result["status"] in ("InsufficientEvidence", "NoDocuments") and (result["specifications"] or result["measurements"] or result["capabilities"] or result["limitations"]):
        raise ValueError("a result without contributing documents must be empty")
