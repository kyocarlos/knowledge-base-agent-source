"""Pull the dedicated CSIT KM V1 manifest per Project.

The ordinary Module/Record traversal is used only to discover Project IDs.
KM metadata is accepted exclusively from the dedicated KM manifest endpoint;
general CSIT File DTOs are never promoted into the KM Contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .manifest import CsitManifestError, CsitManifestEntry, importable_entries


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "data", "results", "records", "modules"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _id(item: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = item.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _module_code(item: Mapping[str, Any]) -> str:
    return _id(item, "moduleCode", "code", "id", "guid", "uuid")


def _has_next(payload: Any, count: int, page: int, page_size: int) -> bool:
    if isinstance(payload, dict):
        for key in ("hasNext", "hasMore", "has_next", "has_more"):
            if key in payload:
                return bool(payload[key])
        total = payload.get("total") or payload.get("totalCount") or payload.get("count")
        if isinstance(total, int):
            return page * page_size < total
    return count >= page_size


@dataclass(frozen=True, slots=True)
class CsitPullResult:
    entries: tuple[CsitManifestEntry, ...]
    skipped: tuple[dict[str, str], ...]
    modules_seen: int
    records_seen: int
    projects_pulled: int


class CsitTraversalPuller:
    """Discover Projects, then Pull only their dedicated KM manifests."""

    def __init__(self, client: Any, *, page_size: int = 50, max_pages: int = 100) -> None:
        if page_size < 1 or max_pages < 1:
            raise ValueError("page_size and max_pages must be positive")
        self.client = client
        self.page_size = page_size
        self.max_pages = max_pages

    def _paged(self, path: str, *, path_params: Mapping[str, object]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for page in range(1, self.max_pages + 1):
            payload = self.client.get(path, path_params=path_params, query={"page": page, "pageSize": self.page_size})
            page_items = _items(payload)
            result.extend(page_items)
            if not _has_next(payload, len(page_items), page, self.page_size):
                return result
        raise CsitManifestError(f"CSIT pagination exceeded max_pages: {path}")

    def pull(self, *, module_codes: set[str] | None = None) -> CsitPullResult:
        modules = _items(self.client.get("/api/modules/enabled"))
        selected = [item for item in modules if not module_codes or _module_code(item) in module_codes]
        skipped: list[dict[str, str]] = []
        candidates: dict[tuple[str, str, str], CsitManifestEntry] = {}
        records_seen = projects_pulled = 0

        for module in selected:
            module_code = _module_code(module)
            if not module_code:
                skipped.append({"stage": "module", "reason": "missing module code"})
                continue
            records = self._paged("/api/modules/{moduleCode}/records", path_params={"moduleCode": module_code})
            records_seen += len(records)
            for record in records:
                project_id = _id(record, "projectId", "recordId", "id", "guid", "uuid")
                if not project_id:
                    skipped.append({"stage": "record", "reason": "missing projectId"})
                    continue
                try:
                    entries = importable_entries(self.client.get_km_manifest(project_id))
                except CsitManifestError as exc:
                    skipped.append({"stage": "manifest", "project_id": project_id, "reason": str(exc)})
                    continue
                projects_pulled += 1
                for entry in entries:
                    candidates[(entry.document_id, entry.file_id, entry.version)] = entry

        return CsitPullResult(
            entries=tuple(candidates.values()),
            skipped=tuple(skipped),
            modules_seen=len(selected),
            records_seen=records_seen,
            projects_pulled=projects_pulled,
        )
