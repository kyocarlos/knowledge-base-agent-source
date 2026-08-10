# Anritsu Agent A2A 配合實作清單

## 1. 目標與角色

KM 是中央 `Orchestrator / Control Plane`，Anritsu Agent 是獨立部署的 `A2A Server / Execution Plane`。

Anritsu Agent 必須接受 KM 透過 A2A 提交的受控測試任務，使用既有儀器控制與 iperf 功能執行測試，產生 Excel 後沿用既有 KM ingest API 上傳。A2A 故障、停用或未啟動時，原本的手動測試、MCP 工具、Excel 產生與上傳功能必須維持正常。

## 2. 不可改變的架構邊界

- A2A 採獨立 sidecar process，不直接併入既有 production agent process。
- 使用獨立 Python virtual environment、port、設定檔、log、PID 與 Windows service。
- A2A adapter 只能透過既有 stable adapter 呼叫原本儀器控制功能。
- 不得在 Anritsu 電腦安裝或直接連線 Neo4j、Qdrant、Redis、Celery。
- 不得建立第二套 Excel ingest；完成後仍呼叫既有 KM upload client／MCP tool。
- A2A credential 與 KM Excel ingest token 必須完全分離，不得互用。
- 不得讓 LLM 傳送或執行任意 shell、PowerShell、SCPI、Python、檔案路徑或 URL。
- 所有可執行測試必須來自固定 allowlisted profile。

## 3. 建議環境與套件

- Windows 11
- Python 3.10 以上，建議 Python 3.11
- 獨立 virtual environment
- 官方 `a2a-sdk[http-server]`，版本需與 KM 端相容 A2A Protocol 1.0
- `fastapi`／`uvicorn`，若 SDK HTTP server extra 未完整提供
- `httpx`
- 既有 Excel parser／generator；缺少時才補 `openpyxl`
- Python 內建 SQLite，用於 task journal
- `python-dotenv` 可選，只可讀取受保護設定

不得直接將 A2A 套件安裝到既有 production agent virtual environment，除非已完成 dependency lock 與完整手動測試回歸。

## 4. 必須新增的模組

建議依既有專案命名調整，但責任必須分離：

| 模組 | 必要責任 |
| --- | --- |
| `a2a_server` | 提供 Agent Card 與 A2A 1.x JSON-RPC endpoint |
| `job_schema` | 驗證固定結構化 job，拒絕 extra fields 與非法值 |
| `profile_registry` | profile allowlist 與各 profile 的固定參數範圍 |
| `task_executor` | queue、instrument lock、執行、timeout、cancel、cleanup |
| `task_journal` | SQLite 持久化、重啟恢復、correlation 與 audit |
| `result_handoff` | 原子產出 Excel、計算 hash、呼叫既有 KM uploader |
| `health` | 回報版本、能力、dry-run／real mode 與儀器占用狀態 |

## 5. Agent Card 契約

必須提供：

```text
GET https://<anritsu-host>/.well-known/agent-card.json
```

要求：

- A2A protocol version：`1.0` 或相容的 `1.x`
- protocol binding：`JSONRPC`
- 實際 A2A interface 使用相同 HTTPS origin，例如 `https://<anritsu-host>/a2a`
- 必須宣告 `run_iperf_test` skill
- 建議另外宣告 `get_test_status`、`cancel_test`
- input/output mode 至少支援 `application/json`
- security scheme 宣告獨立 A2A Bearer 或 mTLS
- 不得包含 token、密碼、內部檔案路徑或不必要的內部服務 URL

KM 會拒絕以下 Agent Card：

- 沒有 A2A 1.x JSON-RPC interface
- 沒有 `run_iperf_test`
- interface URL 與 discovery URL 不同 origin
- 缺少必要 identity/capability

## 6. A2A 認證

- 建立一組專用的 `KM -> Anritsu A2A` credential。
- 不得使用現有 `anritsu-agent-01` KM ingest token。
- 正式環境使用 VPN + HTTPS；建議再加 mTLS。
- credential 只存 Windows Credential Manager、secret store 或受保護環境變數。
- token 不得寫入 Agent Card、Excel、SQLite task payload、log、錯誤訊息或 Git。
- 至少區分 `test:run`、`test:status`、`test:cancel` scope，或提供等價權限控制。
- 無 credential、錯誤 credential、錯誤 scope 均必須顯性拒絕。

## 7. 固定 Job Schema

KM 會透過 A2A Data Part 傳送類似以下 payload：

```json
{
  "job_schema_version": "1.0",
  "dry_run": true,
  "job_type": "run_iperf_test",
  "environment": "anritsu",
  "profile_id": "ncq2200b2v-throughput-v1",
  "run_id": "run-20260806-001",
  "requested_by": "operator-01",
  "duration_seconds": 60,
  "test_cases": ["sa_dl_tcp", "sa_ul_tcp"]
}
```

