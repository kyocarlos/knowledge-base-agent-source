"""Read and verify a Wi-Fi8 export package (``km.wifi8-package.v1``).

Contract: docs/wifi8-km-package-v1.md. Any mismatch rejects the whole package.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE_SCHEMA = "km.wifi8-package.v1"
MEMBERS = frozenset({"documents.jsonl", "segments.jsonl"})
REQUIRED_DOCUMENT_FIELDS = ("revision_id", "title", "analysis_eligible", "source_sha256", "text_status")
REQUIRED_SEGMENT_FIELDS = ("segment_id", "revision_id", "ordinal", "kind", "location", "text")


class PackageError(ValueError):
    """The package is not a valid, intact Wi-Fi8 export."""


@dataclass(frozen=True)
class Wifi8Package:
    manifest: dict[str, Any]
    documents: list[dict[str, Any]]
    segments: list[dict[str, Any]]

    @property
    def package_id(self) -> str:
        return self.manifest["package_id"]


def _jsonl(data: bytes, name: str, required: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(data.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PackageError(f"{name} line {number} is not JSON") from exc
        if not isinstance(row, dict) or any(field not in row for field in required):
            raise PackageError(f"{name} line {number} is missing required fields")
        rows.append(row)
    return rows


def read_package(path: Path, *, max_uncompressed_bytes: int) -> Wifi8Package:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise PackageError("not a zip package") from exc
    with archive:
        names = set(archive.namelist())
        if names != MEMBERS | {"manifest.json"}:
            raise PackageError("unexpected package members")
        if sum(info.file_size for info in archive.infolist()) > max_uncompressed_bytes:
            raise PackageError("package exceeds the configured size limit")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except json.JSONDecodeError as exc:
            raise PackageError("manifest is not JSON") from exc
        if manifest.get("schema") != PACKAGE_SCHEMA or not str(manifest.get("package_id") or "").startswith("wifi8-"):
            raise PackageError("unsupported package schema")
        files = manifest.get("files") or {}
        if set(files) != MEMBERS:
            raise PackageError("manifest does not list the package members")
        data = {}
        for name in MEMBERS:
            content = archive.read(name)
            if hashlib.sha256(content).hexdigest() != files[name].get("sha256") or len(content) != files[name].get("bytes"):
                raise PackageError(f"checksum mismatch: {name}")
            data[name] = content
    content_sha = hashlib.sha256(b"".join(files[n]["sha256"].encode() for n in sorted(MEMBERS))).hexdigest()
    if content_sha != manifest.get("content_sha256") or manifest["package_id"] != f"wifi8-{content_sha[:16]}":
        raise PackageError("package identity does not match its content")
    documents = _jsonl(data["documents.jsonl"], "documents.jsonl", REQUIRED_DOCUMENT_FIELDS)
    segments = _jsonl(data["segments.jsonl"], "segments.jsonl", REQUIRED_SEGMENT_FIELDS)
    known = {d["revision_id"] for d in documents}
    if len(known) != len(documents):
        raise PackageError("duplicate revision_id in documents.jsonl")
    if any(s["revision_id"] not in known for s in segments):
        raise PackageError("segment refers to an unknown revision_id")
    return Wifi8Package(manifest=manifest, documents=documents, segments=segments)
