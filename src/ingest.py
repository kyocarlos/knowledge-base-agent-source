"""
知識庫攝入腳本
將 Markdown 文件攝入 Neo4j 知識圖譜 + QDrant 向量資料庫
"""

import json
import logging
import os
import yaml
from pathlib import Path

from .storage_paths import resolve_storage_category, infer_storage_category_from_path
from .runtime_config import resolve_neo4j_uri
from .knowledge_package import build_package_id, resolve_document_version

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_config():
    """載入設定"""
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    neo4j_config = config.setdefault("neo4j", {})
    neo4j_config["uri"] = resolve_neo4j_uri(neo4j_config.get("uri", "bolt://neo4j:7687"))
    neo4j_config["user"] = os.getenv("NEO4J_USER", neo4j_config.get("user", "neo4j"))
    neo4j_config["password"] = os.getenv("NEO4J_PASSWORD", neo4j_config.get("password", "#*cda40da40"))
    return config


def _get_neo4j_connection_info(config: dict) -> tuple[str, str, str]:
    neo4j_config = config.get("neo4j", {})
    return (
        neo4j_config.get("uri", "bolt://neo4j:7687"),
        neo4j_config.get("user", "neo4j"),
        neo4j_config.get("password", "#*cda40da40"),
    )


def cleanup_existing_document(
    doc_name: str,
    enable_vector: bool = True,
    cleanup_assets: bool = True,
) -> bool:
    """
    清除指定文件的既有攝入結果，避免重複攝入累加。

    會移除：
    - Document 節點
    - 以 doc_name 為 source 的關係
    - TextUnit 節點
    - QDrant 中 doc_name 對應的向量點
    """
    try:
        from neo4j import GraphDatabase
        from .chunk_assets import cleanup_document_assets

        config = load_config()
        neo4j_uri, neo4j_user, neo4j_password = _get_neo4j_connection_info(config)
        driver = GraphDatabase.driver(
            neo4j_uri,
            auth=(neo4j_user, neo4j_password)
        )

        with driver.session() as session:
            session.run(
                """
                MATCH ()-[r]->()
                WHERE r.source = $doc_name
                DELETE r
                """,
                doc_name=doc_name,
            )
            session.run(
                """
                MATCH (t:TextUnit {source: $doc_name})
                DETACH DELETE t
                """,
                doc_name=doc_name,
            )
            session.run(
                """
                MATCH (d:Document {name: $doc_name})
                DETACH DELETE d
                """,
                doc_name=doc_name,
            )

        driver.close()
        logger.info(f"已清除舊文件資料: {doc_name}")

        if enable_vector:
            try:
                from src.vector_store import get_vector_store
                vector_store = get_vector_store()
                if vector_store.delete_by_doc(doc_name):
                    logger.info(f"已清除舊向量資料: {doc_name}")
            except Exception as vector_error:
                logger.warning(f"清除舊向量資料失敗，將繼續攝入: {vector_error}")

        if cleanup_assets:
            try:
                if cleanup_document_assets(doc_name):
                    logger.info(f"已清除舊資產資料: {doc_name}")
            except Exception as asset_error:
                logger.warning(f"清除舊資產資料失敗，將繼續攝入: {asset_error}")

        return True
    except Exception as e:
        logger.warning(f"清除舊文件資料失敗，將繼續攝入: {e}")
        return False


