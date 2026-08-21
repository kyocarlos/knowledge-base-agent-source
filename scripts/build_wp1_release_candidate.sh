#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
    printf 'Usage: %s --release-id ID [--output PATH]\n' "$0"
}

release_id=""
output="outputs/wp1-release-candidate-build.json"
while (($#)); do
    case "$1" in
        --release-id) release_id="${2:?--release-id requires a value}"; shift 2 ;;
        --output) output="${2:?--output requires a value}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done

[[ "$release_id" =~ ^[A-Za-z0-9._/-]{1,128}$ ]] || {
    printf 'release id must contain only safe characters\n' >&2
    exit 2
}
command -v docker >/dev/null 2>&1 || { printf 'docker is required\n' >&2; exit 1; }
command -v git >/dev/null 2>&1 || { printf 'git is required\n' >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { printf 'python3 is required\n' >&2; exit 1; }

commit="$(git rev-parse HEAD)"
build_timestamp="$(date --iso-8601=seconds)"
image_tag="kb-wp1-release:${release_id}"
mkdir -p "$(dirname -- "$output")"

# Build only a local image. This command has no compose-up, deploy, migration,
# database, or production side effect.
docker build --pull=false --quiet --tag "$image_tag" . >/dev/null
image_id="$(docker image inspect "$image_tag" --format '{{.Id}}')"

python3 - "$output" "$commit" "$release_id" "$build_timestamp" "$image_tag" "$image_id" <<'PY'
import json
import sys
from pathlib import Path

output, commit, release_id, timestamp, image_tag, image_id = sys.argv[1:]
payload = {
    "schema": "km.wp1.release-candidate-build.v1",
    "release_candidate_commit": commit,
    "release_id": release_id,
    "build_timestamp": timestamp,
    "image_tag": image_tag,
    "image_id": image_id,
    "image_digest_source": "local docker image ID; registry digest requires a separately approved registry push",
    "production_touched": False,
    "deployed": False,
    "secrets_included": False,
}
Path(output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(output)
PY
