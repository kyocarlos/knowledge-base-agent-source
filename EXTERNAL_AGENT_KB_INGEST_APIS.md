# External Agent KB Ingest APIs

本文件提供外部電腦或外部 AI agent 將檔案傳入 knowledge-base，並由 KB 後端攝入 Neo4j / Qdrant 的受控 API 規格。

預設主要入口：

```text
https://127.0.0.1:3030
```

外部 agent 不應直接連線 Neo4j、Qdrant、Redis 或主機檔案系統。外部 agent 只需要把標準化檔案 artifact 上傳到 KB API；轉檔、去重、寫入 Neo4j、寫入 Qdrant、更新索引都由 KB 後端統一執行。

## 與查詢文件的分工

| File | Purpose | Access Type |
|---|---|---|
| `EXTERNAL_AGENT_KB_QUERY_APIS.md` | 查詢 KB 既有資料 | read-only |
| `EXTERNAL_AGENT_KB_INGEST_APIS.md` | 上傳檔案並攝入 KB | write / ingest |

正式部署時，query token 與 ingest token 必須分開。不要把具備 ingest 權限的 token 發給只需要查詢的 agent。

## Ingest 資料流

```text
External agent
  -> POST /api/upload/ingest?extraction_mode=<mode>
  -> KB web receives multipart file
  -> save original file under data/uploads/<category>/<task_id>/original/
  -> create Redis ingest task state
  -> dispatch Celery ingest_file_task
  -> convert file to Markdown under converted/
  -> write .source.json metadata
  -> ingest_document()
  -> cleanup old same-name document data
  -> write Neo4j graph/document nodes
  -> write Qdrant vector points
  -> refresh index.md
  -> GET /api/upload/tasks/{task_id} returns completed or failed
```

## 使用原則

1. 外部 agent 只呼叫 `/api/upload/ingest` 與 `/api/upload/tasks/{task_id}` 這類受控 API。
2. 外部 agent 不直接寫 Neo4j / Qdrant。
3. 每個上傳檔案應有穩定、可讀、低碰撞的檔名。
4. 測試結果、log、截圖摘要等建議先整理成 Markdown、JSON、HTML、PDF 或 XLSX。
5. 每次上傳後必須輪詢 task 狀態，只有 `completed` 才代表已寫入 KB。
6. 若收到 `duplicate: true`，代表 KB 已偵測到相同檔案內容，不需要重送。
7. 大量上傳時要限速，避免 ingest queue 堆積。

建議輪詢設定：

```text
poll_interval_seconds: 3
max_wait_seconds: 900
max_retries: 300
max_file_size: 200 MB
default_extraction_mode: automation
```

## 支援檔案格式

目前 watch / ingest pipeline 可處理的常見格式：

```text
.xlsx, .xls, .pdf, .docx, .doc, .pptx, .ppt,
.txt, .md, .html, .csv, .json, .xml, .epub, .msg
```

單一 multipart part 目前上限約 `200 MB`。

## Extraction Modes

### GET /extraction-modes

用途：列出 KB 支援的資料萃取模式。

```bash
curl -k "https://127.0.0.1:3030/extraction-modes"
```

外部 agent 上傳時主要使用以下模式：

| Mode | Storage Category | Use Case |
|---|---|---|
| `4g5g` | `4G_5G` | 4G/5G、NR、LTE、throughput、handover 報告 |
| `wifi` | `WiFi` | WiFi throughput、AP、router、wireless 測試 |
| `lab` | `Lab` | 實驗室設備、校驗、借用、環境紀錄 |
| `project` | `Project` | 專案管理、週報、風險、UAT、資源配置 |
| `automation` | `Automation` | 外部 AI agent 測試結果、自動化 log、CI/CD、腳本結果 |

注意：KB 會先依檔名偵測模式；若檔名已能判定類型，檔名判定會優先於 query parameter 的 `extraction_mode`。

## 1. Health Check

### GET /health

用途：確認 KB API 是否在線。

```bash
curl -k "https://127.0.0.1:3030/health"
```

成功回應：

```json
{
  "status": "healthy"
}
```

## 2. Upload And Ingest File

### POST /api/upload/ingest

用途：上傳檔案並提交背景攝入任務。這是外部 agent 將檔案寫入 KB 後端 Neo4j / Qdrant 的主要受控入口。

Query parameter：

| Parameter | Required | Default | Description |
|---|---:|---|---|
| `extraction_mode` | no | `4g5g` | `4g5g`, `wifi`, `lab`, `project`, `automation` |

Multipart form：

| Field | Required | Description |
|---|---:|---|
| `file` | yes | 要上傳攝入的檔案 |

curl 範例：上傳外部 agent 測試結果

```bash
curl -k -X POST \
  "https://127.0.0.1:3030/api/upload/ingest?extraction_mode=automation" \
  -F "file=@test-result-run-20260721-001.md"
```

curl 範例：上傳 WiFi 報告

