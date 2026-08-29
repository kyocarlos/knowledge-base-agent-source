# External Agent KB Controlled Query APIs

本文件提供外部電腦或外部 AI agent 查詢這台 knowledge-base 的受控 API 規格。

預設主要入口：

```text
https://61.216.9.52:3030
```

外部 agent 應只透過本文件列出的 API 查詢 KB。不要直接連線 Neo4j、Qdrant、Redis 或主機檔案系統。

## 使用原則

1. 所有知識查詢優先使用 `POST /search`，再用 `GET /tasks/{task_id}` 取得結果。
2. 若只要文件清單或原文內容，使用 `/api/category-files` 與 `/api/document`。
3. 若要讓外部 agent 自己生成回答，可用 `sources_only: true` 取得來源，再自行整理。
4. 外部 agent 必須保留 `sources`，回答使用者時應引用來源文件。
5. 請設定 timeout、輪詢間隔與最大重試次數，避免無限迴圈打爆 KB。
6. 不使用 `/api/openclaw/chat-config`、`/ws`、`/admin/*`、`/upload/*`、`/skills/*` 作為外部查詢介面。

## 建議外部 Agent 查詢流程

```text
Agent question
  -> POST /search
  -> receive task_id
  -> poll GET /tasks/{task_id}
  -> status == completed
  -> read answer + sources + citation_distribution
  -> produce final response with citations
```

建議輪詢設定：

```text
poll_interval_seconds: 2
max_wait_seconds: 120
max_retries: 60
default_top_k: 10
maximum_top_k: 30
```

## 1. Health Check

### GET /health

用途：確認 KB API 是否在線。

```bash
curl -k "https://61.216.9.52:3030/health"
```

成功回應：

```json
{
  "status": "healthy"
}
```

## 2. Root Info

### GET /

用途：取得 API 基本資訊。

```bash
curl -k "https://61.216.9.52:3030/"
```

成功回應：

```json
{
  "message": "知識庫搜尋系統 API",
  "version": "1.0.0"
}
```

## 3. Submit Knowledge Search

### POST /search

用途：提交 KB 搜尋任務。這是外部 agent 查詢所有 KB 內容的主要入口。

Request body：

```json
{
  "query": "請查詢 SCE2200 的 Handover 測試結果",
  "mode": "auto",
  "user_id": "external-agent-01",
  "top_k": 10,
  "sources_only": false
}
```

欄位說明：

| Field | Type | Required | Description |
|---|---:|---:|---|
| `query` | string | yes | 使用者問題或 agent 查詢語句 |
| `mode` | string | no | `auto`, `basic`, `deep`, `vector`, `hybrid` |
| `user_id` | string | no | 外部 agent ID，建議固定填入 |
| `top_k` | number | no | 回傳來源數量上限，建議 5-10，最高不超過 30 |
| `sources_only` | boolean | no | `true` 表示偏向取回來源，讓 agent 自行組答案 |

查詢模式建議：

| Mode | Usage |
|---|---|
| `auto` | 一般問題預設使用，讓 KB 自動選路由 |
| `vector` | 快速找相關文件片段 |
| `hybrid` | 需要較完整整合回答，但延遲可能較高 |
| `basic` | 較簡單的查詢 |
| `deep` | 圖譜或深度查詢 |

curl 範例：

```bash
curl -k -X POST "https://61.216.9.52:3030/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "請查詢 SCE2200 的 Handover 測試結果",
    "mode": "auto",
    "top_k": 10,
    "sources_only": false,
    "user_id": "external-agent-01"
  }'
```

成功回應：

```json
{
  "task_id": "8f8d1c2e-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "submitted",
  "message": "任務已提交，請使用 /tasks/{task_id} 查詢結果"
}
```

快取命中時可能回傳：

```json
{
  "task_id": "cached",
  "status": "completed",
  "message": "從快取回傳"
}
```

注意：目前 `task_id == cached` 時，外部 agent 可能無法透過 `/tasks/cached` 取得原始結果；建議 agent 若收到 `cached`，可稍後改變 `user_id` 或在 query 後加明確條件重送一次。正式化時建議新增 `/api/agent/query` 由 KB 端處理快取結果回傳。

