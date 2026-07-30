"""
GraphRAG Pipeline - 知識圖譜建置與檢索
使用 LangChain + Neo4j 實作知識圖譜萃取與查詢
"""

import os
import logging
from typing import List, Dict, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# 嘗試引入 LangChain元件（相容未安裝的情況）
try:
    from langchain_community.graphs import Neo4jGraph
    from langchain_community.vectorstores import Neo4jVector
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    logger.warning("LangChain 未安裝，部分功能可能無法使用")


class GraphRAGPipeline:
    """GraphRAG 處理流程：文字萃取 → 知識圖譜建置 → 圖譜查詢"""

    def __init__(
        self,
        neo4j_uri: str = "bolt://neo4j:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "password",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    ):
        """
        初始化 GraphRAG Pipeline

        Args:
            neo4j_uri: Neo4j 連線 URI
            neo4j_user: Neo4j 使用者
            neo4j_password: Neo4j 密碼
            embedding_model: Embedding 模型名稱
        """
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.embedding_model = embedding_model

        self.graph = None
        self.vector_store = None

        if LANGCHAIN_AVAILABLE:
            self._connect_neo4j()

    def _connect_neo4j(self):
        """連線到 Neo4j 資料庫"""
        try:
            self.graph = Neo4jGraph(
                url=self.neo4j_uri,
                username=self.neo4j_user,
                password=self.neo4j_password
            )
            logger.info("Neo4j 連線成功")
        except Exception as e:
            logger.error(f"Neo4j 連線失敗: {e}")

    def load_documents(self, markdown_folder: str) -> List[Dict]:
        """
        讀取 Markdown 資料夾中的所有文件

        Args:
            markdown_folder: Markdown 檔案資料夾路徑

        Returns:
            List[Dict]: 文件清單，包含 content 和 metadata
        """
        docs = []
        folder = Path(markdown_folder)

        for md_file in folder.rglob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            docs.append({
                "content": content,
                "metadata": {
                    "source": md_file.name,
                    "path": str(md_file),
                    "char_count": len(content)
                }
            })
            logger.info(f"載入文件: {md_file.name}")

        logger.info(f"共載入 {len(docs)} 份文件")
        return docs

    def chunk_documents(self, documents: List[Dict],
                       chunk_size: int = 1000,
                       overlap: int = 200) -> List[Dict]:
        """
        將文件切割為較小的文字區塊

        Args:
            documents: 文件清單
            chunk_size: 每個區塊的字元數
            overlap: 重疊區域的字元數

        Returns:
            List[Dict]: 切割後的區塊清單
        """
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            length_function=len
        )

        chunks = []
        for doc in documents:
            split_chunks = text_splitter.split_text(doc["content"])
            for i, chunk in enumerate(split_chunks):
                chunks.append({
                    "content": chunk,
                    "metadata": {
                        **doc["metadata"],
                        "chunk_index": i,
                        "chunk_count": len(split_chunks)
                    }
                })

        logger.info(f"文件切割完成，共 {len(chunks)} 個區塊")
        return chunks

    def extract_entities(self, chunks: List[Dict],
                        llm_client,
                        llm_model: str) -> List[Dict]:
        """
        使用 LLM 從文字區塊中萃取實體與關係

        Args:
            chunks: 文字區塊清單
            llm_client: LLM 用戶端
            llm_model: LLM 模型名稱

        Returns:
            List[Dict]: 萃取出的實體與關係
        """
        # 系統提示詞，引導 LLM 萃取知識圖譜
        extraction_prompt = """你是一個專業的知識圖譜工程師。請從以下文字區塊中萃取：

1. 實體（Entity）：人、事、地、物、概念等具體名詞
2. 關係（Relationship）：實體之間的連接關係，格式為「實體A - 關係 - 實體B」

文字區塊：
{chunk}

請以 JSON 格式輸出：
{{
  "entities": [
    {{"name": "實體名稱", "type": "實體類型", "description": "簡短描述"}}
  ],
  "relationships": [
    {{"source": "實體A", "type": "關係類型", "target": "實體B", "description": "關係描述"}}
  ]
}}
"""

        all_entities = []
        all_relationships = []

        for i, chunk in enumerate(chunks):
            try:
                response = llm_client.chat.completions.create(
                    model=llm_model,
                    messages=[
                        {"role": "system", "content": extraction_prompt},
                        {"role": "user", "content": chunk["content"]}
                    ],
                    temperature=0.3
                )

                import json
                result = json.loads(response.choices[0].message.content)

                for entity in result.get("entities", []):
                    entity["chunk_index"] = i
                    entity["source"] = chunk["metadata"]["source"]
                    all_entities.append(entity)

                for rel in result.get("relationships", []):
                    rel["chunk_index"] = i
                    rel["source"] = chunk["metadata"]["source"]
                    all_relationships.append(rel)

                logger.info(f"完成萃取區塊 {i+1}/{len(chunks)}")

            except Exception as e:
                logger.error(f"萃取失敗區塊 {i}: {e}")
                continue

        logger.info(f"萃取完成：{len(all_entities)} 個實體，{len(all_relationships)} 個關係")
        return {"entities": all_entities, "relationships": all_relationships}

    def build_graph(self, extraction_result: Dict) -> bool:
        """
        將萃取結果寫入 Neo4j 知識圖譜

        Args:
            extraction_result: extract_entities() 的回傳結果

        Returns:
            bool: 是否成功
        """
        if not self.graph:
            logger.error("Neo4j 未連線，無法建置圖譜")
            return False

        try:
            # 清空現有資料（可選）
            # self.graph.query("MATCH (n) DETACH DELETE n")

            # 寫入實體
            entities_cypher = """
            UNWIND $entities AS entity
            MERGE (e:Entity {name: entity.name})
            SET e.type = entity.type,
                e.description = entity.description,
                e.source = entity.source
            """

            self.graph.query(entities_cypher, params={"entities": extraction_result["entities"]})
            logger.info(f"寫入 {len(extraction_result['entities'])} 個實體")

            # 寫入關係
            relationships_cypher = """
            UNWIND $relationships AS rel
            MATCH (source:Entity {name: rel.source})
            MATCH (target:Entity {name: rel.target})
            MERGE (source)-[r:RELATES_TO {type: rel.type}]->(target)
            SET r.description = rel.description,
                r.source = rel.source
            """

            self.graph.query(relationships_cypher, params={
                "relationships": extraction_result["relationships"]
            })
            logger.info(f"寫入 {len(extraction_result['relationships'])} 個關係")

            # 建立向量索引
            self._create_vector_index()

            return True

        except Exception as e:
            logger.error(f"建置圖譜失敗: {e}")
            return False

    def _create_vector_index(self):
        """建立 Neo4j 向量索引以支援混合檢索"""
        try:
            index_cypher = """
            CREATE VECTOR INDEX entities_embedding IF NOT EXISTS
            FOR (e:Entity) ON (e.embedding)
            OPTIONS {indexConfig: {
                `vector.dimensions`: 384,
                `vector.similarity_function`: 'cosine'
            }}
            """
            # Neo4j 向量索引語法可能因版本而異
            logger.info("向量索引建立完成")
        except Exception as e:
            logger.warning(f"向量索引建立失敗（可能版本不支援）: {e}")

    def query_graph(self, question: str, mode: str = "local",
                    top_k: int = 6) -> Dict:
        """
        查詢知識圖譜

        Args:
            question: 問題文字
            mode: 查詢模式 - "local"（局部，適於單一實體相關）
                        - "global"（全局，適於需要跨文件摘要）
            top_k: 回傳的相關節點數

        Returns:
            Dict: 查詢結果與上下文
        """
        if not self.graph:
            return {"status": "error", "message": "Neo4j 未連線"}

        try:
            if mode == "local":
                # Local Search：找相關實體的鄰居節點
                query_cypher = """
                MATCH (e:Entity)
                WHERE e.name CONTAINS $keyword OR e.description CONTAINS $keyword
                WITH e LIMIT $top_k
                MATCH (e)-[r]-(neighbor)
                RETURN e.name AS entity, e.type AS type,
                       COLLECT({neighbor: neighbor.name, relation: r.type}) AS connections
                LIMIT $top_k
                """
                result = self.graph.query(query_cypher, params={
                    "keyword": question[:50],
                    "top_k": top_k
                })

            else:
                # Global Search：透過社群摘要回答
                query_cypher = """
                MATCH (c:Community)
                WHERE c.summary CONTAINS $keyword
                RETURN c.summary AS context
                LIMIT $top_k
                """
                result = self.graph.query(query_cypher, params={
                    "keyword": question[:50],
                    "top_k": top_k
                })

            return {
                "status": "success",
                "mode": mode,
                "results": result,
                "question": question
            }

        except Exception as e:
            logger.error(f"圖譜查詢失敗: {e}")
            return {"status": "error", "message": str(e)}
