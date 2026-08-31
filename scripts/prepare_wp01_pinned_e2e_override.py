#!/usr/bin/env python3
"""Validate a candidate image and create an ephemeral Compose image override.

The override deliberately pins only the application services. It never starts,
stops, or recreates a container.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


APP_SERVICES = ("web", "celery_search_worker", "celery_ingest_worker", "celery_beat")


def run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout if capture else ""


def validate_image(image: str) -> dict[str, object]:
    metadata = json.loads(run(["docker", "image", "inspect", image, "--format", "{{json .}}"], capture=True))
    config = metadata.get("Config") or {}
    working_dir = config.get("WorkingDir") or ""
    if working_dir != "/app":
        raise RuntimeError(f"candidate image WORKDIR must be /app, got {working_dir!r}")
    run([
        "docker", "run", "--rm", "--entrypoint", "sh", image,
        "-lc", "test -f /app/app/main.py && test -f /app/src/main.py",
    ])
    return {
        "image": image,
        "image_id": metadata.get("Id"),
        "working_dir": working_dir,
        "app_main_present": True,
        "src_main_present": True,
        "default_command": config.get("Cmd"),
    }


def write_override(output: Path, image: str) -> None:
    services = "\n".join(
        f"  {service}:\n    image: {image}"
        for service in APP_SERVICES
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "# Generated; ephemeral and must not be committed.\n"
        "services:\n"
        f"{services}\n",
        encoding="utf-8",
    )
    os.chmod(output, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = validate_image(args.image)
    write_override(args.output, args.image)
    print(json.dumps({"override": str(args.output.resolve()), "candidate": evidence}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
