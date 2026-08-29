"""Deterministic Neo4j projection for canonical test-report workbooks."""

from __future__ import annotations

import hashlib


def _id(*parts: object) -> str:
    return "::".join(str(part) for part in parts)


def write_canonical_test_graph(
    report: dict,
    doc_name: str,
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
) -> dict:
    from neo4j import GraphDatabase

    manifest = report["manifest"]
    environment = manifest["environment"]
    run_id = manifest["run_id"]
    run_key = _id(environment, run_id)
    project_code = manifest["project_code"]
    dut_model = manifest["dut_model"]
    verdict_by_case = {str(row.get("case_id")): row for row in report.get("verdicts", [])}
    measurements = report.get("measurements", [])

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        with driver.session() as session:
            for statement in (
                "CREATE CONSTRAINT test_environment_name IF NOT EXISTS FOR (e:TestEnvironment) REQUIRE e.name IS UNIQUE",
                "CREATE CONSTRAINT test_run_key IF NOT EXISTS FOR (r:TestRun) REQUIRE r.key IS UNIQUE",
                "CREATE CONSTRAINT dut_model IF NOT EXISTS FOR (d:DUT) REQUIRE d.model IS UNIQUE",
                "CREATE CONSTRAINT radio_config_id IF NOT EXISTS FOR (c:RadioConfig) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT verdict_id IF NOT EXISTS FOR (v:Verdict) REQUIRE v.id IS UNIQUE",
            ):
                session.run(statement)
            session.run(
                """
                MERGE (e:TestEnvironment {name: $environment})
                MERGE (r:TestRun {key: $run_key})
                SET r.run_id = $run_id, r.environment = $environment, r.project_code = $project_code,
                    r.dut_model = $dut_model, r.started_at = $started_at, r.finished_at = $finished_at,
                    r.overall_verdict = $overall_verdict, r.schema_version = $schema_version,
                    r.doc_name = $doc_name, r.updated_at = datetime()
                MERGE (p:Project {code: $project_code})
                MERGE (d:DUT {model: $dut_model})
                MERGE (e)-[:EXECUTED]->(r)
                MERGE (p)-[:HAS_RUN]->(r)
                MERGE (r)-[:TESTED_DUT]->(d)
                WITH r
                OPTIONAL MATCH (report:Report {doc_name: $doc_name})
                FOREACH (_ IN CASE WHEN report IS NULL THEN [] ELSE [1] END | MERGE (r)-[:REPRESENTED_BY]->(report))
                """,
                environment=environment, run_key=run_key, run_id=run_id, project_code=project_code,
                dut_model=dut_model, started_at=manifest["started_at"], finished_at=manifest["finished_at"],
                overall_verdict=manifest["overall_verdict"], schema_version=manifest["schema_version"],
                doc_name=doc_name,
            )
            config_id = _id(run_key, "radio")
            session.run(
                """
                MERGE (c:RadioConfig {id: $config_id})
                SET c.values_json = $values_json, c.updated_at = datetime()
                WITH c MATCH (r:TestRun {key: $run_key}) MERGE (r)-[:USES_CONFIG]->(c)
                """,
                config_id=config_id, run_key=run_key,
                values_json=__import__("json").dumps(report.get("radio_config", []), ensure_ascii=False, default=str),
            )
            for case in report.get("test_cases", []):
                external_case_id = str(case.get("case_id"))
                case_id = _id(run_key, "case", external_case_id)
                session.run(
                    """
                    MERGE (c:TestCase {id: $case_id})
                    SET c.case_id = $external_case_id, c.name = $name, c.status = $status,
                        c.run_id = $run_id, c.environment = $environment, c.doc_name = $doc_name,
                        c.updated_at = datetime()
                    WITH c MATCH (r:TestRun {key: $run_key}) MERGE (r)-[:HAS_CASE]->(c)
                    WITH c OPTIONAL MATCH (sc:SourceChunk {doc_name: $doc_name})
                    FOREACH (_ IN CASE WHEN sc IS NULL THEN [] ELSE [1] END | MERGE (c)-[:SUPPORTED_BY]->(sc))
                    """,
                    case_id=case_id, external_case_id=external_case_id, name=str(case.get("name") or ""),
                    status=str(case.get("status") or ""), run_id=run_id, environment=environment,
                    doc_name=doc_name, run_key=run_key,
                )
                verdict = verdict_by_case.get(external_case_id)
                if verdict:
                    verdict_id = _id(case_id, "verdict")
                    session.run(
                        """
                        MERGE (v:Verdict {id: $verdict_id})
                        SET v.value = $value, v.reason = $reason, v.updated_at = datetime()
                        WITH v MATCH (c:TestCase {id: $case_id}) MERGE (c)-[:HAS_VERDICT]->(v)
                        """,
                        verdict_id=verdict_id, case_id=case_id, value=str(verdict.get("verdict") or ""),
                        reason=str(verdict.get("reason") or ""),
                    )
            for index, metric in enumerate(measurements):
                external_case_id = str(metric.get("case_id"))
                case_id = _id(run_key, "case", external_case_id)
                metric_signature = hashlib.sha1(
                    f"{metric.get('metric')}|{metric.get('value')}|{metric.get('unit')}|{index}".encode()
                ).hexdigest()[:16]
                metric_id = _id(case_id, "metric", metric_signature)
                session.run(
                    """
                    MERGE (m:Measurement {id: $metric_id})
                    SET m.name = $name, m.value = $value, m.unit = $unit,
                        m.lower_limit = $lower_limit, m.upper_limit = $upper_limit,
                        m.run_id = $run_id, m.environment = $environment, m.updated_at = datetime()
                    WITH m MATCH (c:TestCase {id: $case_id}) MERGE (c)-[:HAS_MEASUREMENT]->(m)
                    """,
                    metric_id=metric_id, case_id=case_id, name=str(metric.get("metric") or ""),
                    value=float(metric["value"]), unit=str(metric.get("unit") or ""),
                    lower_limit=metric.get("lower_limit"), upper_limit=metric.get("upper_limit"),
                    run_id=run_id, environment=environment,
                )
        return {"test_runs": 1, "test_cases": len(report.get("test_cases", [])), "measurements": len(measurements)}
    finally:
        driver.close()
