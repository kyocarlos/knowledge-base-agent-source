from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_v1_router_has_no_infrastructure_dependencies():
    imports = imported_modules(PROJECT_ROOT / "app" / "api" / "v1" / "router.py")
    forbidden = ("celery", "redis", "neo4j", "qdrant", "psycopg", "src.web_api", "src.vector_store")
    assert not any(module == item or module.startswith(f"{item}.") for module in imports for item in forbidden)


def test_wp0_does_not_modify_a2a_runtime_contract():
    main_source = (PROJECT_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "km_a2a_bridge" not in main_source
