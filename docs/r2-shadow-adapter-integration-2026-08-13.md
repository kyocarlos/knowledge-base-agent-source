# R2 Shadow Adapter Integration 紀錄

日期：2026-08-13  
範圍：KM R1 contract 與 Anritsu OpenClaw 本機受控 adapter 邊界的本機 shadow 驗證。

## 本次實作

新增 `km_a2a_bridge/anritsu_shadow_adapter.py`：

- `ShadowAdapterRequest`：固定 adapter schema 1.0。
- `ShadowAdapterResponse`：固定 owner、correlation、capability 與 side-effect evidence。
- `ShadowSideEffectCounts`：七項副作用均固定為 0。
- `MockAnritsuOpenClawAdapter`：只在本機記憶體執行，不連線、不啟動 process、不接觸儀器。

## Shadow request 邊界

只接受：

- `dry_run=true`
- `environment=anritsu`
- `profile_id=ncq2200b2v-throughput-v1`
- `sa_dl_tcp` 或 `sa_ul_tcp`
- 最多兩個不重複 test case
- `run_id`、`context_id`、`a2a_task_id`

拒絕：

- `dry_run=false`
- extra fields、shell command、路徑、URL
- 未知 profile 或 test case
- 重複 test case

## 驗收證據

```text
PYTHONPATH=. uv run --with a2a-sdk==1.1.2 --with pytest \
  pytest -q tests/test_km_a2a_real_contracts.py \
  tests/test_km_a2a_mock_real_runtime.py \
  tests/test_km_a2a_real_registry.py \
  tests/test_km_a2a_safety_lifecycle.py \
  tests/test_km_a2a_anritsu_shadow_adapter.py

30 passed
```

已驗證：

1. 三個 correlation 在 adapter response 中保持一致。
2. `execution_owner=anritsu-openclaw`。
3. `instrument_available=false` 與 `real_instrument_access=false`。
4. 七項副作用計數均為 0。
5. `dry_run=false` 與未授權欄位會被拒絕。
6. cancel response 仍不取得 lock、不操作儀器。

## 目前 Gate

本次只證明 KM 端可以依固定 schema 驗證一個本機 shadow adapter；沒有證明 Anritsu Windows 已安裝或啟動此 adapter。

```text
R1 contract/mock/registry/safety：PASS
R2 KM-local shadow adapter contract：PASS
R2 cross-machine Anritsu shadow：NO-GO
R3 real instrument：NO-GO
```

Anritsu 端仍需交付：adapter source/version、loopback 或 named-pipe 綁定證據、實際 sidecar-to-adapter dry-run log、三個 correlation 對查結果，以及原有手動測試/MCP/Excel/uploader 回歸結果。
