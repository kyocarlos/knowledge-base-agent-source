from __future__ import annotations

import subprocess
import sys
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_compose_template_has_separate_persistent_stateful_services():
    document = yaml.safe_load((ROOT / "deploy/tenant-isolation/docker-compose.instance.yml").read_text())
    services = document["services"]
    assert {"neo4j", "qdrant", "timescaledb", "report_registry", "redis", "web"} <= services.keys()
    assert "qdrant_storage:/qdrant/storage" in services["qdrant"]["volumes"]
    assert services["web"]["environment"]["KM_INSTANCE_ID"] == "${KM_INSTANCE_ID}"
    assert "KM_HTTPS_PORT" in services["nginx"]["ports"][0]
    assert "container_name" not in services["neo4j"]
    assert document["networks"]["control_network"]["external"] is True


def test_control_plane_has_only_auth_state_and_no_km_business_stores():
    document = yaml.safe_load((ROOT / "deploy/control-plane/docker-compose.control.yml").read_text())
    assert {"control_db", "control_auth"} == set(document["services"])
    assert all("ports" not in service for service in document["services"].values())
    rendered = json.dumps(document).lower()
    assert "qdrant" not in rendered and "neo4j" not in rendered and "timescale" not in rendered


def test_three_example_definitions_are_distinct():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_tenant_isolation.py",
            "deploy/tenant-isolation/test.env.example",
            "deploy/tenant-isolation/da40.env.example",
            "deploy/tenant-isolation/rd2.env.example",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert "PASS" in result.stdout


def test_existing_data_is_explicitly_designated_as_test_only():
    baseline = json.loads((ROOT / "docs/test-data-plane-baseline-20260929.json").read_text())
    assert baseline["instance_id"] == "test"
    assert baseline["neo4j"]["nodes"] == 1832
    assert baseline["qdrant"]["knowledge_base_points"] == 4001
    assert "DA40 and RD2 must start empty" in baseline["non_destructive_guarantee"]
