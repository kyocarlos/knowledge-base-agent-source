"""Pull CSIT Asset (equipment / goods) master data through read-only GETs.

Covers the four Phase 1 Asset endpoints of CSIT_KM_REST_API_v1.0:
list, detail, file list and file content.  Assets are a Knowledge Source of
their own (spec, location, owner, custodian); they are not Test Reports and
never go through the Project manifest.  This module only reads and shapes
metadata; it does not download file content or write any KM store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .pull import _items

ASSET_LIST_PATH = "/api/assets/{moduleCode}"
ASSET_DETAIL_PATH = "/api/assets/{moduleCode}/{id}"
ASSET_FILES_PATH = "/api/assets/{moduleCode}/{id}/files"
ASSET_FILE_CONTENT_PATH = "/api/assets/files/{fileId}/content"

# The workbook names ``equipment`` and ``goods`` as example moduleCodes.
DEFAULT_ASSET_MODULES = ("equipment", "goods")

# Finance / personal fields in ApparatusDetailDto.  KM answers about spec,
# place, owner and custodian; price and account data are not needed for that.
EXCLUDED_FIELDS = frozenset(
    {"costprice", "priceuse", "yearsuse", "daysuse", "procurementstaff", "custodianaccount", "imei"}
)


def _field(item: Mapping[str, Any], *names: str) -> str:
    """Case-insensitive scalar lookup; CSIT DTO casing is not frozen."""
    lowered = {str(key).lower(): value for key, value in item.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None and not isinstance(value, (dict, list)) and str(value).strip():
            return str(value).strip()
    return ""


@dataclass(frozen=True, slots=True)
class CsitAssetFile:
    file_id: str
    file_name: str = ""
    content_type: str = ""
    file_size: int = 0

    @classmethod
    def from_dict(cls, item: Mapping[str, Any]) -> "CsitAssetFile | None":
        file_id = _field(item, "id", "fileId")
        if not file_id:
            return None
        size = _field(item, "fileSize", "size")
        return cls(
            file_id=file_id,
            file_name=_field(item, "fileName", "name", "originalName"),
            content_type=_field(item, "contentType", "mimeType"),
            file_size=int(size) if size.isdigit() else 0,
        )


@dataclass(frozen=True, slots=True)
class CsitAssetEntry:
    module_code: str
    asset_id: str
    name: str
    fields: tuple[tuple[str, str], ...]
    files: tuple[CsitAssetFile, ...] = ()

    @property
    def document_id(self) -> str:
        return f"csit-asset:{self.module_code}:{self.asset_id}"

    def value(self, name: str) -> str:
        key = name.lower()
        return next((v for k, v in self.fields if k.lower() == key), "")

    def to_source_metadata(self) -> dict[str, Any]:
        return {
            "source_system": "CSIT",
            "source_record_id": self.asset_id,
            "document_id": self.document_id,
            "artifact_type": "asset",
            "csit_module_code": self.module_code,
            "csit_asset_id": self.asset_id,
            "csit_asset_kind": self.value("kind"),
            "csit_asset_row_version": self.value("rowVersion"),
            "source_file_name": self.name,
            "csit_asset_file_ids": [f.file_id for f in self.files],
        }

    def to_text(self) -> str:
        """Render a plain Markdown card suitable for the document pipeline."""
        lines = [f"# {self.name or self.asset_id}", ""]
        lines += [f"- {key}: {value}" for key, value in self.fields]
        if self.files:
            lines += ["", "## 附件"] + [f"- {f.file_name or f.file_id}" for f in self.files]
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class CsitAssetPullResult:
    entries: tuple[CsitAssetEntry, ...]
    skipped: tuple[dict[str, str], ...]
    modules_seen: int


class CsitAssetPuller:
    """List → detail → files for each Asset module; fail-closed per asset."""

    def __init__(self, client: Any, *, module_codes: tuple[str, ...] = DEFAULT_ASSET_MODULES, include_files: bool = True) -> None:
        if not module_codes:
            raise ValueError("at least one asset module code is required")
        self.client = client
        self.module_codes = tuple(module_codes)
        self.include_files = include_files

    def pull(self, *, keyword: str | None = None, kind: str | None = None) -> CsitAssetPullResult:
        entries: list[CsitAssetEntry] = []
        skipped: list[dict[str, str]] = []
        for module_code in self.module_codes:
            try:
                listing = _items(self.client.get(ASSET_LIST_PATH, path_params={"moduleCode": module_code}, query={"keyword": keyword, "kind": kind}))
            except Exception as exc:  # sanitized: only the exception type leaves this module
                skipped.append({"stage": "list", "module_code": module_code, "reason": type(exc).__name__})
                continue
            for row in listing:
                asset_id = _field(row, "id", "assetId")
                if not asset_id:
                    skipped.append({"stage": "asset", "module_code": module_code, "reason": "missing asset id"})
                    continue
                try:
                    entries.append(self._entry(module_code, asset_id))
                except Exception as exc:
                    skipped.append({"stage": "detail", "module_code": module_code, "asset_id": asset_id, "reason": type(exc).__name__})
        return CsitAssetPullResult(entries=tuple(entries), skipped=tuple(skipped), modules_seen=len(self.module_codes))

    def _entry(self, module_code: str, asset_id: str) -> CsitAssetEntry:
        params = {"moduleCode": module_code, "id": asset_id}
        detail = self.client.get(ASSET_DETAIL_PATH, path_params=params)
        if not isinstance(detail, Mapping):
            raise ValueError("asset detail is not an object")
        fields = tuple(
            (str(key), _field(detail, str(key)))
            for key in detail
            if str(key).lower() not in EXCLUDED_FIELDS and _field(detail, str(key))
        )
        files: list[CsitAssetFile] = []
        if self.include_files:
            for item in _items(self.client.get(ASSET_FILES_PATH, path_params=params)):
                parsed = CsitAssetFile.from_dict(item)
                if parsed:
                    files.append(parsed)
        return CsitAssetEntry(
            module_code=module_code,
            asset_id=asset_id,
            name=_field(detail, "name", "nameEn"),
            fields=fields,
            files=tuple(files),
        )
