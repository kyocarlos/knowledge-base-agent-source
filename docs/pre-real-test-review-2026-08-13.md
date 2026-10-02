# Anritsu 真實測試開放前審查

日期：2026-08-13  
審查範圍：KM A2A bridge、Anritsu Docker userspace POC、真實儀器測試前 Gate

## 結論

目前結論為 **NO-GO**。跨機網路、認證、Agent Card 與 dry-run 委派已通過，
但目前系統仍明確禁止真實儀器操作：

```text
KM_A2A_ENABLED=true
KM_A2A_TRANSPORT=sdk-dry-run
real_instrument_access=false
Anritsu mode=dry-run
instrument_available=false
```

本次審查沒有送出真實測試請求，也沒有修改真機開關。

## 已通過項目

| Gate | 證據 | 狀態 |
| --- | --- | --- |
| Tailscale peer | `100.72.21.115` 可見 | PASS |
| Tailscale connectivity | `tailscale ping` 經 DERP(hkg)成功 | PASS |
| Anritsu health | `/health=200`、`/healthz=200` | PASS |
| Agent Card | JSONRPC 1.0、`run_iperf_test`、same-origin `/a2a` | PASS |
| Method protection | GET `/a2a=405`、Allow=POST | PASS |
| Authentication | 無 token=401、錯 token=403 | PASS |
| Correct Bearer dry-run | Task completed、correlation完整 | PASS |
| Side-effect protection | 7項 counters 全為 0 | PASS |
| KM bridge tests | 61 passed | PASS |

## 阻塞項目

| 項目 | 實際證據 | 判定 |
| --- | --- | --- |
| Real transport | `BridgeConfig`只接受`mock`或`sdk-dry-run` | BLOCKED |
| Real job contract | `TestJob.dry_run`固定為`Literal[True]` | BLOCKED |
| Anritsu instrument capability | `/health`為`instrument_available=false`、`mode=dry-run` | BLOCKED |
| Instrument lock | 目前只驗證 dry-run counter，沒有 real lock lease | BLOCKED |
| Human approval | 未有 real-run approval token／expiry／operator audit contract | BLOCKED |
| Timeout/cancel | 未完成真實儀器 cancel、timeout、safe-state 流程驗證 | BLOCKED |
| Result artifact | 尚未證明真實 Excel、hash、artifact binding與KM ingest correlation | BLOCKED |
| Audit and recovery | 尚未完成 real-run audit、告警、crash recovery與回滾演練 | BLOCKED |
| Transport security | 目前為受控 Tailscale HTTP POC，非正式 HTTPS | BLOCKED |

## 必須完成的放行條件

1. 新增與 dry-run 完全分離的 real transport，不得由自然語言或任意欄位切換。
2. 增加明確的 real-run feature flag、operator approval、短效 approval token 與過期機制。
3. Anritsu 回報真實 mode、instrument capability、可用 profile 與實際 lock 狀態。
4. 實作 single-flight instrument lock，含 lease、renew、owner verification 與 crash recovery。
5. 實作 timeout、cancel、safe-state、cleanup，並以硬體前 shadow／mock 流程驗證。
6. 僅允許固定 profile/test case schema；禁止傳送 shell、SCPI、任意路徑或任意 URL。
7. 完成真實 Excel artifact、SHA-256、run_id、a2a_task_id、ingest_task_id 的關聯契約。
8. 完成 result upload 與 KM ingest 的 idempotency、conflict、retry、失敗告警測試。
9. 完成 real-run audit log，禁止 token、儀器秘密與敏感 payload 進入 log。
10. 完成正式 HTTPS／憑證驗證，或由安全審查明確核准目前 POC 傳輸範圍。
11. 在真實儀器前完成單一授權操作者批准的 shadow run，且七項副作用計數與 cleanup 證據完整。
12. 建立 real-run rollback／emergency stop 操作手冊並實際演練。

## 建議分階段

| 階段 | 內容 | 放行結果 |
| --- | --- | --- |
| R0 | real contract、威脅模型、責任與批准流程 | 可進入開發 |
| R1 | mock real transport、lock、cancel、artifact schema | 可進 shadow |
| R2 | Anritsu shadow mode，不接儀器、不產正式結果 | 可進受控 pilot |
| R3 | 單一人工批准 real test，限制一個 profile／一個 test case | 由主管核准 |
| R4 | 真實結果上傳、KM ingest、回滾與稽核驗收 | 才可擴大使用 |

## 回滾原則

在任何 real-run 開發期間，保持目前 `sdk-dry-run` 版本可啟動；real transport
必須使用獨立設定與獨立 service。發生異常時只需停用 real service、恢復
`KM_A2A_ENABLED=false` 或 `real_instrument_access=false`，不得修改既有 KM
chat、search、report upload、ingest 或主資料庫。