def _write_neo4j_document(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    doc_name: str,
    doc_path: str,
    content: str,
    extraction_mode: str,
    storage_category: str | None = None,
    result: dict | None = None,
) -> None:
    """將單一文件寫入 Neo4j。"""
    from neo4j import GraphDatabase

    result = result or {}
    identity = {}
    metadata_path = Path(doc_path).with_name(f"{Path(doc_path).stem}.source.json")
    if metadata_path.exists():
        try:
            source_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            identity = {
                key: source_metadata[key]
                for key in (
                    "source_system", "environment_id", "project_id", "run_id", "artifact_type",
                    "report_schema", "original_file_name", "source_file_hash", "ingest_file_hash",
                    "document_id", "idempotency_key", "generated_at",
                )
                if source_metadata.get(key) not in (None, "")
            }
            document_version = resolve_document_version(source_metadata)
        except Exception as metadata_error:
            logger.warning("讀取 Neo4j 文件身份 metadata 失敗: %s", metadata_error)
            document_version = resolve_document_version({})
    else:
        document_version = resolve_document_version({})
    identity.update({
        "package_schema_version": "1.0",
        "package_id": build_package_id(identity.get("document_id", doc_name), document_version),
        "document_version": document_version,
        "publish_status": "draft",
        "is_current": False,
    })
    driver = GraphDatabase.driver(
        neo4j_uri,
        auth=(neo4j_user, neo4j_password)
    )

    with driver.session() as session:
        session.run("""
            MERGE (d:Document {package_id: $package_id})
            SET d.name = $name,
                d.content = $content,
                d.source = $source,
                d.extraction_mode = $mode,
                d.storage_category = $storage_category,
                d.package_schema_version = $package_schema_version,
                d.package_id = $package_id,
                d.document_version = $document_version,
                d.publish_status = $publish_status,
                d.is_current = $is_current,
                d += $identity
        """, name=doc_name, content=content[:1000], source=doc_path, mode=extraction_mode, storage_category=storage_category or "", package_schema_version=identity["package_schema_version"], package_id=identity["package_id"], document_version=document_version, publish_status=identity["publish_status"], is_current=identity["is_current"], identity=identity)

        session.run("""
            MATCH (d:Document {package_id: $package_id})
            CREATE (t:TextUnit {content: $content, source: $source})
            CREATE (d)-[:CONTAINS]->(t)
        """, name=doc_name, package_id=identity["package_id"], content=content[:2000], source=doc_name)

        for entity in result.get("entities", []):
            entity_name = entity.get("Name") or entity.get("name", "")
            if not entity_name:
                logger.warning(f"實體缺少名稱欄位: {entity}")
                continue
            session.run("""
                MERGE (e:Entity {name: $entity_name})
                SET e.type = $entity_type,
                    e.description = $entity_desc,
                    e.source = $entity_source,
                    e.extraction_mode = $mode
            """, entity_name=entity_name, entity_type=entity.get("type", "概念"),
                entity_desc=entity.get("description", ""),
                entity_source=doc_name,
                mode=extraction_mode)

        for rel in result.get("relationships", []):
            source_name = rel.get("source") or rel.get("Source", "")
            target_name = rel.get("target") or rel.get("Target", "")
            if not source_name or not target_name:
                logger.warning(f"關係缺少名稱欄位: {rel}")
                continue
            rel_type = rel.get("type") or rel.get("Type", "相關")
            session.run("""
                MATCH (s:Entity {name: $source_node})
                MATCH (t:Entity {name: $target_node})
                MERGE (s)-[r:RELATES_TO {type: $rel_type}]->(t)
                SET r.description = $rel_desc,
                    r.source = $source_doc
            """, source_node=source_name, target_node=target_name,
                rel_type=rel_type,
                rel_desc=rel.get("description", ""),
                source_doc=doc_name)

    driver.close()


