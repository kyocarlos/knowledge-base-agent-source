# WP1 Evidence — Docker／Redis／Celery／Config 正式化

本週證據截止：2026-08-11 16:42 Asia/Taipei

| 類別 | 得分／權重 | 證據與限制 |
|---|---:|---|
| 規格與 Contract | 15/15 | v2.6 Excel「Docker／Redis／Celery／環境設定」由 Anderson 主實作；typed config、Job status、queue／retry／timeout／idempotency contract。 |
| 程式實作 | 35/35 | 原 WP1 `2a4ba2af`～`cfe5eb0d`；live integration 加入 scheduler、secret boundary、search trace fix 與 rollback tooling。 |
| 測試 | 25/25 | rollout 分支 pytest `90 passed`；queue/retry/non-retry、trace、idempotency、worker contract、Compose 與 credential scan 通過。 |
| E2E／驗收 | 15/15 | 隔離 worker restart／Redis persistence／ingest idempotency、shadow rollback、candidate search、一次 production rollback、修正後再部署與真實 maintenance checkpoint dry-run均通過。 |
| PR／合併／文件／回滾 | 6/10 | backup／rollback script、操作規格、部署紀錄與 GitHub rollout branch 已交付；仍無 rollout PR review／merge。 |

總分：**96/100**。真實故障與回退 Gate 已演練，但 PR／Review／Merge Gate 尚未關閉，不得宣稱 100%。

## 本週新增證據

- 兩份約 9.6 GB checkpoint 已建立並完成 SHA、archive、PostgreSQL、SQLite、Neo4j 與 Qdrant 可讀性檢查。
- Shadow drill：baseline 200 → injected 503 → rollback 200，image ID 完全恢復。
- 第一次 production cutover 的 `/search` 500 觸發真實 Level 1 rollback，五個 application image ID 恢復且資料 volumes 未重建。
- 修正 FastAPI HTTP Request trace propagation，加入 regression test；第二次 candidate 與 production cutover 通過。
- Web、search worker、ingest worker、Beat 使用相同 application image ID；兩個 Celery nodes pong，Beat scheduler 持續派送。
- Application rollback 保留 `--execute` 與 production confirmation 雙重保護；dry-run 不需確認碼且已由測試固定。

## 截止後 CI

- rollout commit `dce63ae6` 的 WP1 run `31475084385`：backend 與 frontend 成功。
- repository-hygiene 在 `actions/checkout@v4` 階段因 GitHub runner TLS CA 驗證失敗而未執行；annotation 為 `server certificate verification failed`／git exit 128，不是 whitespace 或 credential scan 失敗。需以後續重跑結果關閉 CI Gate。

## v2.6 歸類

- `A`：typed config、queue routing、canonical status、trace、retry、idempotency、worker restart／health、backup／application rollback 可直接保留。
- `B`：舊 Phase 0 命名改列 Phase 1 前置；CSIT 正式狀態不得移入本地 Job status。
- `C`：缺 rollout PR review／merge，以及原始 shadow／Webwright artifact 的 GitHub 持久化。
- `D`：CSIT Schema、Workflow 與商業狀態由 Patty 提供 Contract，不由 WP1 擴張。
