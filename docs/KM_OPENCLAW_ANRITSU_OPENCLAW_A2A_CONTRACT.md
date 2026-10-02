# KM OpenClaw 到 Anritsu OpenClaw A2A 契約

## 目的

KM OpenClaw 是中心 agent。使用者在 KM OpenClaw 下達固定範圍的測試命令後，KM 透過本機 `km-a2a-bridge` 將命令交給 Anritsu agent。Anritsu agent 再透過本機工具/MCP 控制測試儀器、iperf、Excel 產生與 KB 攝入。

## 目前實際狀態

目前已驗證的路徑是：

```text
KM OpenClaw skill
  -> scripts/km_anritsu_command.py
  -> 127.0.0.1:18181 km-a2a-bridge
  -> Tailscale 100.72.21.115:8790 Anritsu A2A sidecar
```

目前 `:8790` 是 sidecar，不是已被證實的 Anritsu OpenClaw Gateway。現有跨機測試是 A2A bridge-to-sidecar dry-run，不能宣稱已完成 OpenClaw-to-OpenClaw 或真實儀器測試。

## 目標狀態

```text
使用者
  -> KM OpenClaw
  -> 受控 A2A skill / localhost bridge
  -> Anritsu A2A ingress
  -> Anritsu OpenClaw
  -> Anritsu 本機 MCP / instrument adapter
  -> iperf + Excel
  -> KM ingest API
```

Anritsu A2A ingress 可以是 OpenClaw 的受控 tool/skill adapter，不要求把 OpenClaw Gateway 直接暴露到 Tailscale。`:8790` 應維持網路驗證與 allowlist 邊界；由 sidecar 在本機轉交給 Anritsu OpenClaw，或由 Anritsu OpenClaw 明確接管相同的固定 schema。

### Anritsu 端必要實作

Anritsu 必須提供只綁 loopback 或 named pipe 的 adapter。其位置以 `ANRITSU_OPENCLAW_ADAPTER_URL` 與受保護 token file 設定，不由 KM 猜測。sidecar 將已驗證的固定 `run_iperf_test` schema 轉交 adapter，adapter 再呼叫 Anritsu OpenClaw 的 allowlisted skill/tool。Adapter 回應必須帶回 `run_id`、`context_id`、`a2a_task_id`、`execution_owner=anritsu-openclaw` 與 dry-run 狀態。

## 命令契約

KM 只可送出固定 schema `job_schema_version=1.0`、`job_type=run_iperf_test`、`environment=anritsu`、allowlisted `profile_id` 與 `sa_dl_tcp`/`sa_ul_tcp`。`dry_run` 在目前階段固定為 `true`，不可由自然語言或遠端參數改成 false。

每次命令必須保留：

- `run_id`
- A2A `context_id`
- A2A `task_id`
- KM bridge journal task key
- 操作者/來源 session identifier
- 後續 report、Excel hash、ingest task id

## OpenClaw 邊界

- KM OpenClaw 不得直接呼叫 Anritsu 儀器、iperf、Windows shell 或資料庫。
- KM OpenClaw 不得自行組合任意 JSON-RPC 方法或 URL；只能呼叫本機受控 client。
- Anritsu OpenClaw 不得接受任意命令字串；只能把固定 profile/test case 映射到預先核准的本機工具流程。
- 真實儀器操作必須另有人工批准、instrument lock、timeout/cancel、safe-state、artifact hash、KB ingest correlation 與 audit evidence。

## 驗收階段

1. KM OpenClaw skill 能提交 dry-run，bridge journal 有紀錄。
2. Anritsu sidecar 回傳 Agent Card、401/403、固定 schema dry-run，七項副作用計數為 0。
3. Anritsu OpenClaw adapter 能接收相同固定 schema，且能在本機留下 correlation/audit log。
4. 兩端 OpenClaw log 能以 `run_id`、`context_id`、`a2a_task_id` 對查。
5. 完成真實測試前審查後，才可另行批准移除 dry-run 限制。

第 3、4 項未通過前，KM 的成功只代表 sidecar dry-run，不代表 Anritsu OpenClaw 已實際接收或執行命令。

## 回滾

移除或停用 KM workspace 的此 skill、將 `KM_A2A_ENABLED=false`，並停止 `km-a2a-bridge.service` 即可回到既有 KM OpenClaw 與 KB 流程；不修改 Portal、chat、search、report upload 或 ingest API。
