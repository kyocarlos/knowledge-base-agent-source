# 📚 知識庫系統 - GraphRAG + RAG 雙模式搜尋

## 🏗️ 系統架構

```
📄 檔案輸入 (PDF/DOCX/PPT/XLSX/TXT/圖檔)
         ↓
🔄 MarkItDown 轉換為 Markdown
         ↓
    ┌────┴────┐
    ↓         ↓
 📚 基本搜尋   🧠 深層搜尋
 (RAG)        (GraphRAG)
    ↓         ↓
 向量檢索     知識圖譜
    ↓         ↓
    Docker 內 KB 服務的 Neo4j 向量索引  Docker 內 KB 服務的 Neo4j 圖結構
    └────┬────┘
         ↓
    🤖 LLM 生成答案
```

## 📁 目錄結構

```
knowledge-base/
├── config/
│   └── config.yaml.example   # 設定檔範例
├── data/
│   ├── raw/                  # 原始檔案（放 PDF/DOCX 等）
│   └── markdown/              # 轉換後的 Markdown
├── src/
│   ├── converter/             # 檔案轉換模組（MarkItDown）
│   ├── graphrag/              # GraphRAG 知識圖譜模組
│   ├── search/                # 雙模式搜尋引擎
│   ├── ui/                    # Gradio 前端介面
│   └── main.py                # 主程式
├── requirements.txt
└── README.md
```

## 🚀 快速開始

### 1. 安裝相依套件

```bash
cd knowledge-base
python3.12 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

### 2. 啟動 Docker 內 KB 服務的 Neo4j

```bash
# 啟動 knowledge-base 的 Docker stack
docker compose up -d

# Neo4j 由 KB 容器提供，對應的 Bolt 連線為 bolt://neo4j:7687
# Browser 介面請使用本專案對應的主機埠
```

### 3. 設定 config.yaml

```bash
cp config/config.yaml.example config/config.yaml
# 編輯 config.yaml，填入 API key，Neo4j 預設會使用容器內 KB 服務
```

### 4. 放置原始檔案

```bash
# 將 PDF/DOCX 等原始檔案放入 data/raw/
cp your-document.pdf data/raw/
```

### 5. 轉換檔案為 Markdown

```python
from src.converter import FileConverter

converter = FileConverter()
result = converter.convert_file("data/raw/report.pdf", "data/markdown/report.md")
print(result)
```

### 6. 攼入知識圖譜

```python
from src.main import KnowledgeBaseSystem

kb = KnowledgeBaseSystem("config/config.yaml")
kb.ingest_documents("data/markdown")
```

### 7. 啟動搜尋介面

```python
from src.ui import KnowledgeBaseUI

kb = KnowledgeBaseSystem("config/config.yaml")
ui = KnowledgeBaseUI(kb)
ui.launch(server_port=7860)
```

或使用命令列搜尋：

```python
# 基本搜尋
result = kb.basic_search("特休假可以請幾天？")

# 深層搜尋
result = kb.deep_search("比較特休假和家庭照顧假的差異？")

# 自動模式
result = kb.search("什麼是 GraphRAG？", mode="auto")
```

## ⚙️ 設定說明

### LLM 提供者

```yaml
# 選項 1: OpenAI
llm_provider: "openai"
llm_model: "gpt-4o"
llm_api_key: "sk-..."

# 選項 2: Google Gemini（你已設定的備援模型）
llm_provider: "google"
llm_model: "gemma-4-31b-it"

# LLM 設定（目前僅保留 Ollama）
llm_provider: "ollama"
llm_model: "gemma4:12b"
```

### Docker 內 KB 服務的 Neo4j 連線

```yaml
neo4j_uri: "bolt://neo4j:7687"
neo4j_user: "neo4j"
neo4j_password: "your-password"
```

## 🎯 搜尋模式

| 模式 | 說明 | 適用情境 |
|------|------|---------|
| `basic` | 傳統 RAG 向量搜尋 | 快速事實查詢、FAQ |
| `deep` | GraphRAG 知識圖譜 | 多跳推理、跨文件關聯 |
| `auto` | 自動選擇 | 不確定時使用 |

## 📝 使用範例

```python
# 批次轉換整個資料夾
results = converter.convert_batch(
    input_folder="data/raw",
    output_folder="data/markdown",
    file_patterns=[".pdf", ".docx", ".pptx"]
)

# 攼入時設定區塊大小
kb.ingest_documents("data/markdown", chunk_size=1000, overlap=200)

# 搜尋並查看來源
result = kb.search("家庭照顧假可以請幾天？", mode="basic")
print(result["answer"])
print(result["sources"])
```

## 🛠️ 開發

```bash
# 安裝可重現的測試依賴
pip install -r requirements-dev.txt

# 執行 repository 測試；pytest.ini 會限制收集範圍為 tests/
python -m pytest

# 啟動正式 API shell（舊路由由 compatibility layer 保留）
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 新版 platform contract
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/version

# 檢查 Docker 內 KB 服務的 Neo4j 連線
python -c "from src.graphrag import GraphRAGPipeline; g = GraphRAGPipeline(); print('Neo4j connected' if g.graph else 'Failed')"
```

## ⚠️ 注意事項

1. **Python 版本**：使用 Python 3.12 或 3.13（不支援 3.14）
2. **LLM 成本**：實體萃取會呼叫大量 LLM，注意 API 費用
3. **Docker 內 KB 服務的 Neo4j 效能**：大規模圖譜需要優化 Cypher 查詢
4. **圖片處理**：需要 OCR 時請使用 `markitdown[all]` 並設定 LLM client
5. **新電腦重建**：如果你要把系統搬到另一台機器，先看 `docs/github-backup-plan.md`，程式碼走 GitHub，資料走獨立備份 bundle。
6. **重建 SOP**：完整的新電腦部屬步驟整理在 `docs/new-machine-rebuild-guide.md`。
7. **安裝手冊**：如果要把 release 安裝包裝到另一台電腦，請先看 `docs/onprem-install-guide.md`。

## 📚 技術棧

- **檔案轉換**：MarkItDown（Microsoft 開源）
- **知識圖譜**：Docker 內 KB 服務的 Neo4j + LangChain
- **LLM**：Ollama（gemma4:12b）
- **前端**：Gradio
- **向量搜尋**：Docker 內 KB 服務的 Neo4j Vector 或 ChromaDB