## 4. Get Search Task Result

### GET /tasks/{task_id}

用途：取得 `/search` 任務狀態與結果。

```bash
curl -k "https://61.216.9.52:3030/tasks/8f8d1c2e-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

Pending 回應：

```json
{
  "task_id": "8f8d1c2e-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "pending",
  "queue_position": 1
}
```

Completed 回應：

```json
{
  "task_id": "8f8d1c2e-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "completed",
  "answer": "...",
  "sources": [
    {
      "source": "type6_NR-Handover-SCE2200-n79-EV-V13.8.md",
      "content": "...",
      "score": 0.82
    }
  ],
  "citation_distribution": {
    "category_counts": {
      "4G/5G": 2,
      "WiFi": 0,
      "Lab": 0,
      "Project": 0,
      "Automation": 0
    },
    "total_sources": 2
  },
  "mode": "report_graph"
}
```

Failed 回應：

```json
{
  "task_id": "8f8d1c2e-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "failed",
  "error": "..."
}
```

Agent 處理規則：

```text
if status in ["pending", "started", "retry"]:
  wait 2 seconds and poll again
elif status == "completed":
  use answer and sources
elif status == "failed":
  report error and optionally retry once
else:
  wait or fail after max_wait_seconds
```

## 5. Category Relevance

### POST /category-relevance

用途：估算問題與各資料分類的關聯程度。適合 agent 在查詢前判斷問題偏向 4G/5G、WiFi、Lab、Project 或 Automation。

Request body：

```json
{
  "query": "NCQ2200B2V-D294 的 WiFi throughput 結果是什麼？",
  "top_k": 20
}
```

curl 範例：

```bash
curl -k -X POST "https://61.216.9.52:3030/category-relevance" \
  -H "Content-Type: application/json" \
  -d '{"query":"NCQ2200B2V-D294 的 WiFi throughput 結果是什麼？","top_k":20}'
```

回應：

```json
{
  "query": "NCQ2200B2V-D294 的 WiFi throughput 結果是什麼？",
  "categories": {
    "4G/5G": 0,
    "WiFi": 3,
    "Lab": 0,
    "Project": 0,
    "Automation": 0
  }
}
```

## 6. Analyze Question

### POST /analyze-question

用途：分析問題與分類權重，回傳正規化分數、相關文件與預估等待時間。這是輔助 API，不是主要查詢 API。

Request body：

```json
{
  "query": "請比較 SCU2140 和 SCU2060 的下載速度差異"
}
```

curl 範例：

```bash
curl -k -X POST "https://61.216.9.52:3030/analyze-question" \
  -H "Content-Type: application/json" \
  -d '{"query":"請比較 SCU2140 和 SCU2060 的下載速度差異"}'
```

主要回應欄位：

```json
{
  "query": "...",
  "category_scores": {},
  "normalized_scores": {},
  "related_docs": {},
  "top_category": "4G/5G",
  "top_score": 80,
  "confidence": 0.8,
  "analysis_method": "weighted_query_and_document_scoring",
  "estimated_wait_seconds": 10
}
```

## 7. Source Category Resolver

### POST /api/source-categories

用途：將來源文件名稱解析成 KB 分類。適合 agent 拿到 `sources` 後確認引用分布。

Request body：

```json
{
  "sources": [
    "type6_NR-Handover-SCE2200-n79-EV-V13.8.md",
    "type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.md"
  ]
}
```

curl 範例：

```bash
curl -k -X POST "https://61.216.9.52:3030/api/source-categories" \
  -H "Content-Type: application/json" \
  -d '{
    "sources": [
      "type6_NR-Handover-SCE2200-n79-EV-V13.8.md",
      "type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.md"
    ]
  }'
