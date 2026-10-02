#!/usr/bin/env python3
"""Verify rendered Compose release metadata before changing application services."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.release_metadata import validate_release_identity


DEFAULT_SERVICES = ("web", "celery_search_worker", "celery_ingest_worker", "celery_beat")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--build-timestamp", required=True)
    parser.add_argument("--services", nargs="+", default=DEFAULT_SERVICES)
    args = parser.parse_args()

    try:
        expected = validate_release_identity(
            source_commit=args.commit,
            release_id=args.release_id,
            image_digest=args.image_digest,
            build_timestamp=args.build_timestamp,
        )
        rendered = json.load(sys.stdin)
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"release metadata preflight failed: {exc}") from exc

    services = rendered.get("services", {})
    observed: dict[str, dict[str, str]] = {}
    for service_name in args.services:
        service = services.get(service_name)
        if not isinstance(service, dict):
            raise SystemExit(f"release metadata preflight failed: missing service {service_name}")
        environment = service.get("environment")
        if not isinstance(environment, dict):
            raise SystemExit(
                f"release metadata preflight failed: {service_name} environment is not rendered"
            )
        service_values = {name: environment.get(name) for name in expected}
        if service_values != expected:
            mismatches = sorted(name for name in expected if service_values.get(name) != expected[name])
            raise SystemExit(
                f"release metadata preflight failed: {service_name} mismatch: {','.join(mismatches)}"
            )
        validate_release_identity(
            source_commit=service_values["KM_GIT_COMMIT"],
            release_id=service_values["KM_RELEASE_ID"],
            image_digest=service_values["KM_IMAGE_DIGEST"],
            build_timestamp=service_values["KM_BUILD_TIMESTAMP"],
        )
        observed[service_name] = service_values

    print(
        json.dumps(
            {
                "schema": "km.release-compose-metadata-validation.v1",
                "services": list(args.services),
                "metadata_consistent": len({tuple(values.items()) for values in observed.values()}) == 1,
                "result": "PASS",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
