"""CSIT integration contracts and read-only adapter primitives."""

from .client import AuthProvider, CsitReadOnlyClient, CsitRequestError, KM_MANIFEST_PATH, StaticHeaderAuthProvider
from .contract import CsitContract, CsitEndpoint, load_contract
from .report_mapping import CsitMetadataError, CsitReportSource
from .manifest import CsitManifestEntry, CsitManifestError, importable_entries, normalize_file_contract, parse_manifest, verify_download_hash
from .pull import CsitPullResult, CsitTraversalPuller
from .ingest import CsitManifestIngestError, CsitManifestIngestResult, CsitManifestIngestor
from .sync import CsitSyncResult, sync_csit_manifest

__all__ = [
    "CsitContract",
    "CsitEndpoint",
    "AuthProvider",
    "CsitReadOnlyClient",
    "CsitRequestError",
    "KM_MANIFEST_PATH",
    "StaticHeaderAuthProvider",
    "CsitMetadataError",
    "CsitReportSource",
    "load_contract",
    "CsitManifestEntry",
    "CsitManifestError",
    "parse_manifest",
    "normalize_file_contract",
    "importable_entries",
    "verify_download_hash",
    "CsitPullResult",
    "CsitTraversalPuller",
    "CsitManifestIngestError",
    "CsitManifestIngestResult",
    "CsitManifestIngestor",
    "CsitSyncResult",
    "sync_csit_manifest",
]
