# WP0 受控寫入型 E2E 驗收 Gate

## 目的

本 Gate 將 shadow stack 已驗證的 Report upload、review、ingest、Neo4j／Qdrant 寫入與 cleanup 流程，轉成正式環境可審查的放行條件。它不會自動啟用正式寫入，也不會把 shadow 證據視為 production acceptance。

## 必要條件

1. 使用全新的 v2.6 `test_run_id`，且符合當次非正式環境明確設定的 E2E prefix。
2. Agent、Reviewer、Cleanup 使用三組不同的短效 credential；不得共用正式 token。
3. `KB_E2E_WRITE_MODE_ENABLED`、`KB_E2E_CLEANUP_ENABLED` 與 hash registry 必須由受控部署注入，repository 只保留空值範例。
4. Upload 必須驗證 Excel contract、Manifest、附件 hash、environment 與 idempotency key。
5. Review／Approve 必須產生 ingest task，且 worker 必須到達 `completed`。
6. Neo4j 必須能以 `test_run_id` 查到 scoped TestRun、TestCase、Measurement。
7. Qdrant 必須能以相同 `test_run_id` 查到至少一個 scoped point。
8. Cleanup dry-run 必須先回報所有 scoped records；active task 不得被強制刪除。
9. Cleanup apply 後，Neo4j、Qdrant、Redis task、staging files、submission registry 必須與 dry-run counts 對帳一致。
10. 清理後 submission 查詢必須回 `404`，並保存去識別化 response／log／hash。

## 自動驗證

```bash
python3 scripts/verify_write_e2e_gate.py \
  outputs/wp0-write-e2e-20260819/shadow-write-e2e-fixed-evidence.json
```

Verifier 通過時只輸出 `SHADOW_WRITE_E2E_PASS` 與 `production_ready=false`。它會拒絕 production touched、未完成 ingest、Neo4j／Qdrant count 不一致或 cleanup 未對帳的證據。

## 正式環境仍需人工 Gate

目前正式 KB 不得直接執行寫入型 E2E。正式測試前仍要由 Owner 確認：

- 使用獨立非正式資料庫／collection 或明確可回復的 maintenance window。
- 環境旗標與 credential 只在測試期間短暫啟用。
- 事前 backup／rollback checkpoint 已保存。
- 正式入口 Health／Version、Worker、Redis、Neo4j、Qdrant 均健康。
- 測試完成後立即執行 cleanup，並由第二次只讀查詢確認零殘留。
- 失敗時停在 `NO-GO`，不得以部分成功或人工刪除取代 cleanup evidence。

## 目前狀態

- Shadow write E2E：PASS。
- Neo4j scoped write／cleanup：PASS，`1/1/1`。
- Qdrant scoped write／cleanup：PASS，`4` points。
- 正式環境 write E2E：尚未執行。
- Production acceptance：`NO-GO`。
