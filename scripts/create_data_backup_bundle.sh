#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_ROOT="${KB_BACKUP_ROOT:-$PROJECT_DIR/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BUNDLE_NAME="knowledge-base-data-${STAMP}.tar.gz"
BUNDLE_PATH="$BACKUP_ROOT/$BUNDLE_NAME"
MANIFEST_PATH="$BACKUP_ROOT/knowledge-base-data-${STAMP}.manifest.txt"

mkdir -p "$BACKUP_ROOT"

paths=()
for rel in data/raw data/processed data/assets data/uploads config/config.yaml; do
  if [[ -e "$PROJECT_DIR/$rel" ]]; then
    paths+=("$rel")
  fi
done

if [[ ${#paths[@]} -eq 0 ]]; then
  echo "No backup sources found."
  exit 1
fi

{
  echo "project_dir=$PROJECT_DIR"
  echo "git_commit=$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "created_at=$STAMP"
  echo "included_paths:"
  printf '  - %s\n' "${paths[@]}"
} > "$MANIFEST_PATH"

tar -czf "$BUNDLE_PATH" -C "$PROJECT_DIR" "${paths[@]}"
sha256sum "$BUNDLE_PATH" >> "$MANIFEST_PATH"

echo "Created backup bundle:"
echo "  $BUNDLE_PATH"
echo "Manifest:"
echo "  $MANIFEST_PATH"
