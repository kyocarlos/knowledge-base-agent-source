"""
知識庫索引生成器
產生 index.md - 知識庫的全域內容字典
"""

import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

# 分類名稱映射
CATEGORY_NAMES = {
    "4g5g": "4G/5G 電信設備",
    "4g_5g": "4G/5G 電信設備",
    "wifi": "WiFi 網路設備",
    "lab": "實驗室管理",
    "project": "專案管理",
    "automation": "自動化管理",
    "report": "Report 測試報告",
    "simple": "簡化文件",
}

# 分類順序
CATEGORY_ORDER = ["4g5g", "4g_5g", "report", "wifi", "lab", "project", "automation", "simple"]


def load_neo4j_config() -> Dict:
    """載入 Neo4j 設定"""
    import yaml
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_documents_from_neo4j() -> List[Dict]:
    """從 Neo4j 取得所有文件資訊"""
    try:
        config = load_neo4j_config()
        neo4j_config = config["neo4j"]
        
        driver = GraphDatabase.driver(
            neo4j_config["uri"],
            auth=(neo4j_config["user"], neo4j_config["password"])
        )
        
        documents = []
        
        with driver.session() as session:
            # 取得所有文件節點
            result = session.run("""
                MATCH (d:Document)
                RETURN d.name AS name, 
                       d.content AS content, 
                       d.extraction_mode AS mode,
                       d.search_count AS search_count,
                       d.source AS source
                ORDER BY d.name
            """)
            
            for record in result:
                name = record.get("name", "")
                content = record.get("content", "") or ""
                mode = record.get("mode", "unknown")
                search_count = record.get("search_count", 0) or 0
                source = record.get("source", "")
                
                # 從內容中提取摘要（取第一段非標題文字）
                summary = extract_summary(content)
                
                # 從內容中提取關鍵字
                keywords = extract_keywords(content)
                
                documents.append({
                    "name": name,
                    "summary": summary,
                    "keywords": keywords,
                    "mode": mode,
                    "search_count": search_count,
                    "source": source,
                })
        
        driver.close()
        return documents
        
    except Exception as e:
        logger.error(f"從 Neo4j 取得文件失敗: {e}")
        return []


def extract_summary(content: str, max_length: int = 100) -> str:
    """從文件內容中提取摘要"""
    if not content:
        return "無摘要"
    
    lines = content.split("\n")
    for line in lines:
        line = line.strip()
        # 跳過標題、空行、列表
        if not line or line.startswith("#") or line.startswith("-") or line.startswith("*") or line.startswith("|"):
            continue
        # 返回第一段有意義的文字
        if len(line) > 20:  # 至少20個字
            if len(line) > max_length:
                return line[:max_length] + "..."
            return line
    
    return "無摘要"


def extract_keywords(content: str) -> List[str]:
    """從內容中提取關鍵字（簡化版：取常見的技術術語）"""
    # 移除 markdown 語法
    import re
    text = re.sub(r'[#*|`\[\](){}]', '', content)
    text = re.sub(r'\n+', ' ', text)
    
    # 常見的技術關鍵字模式
    patterns = [
        r'\b[A-Z]{2,}[A-Z0-9]*\b',  # 全大寫縮寫如 LTE, 5G, WiFi, MIMO
        r'\b\d+[A-Za-z]+\d*\b',  # 如 802.11ax
        r'\b[A-Za-z]+[_-]?[A-Za-z]+[_-]?\d*\b',  # 如 WiFi_7, QAM
    ]
    
    keywords = set()
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches[:3]:  # 每個模式最多取3個
            if len(match) > 2:
                keywords.add(match)
    
    return list(keywords)[:5]  # 最多5個關鍵字


def get_status_emoji(search_count: int) -> str:
    """根據搜尋次數回傳狀態 emoji"""
    if search_count >= 20:
        return "🟢"
    elif search_count >= 10:
        return "🔵"
    elif search_count >= 1:
        return "🟡"
    else:
        return "⚪"


