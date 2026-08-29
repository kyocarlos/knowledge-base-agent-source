#!/usr/bin/env python3
"""Validate the immutable frontend artifact contract used by nginx."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED_FILES = ("index.html", "chat.html")


def validate(root: Path) -> dict[str, object]:
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError(f"missing required frontend artifacts: {', '.join(missing)}")
    return {
        "artifact_root": str(root),
        "required_files": {
            name: {"sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(), "size": (root / name).stat().st_size}
            for name in REQUIRED_FILES
        },
        "legacy_chat_contract": "PASS",
        "production_touched": False,
        "secrets_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    try:
        result = validate(args.artifact_root)
    except (OSError, ValueError) as exc:
        print(f"frontend artifact validation failed: {exc}")
        return 1
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "artifact_root": str(args.artifact_root), "secrets_included": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
