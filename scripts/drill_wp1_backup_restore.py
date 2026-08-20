#!/usr/bin/env python3
"""Exercise the repository data backup bundle in an isolated shadow directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


def tree_hash(root: Path, included: tuple[str, ...] = ("data", "config")) -> str:
    digest = hashlib.sha256()
    selected = [root / name for name in included]
    for path in sorted(p for base in selected for p in base.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = args.report.expanduser().resolve()
    report.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, object] = {
        "schema": "km.wp1.backup-restore-shadow.v1",
        "mode": "isolated-shadow",
        "production_touched": False,
        "data_write_scope": "temporary filesystem only",
    }
    with tempfile.TemporaryDirectory(prefix="kb-wp1-backup-") as temp:
        root = Path(temp)
        project = root / "project"
        backup_root = root / "backups"
        restore = root / "restored"
        for relative in ("data/raw", "data/processed", "data/assets", "data/uploads", "config"):
            (project / relative).mkdir(parents=True)
        (project / "data/raw/sample.txt").write_text("shadow source record\n", encoding="utf-8")
        (project / "data/processed/result.json").write_text('{"status":"shadow"}\n', encoding="utf-8")
        (project / "config/config.yaml").write_text("mode: shadow\n", encoding="utf-8")

        (project / "scripts").mkdir()
        script = project / "scripts/create_data_backup_bundle.sh"
        source_script = Path(__file__).with_name("create_data_backup_bundle.sh")
        shutil.copyfile(source_script, script)
        script.chmod(0o700)
        before = tree_hash(project)
        result = subprocess.run(
            [str(script)], cwd=project, env={"PATH": "/usr/bin:/bin", "KB_BACKUP_ROOT": str(backup_root)},
            text=True, capture_output=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"backup command failed ({result.returncode}): stdout={result.stdout.strip()} stderr={result.stderr.strip()}"
            )
        bundles = sorted(backup_root.glob("*.tar.gz"))
        manifests = sorted(backup_root.glob("*.manifest.txt"))
        if len(bundles) != 1 or len(manifests) != 1:
            raise RuntimeError("backup bundle or manifest count mismatch")
        bundle, manifest = bundles[0], manifests[0]
        evidence["backup_command_output"] = result.stdout
        evidence["bundle_sha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
        evidence["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
        evidence["manifest"] = manifest.read_text(encoding="utf-8")

        shutil.rmtree(project / "data")
        (project / "data").mkdir()
        restore.mkdir()
        with tarfile.open(bundle, "r:gz") as archive:
            archive.extractall(restore)
        restored_hash = tree_hash(restore)
        evidence["source_tree_hash"] = before
        evidence["restored_tree_hash"] = restored_hash
        evidence["restore_verified"] = before == restored_hash
        if before != restored_hash:
            raise RuntimeError(f"restore hash mismatch: {before} != {restored_hash}")

    evidence["cleanup_verified"] = True
    output = report / "backup-restore-shadow-20260820.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
