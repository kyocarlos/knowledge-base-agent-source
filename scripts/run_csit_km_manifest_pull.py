#!/usr/bin/env python3
"""Run the KM-owned CSIT manifest Pull, safely defaulting to dry-run.

The command discovers Project IDs through the enabled-module API, fetches the
dedicated KM V1 manifest, and (only with ``--execute``) downloads and hands
eligible entries to the existing KM document pipeline.  It never reads CSIT
DB/NAS and never prints credentials or document content.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.csit import CsitReadOnlyClient, load_contract, sync_csit_manifest
from src.document_normalization import NormalizationCatalog
from src.ingest_registry import IngestRegistry


def _secret(env_name: str, default_path: str) -> str:
    path = Path(os.getenv(env_name, default_path))
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"empty protected secret file: {path}")
    return value


def _load_catalog(path: Path | None) -> NormalizationCatalog:
    if path is None:
        return NormalizationCatalog.from_dict({})
    return NormalizationCatalog.from_dict(json.loads(path.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="download and run the existing KM ingest pipeline")
    parser.add_argument("--module-code", action="append", dest="module_codes", default=[])
    parser.add_argument("--contract", type=Path, default=ROOT / "config/csit_api_contract.json")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--staging-dir", type=Path, default=Path(os.getenv("CSIT_KM_STAGING_DIR", "data/staging/csit-km")))
    parser.add_argument("--output-dir", type=Path, default=Path(os.getenv("CSIT_KM_OUTPUT_DIR", "data/processed/csit-km")))
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args(argv)

    base_url = os.getenv("CSIT_BASE_URL", "https://csit-system.test:8443")
    ca_cert = os.getenv("CSIT_CA_CERT", "/run/secrets/csit-stage-public.crt")
    username = _secret("CSIT_USERNAME_FILE", "/run/secrets/csit-username")
    password = _secret("CSIT_PASSWORD_FILE", "/run/secrets/csit-password")
    contract = load_contract(args.contract)

    with CsitReadOnlyClient(
        base_url,
        contract,
        username=username,
        password=password,
        timeout=float(os.getenv("CSIT_TIMEOUT_SECONDS", "20")),
        verify=ca_cert,
    ) as client:
        result = sync_csit_manifest(
            client,
            registry=IngestRegistry() if args.execute else None,
            execute=args.execute,
            module_codes=args.module_codes,
            page_size=args.page_size,
            max_pages=args.max_pages,
            staging_dir=str(args.staging_dir),
            output_dir=str(args.output_dir),
            normalization_catalog=_load_catalog(args.catalog),
        )
        summary = result.as_dict()
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
