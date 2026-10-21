# Anritsu OpenClaw Receiver 兩天 Dry-run 測試

## 範圍

本測試只驗證 KM OpenClaw / KM A2A bridge 到 Anritsu OpenClaw receiver 的通訊與 correlation。每次請求固定：

- `dry_run=true`
- profile：`ncq2200b2v-throughput-v1`
- test case：`sa_dl_tcp`
- 不取得儀器 lock、不啟動 iperf、不產生正式 Excel、不呼叫 KB ingest

## Gate

每個 sample 必須同時滿足：`TASK_STATE_COMPLETED`、`openclaw_forward_status=accepted`、`openclaw_receiver=anritsu-openclaw`、存在 `openclaw_audit_id`，且 `run_id`、`context_id`、`a2a_task_id` 完整；所有 dry-run side-effect counters 必須為 0。

## 啟動

```bash
cd /home/da40_ai_gb10/knowledge-base
python3 scripts/run_anritsu_openclaw_2day_monitor.py \
  --hours 48 --interval-seconds 1800 \
  --log /home/da40_ai_gb10/.local/state/km-a2a/anritsu-openclaw-2day.jsonl
```

每次 sample 都使用新的 `run_id`，不可重用前次任務。結果只保存於本機 state JSONL，不保存 token。

## 查詢

```bash
tail -n 5 /home/da40_ai_gb10/.local/state/km-a2a/anritsu-openclaw-2day.jsonl
systemctl --user status km-a2a-bridge.service
```

兩天結束後，只有所有 samples 都是 `gate=PASS` 才能判定通訊穩定。任何失敗都必須保留失敗 run、錯誤類型與對應的 KM/Anritsu log，不得以後續成功覆蓋。

## 目前限制

這是 receiver dry-run 穩定性測試，不是實體儀器測試。`instrument_available=false`、`real_instrument_access=false` 必須在整個測試期間維持不變。