```bash
curl -k -X POST \
  "https://127.0.0.1:3030/api/upload/ingest?extraction_mode=wifi" \
  -F "file=@type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.xlsx"
```

curl 範例：上傳 4G/5G 報告

```bash
curl -k -X POST \
  "https://127.0.0.1:3030/api/upload/ingest?extraction_mode=4g5g" \
  -F "file=@type6_NR-Handover-SCE2200-n79-EV-V13.8.xlsx"
```

成功提交回應：

```json
{
  "status": "submitted",
  "task_id": "ingest_20260721_103000_ab12cd34",
  "file_name": "test-result-run-20260721-001.md",
  "file_hash": "sha256...",
  "storage_category": "Automation",
  "extraction_mode": "automation",
  "extraction_mode_name": "Automation",
  "queue_position": 1,
  "message": "已加入攝入佇列"
}
```

重複檔案且已攝入時可能回應：

```json
{
  "status": "success",
  "file_name": "test-result-run-20260721-001.md",
  "task_id": "ingest_20260721_103000_ab12cd34",
  "converted_path": "/app/data/uploads/Automation/ingest_.../converted/test-result-run-20260721-001.md",
  "ingested": true,
  "duplicate": true,
  "file_hash": "sha256...",
  "extraction_mode": "automation",
  "message": "檔案內容已攝入，已略過重複提交"
}
```

相同檔案正在處理時可能回應：

```json
{
  "status": "submitted",
  "file_name": "test-result-run-20260721-001.md",
  "task_id": "ingest_20260721_103000_ab12cd34",
  "ingested": false,
  "duplicate": true,
  "queue_position": 1,
  "message": "相同檔案已在處理中，請等待目前任務完成"
}
```

## 3. Get Ingest Task Status

### GET /api/upload/tasks/{task_id}

用途：查詢單一 ingest 任務狀態。

```bash
curl -k "https://127.0.0.1:3030/api/upload/tasks/ingest_20260721_103000_ab12cd34"
```

常見回應：

```json
{
  "task_id": "ingest_20260721_103000_ab12cd34",
  "file_name": "test-result-run-20260721-001.md",
  "original_path": "/app/data/uploads/Automation/ingest_.../original/test-result-run-20260721-001.md",
  "converted_path": "/app/data/uploads/Automation/ingest_.../converted/test-result-run-20260721-001.md",
  "file_hash": "sha256...",
  "storage_category": "Automation",
  "extraction_mode": "automation",
  "status": "writing_qdrant",
  "progress": 85,
  "status_text": "寫入向量資料庫中",
  "step": "正在寫入 QDrant 向量資料庫",
  "ingested": false,
  "queue_position": 0,
  "error": null
}
```

## Ingest Status Lifecycle

| Status | Progress | Meaning |
|---|---:|---|
| `queued` | 5 | 等待背景任務處理 |
| `upload_saved` | 10 | 檔案已接收並儲存 |
| `converting` | 20 | 正在轉 Markdown |
| `converted` | 30 | Markdown 轉換完成 |
| `extracting` | 50 | 正在萃取文件實體與關係 |
| `writing_neo4j` | 70 | 正在寫入 Neo4j |
| `writing_qdrant` | 85 | 正在寫入 Qdrant |
| `refreshing_index` | 95 | 正在更新 `index.md` |
| `completed` | 100 | 文件已完成攝入 |
| `failed` | 0 | 攝入失敗 |

Agent 處理規則：

```text
if status in ["queued", "upload_saved", "converting", "converted", "extracting", "writing_neo4j", "writing_qdrant", "refreshing_index"]:
  wait poll_interval_seconds and poll again
elif status == "completed":
  treat file as searchable in KB
elif status == "failed":
  read error, report failure, retry only if the failure is transient
else:
  fail after max_wait_seconds
```

## 4. List Recent Ingest Tasks

### GET /api/upload/tasks

用途：列出目前與近期 ingest 任務。適合外部 agent 做批次上傳後的總覽。

```bash
curl -k "https://127.0.0.1:3030/api/upload/tasks"
```

回應格式：

```json
{
  "active": [],
  "queued": [],
  "recent": [
    {
      "task_id": "ingest_20260721_103000_ab12cd34",
      "file_name": "test-result-run-20260721-001.md",
      "status": "completed",
      "progress": 100,
      "ingested": true
    }
  ]
}
```

## 5. Verify The File Is Queryable

攝入完成後，外部 agent 可以使用查詢文件 `EXTERNAL_AGENT_KB_QUERY_APIS.md` 的 `/search` 流程確認內容可被查到。

範例：

```bash
curl -k -X POST "https://127.0.0.1:3030/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "請查詢 test-result-run-20260721-001 的測試結果摘要",
    "mode": "auto",
    "top_k": 10,
    "user_id": "external-agent-01"
  }'
```

或直接依分類讀取文件：

```bash
curl -k "https://127.0.0.1:3030/api/category-files?category=Automation"
curl -k "https://127.0.0.1:3030/api/document?category=Automation&doc_name=test-result-run-20260721-001"
```

