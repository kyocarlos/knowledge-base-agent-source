# R0 Real-run Contract 與放行 Gate

日期：2026-08-13  
範圍：KM OpenClaw、KM A2A bridge、Anritsu A2A ingress 與 Anritsu OpenClaw 之間的真實儀器測試開放前規格。

## 1. R0 決策

R0 的目標是先完成 contract、威脅模型、責任邊界、人工批准與放行條件；R0 不包含 real transport 實作，也不會修改目前的 dry-run 保護。

目前決策：`NO-GO`

```text
KM_A2A_ENABLED=true
KM_A2A_TRANSPORT=sdk-dry-run
real_instrument_access=false
Anritsu mode=dry-run
Anritsu instrument_available=false
```

因此本文件的「規格完成」不等於「真實測試已可執行」。任何 R0 Gate 未通過時，`dry_run=false` 必須被拒絕。

## 2. 目標邊界

```text
KM OpenClaw
  -> localhost-only KM A2A bridge
  -> allowlisted Anritsu A2A ingress
  -> Anritsu OpenClaw receiver
  -> allowlisted local instrument skill
  -> instrument / iPerf
  -> Excel artifact
  -> authenticated KM report ingest
```

禁止的路徑：

- KM OpenClaw 直接呼叫 Windows shell、SCPI、iPerf、儀器 API 或資料庫。
- LLM 產生任意命令、任意 URL、任意檔案路徑或任意 profile。
- 外部 agent 直接連 Neo4j、Qdrant、Redis 或 KM 內部資料庫。
- 由自然語言、query string 或遠端 payload 將 dry-run 切換成 real-run。
- 以現有 KM ingest token 代替 A2A 控制權限。

## 3. Real-run request contract（規格草案）

Real-run 必須使用獨立 schema，不得把現有 `TestJob` 的 `dry_run: Literal[True]` 改成可任意切換的 boolean。

必要欄位：

| 欄位 | 要求 |
|---|---|
| `job_schema_version` | 固定版本，變更需相容性審查 |
| `job_type` | 只允許 `run_iperf_test` |
| `environment` | 只允許 `anritsu` |
| `profile_id` | 只允許已核准 profile |
| `test_cases` | 只允許已核准 test case，單次最多一項 |
| `run_id` | 呼叫端產生且全鏈路唯一，不可重用 |
| `requested_by` | 綁定 KM session、操作者與來源 agent |
| `approval_id` | 短效、single-use、不可由模型產生 |
| `approval_expires_at` | 必須晚於現在且不可超過政策上限 |
| `duration_seconds` | 有上下限，超時自動進入 cancel/safe-state |
| `dry_run` | real contract 固定為 `false`，不可由自然語言覆蓋 |
| `artifact_policy` | 指定檔案格式、hash、保存位置與 ingest policy |

拒絕條件：schema 額外欄位、未知 profile/test case、重複 run_id、過期或重用 approval、操作者不符、已有 active lock、超時上限、非 Anritsu environment、任意 command/path/url 欄位。

## 4. 回應與狀態契約

Real-run 回應必須保存：

- `run_id`
- `context_id`
- `a2a_task_id`
- `approval_id`
- `instrument_lock_id`
- `execution_owner=anritsu-openclaw`
- `test_status`
- `report_status`
- `ingest_status`
- `artifact_sha256`
- `ingest_task_id`
- `audit_id`

允許的狀態轉移：

```text
submitted -> approved -> queued -> running -> collecting -> ingesting -> completed
                         |          |         |             |
                         +--------> canceled  +-----------> failed
```

`completed` 不得只代表 A2A message 被接受；必須同時有真實測試、artifact hash、結果驗證及 ingest correlation 證據。

## 5. 人工批准規格

人工批准必須由受控 KM API 或管理流程產生，不能由 OpenClaw 自己批准。現階段採單一授權操作者批准，不要求雙人批准；批准內容至少包含：

- `approval_id`、授權操作者 ID
- profile、test case、duration、environment
- 目的與變更理由
- 建立時間、到期時間、single-use 狀態
- 授權操作者的 audit record

