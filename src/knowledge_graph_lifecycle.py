"""Neo4j visibility transition for knowledge package revisions."""

from __future__ import annotations

import os


class KnowledgeGraphLifecycle:
    def __init__(self):
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
        )

    def set_package_visibility(self, package_id: str, publish_status: str, is_current: bool) -> bool:
        with self.driver.session() as session:
            result = session.run(
                "MATCH (n) WHERE n.package_id = $package_id "
                "SET n.publish_status = $publish_status, n.is_current = $is_current "
                "RETURN count(n) AS updated",
                package_id=package_id, publish_status=publish_status, is_current=is_current,
            ).single()
        return bool(result and result["updated"])

    def close(self) -> None:
        self.driver.close()
