"""
Neo4j Schema 初始化
建立知識圖譜所需的 Node 和 Relationship 類型
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def setup_neo4j_schema(neo4j_uri: str, neo4j_user: str, neo4j_password: str):
    """
    初始化 Neo4j Schema

    建立的標籤和關係類型：
    - Node: Document, TextUnit, Entity, Community
    - Relationship: PART_OF, RELATES_TO, BELONGS_TO
    """

    try:
        from neo4j import GraphDatabase

    except ImportError:
        logger.error("neo4j Python 驅動未安裝，請執行：pip install neo4j")
        return False

    driver = None

    try:
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        with driver.session() as session:
            # ===== 1. 建立約束和索引 =====

            # 文件唯一性約束
            session.run("""
                CREATE CONSTRAINT document_name IF NOT EXISTS
                FOR (d:Document) REQUIRE d.name IS UNIQUE
            """)

            # 實體唯一性約束
            session.run("""
                CREATE CONSTRAINT entity_name IF NOT EXISTS
                FOR (e:Entity) REQUIRE e.name IS UNIQUE
            """)

            # 文字區塊索引
            session.run("""
                CREATE INDEX text_chunk_index IF NOT EXISTS
                FOR (t:TextUnit) ON (t.content)
            """)

            # 實體類型索引
            session.run("""
                CREATE INDEX entity_type_index IF NOT EXISTS
                FOR (e:Entity) ON (e.type)
            """)

            # 報告關聯圖譜
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
            session.run("""
                CREATE INDEX report_type_index IF NOT EXISTS
                FOR (r:Report) ON (r.report_type)
            """)
            session.run("""
                CREATE INDEX testitem_name_index IF NOT EXISTS
                FOR (t:TestItem) ON (t.name)
            """)

            logger.info("約束和索引建立完成")

            # 在 Neo4j 5.x 中，標籤是隱式創建的，不需要預先聲明
            # 所以這裡只做一個簡單的驗證查詢
            try:
                result = session.run("""
                    MATCH (n)
                    WITH labels(n) AS labels, count(*) AS count
                    RETURN labels, count
                    ORDER BY count DESC
                    LIMIT 10
                """)
                
                logger.info("當前圖譜內容：")
                for record in result:
                    logger.info(f"  {record['labels']}: {record['count']} nodes")
                
                logger.info("Neo4j Schema 初始化完成！")
            except Exception as e:
                logger.warning(f"驗證查詢失敗（不影響功能）: {e}")
            
            return True

    except Exception as e:
        logger.error(f"Neo4j Schema 初始化失敗: {e}")
        return False

    finally:
        if driver:
            driver.close()


def clear_all_data(neo4j_uri: str, neo4j_user: str, neo4j_password: str):
    """清除所有資料（用於重建）"""

    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
            logger.info("所有資料已清除")

        driver.close()

    except Exception as e:
        logger.error(f"清除資料失敗: {e}")


def get_graph_stats(neo4j_uri: str, neo4j_user: str, neo4j_password: str) -> dict:
    """取得圖譜統計資訊"""

    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        with driver.session() as session:
            # 節點數量
            node_result = session.run("""
                MATCH (n)
                RETURN labels(n) AS labels, count(*) AS count
            """)
            nodes = {}
            for r in node_result:
                # labels 是列表，取第一個 label 作為類型名稱
                label_list = r['labels']
                label_name = label_list[0] if label_list else 'Unknown'
                nodes[label_name] = r['count']

            # 關係數量
            rel_result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) AS rel_type, count(*) AS count
            """)
            relationships = {r['rel_type']: r['count'] for r in rel_result}

            return {
                "nodes": nodes,
                "relationships": relationships
            }

        driver.close()

    except Exception as e:
        logger.error(f"取得統計失敗: {e}")
        return {}


# ===== 快速執行 =====

if __name__ == "__main__":
    import yaml

    # 載入設定
    config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        neo4j_uri = config.get("neo4j_uri", "bolt://neo4j:7687")
        neo4j_user = config.get("neo4j_user", "neo4j")
        neo4j_password = config.get("neo4j_password", "change-me")

        print(f"連線到 Neo4j: {neo4j_uri}")

        # 初始化 Schema
        setup_neo4j_schema(neo4j_uri, neo4j_user, neo4j_password)

        # 顯示統計
        stats = get_graph_stats(neo4j_uri, neo4j_user, neo4j_password)
        print("\n圖譜統計：")
        print(f"  節點：{stats.get('nodes', {})}")
        print(f"  關係：{stats.get('relationships', {})}")

    else:
        print("請先建立 config/config.yaml")