驗證要求：

- `job_schema_version` 必須是支援版本。
- `job_type` 目前只能是 `run_iperf_test`。
- `environment` 必須是 `anritsu`。
- `profile_id` 必須存在 allowlist。
- `run_id` 必須是安全識別字，且作為冪等鍵的一部分。
- `duration_seconds` 必須在 profile 允許範圍內，系統硬上限不得超過 3600 秒。
- `test_cases` 不得為空，且每個 case 必須在 profile allowlist。
- 拒絕未定義欄位、任意命令、任意路徑、任意 URL 與未授權參數。

## 8. Dry-run 硬性規則

收到 `dry_run: true` 時：

- 不得取得 instrument lock。
- 不得連線或修改儀器狀態。
- 不得啟動 iperf process。
- 不得產生正式測試 Excel。
- 不得呼叫 KM ingest API。
- 只能驗證認證、schema、profile、policy、queue 決策與 correlation。
- 回傳內容必須清楚標記 dry-run，且不可宣稱已完成真實測試。

在 KM 主 Agent 核准前，A2A Server 必須維持 dry-run-only feature flag；不得開放真實 profile。

## 9. Task Lifecycle

至少支援以下狀態或可明確映射到 A2A 1.x 標準狀態：

| 狀態 | 語意 |
| --- | --- |
| `submitted` | 已收到並建立 task |
| `queued` | 已接受，但尚未取得 instrument lock |
| `working` | 已取得 lock，正在執行 |
| `completed` | A2A 工作已到終態；不代表 ingest 一定完成 |
| `rejected` | 因 policy、busy 或 capacity 拒絕 |
| `failed` | 執行失敗並保留 error code |
| `canceled` | 已完成取消與 cleanup |

穩定 rejection reason 至少包含：

```text
busy
policy_denied
capacity_exceeded
profile_not_allowed
invalid_request
agent_offline
```

KM 可以隨時提交任務，但 Anritsu Agent 可以依 policy 選擇排隊或拒絕。`accepted` 不等於已取得儀器，也不等於已開始測試。

## 10. 儀器 Exclusive Lock

- 同一台儀器預設最大 concurrency 為 1。
- 人工測試與 A2A 測試必須共用同一個 lock mechanism。
- lock 至少保存 `owner`、`a2a_task_id`、`run_id`、TTL、heartbeat、acquired_at。
- 第二個 task 不得操作已被占用的儀器，只能 queued 或 rejected。
- timeout、cancel、exception、process crash 都必須執行 cleanup。
- cleanup 必須停止 iperf child process，並使儀器回到已知 safe state。
- task 不得釋放不屬於自己的 lock。
- Agent 重啟後必須辨識 stale lock 並依明確 policy reconcile，不得直接假設可用。

## 11. Correlation 與冪等

每個 task 必須持久保存：

```text
context_id
a2a_task_id
run_id
ingest_task_id
file_hash
```

規則：

- `context_id` 與 `a2a_task_id` 由 A2A lifecycle 建立。
- `run_id` 必須沿用 KM job payload。
- 完成 Excel 上傳後才取得並保存 `ingest_task_id`。
- Excel 關閉並完成 atomic rename 後才計算 `file_hash`。
- 相同 environment + run_id + 相同 job 重新提交時，回傳原 task，不得重跑儀器。
- 相同 environment + run_id 但 job 不同時，回傳 conflict。
- upload／ingest retry 必須沿用相同 run_id/idempotency，不得重新執行實體測試。

## 12. 三種狀態必須分離

不得只使用一個 `completed` 表示全部成功。至少保存：

```json
{
  "test_status": "pending|running|completed|failed",
  "report_status": "pending|running|completed|failed",
  "ingest_status": "pending|running|completed|failed"
}
```

範例：

- 測試成功但 Excel 產生失敗：`test=completed, report=failed, ingest=pending`
- Excel 上傳成功但 KB 攝入失敗：`test=completed, report=completed, ingest=failed`
- A2A dry-run 完成：三種狀態仍不得宣稱真實完成

## 13. Excel 與既有 KM Ingest

真實測試階段才執行：

1. 每個 `run_id` 使用獨立工作目錄。
2. 先寫 temporary file。
3. 關閉 workbook 並確認可重新開啟。
4. atomic rename 成正式 `.xlsx`。
5. 計算 SHA-256。
6. 沿用既有 uploader／MCP tool 呼叫 KM strict ingest API。
7. 保存 KM 回傳的 `ingest_task_id`。
8. 輪詢 ingest 狀態直到 completed／failed／timeout。