def setup_neo4j_schema():
    """初始化 Neo4j Schema"""
    try:
        from neo4j import GraphDatabase
        from src.report_graph import setup_report_graph_schema
        config = load_config()
        neo4j_uri, neo4j_user, neo4j_password = _get_neo4j_connection_info(config)
        
        driver = GraphDatabase.driver(
            neo4j_uri,
            auth=(neo4j_user, neo4j_password)
        )
        
        with driver.session() as session:
            # 建立約束
            session.run("""
                CREATE CONSTRAINT document_name IF NOT EXISTS
                FOR (d:Document) REQUIRE d.name IS UNIQUE
            """)
            session.run("""
                CREATE CONSTRAINT entity_name IF NOT EXISTS
                FOR (e:Entity) REQUIRE e.name IS UNIQUE
            """)
            
            # 建立索引
            session.run("""
                CREATE INDEX text_chunk_index IF NOT EXISTS
                FOR (t:TextUnit) ON (t.content)
            """)
            session.run("""
                CREATE INDEX entity_type_index IF NOT EXISTS
                FOR (e:Entity) ON (e.type)
            """)
            session.run("""
                CREATE CONSTRAINT report_doc_name IF NOT EXISTS
                FOR (r:Report) REQUIRE r.doc_name IS UNIQUE
            """)
            session.run("""
                CREATE CONSTRAINT project_code IF NOT EXISTS
                FOR (p:Project) REQUIRE p.code IS UNIQUE
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

            # 若單獨執行 ingest.py，也同步初始化 report graph schema
            setup_report_graph_schema(neo4j_uri, neo4j_user, neo4j_password)
            
        driver.close()
        logger.info("Neo4j Schema 初始化完成")
        return True
    except Exception as e:
        logger.error(f"Schema 初始化失敗: {e}")
        return False


def ingest_document(
    doc_path: str,
    enable_vector: bool = True,
    extraction_mode: str = None,
    preserve_assets: bool = False,
):
    """攝入單一文件
    
    Args:
        doc_path: 文件路徑
        enable_vector: 是否寫入向量資料庫
        extraction_mode: 萃取模式，可為 4g5g/wifi/lab/project/automation/report/simple，如果為 None 則自動偵測
    """
    
    # 根據萃取模式選擇不同的系統提示詞
    from src.extract_entities import get_extraction_prompt, EXTRACTION_MODES
    
    # 如果沒有指定萃取模式，自動偵測
    if extraction_mode is None:
        filename = Path(doc_path).stem
        extraction_mode = detect_extraction_mode(filename)
    
    # 驗證萃取模式是否有效
    if extraction_mode not in EXTRACTION_MODES:
        logger.warning(f"未知的萃取模式: {extraction_mode}，使用預設模式 (4g5g)")
        extraction_mode = "4g5g"
    
    system_prompt = get_extraction_prompt(extraction_mode)
    mode_name = EXTRACTION_MODES.get(extraction_mode, {}).get("name", extraction_mode)
    logger.info(f"使用萃取模式: {mode_name}")
    source_metadata = {}
    source_metadata_path = Path(doc_path).with_name(f"{Path(doc_path).stem}.source.json")
    if source_metadata_path.exists():
        try:
            source_metadata = json.loads(source_metadata_path.read_text(encoding="utf-8"))
        except Exception as metadata_error:
            logger.warning(f"讀取文件身份 metadata 失敗: {metadata_error}")
    doc_name = source_metadata.get("document_id") or Path(doc_path).stem
    content = Path(doc_path).read_text(encoding="utf-8")
    from src.ingest_registry import IngestRegistry
    # Revisioned packages coexist until lifecycle publish supersedes the old
    # one. Legacy documents retain the existing cleanup behavior.
    if not IngestRegistry().has_knowledge_revisions(str(doc_name)):
        cleanup_existing_document(
            doc_name,
            enable_vector=enable_vector,
            cleanup_assets=not preserve_assets,
        )
    
    # ============================================================
    # Report 模式：保留文件結構 + chunk 向量，不做實體萃取
    # ============================================================
    if extraction_mode == "report":
        logger.info(f"[Report 模式] 寫入文件結構與 QDrant，不經 LLM 萃取")
        try:
            config = load_config()
            neo4j_uri, neo4j_user, neo4j_password = _get_neo4j_connection_info(config)
            from src.chunker import chunk_document
            from src.report_graph import write_report_graph, setup_report_graph_schema

            setup_report_graph_schema(neo4j_uri, neo4j_user, neo4j_password)
            report_chunks = chunk_document(doc_path)
            _write_neo4j_document(
                neo4j_uri=neo4j_uri,
                neo4j_user=neo4j_user,
                neo4j_password=neo4j_password,
                doc_name=doc_name,
                doc_path=doc_path,
                content=content,
                extraction_mode=extraction_mode,
                storage_category=resolve_storage_category(extraction_mode, doc_path),
                result={"entities": [], "relationships": []},
            )
            logger.info(f"[Report] Neo4j 文件結構完成: {Path(doc_path).name}")

            graph_stats = write_report_graph(
                neo4j_uri=neo4j_uri,
                neo4j_user=neo4j_user,
                neo4j_password=neo4j_password,
                doc_name=doc_name,
                doc_path=doc_path,
                content=content,
                chunks=report_chunks,
            )
            if not any(int(graph_stats.get(key, 0) or 0) > 0 for key in ("sections", "test_items", "test_cases", "metrics")):
                raise RuntimeError("Report 圖譜寫入後未產生任何節點統計")
            logger.info(
                "[Report] 圖譜關聯完成: sections=%s test_items=%s cases=%s metrics=%s",
                graph_stats.get("sections", 0),
                graph_stats.get("test_items", 0),
                graph_stats.get("test_cases", 0),
                graph_stats.get("metrics", 0),
            )

            if enable_vector:
                if not ingest_vector(doc_path):
                    raise RuntimeError("Report 模式 QDrant 寫入失敗")
                logger.info(f"[Report] QDrant 寫入完成: {Path(doc_path).name}")

            return True
        except Exception as e:
            logger.error(f"[Report] 寫入失敗: {e}")
            return False

    # ============================================================
    # Vector-only 模式：直接分塊寫入 QDrant，不寫入 Neo4j
    # ============================================================
    if extraction_mode in {"lab", "project", "automation"}:
        logger.info(f"[Vector-only 模式] 直接寫入 QDrant，不經 LLM / Neo4j: {extraction_mode}")
        try:
            if enable_vector:
                if not ingest_vector(doc_path, storage_category=resolve_storage_category(extraction_mode, doc_path)):
                    raise RuntimeError("Vector-only 模式 QDrant 寫入失敗")
                logger.info(f"[Vector-only] QDrant 寫入完成: {Path(doc_path).name}")
            return True
        except Exception as e:
            logger.error(f"[Vector-only] 寫入失敗: {e}")
            return False

    # ============================================================
    # Type6 簡化模式：直接轉 MD 寫入 QDrant，不寫入 Neo4j
    # ============================================================
    if extraction_mode == "simple":
        logger.info(f"[Type6 簡化模式] 直接寫入 QDrant，不經 LLM 萃取")
        try:
            from src.report_graph import infer_report_type
            report_type = infer_report_type(doc_name, content)
            report_graph_required = report_type != "generic_report"
            report_graph_written = False

            # 報告型 simple 文件先補寫 Neo4j 圖譜，避免只進向量庫。
            if report_graph_required:
                logger.info(f"[Type6] 偵測到報告型文件 ({report_type})，補寫 Neo4j 圖譜: {Path(doc_path).name}")
                try:
                    config = load_config()
                    neo4j_uri, neo4j_user, neo4j_password = _get_neo4j_connection_info(config)
                    from src.chunker import chunk_document
                    from src.report_graph import write_report_graph, setup_report_graph_schema

                    setup_report_graph_schema(neo4j_uri, neo4j_user, neo4j_password)
                    report_chunks = chunk_document(doc_path)
                    _write_neo4j_document(
                        neo4j_uri=neo4j_uri,
                        neo4j_user=neo4j_user,
                        neo4j_password=neo4j_password,
                        doc_name=doc_name,
                        doc_path=doc_path,
                        content=content,
                        extraction_mode="report",
                        storage_category=resolve_storage_category("report", doc_path),
                        result={"entities": [], "relationships": []},
                    )
                    write_report_graph(
                        neo4j_uri=neo4j_uri,
                        neo4j_user=neo4j_user,
                        neo4j_password=neo4j_password,
                        doc_name=doc_name,
                        doc_path=doc_path,
                        content=content,
                        chunks=report_chunks,
                    )
                    report_graph_written = any(
                        int(graph_stats.get(key, 0) or 0) > 0
                        for key in ("sections", "test_items", "test_cases", "metrics")
                    )
                    if not report_graph_written:
                        raise RuntimeError("報告圖譜寫入後未產生任何節點統計")
                    logger.info(f"[Type6] 報告圖譜寫入完成: {Path(doc_path).name}")
                except Exception as graph_exc:
                    logger.warning(f"[Type6] 報告圖譜寫入失敗: {graph_exc}")

            # 只寫入向量資料庫
            if not ingest_vector(doc_path):
                raise RuntimeError("Type6 模式 QDrant 寫入失敗")
            logger.info(f"[Type6] QDrant 寫入完成: {Path(doc_path).name}")

            if report_graph_required and not report_graph_written:
                raise RuntimeError("Type6 報告圖譜寫入失敗")

            return True
        except Exception as e:
            logger.error(f"[Type6] QDrant 寫入失敗: {e}")
            return False
    try:
        from neo4j import GraphDatabase
        config = load_config()
        neo4j_uri, neo4j_user, neo4j_password = _get_neo4j_connection_info(config)
        content = Path(doc_path).read_text(encoding="utf-8")
        
        # 讀取 ollama client
        from src.web_api.ollama_client import OllamaClient
        ollama_config = config["ollama"]
        
        llm = OllamaClient(
            model=ollama_config.get("model", "gemma4:12b"),
            base_url=ollama_config["instances"][0] if len(ollama_config["instances"]) > 0 else ollama_config.get("base_url", "http://localhost:11434")
        )
        
        # 嘗試萃取
        result = {}
        try:
            import re

            # 呼叫 LLM 萃取（最多重試 2 次）
            max_retries = 2
            for attempt in range(max_retries):
                response = llm.chat([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content[:6000]}
                ])
                
                # 嘗試解析 JSON
                try:
                    result = json.loads(response)
                    break  # 成功，跳出重試循環
                except json.JSONDecodeError:
                    # 嘗試從回應中提取 JSON
                    json_match = re.search(r'\{[\s\S]*\}', response)
                    if json_match:
                        try:
                            result = json.loads(json_match.group())
                            break  # 成功，跳出重試循環
                        except json.JSONDecodeError:
                            pass  # 繼續重試
                    
                    if attempt < max_retries - 1:
                        logger.warning(f"JSON 解析失敗 (嘗試 {attempt+1}/{max_retries})，重試中...")
                        continue
                    else:
                        raise ValueError(f"無法從回應中提取 JSON: {response[:200]}")

            # LLM 成功時也要寫入 Neo4j，否則只會有向量、不會有圖譜資料
            _write_neo4j_document(
                neo4j_uri=neo4j_uri,
                neo4j_user=neo4j_user,
                neo4j_password=neo4j_password,
                doc_name=doc_name,
                doc_path=doc_path,
                content=content,
                extraction_mode=extraction_mode,
                storage_category=resolve_storage_category(extraction_mode, doc_path),
                result=result,
            )
            logger.info(f"[Step 2/4] Neo4j 寫入完成: {doc_name}")
            logger.info(f"  - 實體: {len(result.get('entities', []))}")
            logger.info(f"  - 關係: {len(result.get('relationships', []))}")

            if enable_vector:
                logger.info(f"[Step 3/4] 開始寫入 QDrant: {doc_path}")
                try:
                    if not ingest_vector(doc_path, storage_category=resolve_storage_category(extraction_mode, doc_path)):
                        raise RuntimeError("QDrant 寫入失敗")
                    logger.info(f"[Step 3/4] QDrant 寫入完成: {doc_name}")
                except Exception as ve:
                    logger.warning(f"[Step 3/4] QDrant 寫入失敗，已略過: {ve}")

            return True
        except Exception as llm_error:
            logger.warning(f"LLM 萃取失敗，將以無萃取模式繼續: {llm_error}")

            _write_neo4j_document(
                neo4j_uri=neo4j_uri,
                neo4j_user=neo4j_user,
                neo4j_password=neo4j_password,
                doc_name=doc_name,
                doc_path=doc_path,
                content=content,
                extraction_mode=extraction_mode,
                storage_category=resolve_storage_category(extraction_mode, doc_path),
                result=result,
            )
            logger.info(f"[Step 2/4] Neo4j 寫入完成: {doc_name}")
            logger.info(f"  - 實體: {len(result.get('entities', []))}")
            logger.info(f"  - 關係: {len(result.get('relationships', []))}")
            
            # 同時寫入向量資料庫
            if enable_vector:
                logger.info(f"[Step 3/4] 開始寫入 QDrant: {doc_path}")
                try:
                    if not ingest_vector(doc_path, storage_category=resolve_storage_category(extraction_mode, doc_path)):
                        raise RuntimeError("QDrant 寫入失敗")
                    logger.info(f"[Step 3/4] QDrant 寫入完成: {doc_name}")
                except Exception as ve:
                    logger.warning(f"[Step 3/4] QDrant 寫入失敗，已略過: {ve}")

            return True
            
        except Exception as e:
            logger.error(f"萃取失敗: {e}")
            # 仍然寫入文件節點
            driver = GraphDatabase.driver(
                neo4j_uri,
                auth=(neo4j_user, neo4j_password)
            )
            with driver.session() as session:
                session.run("""
                    MERGE (d:Document {name: $name})
                    SET d.content = $content,
                        d.source = $source,
                        d.extraction_mode = $mode,
                        d.storage_category = $storage_category
                """, name=doc_name, content=content[:1000], source=doc_path, mode=extraction_mode, storage_category=resolve_storage_category(extraction_mode, doc_path))
            driver.close()
            logger.info(f"文件已寫入（無萃取）: {doc_name}")

            # 同時寫入向量資料庫
            if enable_vector:
                logger.info(f"[Fallback] 開始寫入 QDrant: {doc_path}")
                try:
                    if not ingest_vector(doc_path, storage_category=resolve_storage_category(extraction_mode, doc_path)):
                        raise RuntimeError("QDrant 寫入失敗")
                    logger.info(f"[Fallback] QDrant 寫入完成: {doc_name}")
                except Exception as ve:
                    logger.warning(f"[Fallback] QDrant 寫入失敗，已略過: {ve}")

            return True
            
    except Exception as e:
        logger.error(f"攝入失敗 {doc_path}: {e}")
        return False


def ingest_vector(doc_path: str, storage_category: str | None = None):
    """將文件寫入向量資料庫"""
    try:
        from src.vector_store import get_vector_store
        from src.chunker import chunk_document

        doc_name = Path(doc_path).stem
        source_metadata = {}

        # 分塊
        chunks = chunk_document(doc_path)
        resolved_category = storage_category or infer_storage_category_from_path(doc_path)
        extraction_mode = resolved_category.lower().replace("_", "") if resolved_category else "4g5g"
        if resolved_category == "4G_5G":
            extraction_mode = "4g5g"
        elif resolved_category == "WiFi":
            extraction_mode = "wifi"
        elif resolved_category == "Lab":
            extraction_mode = "lab"
        elif resolved_category == "Project":
            extraction_mode = "project"
        elif resolved_category == "Automation":
            extraction_mode = "automation"
        elif resolved_category == "Report":
            extraction_mode = "report"
        elif resolved_category == "Simple":
            extraction_mode = "simple"

        metadata_path = Path(doc_path).with_name(f"{Path(doc_path).stem}.source.json")
        if metadata_path.exists():
            try:
                source_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception as metadata_error:
                logger.warning(f"讀取向量 metadata 失敗: {metadata_error}")
        doc_name = source_metadata.get("document_id") or doc_name

        for chunk in chunks:
            metadata = chunk.setdefault("metadata", {})
            metadata.setdefault("storage_category", resolved_category)
            metadata.setdefault("extraction_mode", extraction_mode)
            for key in (
                "run_id", "environment", "project_code", "dut_model", "band",
                "protocol", "direction", "verdict", "started_at", "schema_version",
                "source_system", "environment_id", "project_id", "artifact_type", "report_schema",
                "original_file_name", "source_file_hash", "ingest_file_hash", "document_id",
                "idempotency_key", "generated_at",
            ):
                if source_metadata.get(key) not in (None, ""):
                    metadata.setdefault(key, source_metadata[key])
        logger.info(f"向量攝入: {doc_name}, {len(chunks)} 個區塊")

        # 寫入 QDrant
        vector_store = get_vector_store()
        vector_store.add_documents(chunks, doc_name)

        # Keep revision state durable after the real stores receive the package.
        package_metadata = chunks[0].get("metadata", {}) if chunks else {}
        if package_metadata.get("package_id"):
            from .ingest_registry import IngestRegistry
            IngestRegistry().register_knowledge_revision(package_metadata)

        logger.info(f"向量攝入完成: {doc_name}")
        return True

    except Exception as e:
        logger.error(f"向量攝入失敗: {e}")
        return False


def ingest_all(raw_folder: str, enable_vector: bool = True, extraction_mode: str = None):
    """攝入資料夾中所有 Markdown 檔案
    
    Args:
        raw_folder: 資料夾路徑
        enable_vector: 是否寫入向量資料庫
        extraction_mode: 萃取模式，如果為 None，則由檔案名稱自動判斷
    """
    config = load_config()
    
    # 初始化 Schema
    setup_neo4j_schema()
    
    # 讀取所有 .md 檔案
    raw_path = Path(raw_folder)
    md_files = [
        md_file for md_file in raw_path.rglob("*.md")
        if md_file.name.lower() != "index.md" and "wiki" not in md_file.parts
    ]
    
    logger.info(f"找到 {len(md_files)} 個 Markdown 檔案")
    
    for md_file in md_files:
        logger.info(f"處理中: {md_file.name}")
        # 根據檔案名稱自動判斷萃取模式
        file_mode = extraction_mode or detect_extraction_mode(md_file.stem)
        ingest_document(str(md_file), enable_vector=enable_vector, extraction_mode=file_mode)
    
    logger.info("攝入完成！")
    
    # 生成 index.md
    try:
        from src.index_generator import generate_index_md
        generate_index_md()
        logger.info("index.md 已更新")
    except Exception as e:
        logger.warning(f"index.md 更新失敗: {e}")


def detect_extraction_mode(filename: str) -> str:
    """
    根據檔案名稱自動判斷萃取模式
    
    命名規則：
    - SIT-SR-SC: 4G/5G 類別
    - SIT-TR-WL: WiFi 類別
    
    Args:
        filename: 檔案名稱（不含副檔名）
    
    Returns:
        extraction_mode: 萃取模式 ID
    """
    # 轉小寫進行匹配
    fname_lower = filename.lower()

    if "sit-sr-sc" in fname_lower:
        logger.info(f"偵測到 SIT-SR-SC (4G/5G 類別): {filename}")
        return "4g5g"
    if "sit-tr-wl" in fname_lower:
        logger.info(f"偵測到 SIT-TR-WL (WiFi 類別): {filename}")
        return "wifi"
    else:
        # 預設使用 4G/5G 模式
        logger.info(f"未偵測到特定類型，使用預設模式 (4G/5G): {filename}")
        return "4g5g"


def setup_vector_schema():
    """初始化向量資料庫 Schema"""
    try:
        from src.vector_store import get_vector_store
        vs = get_vector_store()
        logger.info("向量資料庫 Schema 初始化完成")
        return True
    except Exception as e:
        logger.error(f"向量 Schema 初始化失敗: {e}")
        return False
