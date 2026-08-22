#!/usr/bin/env python3
"""Generate non-secret runtime identity variables for an approved release."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


COMMIT = re.compile(r"^[0-9a-f]{40}$")
RELEASE = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
TIMESTAMP = re.compile(r"^[0-9TZ:._+/-]{1,64}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--build-timestamp", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    values = {
        "KM_GIT_COMMIT": (COMMIT, args.commit),
        "KM_RELEASE_ID": (RELEASE, args.release_id),
        "KM_IMAGE_DIGEST": (DIGEST, args.image_digest),
        "KM_BUILD_TIMESTAMP": (TIMESTAMP, args.build_timestamp),
    }
    for name, (pattern, value) in values.items():
        if not pattern.fullmatch(value):
            raise SystemExit(f"{name} has an invalid format")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(f"{name}={value}\n" for name, (_, value) in values.items()),
        encoding="utf-8",
    )
    args.output.chmod(0o600)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
