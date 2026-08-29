#!/usr/bin/env python3
"""Create a protected, verifiable pre-WP0/WP1 rollback checkpoint."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


APP_CONTAINERS = {
    "web": "kb-web",
    "celery_search_worker": "kb-celery-search",
    "celery_ingest_worker": "kb-celery-ingest",
    "celery_beat": "kb-celery-beat",
    "nginx": "kb-nginx",
}
DATA_CONTAINERS = {
    "redis": "kb-redis",
    "neo4j": "kb-neo4j",
    "report_registry": "kb-report-registry",
    "qdrant": "kb-qdrant",
}


def run(args: list[str], *, cwd: Path | None = None, stdout=None, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, stdout=stdout, text=text, check=True)


def output(args: list[str], *, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def container_env(name: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output(["docker", "inspect", name, "--format", "{{range .Config.Env}}{{println .}}{{end}}"] ).splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def require_containers(names: list[str]) -> None:
    missing = []
    for name in names:
        result = subprocess.run(["docker", "inspect", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            missing.append(name)
    if missing:
        raise RuntimeError(f"required containers are missing: {', '.join(missing)}")


def safe_label(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-.").lower()
    if not cleaned:
        raise ValueError("label must contain at least one safe character")
    return cleaned


def write_secure(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    path.chmod(0o600)


def dotenv_quote(value: str) -> str:
    return "'" + value.replace("'", "\\'") + "'"


def archive_paths(source: Path, destination: Path, paths: list[str], excludes: list[str] | None = None) -> None:
    existing = [item for item in paths if (source / item).exists()]
    if not existing:
        return
    command = ["tar", "-czf", str(destination)]
    for pattern in excludes or []:
        command.append(f"--exclude={pattern}")
    command.extend(["-C", str(source), *existing])
    run(command)
    destination.chmod(0o600)


def backup_sqlite(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    destination.chmod(0o600)


def neo4j_export(destination: Path) -> dict[str, int]:
    env = container_env(DATA_CONTAINERS["neo4j"])
    auth = env.get("NEO4J_AUTH", "")
    if "/" not in auth:
        raise RuntimeError("kb-neo4j does not expose a usable NEO4J_AUTH value")
    user, password = auth.split("/", 1)
    statement = (
        "CALL apoc.export.cypher.all(null,{stream:true,format:'cypher-shell'}) "
        "YIELD cypherStatements,nodes,relationships,properties "
        "RETURN cypherStatements,nodes,relationships,properties"
    )
    payload = json.dumps({"statements": [{"statement": statement}]}).encode()
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(
        "http://127.0.0.1:17474/db/neo4j/tx/commit",
        data=payload,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    if result.get("errors"):
        raise RuntimeError(f"Neo4j export failed: {result['errors']}")
    cypher, nodes, relationships, properties = result["results"][0]["data"][0]["row"]
    write_secure(destination, cypher)
    return {"nodes": nodes, "relationships": relationships, "properties": properties}


def qdrant_snapshots(destination: Path) -> dict[str, dict[str, object]]:
    destination.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen("http://127.0.0.1:6335/collections", timeout=30) as response:
        collections = [item["name"] for item in json.load(response)["result"]["collections"]]
    result: dict[str, dict[str, object]] = {}
    for collection in collections:
        request = urllib.request.Request(
            f"http://127.0.0.1:6335/collections/{collection}/snapshots", data=b"", method="POST"
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            snapshot = json.load(response)["result"]
        name = snapshot["name"]
        target = destination / collection / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(
            f"http://127.0.0.1:6335/collections/{collection}/snapshots/{name}", timeout=300
        ) as response, target.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        target.chmod(0o600)
        result[collection] = {"snapshot": name, "size": target.stat().st_size}
    return result


def checksum_tree(root: Path) -> None:
    lines = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "SHA256SUMS":
            continue
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        lines.append(f"{digest}  {path.relative_to(root)}")
    write_secure(root / "SHA256SUMS", "\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--backup-root", type=Path, default=Path.home() / "kb-pre-wp01-backups")
    parser.add_argument("--label", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--skip-image-archive", action="store_true", help="Tag images but do not save images.tar")
    args = parser.parse_args()

    source = args.source_root.resolve()
    label = safe_label(args.label)
    root = args.backup_root.expanduser().resolve()
    partial = root / f".{label}.partial"
    checkpoint = root / label
    if partial.exists() or checkpoint.exists():
        raise RuntimeError(f"checkpoint already exists: {checkpoint}")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    partial.mkdir(mode=0o700)

    require_containers([*APP_CONTAINERS.values(), *DATA_CONTAINERS.values()])
    started = datetime.now(timezone.utc).isoformat()
    manifest: dict[str, object] = {
        "schema_version": 1,
        "label": label,
        "created_at": started,
        "source_root": str(source),
        "git_head": output(["git", "rev-parse", "HEAD"], cwd=source),
        "git_branch": output(["git", "branch", "--show-current"], cwd=source),
        "consistency": "online component snapshots; full cross-store restore requires a maintenance checkpoint",
        "application_services": list(APP_CONTAINERS),
        "containers": {},
    }
    try:
        source_dir = partial / "source"
        source_dir.mkdir()
        run(["git", "archive", "--format=tar.gz", "-o", str(source_dir / "git-head.tar.gz"), "HEAD"], cwd=source)
        write_secure(source_dir / "git-status.txt", output(["git", "status", "--short", "--branch"], cwd=source) + "\n")
        with (source_dir / "tracked-worktree.patch").open("wb") as handle:
            run(
                ["git", "diff", "--binary", "HEAD", "--", ".", ":!config/**", ":!data/**", ":!**/__pycache__/**"],
                cwd=source,
                stdout=handle,
                text=False,
            )
        (source_dir / "tracked-worktree.patch").chmod(0o600)

        archive_paths(source, partial / "config.tar.gz", ["config"])
        archive_paths(
            source,
            partial / "data-files.tar.gz",
            ["data"],
            excludes=["*.sqlite", "*.sqlite3", "*.db", "*.pyc", "__pycache__"],
        )
        backup_sqlite(source / "data/ingestion-registry.sqlite3", partial / "databases/sqlite/ingestion-registry.sqlite3")

        runtime = partial / "runtime"
        runtime.mkdir()
        for name in ("docker-compose.yml", "nginx.conf"):
            if (source / name).exists():
                shutil.copy2(source / name, runtime / name)
                (runtime / name).chmod(0o600)
        archive_paths(source, runtime / "frontend-build.tar.gz", [".frontend-build-runtime-user8"])

        inspect_payload = {}
        image_tags = {}
        image_ids = []
        for service, container in APP_CONTAINERS.items():
            raw = json.loads(output(["docker", "inspect", container]))[0]
            inspect_payload[container] = raw
            image_id = raw["Image"]
            tag = f"kb-pre-wp01/{service}:{label}"
            run(["docker", "image", "tag", image_id, tag])
            image_tags[service] = tag
            image_ids.append(image_id)
            manifest["containers"][container] = {"image_id": image_id, "rollback_tag": tag}
        write_secure(runtime / "container-inspect.json", json.dumps(inspect_payload, ensure_ascii=False, indent=2))

        override = ["services:"]
        for service, tag in image_tags.items():
            override.extend([f"  {service}:", f"    image: {tag}", "    pull_policy: never"])
        write_secure(runtime / "rollback-images.yml", "\n".join(override) + "\n")

        web_env = container_env(APP_CONTAINERS["web"])
        report_env = container_env(DATA_CONTAINERS["report_registry"])
        rollback_values = {
            "KB_REPORT_DB_PASSWORD": report_env.get("POSTGRES_PASSWORD", ""),
            "KB_INGEST_REQUIRE_AGENT_AUTH": web_env.get("KB_INGEST_REQUIRE_AGENT_AUTH", "false"),
            "KB_ALLOW_LEGACY_INGEST": web_env.get("KB_ALLOW_LEGACY_INGEST", "false"),
            "KB_AGENT_TOKEN_HASHES_JSON": web_env.get("KB_AGENT_TOKEN_HASHES_JSON", "{}"),
            "KB_REVIEWER_TOKEN_HASHES_JSON": web_env.get("KB_REVIEWER_TOKEN_HASHES_JSON", "{}"),
        }
        write_secure(runtime / "rollback.env", "\n".join(f"{key}={dotenv_quote(value)}" for key, value in rollback_values.items()) + "\n")

        images_dir = partial / "images"
        images_dir.mkdir()
        write_secure(images_dir / "image-tags.json", json.dumps(image_tags, indent=2))
        if not args.skip_image_archive:
            run(["docker", "image", "save", "-o", str(images_dir / "application-images.tar"), *image_tags.values()])
            (images_dir / "application-images.tar").chmod(0o600)
        manifest["image_archive_included"] = not args.skip_image_archive

        databases = partial / "databases"
        databases.mkdir(exist_ok=True)
        with (databases / "postgres-kb-reports.dump").open("wb") as handle:
            run(
                ["docker", "exec", DATA_CONTAINERS["report_registry"], "pg_dump", "-U", "kb_report", "-d", "kb_reports", "--format=custom"],
                stdout=handle,
                text=False,
            )
        (databases / "postgres-kb-reports.dump").chmod(0o600)
        run(["docker", "exec", DATA_CONTAINERS["redis"], "redis-cli", "SAVE"], stdout=subprocess.DEVNULL)
        with (databases / "redis-data.tar").open("wb") as handle:
            run(["docker", "exec", DATA_CONTAINERS["redis"], "tar", "-C", "/data", "-cf", "-", "."], stdout=handle, text=False)
        (databases / "redis-data.tar").chmod(0o600)
        manifest["neo4j"] = neo4j_export(databases / "neo4j-export.cypher")
        manifest["qdrant"] = qdrant_snapshots(databases / "qdrant")

        write_secure(partial / "checkpoint.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        checksum_tree(partial)
        partial.rename(checkpoint)
        print(checkpoint)
        return 0
    except Exception:
        print(f"backup failed; partial checkpoint retained for diagnosis: {partial}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
