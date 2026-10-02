# Anritsu / Amarisoft 4G/5G 測試結果知識庫整合架構

## 架構摘要

```text
Anritsu 測試環境                         Amarisoft 測試環境
Agent A + 儀器控制 + iperf              Agent B + 儀器控制 + iperf
          |                                       |
          |- 產生標準 Excel                       |- 產生標準 Excel
          |- 本機驗證                             |- 本機驗證
          `- Local KB MCP Bridge                  `- Local KB MCP Bridge
                         |  VPN + HTTPS + Agent Token
                         v
                 KB Agent Ingest API
                         |
                 Redis / Celery Ingest
                  +------+--------+
                  v               v
          Neo4j 結構化圖譜    Qdrant 原文向量
                  +------+--------+
                         v
             Knowledge Base Search / Chat
                         v
           查單次結果、趨勢、跨環境比較
```

兩個測試 Agent 保持完全獨立，只共用 Excel 契約、MCP 工具及 KB。Agent 不得取得 Neo4j、Qdrant、Redis 或主機檔案系統權限。

## 核心實作

### 1. 標準 Excel 契約

每次測試產生一份不可變 Excel，檔名使用：

```text
4G5G-{environment}-{project}-{dut}-{run_id}-{timestamp}.xlsx
```

固定工作表：

- `Manifest`：`schema_version`、`run_id`、`environment`、Agent/儀器版本、開始與完成時間、專案、DUT、韌體、總判定。
- `RadioConfig`：RAT、SA/NSA、band、頻寬、頻率、MIMO、cell、訊號與網路設定。
- `IperfResults`：case ID、TCP/UDP、DL/UL/BiDir、streams、duration、目標速率、實測 Mbps、jitter、loss、retransmits、RTT、exit code。
- `Verdicts`：case ID、門檻、Pass/Fail、判定原因。
- `RawIperf`：原始 iperf JSON/text、執行命令、開始時間、結束時間及 checksum。

`environment` 固定為 `anritsu` 或 `amarisoft`。判定與欄位驗證由普通程式碼完成，不交給 LLM 推測。

### 2. 本機 MCP Bridge

Anritsu、Amarisoft 的 Windows 測試電腦各安裝相同的 Python stdio MCP Server，提供：

- `kb_validate_report(file_path)`：驗證副檔名、Excel schema、必要欄位、run ID、iperf exit code 及檔案可讀性。
- `kb_ingest_report(file_path)`：讀取 Manifest、計算 SHA-256、上傳並回傳 `task_id`。
- `kb_get_ingest_status(task_id)`：取得目前攝入階段與錯誤。
- `kb_wait_for_ingest(task_id, timeout_seconds)`：等待 `completed` 或明確失敗。
- `kb_retry_pending()`：重送本機 outbox 中因 VPN、timeout 或 5xx 失敗的報告。

設定由環境變數或受保護設定檔提供：`KB_BASE_URL`、`KB_AGENT_ID`、`KB_INGEST_TOKEN`、`KB_CA_CERT`、`KB_REPORT_ROOT`。正式環境禁止使用 `-k`，並限制 MCP 只能讀取核准的報告目錄。

### 3. KB 攝入介面

新增穩定、具版本的 Agent API：

```text
GET  /api/agent/v1/health
POST /api/agent/v1/reports
GET  /api/agent/v1/ingest-tasks/{task_id}
```

`POST /reports` 使用 multipart Excel，並帶：

```text
Authorization: Bearer <agent-token>
Idempotency-Key: <run_id>
X-Agent-ID: anritsu-agent-01
```

此 API 驗證 token scope、Agent 身分、Excel schema 及 `environment` 是否符合 token。通過後共用現有 Redis/Celery 攝入流程，不另建第二套資料管線。

冪等規則：

- 相同 `run_id`、相同 hash：回傳原 task/result。
- 相同 `run_id`、不同 hash：回 `409 run_id_conflict`。
- 不同 `run_id`：保留為不同測試紀錄。
- 只有 Neo4j、Qdrant 與來源檔案驗證全部成功，狀態才能成為 `completed`。

### 4. Neo4j 與 Qdrant

新增 canonical Excel parser，避免完全依賴通用 Markdown/LLM 推斷。`report` 模式納入受控上傳模式，並保留現有舊文件相容性。

Neo4j 建立：

```text
(TestEnvironment)-[:EXECUTED]->(TestRun)
(TestRun)-[:TESTED_DUT]->(DUT)
(TestRun)-[:USES_CONFIG]->(RadioConfig)
(TestRun)-[:HAS_CASE]->(TestCase)
(TestCase)-[:MEASURED]->(Metric)
(TestCase)-[:SUPPORTED_BY]->(SourceChunk)
(Project)-[:HAS_RUN]->(TestRun)
```