## Recommended External Agent Artifact Format

外部測試 agent 建議優先產生 Markdown。Markdown 比純 JSON 更容易被 KB 搜尋、切 chunk 與引用。

範例：

```md
# Test Result: run-20260721-001

- Run ID: run-20260721-001
- Source Environment: external-agent-lab-01
- Agent ID: external-agent-01
- Agent Version: 1.4.2
- Project: KB regression
- DUT: SCE2200
- Started At: 2026-07-21T10:00:00+08:00
- Finished At: 2026-07-21T10:12:00+08:00
- Result: PASS

## Summary

本次測試完成 KB query / ingest / search smoke test，結果 PASS。

## Steps

| Step | Action | Expected | Actual | Result |
|---|---|---|---|---|
| 1 | GET /health | healthy | healthy | PASS |
| 2 | POST /search | task submitted | task submitted | PASS |
| 3 | GET /tasks/{task_id} | completed | completed | PASS |

## Errors

No blocking errors.

## Evidence

- Log file: run-20260721-001.log
- Screenshot: run-20260721-001-chat.png
```

## Batch Upload Pattern

外部 agent 批次上傳時應逐檔提交，保留每個 `task_id`，再逐一輪詢。

Pseudo flow：

```text
for file in artifact_files:
  upload file
  store task_id

for task_id in task_ids:
  poll until completed or failed

if all completed:
  run query verification
else:
  report failed task_id and error
```

簡化 bash 範例：

```bash
TASK_ID=$(curl -sk -X POST \
  "https://127.0.0.1:3030/api/upload/ingest?extraction_mode=automation" \
  -F "file=@test-result-run-20260721-001.md" \
  | jq -r '.task_id')

for i in $(seq 1 300); do
  RESULT=$(curl -sk "https://127.0.0.1:3030/api/upload/tasks/${TASK_ID}")
  STATUS=$(echo "$RESULT" | jq -r '.status')
  if [ "$STATUS" = "completed" ]; then
    echo "$RESULT" | jq .
    break
  fi
  if [ "$STATUS" = "failed" ]; then
    echo "$RESULT" | jq .
    exit 1
  fi
  sleep 3
done
```

## Watch Folder Alternative

若外部電腦不能直接呼叫 HTTPS API，可改用受控檔案投遞：

```text
External agent
  -> SCP/SFTP/shared folder
  -> KB data/watch
  -> Celery Beat watch_folder_scan
  -> convert
  -> ingest_document()
  -> Neo4j / Qdrant
```

這條路徑需要 KB 管理者事先設定 watch folder 權限、排程與檔案命名規則。對外部 agent 而言，API 上傳通常比較可追蹤，因為會立即拿到 `task_id`。

## APIs Intentionally Excluded For External Ingest Agents

以下 API 不應提供給外部 ingest agent 作為一般操作介面：

| Endpoint Pattern | Reason |
|---|---|
| Direct Neo4j / Qdrant ports | 會繞過 KB schema、去重、清舊資料與 audit |
| `/admin/*` | 管理與維運端點，不是外部 ingest 介面 |
| `/api/upload/tasks/clear` | 會清除任務歷史，不應由外部 agent 操作 |
| `/upload/json` / `/api/upload/json` | 目前不是完整 Neo4j/Qdrant 攝入主路徑 |
| `/upload` / `/api/upload` | 只上傳/轉檔，不保證完成 Neo4j/Qdrant 攝入 |
| `/skills/*`, `/api/skills/*` | 技能讀寫與內部設定 |
| `/api/openclaw/chat-config`, `/ws` | Chat runtime，不是 ingest 介面 |

## Security Recommendations For Production

正式讓外部 agent 上傳資料前，建議先補上：

1. `Authorization: Bearer <token>`。
2. token scope 分離：`kb:query:read`、`kb:document:read`、`kb:ingest:write`。
3. IP allowlist 或 mTLS。
4. rate limit，例如每個 ingest agent 每分鐘最多 3-10 個檔案。
5. audit log：記錄 `agent_id`、來源 IP、file name、file hash、task_id、status、storage_category、latency。
6. file size、content type、extension allowlist。
7. malware scan 或至少副檔名與 MIME 檢查。
8. idempotency key 或以 `file_hash` 去重。
9. 明確的 retention policy：原始檔、converted Markdown、source metadata 保存多久。

## Minimal Agent Contract

外部 ingest agent 至少應實作：

```json
{
  "base_url": "https://127.0.0.1:3030",
  "health_endpoint": "GET /health",
  "ingest_endpoint": "POST /api/upload/ingest?extraction_mode={mode}",
  "task_endpoint": "GET /api/upload/tasks/{task_id}",
  "default_extraction_mode": "automation",
  "supported_modes": ["4g5g", "wifi", "lab", "project", "automation"],
  "poll_interval_seconds": 3,
  "max_wait_seconds": 900,
  "max_file_size_mb": 200,
  "must_wait_for_completed": true,
  "must_not_connect_to_databases_directly": true
}
```

