"""Compare a protected DEV Compose reconstruction with existing CSIT containers.

Only environment key names and equality results are emitted. Secret values stay in memory.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def _json_command(argv: list[str]):
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Command failed (exit {result.returncode}); inspect inputs locally")
    return json.loads(result.stdout)


def _text_command(argv: list[str]) -> str:
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Command failed (exit {result.returncode}); inspect inputs locally")
    return result.stdout.strip()


def _duration_ns(value) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    units = {"ns": 1, "us": 1000, "ms": 1000000, "s": 1000000000, "m": 60000000000, "h": 3600000000000}
    total = 0
    for number, unit in re.findall(r"(\d+)(ns|us|ms|s|m|h)", str(value)):
        total += int(number) * units[unit]
    if total == 0 and value not in ("0", "0s"):
        raise ValueError("Unsupported duration")
    return total


def _health_compose(source, image):
    data = source if source is not None else image
    if not data:
        return None
    return {
        "test": data.get("test") or data.get("Test"),
        "interval": _duration_ns(data.get("interval", data.get("Interval"))),
        "timeout": _duration_ns(data.get("timeout", data.get("Timeout"))),
        "retries": data.get("retries", data.get("Retries", 0)),
        "start_period": _duration_ns(data.get("start_period", data.get("StartPeriod"))),
    }


def _health_inspect(data):
    if not data:
        return None
    return {
        "test": data.get("Test"),
        "interval": data.get("Interval", 0),
        "timeout": data.get("Timeout", 0),
        "retries": data.get("Retries", 0),
        "start_period": data.get("StartPeriod", 0),
    }


def _mounts_compose(service):
    mounts = []
    for mount in service.get("volumes", []):
        kind = mount["type"]
        source = mount.get("source", "")
        mounts.append((kind, source, mount["target"], not mount.get("read_only", False)))
    return sorted(mounts)


def _mounts_inspect(container):
    mounts = []
    for mount in container["Mounts"]:
        source = mount.get("Name") if mount["Type"] == "volume" else mount["Source"]
        mounts.append((mount["Type"], source, mount["Destination"], mount["RW"]))
    return sorted(mounts)


def _runtime_spec(service_name, container_name, config, compose_argv):
    service = config["services"][service_name]
    container = _json_command(["docker", "inspect", container_name])[0]
    image = _json_command(["docker", "image", "inspect", service["image"]])[0]
    image_config = image["Config"]
    actual_config = container["Config"]
    host = container["HostConfig"]

    expected_env = dict(entry.split("=", 1) for entry in image_config.get("Env", []) if "=" in entry)
    expected_env.update({key: str(value) for key, value in service.get("environment", {}).items()})
    actual_env = dict(entry.split("=", 1) for entry in actual_config.get("Env", []) if "=" in entry)
    environment_differences = sorted(
        key for key in expected_env.keys() | actual_env.keys() if expected_env.get(key) != actual_env.get(key)
    )

    expected_networks = sorted(config["networks"][key]["name"] for key in service.get("networks", {}))
    actual_networks = sorted(container["NetworkSettings"]["Networks"])
    expected = {
        "image_id": image["Id"],
        "image_revision": image_config.get("Labels", {}).get("org.opencontainers.image.revision"),
        "command": service.get("command") if service.get("command") is not None else image_config.get("Cmd"),
        "entrypoint": service.get("entrypoint") if service.get("entrypoint") is not None else image_config.get("Entrypoint"),
        "working_dir": service.get("working_dir") if service.get("working_dir") is not None else image_config.get("WorkingDir"),
        "user": service.get("user") if service.get("user") is not None else (image_config.get("User") or ""),
        "mounts": _mounts_compose(service),
        "networks": expected_networks,
        "ports": service.get("ports") or [],
        "healthcheck": _health_compose(service.get("healthcheck"), image_config.get("Healthcheck")),
        "restart": service.get("restart") or "",
        "read_only": bool(service.get("read_only")),
        "tmpfs": sorted(item.split(":", 1)[0] for item in service.get("tmpfs", [])),
        "security_opt": sorted(service.get("security_opt") or []),
        "privileged": bool(service.get("privileged")),
    }
    actual = {
        "image_id": container["Image"],
        "image_revision": actual_config.get("Labels", {}).get("org.opencontainers.image.revision"),
        "command": actual_config.get("Cmd"),
        "entrypoint": actual_config.get("Entrypoint"),
        "working_dir": actual_config.get("WorkingDir"),
        "user": actual_config.get("User"),
        "mounts": _mounts_inspect(container),
        "networks": actual_networks,
        "ports": list(host.get("PortBindings") or {}),
        "healthcheck": _health_inspect(actual_config.get("Healthcheck")),
        "restart": host["RestartPolicy"]["Name"],
        "read_only": host["ReadonlyRootfs"],
        "tmpfs": sorted((host.get("Tmpfs") or {}).keys()),
        "security_opt": sorted(host.get("SecurityOpt") or []),
        "privileged": host["Privileged"],
    }
    differences = sorted(key for key in expected if expected[key] != actual[key])
    if environment_differences:
        differences.append("environment")
    expected_mounts = _mounts_compose(service)
    references = {
        "bind_mounts_exist": all(Path(source).exists() for kind, source, _, _ in expected_mounts if kind == "bind"),
        "volumes_exist": all(
            subprocess.run(["docker", "volume", "inspect", source], capture_output=True).returncode == 0
            for kind, source, _, _ in expected_mounts if kind == "volume"
        ),
        "networks_exist": all(
            subprocess.run(["docker", "network", "inspect", name], capture_output=True).returncode == 0
            for name in expected_networks
        ),
    }
    calculated_hash = _text_command(compose_argv + ["config", "--hash", service_name]).split()[-1]
    label_hash = actual_config.get("Labels", {}).get("com.docker.compose.config-hash")
    return {
        "service": service_name,
        "container": container_name,
        "state": container["State"]["Status"],
        "health": (container["State"].get("Health") or {}).get("Status"),
        "image_id": actual["image_id"],
        "image_revision": actual["image_revision"],
        "command": actual["command"],
        "entrypoint": actual["entrypoint"],
        "working_dir": actual["working_dir"],
        "environment_key_names": sorted(actual_env),
        "environment_value_parity": not environment_differences,
        "environment_different_key_names": environment_differences,
        "mounts": actual["mounts"],
        "networks": actual["networks"],
        "ports": actual["ports"],
        "healthcheck": actual["healthcheck"],
        "restart": actual["restart"],
        "user": actual["user"],
        "read_only": actual["read_only"],
        "tmpfs": actual["tmpfs"],
        "security_opt": actual["security_opt"],
        "privileged": actual["privileged"],
        "profiles": service.get("profiles", []),
        "role": "API" if service_name == "api" else "OFF worker",
        "references": references,
        "runtime_critical_semantic_diff": differences,
        "compose_hash": {"reconstructed": calculated_hash, "container_label": label_hash, "classification": "generated_or_stale_metadata" if calculated_hash != label_hash and not differences else "match" if calculated_hash == label_hash else "requires_review"},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--compose-file", action="append", required=True)
    parser.add_argument("--api-container", required=True)
    parser.add_argument("--worker-container", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    for path in [args.env_file, *args.compose_file]:
        if not Path(path).is_file():
            raise SystemExit(f"Missing input: {path}")
    compose_argv = ["docker", "compose", "--profile", "m2m-ready", "--env-file", args.env_file, "-p", args.project]
    for path in args.compose_file:
        compose_argv.extend(["-f", path])
    config = _json_command(compose_argv + ["config", "--format", "json"])
    specs = [
        _runtime_spec("api", args.api_container, config, compose_argv),
        _runtime_spec("worker", args.worker_container, config, compose_argv),
    ]
    document = {
        "schema": "km.csit.normalized-runtime-spec.v1",
        "inputs": {"project": args.project, "compose_files": args.compose_file, "env_file": args.env_file},
        "services": specs,
        "runtime_critical_semantic_diff": sorted({key for item in specs for key in item["runtime_critical_semantic_diff"]}),
        "secret_values_persisted": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    output.chmod(0o600)
    print("NORMALIZED_RUNTIME_SPEC", "PASS" if not document["runtime_critical_semantic_diff"] and all(all(item["references"].values()) for item in specs) else "FAIL")
    for item in specs:
        print(item["service"], "DIFF", item["runtime_critical_semantic_diff"], "HASH", item["compose_hash"]["classification"])


if __name__ == "__main__":
    main()