`TestRun.run_id`、`TestCase.id`、`Metric.id` 設唯一約束。Metric 保留數值、單位、門檻與 verdict，支援精確比較。

Qdrant 仍使用既有 collection，但每個 point 增加 `run_id`、`environment`、`project_code`、`dut_model`、`band`、`protocol`、`direction`、`verdict`、`started_at`、`doc_name`、`chunk_index` payload。

### 5. 使用者查詢

保留現有 `/search`、`/tasks/{task_id}` 與 `chat.html`，增加可選 filters：

```json
{
  "environment": ["anritsu", "amarisoft"],
  "project_code": "NCQ2200B2V",
  "band": "n78",
  "protocol": "TCP",
  "direction": "DL",
  "verdict": "Pass",
  "date_from": "2026-07-01",
  "date_to": "2026-07-31"
}
```

查單一報告時使用 Qdrant 原文與 Neo4j metrics；跨環境、趨勢與數值比較優先使用 Neo4j，再附 Qdrant `SourceChunk` 引用。聊天來源卡片顯示環境、run ID、測試時間、DUT、band 與原始 Excel 名稱。

## 安全與可靠性

- 兩套環境透過 VPN 連線，每個 Agent 使用獨立、可撤銷、僅限 ingest 的 token。
- Token 不寫入 prompt、Excel、log 或原始碼；伺服器只儲存 token hash。
- API 加入檔案大小、格式、rate limit、IP/VPN 來源及 audit log。
- 本機 outbox 保存待上傳檔案、run ID、hash、重試次數與最後錯誤；採指數退避。
- 跨 Neo4j/Qdrant 無法做單一交易，因此 worker 使用冪等 upsert、分階段狀態及 reconciliation job 修復部分成功。
- 現有無認證 `/api/upload/ingest` 保留給內部 UI 相容，但外部 Agent 只能使用 `/api/agent/v1/*`。

## 驗證計畫

- 以 Anritsu、Amarisoft fixture 驗證 Excel parser、欄位型別、單位與缺欄錯誤。
- 驗證 token scope、錯誤環境、路徑越界、超大檔案及無效 workbook 均被拒絕。
- 驗證重複 hash、相同 run 衝突、VPN 中斷、timeout、worker 重啟與資料庫部分失敗。
- 端到端測試：Agent 產生 Excel -> MCP 上傳 -> task completed -> Neo4j 存在 TestRun/Metric -> Qdrant 存在 chunks。
- 透過 `https://61.216.9.52:3030/chat.html` 實測單一結果、Anritsu/Amarisoft 比較、趨勢、Fail 案例與來源引用。
- 先以 Anritsu 單環境試行，再接 Amarisoft；舊報告不搬移，新產生的 canonical 報告開始使用新 schema。

## 已選定假設

- 兩套 Agent 電腦皆可執行本機 stdio MCP Bridge，並可經 VPN 連到 KB。
- Excel 採共同模板，每個 run 一份不可變報告。
- 報告通過程式驗證後自動攝入；失敗測試結果也必須攝入，不因 verdict 為 Fail 而略過。
- 正式名稱統一為 `Amarisoft`，資料識別值使用 `amarisoft`。
- 第一階段沿用既有 Celery、Neo4j、Qdrant 與搜尋主幹，不讓 MCP 直接操作資料庫。

## 現況差距與實作順序

目前 KB 已有 `/api/upload/ingest`、Redis/Celery 攝入工作、Excel 轉 Markdown、Neo4j/Qdrant 寫入與 `/search` 查詢主幹，但尚未提供真正的外部攝入 MCP Server、Agent token 驗證、run ID 冪等控制及標準化測試報告 schema。此外，現有 `automation` 模式只寫 Qdrant，不適合作為要求 Neo4j 與 Qdrant 雙寫的測試報告模式。

建議實作順序：

1. 定義並凍結 Excel schema v1、欄位型別、單位與範例報告。
2. 實作 canonical Excel parser、驗證器及 Neo4j/Qdrant metadata 映射。
3. 新增 `/api/agent/v1/*`、token scope、run ID 冪等與 audit log。
4. 實作 Windows 本機 stdio MCP Bridge、受控路徑與 outbox 重送。
5. 擴充 KB 搜尋 filters、精確 metrics 比較與來源卡片。
6. 完成 Anritsu pilot，再以相同契約接入 Amarisoft，最後執行雙環境端到端驗收。