不得把 Excel 二進位內容放進 A2A JSON-RPC message。A2A 只回傳 report metadata、hash、ingest task ID 與狀態。

## 14. Task Journal、重啟恢復與 Audit

使用 SQLite 或等價的本機持久化方式保存：

- timestamp
- caller／requested_by
- profile_id
- job schema version
- 四個 correlation IDs
- file_hash
- A2A task state
- test/report/ingest status
- rejection reason
- error code；不得包含 secret
- instrument lock owner 與 heartbeat
- retry、cancel、cleanup、upload、ingest 事件

Agent／Windows service 重啟後：

- 不得遺失已接受 task。
- `working` task 必須依 journal 與實際 process／instrument 狀態 reconcile。
- 不得把不確定狀態直接改為 completed。
- stale task 必須明確轉 failed、queued 或 requires-review。

## 15. Health 與監控

提供不洩漏秘密的 health 資訊，至少包含：

- agent name/version
- A2A protocol version
- job schema versions
- supported profile IDs 或安全摘要
- mode：mock／dry-run／real
- service status
- instrument availability／busy，但不得公開密碼或完整內部設定
- journal status
- 最後 heartbeat

## 16. 分階段實作順序

### Phase A：Mock Server

- Agent Card 可取得。
- A2A JSON-RPC 可接收固定 job。
- 回傳 Task、context/task IDs。
- 驗證認證、rejection reason 與 journal。
- 不呼叫既有儀器程式。

### Phase B：Dry-run Adapter

- 接到既有 adapter 邊界，但 `dry_run=true` 時不能取得 lock 或控制儀器。
- 驗證 profile、policy、queue/reject、timeout/cancel。
- 完成 KM 到 Anritsu 跨電腦 dry-run。

### Phase C：單一真實 Profile

- 只有 KM 主 Agent 書面核准後才可開啟。
- 只開一個低風險 allowlisted profile。
- 驗證 instrument lock、iperf、Excel、既有 ingest 與 rollback。

不得跳過 Mock／Dry-run 直接開放真實儀器。

## 17. Anritsu Agent 必須交付的檔案與資訊

- [ ] 原始碼與 dependency lock
- [ ] A2A server 啟動／停止／rollback 指令
- [ ] Agent Card 範例，不含秘密
- [ ] HTTPS discovery base URL
- [ ] A2A interface URL
- [ ] A2A protocol 與 SDK version
- [ ] Job JSON Schema
- [ ] Profile registry 與各參數範圍
- [ ] A2A security scheme／scope 說明
- [ ] 專用 A2A credential 的安全交換方式；不得寫入文件
- [ ] Task state／rejection reason mapping
- [ ] SQLite schema 或 task journal 說明
- [ ] Instrument lock／TTL／heartbeat／cleanup 設計
- [ ] Mock 與 dry-run 測試結果
- [ ] 重複 request、timeout、cancel、重啟恢復測試結果
- [ ] 手動測試回歸結果
- [ ] A2A feature flag 關閉與 one-command rollback 證據

## 18. KM 接受跨電腦 Dry-run 的驗收條件

- [ ] Agent Card 透過 HTTPS 取得，且 interface 同 origin
- [ ] Agent Card 宣告 A2A 1.x JSON-RPC 與 `run_iperf_test`
- [ ] KM Bearer credential 驗證成功，錯誤 credential 被拒絕
- [ ] `dry_run=true` 時無 instrument lock、無 SCPI、無 iperf process
- [ ] 固定 allowlisted profile 可接受
- [ ] 未註冊 profile／任意 command／非法 duration 被拒絕
- [ ] busy 情境可 queued 或回穩定 rejection reason
- [ ] 四個 correlation IDs 可追蹤
- [ ] 三種業務狀態分離
- [ ] 相同 job 重送不產生第二個實體 task
- [ ] Agent 重啟後 task journal 可恢復
- [ ] 停止 A2A sidecar 後原本手動測試仍正常
- [ ] A2A 故障不影響既有 KM chat、search、ingest 與資料庫

## 19. 禁止進入真實儀器階段的情況

以下任一項成立時必須停止，不得自行擴大範圍：

- Agent Card／job schema 尚未定版
- credential 尚未分離或可能出現在 log
- dry-run 仍可能取得 instrument lock
- 人工與 A2A 沒有共用 exclusive lock
- 不具備 timeout／cancel／cleanup
- 重試可能重跑實體測試
- test/report/ingest status 尚未分離
- 沒有 one-command rollback
- 原本手動測試回歸失敗
- KM 主 Agent 尚未核准單一真實 profile

遇到上述情況，Anritsu Agent 應停止並回報：已完成項目、證據、阻塞原因、待 KM 決定事項與已知風險，不得自行開啟真實儀器控制。