```

回應：

```json
{
  "categories": {
    "4G/5G": 1,
    "WiFi": 1,
    "Lab": 0,
    "Project": 0,
    "Automation": 0
  },
  "source_categories": {
    "type6_NR-Handover-SCE2200-n79-EV-V13.8.md": "4G/5G",
    "type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.md": "WiFi"
  },
  "matched_count": 2,
  "unmatched_count": 0
}
```

## 8. List Raw Files

### GET /api/files

用途：列出 `data/raw` 內的原始文件。這是檔案盤點 API，不會回傳完整內容。

```bash
curl -k "https://61.216.9.52:3030/api/files"
```

回應：

```json
{
  "files": [
    {
      "name": "example.pdf",
      "size": 12345,
      "path": "example.pdf",
      "category": null,
      "mtime": 1710000000000000000
    }
  ]
}
```

## 9. Category Stats

### GET /api/category-stats

用途：取得各分類的搜尋統計與狀態。適合 agent 了解 KB 目前分類概況。

```bash
curl -k "https://61.216.9.52:3030/api/category-stats"
```

回應：

```json
{
  "categories": [
    {
      "name": "4G/5G",
      "status": "strong",
      "score": 20,
      "docs": 10,
      "search_count": 20,
      "files": []
    }
  ]
}
```

## 10. List Documents By Category

### GET /api/category-files?category={category}

用途：列出某分類下已處理或已上傳攝入的文件。

支援分類：

```text
4G/5G
WiFi
Lab
Project
Automation
```

curl 範例：

```bash
curl -k "https://61.216.9.52:3030/api/category-files?category=4G%2F5G"
curl -k "https://61.216.9.52:3030/api/category-files?category=WiFi"
curl -k "https://61.216.9.52:3030/api/category-files?category=Automation"
```

回應：

```json
{
  "category": "4G/5G",
  "files": [
    {
      "name": "type6_NR-Handover-SCE2200-n79-EV-V13.8",
      "full_name": "type6_NR-Handover-SCE2200-n79-EV-V13.8.md",
      "modified": "2026-05-20 10:00"
    }
  ],
  "count": 1
}
```

## 11. Get Document Content

### GET /api/document?category={category}&doc_name={doc_name}

用途：取得指定文件的 Markdown 內容。這是外部 agent 讀取 KB 原文的主要入口。

參數：

| Parameter | Required | Description |
|---|---:|---|
| `category` | yes | `4G/5G`, `WiFi`, `Lab`, `Project`, `Automation` |
| `doc_name` | yes | 文件名稱，可帶或不帶 `.md` |

curl 範例：

```bash
curl -k "https://61.216.9.52:3030/api/document?category=4G%2F5G&doc_name=type6_NR-Handover-SCE2200-n79-EV-V13.8"
```

回應：

```json
{
  "category": "4G/5G",
  "doc_name": "type6_NR-Handover-SCE2200-n79-EV-V13.8",
  "full_path": "/home/da40_ai_gb10/knowledge-base/data/processed/4G_5G/type6_NR-Handover-SCE2200-n79-EV-V13.8.md",
  "content": "# ...",
  "content_length": 123456,
  "modified": "2026-05-20 10:00"
}
```

注意：`content` 可能很長。外部 agent 應自行做 chunk、摘要或只擷取需要段落。

## 12. System Stats

### GET /stats

用途：取得簡易系統查詢狀態，例如 worker 數量與快取狀態。

```bash
curl -k "https://61.216.9.52:3030/stats"
```

回應：

```json
{
  "active_workers": 2,
  "queued_tasks": 0,
  "cache_enabled": true
}
```

## 13. Hybrid Status

### GET /hybrid-status

用途：確認 hybrid 查詢目前是否忙碌。外部 agent 若要發送 `mode: "hybrid"`，可先查這個端點。

```bash
curl -k "https://61.216.9.52:3030/hybrid-status"
```

回應：

```json
{
  "current_count": 0,
  "max_allowed": 3,
  "is_busy": false,
  "message": "可以使用"
}
```

## 14. Extraction Modes

### GET /extraction-modes

用途：列出 KB 支援的資料萃取模式。這主要給 ingest 使用，但外部 agent 可用它理解 KB 分類與模式名稱。

```bash
curl -k "https://61.216.9.52:3030/extraction-modes"
```

回應：

```json
{
  "modes": [
    {
      "id": "4g5g",
      "name": "4G/5G",
      "description": "..."
    }
  ]
}
```

## Agent Query Examples

### Example A: Ask KB For An Answer

```bash
TASK_ID=$(curl -sk -X POST "https://61.216.9.52:3030/search" \
  -H "Content-Type: application/json" \
  -d '{"query":"請整理 SCE2200 的 Handover 測試內容與結果","mode":"auto","top_k":10,"user_id":"external-agent-01"}' \
  | jq -r '.task_id')