放行政策：

1. 每次 real-run 必須由一名已授權操作者明確批准；批准權不得由模型或 Anritsu agent 自行產生。
2. approval 只適用於一個 `run_id`、一個 profile、一個 test case。
3. 未使用的 approval 到期即失效；執行失敗不得自動重用。
4. 任何 contract、profile、instrument capability 變更都必須重新批准。

## 6. 威脅模型與控制措施

| 威脅 | 控制措施 | R0 驗收證據 |
|---|---|---|
| LLM 產生任意儀器命令 | 固定 schema、allowlist、extra fields 拒絕 | contract negative tests |
| 重放或重複執行 | single-use approval、run_id registry、idempotency | replay test |
| 同時操作儀器 | single-flight lease、owner verification | lock contention test |
| agent 被冒用 | per-agent credential、scope、operator binding | auth/scope test |
| timeout 後儀器仍運轉 | cancel、safe-state、cleanup watchdog | failure injection test |
| 結果被替換 | server-side hash、artifact binding、immutable audit | hash mismatch test |
| ingest 重複或衝突 | idempotency/conflict policy、outbox/retry | duplicate/conflict test |
| 機密進入 log | secret redaction、payload allowlist | log scan |
| 傳輸被攔截 | 正式 HTTPS/mTLS 或安全審查核准 | TLS/auth evidence |
| KM 或 Anritsu crash | lease expiry、recovery、rollback | crash recovery drill |

## 7. R0 放行 Gate

R0 必須逐項有證據；沒有證據不得標示 PASS。

| Gate | 放行條件 | 目前狀態 |
|---|---|---|
| R0-01 Contract | real schema、狀態、拒絕條件完成審查 | PARTIAL：獨立 schema 已實作並通過單元測試，runtime 尚未整合 |
| R0-02 Scope | profile/test case/environment allowlist 明確 | PARTIAL，dry-run 已有；real 尚未驗證 |
| R0-03 Approval | single-use、短效、單一授權操作者與 audit contract | BLOCKED |
| R0-04 Lock | lease、續租、owner、crash recovery | BLOCKED |
| R0-05 Safety | timeout、cancel、safe-state、cleanup | BLOCKED |
| R0-06 Artifact | Excel、hash、run/task correlation | BLOCKED |
| R0-07 Ingest | idempotency、conflict、retry、告警 | BLOCKED |
| R0-08 Audit | real-run audit、secret redaction、告警 | BLOCKED |
| R0-09 Transport | real transport 與正式傳輸安全 | BLOCKED |
| R0-10 Capability | Anritsu `instrument_available=true` 與 real mode 證據 | BLOCKED |
| R0-11 Recovery | rollback/emergency stop 實際演練 | BLOCKED |
| R0-12 Shadow | 真實儀器前單一授權操作者批准的 shadow 證據 | BLOCKED |

R0 結論：`NO-GO`。目前只能進入 R1 開發，不得進入 R3 real test。

## 8. R0 後續工作順序

1. 由 KM 與 Anritsu 共同審查本文件及 real schema。
2. 實作獨立 R1 mock real transport、lock、approval、cancel 與 artifact schema。
3. 以 failure injection 驗證 timeout、crash recovery、safe-state 與 rollback。
4. 由 Anritsu 提供 instrument capability、real mode 與本機 OpenClaw adapter 證據。
5. 完成 shadow run，確認不接觸正式儀器結果與不攝入正式資料。
6. 只有主管明確批准後，才建立單一 real-run approval 並執行一個 test case。

## 9. 回滾

任何 R0/R1 開發異常時：

```text
停止 real service
-> KM_A2A_ENABLED=false 或 real_instrument_access=false
-> 保留並啟動目前 sdk-dry-run bridge
-> 保存 audit、task、error 與 recovery 證據
-> 不修改 Portal、chat、search、report upload、ingest、Neo4j 或 Qdrant
```

此文件不授權真實測試，也不取代主管批准、Anritsu 端安全審查或正式變更流程。
