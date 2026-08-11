# WP0／WP1 正式導入與回滾演練紀錄

日期：2026-08-11（Asia/Taipei）

## 基準與 checkpoint

- 導入前 source：`dev-work` / `3f15d87bc1e275e6faaf69378afa70d7d785ad6c`
- 線上 checkpoint：`$HOME/kb-pre-wp01-backups/pre-wp01-20260811-153917`
- Maintenance checkpoint：`$HOME/kb-pre-wp01-backups/pre-wp01-maintenance-20260811-155643`
- 每份 checkpoint 約 9.6 GB，包含精確 application images、source/config/data、Neo4j logical export、Qdrant snapshots、PostgreSQL dump、Redis archive 與 SQLite consistent copy。
- Maintenance checkpoint 在 web、nginx、workers、Beat 停止且 queues/active/reserved/scheduled 均為 0 時建立。

## 回滾機制演練

證據：`$HOME/kb-pre-wp01-drills/20260811_154229/rollback-drill.json`

1. Baseline endpoint：HTTP 200，marker=`pre-wp01-baseline`。
2. 注入失敗候選：HTTP 503，marker=`wp01-candidate-failed`。
3. 執行正式 rollback script 相同路徑。
4. 回退後：HTTP 200、baseline marker 恢復、image ID 與 checkpoint 相同。
5. Shadow container、network、volume 全部清理。

## Candidate shadow Gate

- 第一次 candidate API/dependency drill 通過，但未涵蓋實際 `/search` POST。
- 第一次正式切換後，production search smoke 發現 Pydantic `SearchRequest` 被錯當 HTTP Request 讀取 headers，`/search` 回 HTTP 500。
- 立即使用 maintenance checkpoint 執行 production application rollback；web、兩個 workers、Beat、nginx 五個 image ID 全部恢復，legacy `/health`=200、`/search`=200。
- 修正 HTTP Request 注入並新增 trace propagation regression test；完整測試 `89 passed`。
- Candidate Gate 增加 `/search` POST 與 X-Trace-ID 驗證。
- 第二次 candidate 證據：`$HOME/kb-pre-wp01-drills/candidate-20260811_160158/candidate-drill.json`，API/search、web、search worker、ingest worker、Beat 全部通過。

## 正式切換驗收

- Source：`dev-work` 已 fast-forward 至 WP0／WP1 live integration；原 dirty config、memory、pyc 與 data assets 均保留。
- Application image ID：`sha256:ac3c29b8f25f1427e1bcfe24e5d712fd6e4cc2d6a8d387eeaeb4113991338389`。
- Legacy `/health`：200，response shape 不變。
- `/api/v1/health`、`live`、`ready`、`version`：200，包含 trace envelope。
- 未提供 Agent headers 的 `/api/agent/v1/health`：維持 401 與原錯誤內容。
- Production `/search`：200 submitted，背景任務 completed。
- Celery inspect：search 與 ingest workers 兩個 nodes online。
- Celery Beat：running，scheduler started。
- Webwright：正式 `chat.html` 顯示已連線，輸入與送出可用，取得非空 final reply，console/network errors=0。
- Webwright 證據：`/tmp/kb-wp01-webwright/final_runs/run_1/`。

## Application rollback

```bash
python3 scripts/rollback_pre_wp01.py \
  --checkpoint "$HOME/kb-pre-wp01-backups/pre-wp01-maintenance-20260811-155643" \
  --execute \
  --confirm-production PRE_WP01_ROLLBACK
```

Level 2 data restore 仍需 maintenance 與人工雙重確認，不由 application rollback script 自動執行。

## GitHub 同步摘要

- 同步分支：`agent/wp01-production-rollout`。
- 基準：`agent/wp0-wp1-v2.6-acceptance` / `d39f9f790eb0cd0ebaf4a992b2664bd1d8b3143e`，保留 PR #5 的 WP0／WP1 與 v2.6 驗收歷史。
- 同步內容：pre-WP01 backup／rollback scripts、shadow rollback 與 candidate gate、正式環境相容性修正、`/search` trace regression、範例 deployment env，以及本文件。
- 分支驗證：pytest `90 passed`、frontend production build、Python compile、Compose config、shell syntax、whitespace 與 credential scan 全部通過；maintenance checkpoint dry-run 驗證成功。
- 未同步內容：checkpoint archives、database dumps、Qdrant snapshots、application image tar、正式 `.env`、token、密碼及其他 runtime secrets。這些只保存在權限受控的部署主機。
- 本分支只建立審查用 Draft PR，不直接合併 `main` 或規劃分支；正式環境已部署的 image 與 checkpoint 不因 GitHub push 被重建或變更。