for i in $(seq 1 60); do
  RESULT=$(curl -sk "https://61.216.9.52:3030/tasks/${TASK_ID}")
  STATUS=$(echo "$RESULT" | jq -r '.status')
  if [ "$STATUS" = "completed" ]; then
    echo "$RESULT" | jq .
    break
  fi
  if [ "$STATUS" = "failed" ]; then
    echo "$RESULT" | jq .
    exit 1
  fi
  sleep 2
done
```

### Example B: List All Categories Then Read Documents

```bash
curl -sk "https://61.216.9.52:3030/api/category-files?category=4G%2F5G" | jq .
curl -sk "https://61.216.9.52:3030/api/category-files?category=WiFi" | jq .
curl -sk "https://61.216.9.52:3030/api/category-files?category=Lab" | jq .
curl -sk "https://61.216.9.52:3030/api/category-files?category=Project" | jq .
curl -sk "https://61.216.9.52:3030/api/category-files?category=Automation" | jq .
```

Then read a document:

```bash
curl -sk "https://61.216.9.52:3030/api/document?category=WiFi&doc_name=type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10" | jq -r '.content'
```

### Example C: Retrieve Sources Only

```bash
curl -k -X POST "https://61.216.9.52:3030/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "SCU2140 throughput latency BLER",
    "mode": "vector",
    "top_k": 20,
    "sources_only": true,
    "user_id": "external-agent-01"
  }'
```

## APIs Intentionally Excluded For External Query Agents

以下 API 不應提供給外部查詢 agent 作為學習或操作介面：

| Endpoint Pattern | Reason |
|---|---|
| `/api/openclaw/chat-config` | 可能暴露 chat runtime/session 設定 |
| `/ws` | 瀏覽器 chat proxy，不是資料查詢 API |
| `/admin/*` | 管理、維運或內部統計端點 |
| `/upload/*`, `/api/upload/*` | 寫入與攝入端點，應用另一份 ingest 規格控管 |
| `/api/increment-search-count` | 寫入統計，不是查詢 |
| `/skills/*`, `/api/skills/*` | 技能讀寫與內部設定，不是 KB 查詢資料面 |
| `DELETE /tasks/{task_id}` | 會取消任務，外部查詢 agent 不應使用 |

## Security Recommendations For Production

目前文件描述的是現有 API 使用方式。若要正式讓外部電腦長期查詢所有 KB 資料，建議在 API 前補上：

1. `Authorization: Bearer <token>`。
2. token scope：`kb:query:read`、`kb:document:read`，與 ingest/write token 分開。
3. IP allowlist 或 mTLS。
4. rate limit，例如每個 agent 每分鐘 30 次查詢。
5. audit log：記錄 `agent_id`、來源 IP、query、task_id、sources、status、latency。
6. `top_k`、query 長度、回傳內容大小限制。
7. 專用封裝端點：`POST /api/agent/query`，由 KB 端處理 submit + poll + cache 結果。

## Minimal Agent Contract

外部 agent 至少應實作：

```json
{
  "base_url": "https://61.216.9.52:3030",
  "query_endpoint": "POST /search",
  "task_endpoint": "GET /tasks/{task_id}",
  "document_list_endpoint": "GET /api/category-files?category={category}",
  "document_content_endpoint": "GET /api/document?category={category}&doc_name={doc_name}",
  "default_mode": "auto",
  "default_top_k": 10,
  "poll_interval_seconds": 2,
  "max_wait_seconds": 120,
  "must_preserve_sources": true
}
```