def generate_index_content(documents: List[Dict]) -> str:
    """生成 index.md 內容"""
    
    # 按分類分組
    categorized = {}
    uncategorized = []
    
    for doc in documents:
        mode = doc.get("mode", "").lower().replace("-", "_")
        if mode in CATEGORY_ORDER:
            if mode not in categorized:
                categorized[mode] = []
            categorized[mode].append(doc)
        else:
            uncategorized.append(doc)
    
    # 生成 Markdown
    lines = []
    lines.append("# 知識庫索引")
    lines.append("")
    lines.append(f"> 自動生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    
    # 總覽
    total_docs = len(documents)
    total_search = sum(doc.get("search_count", 0) for doc in documents)
    lines.append("## 📊 總覽")
    lines.append("")
    lines.append(f"- **文件總數**：{total_docs}")
    lines.append(f"- **總搜尋次數**：{total_search}")
    lines.append("")
    
    # 依分類輸出
    for cat_key in CATEGORY_ORDER:
        if cat_key not in categorized:
            continue
        
        docs = categorized[cat_key]
        cat_name = CATEGORY_NAMES.get(cat_key, cat_key)
        
        # 計算該分類的總搜尋次數
        cat_search = sum(doc.get("search_count", 0) for doc in docs)
        
        lines.append(f"## 📁 {cat_name}")
        lines.append("")
        lines.append(f"共 {len(docs)} 份文件，搜尋次數：{cat_search}")
        lines.append("")
        
        # 表格標題
        lines.append("| 狀態 | 文件名稱 | 摘要 | 關鍵字 |")
        lines.append("|------|----------|------|--------|")
        
        for doc in sorted(docs, key=lambda x: x.get("search_count", 0), reverse=True):
            status = get_status_emoji(doc.get("search_count", 0))
            name = doc.get("name", "未知")
            summary = doc.get("summary", "無")[:40]
            keywords = ", ".join(doc.get("keywords", [])[:3])
            
            lines.append(f"| {status} | {name} | {summary} | {keywords} |")
        
        lines.append("")
    
    # 未分類
    if uncategorized:
        lines.append("## 📂 未分類")
        lines.append("")
        for doc in uncategorized:
            name = doc.get("name", "未知")
            summary = doc.get("summary", "無")[:50]
            lines.append(f"- **{name}**：{summary}")
        lines.append("")
    
    # 頁尾
    lines.append("---")
    lines.append("")
    lines.append("> 💡 此索引由系統自動維護，反映知識庫的即時狀態")
    
    return "\n".join(lines)


def generate_index_md() -> bool:
    """
    生成 index.md 文件
    
    Returns:
        bool: 是否成功
    """
    try:
        logger.info("開始生成 index.md...")
        
        # 1. 從 Neo4j 取得所有文件
        documents = get_documents_from_neo4j()
        
        if not documents:
            logger.warning("沒有文件可以生成索引")
            return False
        
        logger.info(f"取得 {len(documents)} 份文件")
        
        # 2. 生成內容
        content = generate_index_content(documents)
        
        # 3. 寫入 index.md
        data_dir = Path(__file__).parent.parent / "data"
        index_path = data_dir / "index.md"
        index_path.write_text(content, encoding="utf-8")
        
        logger.info(f"index.md 已生成：{index_path}")
        
        # 4. 同時產生一份 wiki 風格的版本在 wiki 目錄
        wiki_dir = data_dir / "wiki"
        wiki_dir.mkdir(exist_ok=True)
        
        # 依分類建立子目錄
        wiki_index_path = wiki_dir / "index.md"
        wiki_index_path.write_text(content, encoding="utf-8")
        
        logger.info(f"wiki/index.md 已生成：{wiki_index_path}")
        
        return True
        
    except Exception as e:
        logger.error(f"生成 index.md 失敗: {e}")
        return False


def get_index_content() -> Optional[str]:
    """取得目前的 index.md 內容"""
    try:
        data_dir = Path(__file__).parent.parent / "data"
        index_path = data_dir / "index.md"
        
        if index_path.exists():
            return index_path.read_text(encoding="utf-8")
        return None
    except Exception as e:
        logger.error(f"讀取 index.md 失敗: {e}")
        return None


if __name__ == "__main__":
    # 測試：直接執行生成
    logging.basicConfig(level=logging.INFO)
    
    success = generate_index_md()
    if success:
        print("✅ index.md 生成成功！")
    else:
        print("❌ index.md 生成失敗")
