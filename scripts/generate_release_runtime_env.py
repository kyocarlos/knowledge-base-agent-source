#!/usr/bin/env python3
"""Generate non-secret runtime identity variables for an approved release."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.release_metadata import validate_release_identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--build-timestamp", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        values = validate_release_identity(
            source_commit=args.commit,
            release_id=args.release_id,
            image_digest=args.image_digest,
            build_timestamp=args.build_timestamp,
        )
    except ValueError as exc:
        raise SystemExit(f"release metadata is invalid: {exc}") from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(f"{name}={value}\n" for name, value in values.items()),
        encoding="utf-8",
    )
    args.output.chmod(0o600)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
