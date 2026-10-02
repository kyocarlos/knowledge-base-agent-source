# R1 Mock Real Transport 與安全控制紀錄

日期：2026-08-13  
範圍：獨立 real-run contract 的 mock-only lifecycle 驗證。

## 實作內容

新增 `km_a2a_bridge/mock_real_runtime.py`，提供不連網、不啟動 process、不接觸儀器、不寫入 KM ingest 的記憶體控制器：

- single-use approval consumption
- profile 與 test case allowlist
- single-flight instrument lock 模擬
- lock lease expiry 與下一個任務 recovery
- operator cancel
- duration timeout，狀態進入 `canceled` 並釋放 lock
- 非空 artifact 與最大大小檢查
- artifact SHA-256 產生
- `run_id`、`context_id`、`a2a_task_id`、approval、lock、audit、artifact、ingest correlation

另新增 `km_a2a_bridge/real_registry.py`，以獨立 SQLite registry 提供：

- approval register 與 atomic single-use consume
- approval binding、expiry 與重啟後持續存在
- instrument resource single-flight lock
- lock lease、owner verification、renew、release
- expired lock 清理後允許下一個 run 取得資源

另新增 `km_a2a_bridge/safety_lifecycle.py`，定義 adapter 必須提供的安全生命週期：

```text
cancel request -> ensure safe-state -> cleanup
```

當 cancel 本身失敗時仍會繼續嘗試 safe-state 與 cleanup；任何安全動作無法確認時，結果為 `recovery_required`。Worker crash recovery 不重試原命令，而是直接執行 safe-state 與 cleanup。

## 明確不包含

- 不接入 `app.py`、`service.py`、既有 transport 或 OpenClaw skill。
- 不提供 HTTP endpoint。
- 不產生或消費真實 approval token。
- 不控制 Anritsu、iPerf、SCPI 或 Windows process。
- 不執行 Excel 實際產生或 KM ingest。
- 不改變 `KM_A2A_TRANSPORT=sdk-dry-run`、`real_instrument_access=false`。

## 驗證證據

```text
PYTHONPATH=. uv run --with a2a-sdk==1.1.2 --with pytest \
  pytest -q tests/test_km_a2a_real_contracts.py \
  tests/test_km_a2a_mock_real_runtime.py

24 passed
```

測試涵蓋：

1. approval 只可使用一次。
2. lock 只允許 single-flight。
3. cancel 會釋放 lock。
4. timeout 會進入 canceled 並允許後續新任務取得 lock。
5. 過期 lock 可在下一次 submit 前回收。
6. artifact 會產生 SHA-256；空 artifact 不得完成。
7. real response 完成時必須有 artifact hash 與 ingest task ID。
8. registry 重啟後仍能拒絕重用 approval。
9. lock 只能由 owner renew/release，且同一 resource 不可並行取得。
10. cancel、safe-state、cleanup 的呼叫順序固定且可重複查詢。
11. cancel、safe-state 或 cleanup failure 會產生 `recovery_required`，不會假報成功。
12. crash recovery 不重試測試命令，只執行 safe-state 與 cleanup。

## R1 Gate

目前只完成 R1 的 mock lifecycle proof。要進入 R2 shadow 前，仍需補：

- 持久化的 approval single-use registry
- real service 使用 registry 的 lock lease／renew／owner verification
- 將 cancel/safe-state/cleanup adapter 接到 Anritsu 本機受控 adapter
- failure injection 的 service restart/crash recovery
- artifact upload、hash binding 與 ingest outbox contract
- real-run audit redaction 與告警

因此目前結論仍為：`R1 mock PASS，R2 shadow NO-GO`。

本次新增的 KM-local shadow adapter contract 與測試記錄於
[`docs/r2-shadow-adapter-integration-2026-08-13.md`](r2-shadow-adapter-integration-2026-08-13.md)。
這不代表 Anritsu Windows 端已完成 adapter 部署或跨機 shadow。
