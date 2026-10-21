"""Read and verify a Wi-Fi8 export package (``km.wifi8-package.v1`` or ``v2``).

Contract: docs/wifi8-km-package-v1.md (v2 adds figures). Any mismatch rejects the whole package.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE_SCHEMA = "km.wifi8-package.v1"
# v2 adds images.jsonl plus one images/<sha256>.<png|jpg> file per distinct figure; the file name is its checksum.
SCHEMA_MEMBERS = {
    PACKAGE_SCHEMA: frozenset({"documents.jsonl", "segments.jsonl"}),
    "km.wifi8-package.v2": frozenset({"documents.jsonl", "segments.jsonl", "images.jsonl"}),
}
MEMBERS = SCHEMA_MEMBERS[PACKAGE_SCHEMA]
IMAGE_MEMBER = re.compile(r"images/([0-9a-f]{64})\.(png|jpg)")
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg"}
REQUIRED_DOCUMENT_FIELDS = ("revision_id", "title", "analysis_eligible", "source_sha256", "text_status")
REQUIRED_SEGMENT_FIELDS = ("segment_id", "revision_id", "ordinal", "kind", "location", "text")
REQUIRED_IMAGE_FIELDS = ("image_id", "revision_id", "ordinal", "location", "extension")


class PackageError(ValueError):
    """The package is not a valid, intact Wi-Fi8 export."""


@dataclass(frozen=True)
class Wifi8Package:
    manifest: dict[str, Any]
    documents: list[dict[str, Any]]
    segments: list[dict[str, Any]]
    images: list[dict[str, Any]] = ()
    path: Path | None = None

    @property
    def package_id(self) -> str:
        return self.manifest["package_id"]

    def image_bytes(self, image_id: str, extension: str) -> bytes:
        """One figure, checked against its content hash again on every read."""
        with zipfile.ZipFile(self.path) as archive:
            data = archive.read(f"images/{image_id}.{extension}")
        if hashlib.sha256(data).hexdigest() != image_id:
            raise PackageError(f"checksum mismatch: images/{image_id}.{extension}")
        return data


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


def read_package(path: Path, *, max_uncompressed_bytes: int, verify_images: bool = True) -> Wifi8Package:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise PackageError("not a zip package") from exc
    with archive:
        names = set(archive.namelist())
        if "manifest.json" not in names:
            raise PackageError("unexpected package members")
        if sum(info.file_size for info in archive.infolist()) > max_uncompressed_bytes:
            raise PackageError("package exceeds the configured size limit")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except json.JSONDecodeError as exc:
            raise PackageError("manifest is not JSON") from exc
        members = SCHEMA_MEMBERS.get(manifest.get("schema"))
        if members is None or not str(manifest.get("package_id") or "").startswith("wifi8-"):
            raise PackageError("unsupported package schema")
        image_files = {name for name in names if IMAGE_MEMBER.fullmatch(name)}
        if names - image_files != members | {"manifest.json"} or (image_files and "images.jsonl" not in members):
            raise PackageError("unexpected package members")
        files = manifest.get("files") or {}
        if set(files) != members:
            raise PackageError("manifest does not list the package members")
        if verify_images:
            for name in image_files:
                if hashlib.sha256(archive.read(name)).hexdigest() != IMAGE_MEMBER.fullmatch(name).group(1):
                    raise PackageError(f"checksum mismatch: {name}")
        data = {}
        for name in members:
            content = archive.read(name)
            if hashlib.sha256(content).hexdigest() != files[name].get("sha256") or len(content) != files[name].get("bytes"):
                raise PackageError(f"checksum mismatch: {name}")
            data[name] = content
    content_sha = hashlib.sha256(b"".join(files[n]["sha256"].encode() for n in sorted(members))).hexdigest()
    if content_sha != manifest.get("content_sha256") or manifest["package_id"] != f"wifi8-{content_sha[:16]}":
        raise PackageError("package identity does not match its content")
    documents = _jsonl(data["documents.jsonl"], "documents.jsonl", REQUIRED_DOCUMENT_FIELDS)
    segments = _jsonl(data["segments.jsonl"], "segments.jsonl", REQUIRED_SEGMENT_FIELDS)
    known = {d["revision_id"] for d in documents}
    if len(known) != len(documents):
        raise PackageError("duplicate revision_id in documents.jsonl")
    if any(s["revision_id"] not in known for s in segments):
        raise PackageError("segment refers to an unknown revision_id")
    images = _jsonl(data["images.jsonl"], "images.jsonl", REQUIRED_IMAGE_FIELDS) if "images.jsonl" in data else []
    if any(i["revision_id"] not in known for i in images):
        raise PackageError("image refers to an unknown revision_id")
    if {f"images/{i['image_id']}.{i['extension']}" for i in images} != image_files:
        raise PackageError("image files do not match images.jsonl")
    return Wifi8Package(manifest=manifest, documents=documents, segments=segments, images=images, path=path)
