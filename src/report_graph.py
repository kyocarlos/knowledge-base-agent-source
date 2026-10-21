"""
Report 類型文件的 Neo4j 關聯攝入。

目標：
- 讓不同專案的 Excel 報告，能以共通 TestItem 關聯。
- 保留 Section / TestCase / SourceChunk 作為可追溯證據。
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


PROJECT_RE = re.compile(r"(?:scu|sce)\d+", re.IGNORECASE)
SECTION_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def extract_project_code(text: str) -> str | None:
    match = PROJECT_RE.search(text or "")
    if not match:
        return None
    return match.group(0).upper()


def extract_band(text: str) -> str | None:
    match = re.search(r"\bn\d{2,3}[a-z]?\b", text or "", re.IGNORECASE)
    if not match:
        return None
    return match.group(0).lower()


def infer_report_type(doc_name: str, content: str) -> str:
    haystack = f"{doc_name}\n{content}".lower()
    if "handover" in haystack:
        return "handover"
    if "throughput" in haystack or "performance test" in haystack or "ota throughput" in haystack:
        return "throughput"
    if "wifi" in haystack:
        return "wifi"
    return "generic_report"


def extract_report_title(content: str) -> str | None:
    patterns = [
        r"(?im)^\|\s*(OTA Throughput Test Report|NG/Xn Handover Test Report)\s*\|",
        r"(?im)^\|\s*([^|]{8,80}?Test Report)\s*\|",
    ]
    for pattern in patterns:
        match = re.search(pattern, content or "")
        if match:
            return match.group(1).strip()
    return None


def clean_heading(raw_heading: str) -> tuple[str, str]:
    raw_heading = (raw_heading or "").strip()
    match = re.match(r"^(#{1,6})\s+(.+)$", raw_heading)
    if not match:
        return "", raw_heading
    level = str(len(match.group(1)))
    title = match.group(2).strip()
    return level, title


def canonicalize_test_items(section_title: str, section_text: str, report_type: str) -> list[str]:
    """回傳此 section 可對應的標準 TestItem 清單。"""
    text = f"{section_title}\n{section_text}".lower()
    items: list[str] = []

    if "handover" in text or report_type == "handover":
        if any(hint in text for hint in ("handover", "intra xn", "intra ng", "inter xn", "inter ng")):
            return ["handover"]
        if report_type == "handover":
            return ["handover"]

    is_throughput_section = any(hint in text for hint in ("performance test", "throughput", "test result summary", "ota throughput"))
    has_latency_signal = any(hint in text for hint in ("latency test", "rtt (ms)", " latency ", "\nlatency", " rtt ", "\nrtt"))
    has_throughput_signal = any(hint in text for hint in ("throughput", "tcp", "udp", "bler"))

    if is_throughput_section or has_throughput_signal:
        items.append("throughput")

    # Throughput 類報告的 Latency 區塊需要獨立成 TestItem，才能做跨專案 latency 查詢。
    if report_type == "throughput" and has_latency_signal:
        items.append("latency")

    # 去重但保留順序
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def canonicalize_test_item(section_title: str, section_text: str, report_type: str) -> str | None:
    items = canonicalize_test_items(section_title, section_text, report_type)
    return items[0] if items else None


def parse_sections_from_chunks(chunks: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for idx, chunk in enumerate(chunks or []):
        metadata = chunk.get("metadata") or {}
        header = str(metadata.get("header") or "").strip()
        content = str(chunk.get("content") or "").strip()
        if not header:
            heading_match = SECTION_RE.search(content)
            header = heading_match.group(0).strip() if heading_match else "## Untitled"
        grouped[header].append({
            "chunk_index": idx,
            "content": content,
            "metadata": metadata,
        })

    sections: list[dict] = []
    for order, (header, group_chunks) in enumerate(grouped.items()):
        level, title = clean_heading(header)
        section_text = "\n\n".join(item["content"] for item in group_chunks if item["content"])
        sections.append({
            "section_id": _sha1(header.lower()),
            "header": header,
            "level": level,
            "title": title,
            "order": order,
            "text": section_text,
            "chunks": group_chunks,
        })
    return sections


def parse_markdown_table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in (text or "").splitlines():
        if not TABLE_ROW_RE.match(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells:
            rows.append(cells)
    return rows


def extract_case_numbers(section_text: str) -> list[int]:
    case_numbers: set[int] = set()

    # 直接標記：4.13 Test Case 13 / Test Case 13
    for match in re.finditer(r"test case\s*(\d+)", section_text, flags=re.IGNORECASE):
        try:
            case_numbers.add(int(match.group(1)))
        except ValueError:
            pass

    # 表格形式：| Test Case |  | 1 |  | 2 | ...
    for row in parse_markdown_table_rows(section_text):
        row_text = " | ".join(row).lower()
        if "test case" not in row_text:
            continue
        direct = re.search(r"test case\s*(\d+)", row_text, flags=re.IGNORECASE)
        if direct:
            try:
                case_numbers.add(int(direct.group(1)))
            except ValueError:
                pass
            continue
        for cell in row:
            if re.fullmatch(r"\d{1,2}", cell or ""):
                try:
                    case_numbers.add(int(cell))
                except ValueError:
                    pass

    return sorted(case_numbers)


def extract_metric_rows(section_text: str) -> list[dict]:
    metrics: list[dict] = []
    for row in parse_markdown_table_rows(section_text):
        row_text = " | ".join(row).strip()
        if not row_text:
            continue
        lower = row_text.lower()
        if "test case" in lower:
            continue
        if not any(re.search(r"\d", cell or "") for cell in row[1:]):
            continue

        label_parts = [cell for cell in row[:2] if cell and not re.fullmatch(r"\d+(?:\.\d+)?", cell)]
        metric_name = " ".join(label_parts).replace("\n", " ").strip() or row[0].replace("\n", " ").strip()
        value_text = " | ".join(cell for cell in row[1:] if cell)
        metrics.append({
            "name": metric_name,
            "value_text": value_text,
            "row_text": row_text,
        })
    return metrics


def setup_report_graph_schema(neo4j_uri: str, neo4j_user: str, neo4j_password: str) -> bool:
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.error("neo4j Python 驅動未安裝，請執行：pip install neo4j")
        return False

    driver = None
    try:
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        with driver.session() as session:
            session.run("""
                CREATE CONSTRAINT project_code IF NOT EXISTS
                FOR (p:Project) REQUIRE p.code IS UNIQUE
            """)
            session.run("""
                CREATE CONSTRAINT report_doc_name IF NOT EXISTS
                FOR (r:Report) REQUIRE r.doc_name IS UNIQUE
            """)
            session.run("""
                CREATE CONSTRAINT section_id IF NOT EXISTS
                FOR (s:Section) REQUIRE s.id IS UNIQUE
            """)
            session.run("""
                CREATE CONSTRAINT testitem_canonical_name IF NOT EXISTS
                FOR (t:TestItem) REQUIRE t.canonical_name IS UNIQUE
            """)
            session.run("""
                CREATE CONSTRAINT testcase_id IF NOT EXISTS
                FOR (c:TestCase) REQUIRE c.id IS UNIQUE
            """)
            session.run("""
                CREATE CONSTRAINT metric_id IF NOT EXISTS
                FOR (m:Metric) REQUIRE m.id IS UNIQUE
            """)
            session.run("""
                CREATE CONSTRAINT sourcechunk_id IF NOT EXISTS
                FOR (sc:SourceChunk) REQUIRE sc.id IS UNIQUE
            """)
            session.run("""
                CREATE INDEX report_type_index IF NOT EXISTS
                FOR (r:Report) ON (r.report_type)
            """)
            session.run("""
                CREATE INDEX testitem_name_index IF NOT EXISTS
                FOR (t:TestItem) ON (t.name)
            """)
        logger.info("Report Graph Neo4j schema 初始化完成")
        return True
    except Exception as e:
        logger.error(f"Report Graph schema 初始化失敗: {e}")
        return False
    finally:
        if driver:
            driver.close()


def _merge_node(session, cypher: str, **params):
    session.run(cypher, **params)


def write_report_graph(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    doc_name: str,
    doc_path: str,
    content: str,
    chunks: list[dict],
) -> dict:
    """將 report 類文件寫入圖譜結構。"""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.error("neo4j Python 驅動未安裝，無法寫入 report graph")
        return {"sections": 0, "test_items": 0, "test_cases": 0, "metrics": 0}

    project_code = extract_project_code(doc_name or content) or "UNKNOWN"
    report_type = infer_report_type(doc_name, content)
    report_title = extract_report_title(content) or doc_name
    band = extract_band(doc_name or content) or ""
    report_id = doc_name
    source_path = str(Path(doc_path).resolve())
    source_name = Path(doc_path).name
    package_metadata = (chunks[0].get("metadata") or {}) if chunks else {}

    sections = parse_sections_from_chunks(chunks)
    test_items: dict[str, dict] = {}
    total_cases = 0
    total_metrics = 0

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        with driver.session() as session:
            session.run(
                """
                MERGE (p:Project {code: $project_code})
                SET p.name = coalesce(p.name, $project_code),
                    p.domain = coalesce(p.domain, '4G/5G'),
                    p.updated_at = datetime()
                MERGE (r:Report {doc_name: $report_id})
                SET r.project_code = $project_code,
                    r.report_type = $report_type,
                    r.title = $report_title,
                    r.band = $band,
                    r.source_path = $source_path,
                    r.source_name = $source_name,
                    r.package_id = $package_id,
                    r.document_version = $document_version,
                    r.publish_status = $publish_status,
                    r.is_current = $is_current,
                    r.updated_at = datetime()
                MERGE (p)-[:HAS_REPORT]->(r)
                """,
                project_code=project_code,
                report_id=report_id,
                report_type=report_type,
                report_title=report_title,
                band=band,
                source_path=source_path,
                source_name=source_name,
                package_id=str(package_metadata.get("package_id") or ""),
                document_version=str(package_metadata.get("document_version") or ""),
                publish_status=str(package_metadata.get("publish_status") or "draft"),
                is_current=bool(package_metadata.get("is_current", False)),
            )

            for section in sections:
                section_title = section["title"] or section["header"]
                canonical_items = canonicalize_test_items(section_title, section["text"], report_type)
                section_id = f"{doc_name}::{section['section_id']}"
                section_props = {
                    "id": section_id,
                    "doc_name": doc_name,
                    "title": section_title,
                    "header": section["header"],
                    "level": section["level"],
                    "section_order": section["order"],
                    "report_type": report_type,
                    # 保留完整 section text，避免 case 標頭只出現在前幾千字時，
                    # 後段 chunk 會因為 s.text 截斷而無法被 case query 命中。
                    "text": section["text"],
                }
                session.run(
                    """
                    MERGE (s:Section {id: $id})
                    SET s.doc_name = $doc_name,
                        s.title = $title,
                        s.header = $header,
                        s.level = $level,
                        s.section_order = $section_order,
                        s.report_type = $report_type,
                        s.text = $text,
                        s.updated_at = datetime()
                    WITH s
                    MATCH (r:Report {doc_name: $doc_name})
                    MERGE (r)-[:HAS_SECTION]->(s)
                    """,
                    **section_props,
                )

                if canonical_items:
                    for canonical_item in canonical_items:
                        item = test_items.setdefault(canonical_item, {
                            "canonical_name": canonical_item,
                            "display_name": canonical_item.title(),
                        })
                        session.run(
                            """
                            MERGE (t:TestItem {canonical_name: $canonical_name})
                            SET t.name = $display_name,
                                t.updated_at = datetime()
                            WITH t
                            MATCH (r:Report {doc_name: $doc_name})
                            MATCH (s:Section {id: $section_id})
                            MERGE (r)-[:HAS_TEST_ITEM]->(t)
                            MERGE (s)-[:HAS_TEST_ITEM]->(t)
                            """,
                            canonical_name=item["canonical_name"],
                            display_name=item["display_name"],
                            doc_name=doc_name,
                            section_id=section_id,
                        )

                case_numbers = extract_case_numbers(section["text"])
                metrics = extract_metric_rows(section["text"])
                for chunk in section["chunks"]:
                    chunk_index = int(chunk.get("chunk_index", 0) or 0)
                    chunk_id = str(chunk.get("id") or f"{doc_name}::chunk::{chunk_index}::{_sha1(str(chunk.get('content', '')[:500]))[:16]}")
                    chunk_content = str(chunk.get("content") or "")
                    chunk_metadata = chunk.get("metadata") or {}
                    session.run(
                        """
                        MERGE (sc:SourceChunk {id: $chunk_id})
                        SET sc.doc_name = $doc_name,
                            sc.source_path = $source_path,
                            sc.source_name = $source_name,
                            sc.header = $header,
                            sc.chunk_index = $chunk_index,
                            sc.package_id = $package_id,
                            sc.document_version = $document_version,
                            sc.content_hash = $content_hash,
                            sc.publish_status = $publish_status,
                            sc.is_current = $is_current,
                            sc.content = $content,
                            sc.updated_at = datetime()
                        WITH sc
                        MATCH (r:Report {doc_name: $doc_name})
                        MATCH (s:Section {id: $section_id})
                        MERGE (r)-[:HAS_SOURCE_CHUNK]->(sc)
                        MERGE (s)-[:HAS_SOURCE_CHUNK]->(sc)
                        """,
                        chunk_id=chunk_id,
                        doc_name=doc_name,
                        source_path=source_path,
                        source_name=source_name,
                        header=str(chunk_metadata.get("header") or section["header"]),
                        chunk_index=chunk_index,
                        package_id=str(chunk_metadata.get("package_id") or ""),
                        document_version=str(chunk_metadata.get("document_version") or ""),
                        content_hash=str(chunk_metadata.get("content_hash") or ""),
                        publish_status=str(chunk_metadata.get("publish_status") or ""),
                        is_current=bool(chunk_metadata.get("is_current", False)),
                        content=chunk_content,
                        section_id=section_id,
                    )

                    if case_numbers:
                        for case_no in case_numbers:
                            case_id = f"{doc_name}::case::{case_no}::{section_id}"
                            session.run(
                                """
                                MERGE (c:TestCase {id: $case_id})
                                SET c.case_no = $case_no,
                                    c.doc_name = $doc_name,
                                    c.section_id = $section_id,
                                    c.section_title = $section_title,
                                    c.report_type = $report_type,
                                    c.updated_at = datetime()
                                WITH c
                                MATCH (s:Section {id: $section_id})
                                MATCH (sc:SourceChunk {id: $chunk_id})
                                MERGE (s)-[:HAS_CASE]->(c)
                                MERGE (c)-[:SUPPORTED_BY]->(sc)
                                """,
                                case_id=case_id,
                                case_no=case_no,
                                doc_name=doc_name,
                                section_id=section_id,
                                section_title=section_title,
                                report_type=report_type,
                                chunk_id=chunk_id,
                            )
                        total_cases += len(case_numbers)

                    if metrics:
                        for metric in metrics:
                            metric_id = f"{doc_name}::metric::{section_id}::{_sha1(metric['row_text'])[:16]}"
                            session.run(
                                """
                                MERGE (m:Metric {id: $metric_id})
                                SET m.name = $name,
                                    m.row_text = $row_text,
                                    m.value_text = $value_text,
                                    m.doc_name = $doc_name,
                                    m.section_id = $section_id,
                                    m.updated_at = datetime()
                                WITH m
                                MATCH (s:Section {id: $section_id})
                                MATCH (sc:SourceChunk {id: $chunk_id})
                                MERGE (s)-[:HAS_METRIC]->(m)
                                MERGE (sc)-[:HAS_METRIC]->(m)
                                """,
                                metric_id=metric_id,
                                name=metric["name"],
                                row_text=metric["row_text"],
                                value_text=metric["value_text"],
                                doc_name=doc_name,
                                section_id=section_id,
                                chunk_id=chunk_id,
                            )
                            total_metrics += 1

            logger.info(
                "Report graph 寫入完成: %s (sections=%s, test_items=%s, cases=%s, metrics=%s)",
                doc_name,
                len(sections),
                len(test_items),
                total_cases,
                total_metrics,
            )
            return {
                "sections": len(sections),
                "test_items": len(test_items),
                "test_cases": total_cases,
                "metrics": total_metrics,
                "project_code": project_code,
                "report_type": report_type,
            }
    finally:
        driver.close()
