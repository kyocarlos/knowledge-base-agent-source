# Pre-WP01 備份與回滾操作規格

本流程在 WP0／WP1 導入真實系統前建立。備份位於 Git repository 之外，包含秘密與正式資料，不得 commit、push 或放入一般共享目錄。

## 安全邊界

- application rollback 只重建 web、Celery workers、Beat 與 nginx，不刪除或重建資料 volumes。
- production rollback 必須同時提供 `--execute` 與 `--confirm-production PRE_WP01_ROLLBACK`。
- Neo4j Community 使用 APOC stream logical export；Qdrant 使用 collection snapshot；PostgreSQL 使用 custom-format `pg_dump`；SQLite 使用 online backup API。
- 一般線上 checkpoint 是各元件一致，不保證跨 Neo4j／Qdrant／registry 的同一 transaction 時點。正式切換前仍須停止 writers 後建立 maintenance checkpoint，Level 2 full restore 才能使用。
- 腳本不自動執行 Level 2 data restore。資料還原需 maintenance、雙人確認與獨立 runbook。

## 建立 checkpoint

```bash
sudo install -d -m 700 -o "$USER" -g "$USER" "$HOME/kb-pre-wp01-backups"
python3 scripts/pre_wp01_backup.py \
  --source-root /home/da40_ai_gb10/knowledge-base \
  --backup-root "$HOME/kb-pre-wp01-backups" \
  --label pre-wp01-YYYYMMDD-HHMMSS
```

輸出目錄必須包含：

- `checkpoint.json`、`SHA256SUMS`
- `source/git-head.tar.gz`、dirty status／patch
- `config.tar.gz`、`data-files.tar.gz`、一致性 SQLite copy
- Neo4j Cypher export、Qdrant snapshots、PostgreSQL dump、Redis data archive
- 精確 application image tags；預設另含 `application-images.tar`
- 原 compose、container inspect、受控 `rollback.env` 與 image override

## 驗證與 dry-run

```bash
python3 scripts/rollback_pre_wp01.py \
  --checkpoint "$HOME/kb-pre-wp01-backups/<checkpoint>"
```

沒有 `--execute` 時只驗證 SHA256、manifest、image 與參數，不會停止容器。

## Shadow rollback drill

```bash
python3 scripts/drill_pre_wp01_rollback.py \
  --checkpoint "$HOME/kb-pre-wp01-backups/<checkpoint>"
```

演練使用獨立 project、container、network 與隨機 localhost port，不掛載正式 volumes。流程會驗證 baseline 200、候選失敗 503、rollback 後 baseline 200，以及 container image ID 回到 checkpoint。

## 正式 application rollback

先進入 maintenance，停止新 upload／ingest，保存故障 logs 與 task IDs，再執行：

```bash
python3 scripts/rollback_pre_wp01.py \
  --checkpoint "$HOME/kb-pre-wp01-backups/<checkpoint>" \
  --execute \
  --confirm-production PRE_WP01_ROLLBACK
```

成功條件：`/health` 通過，且 Portal、chat/WebSocket、search、Excel ingest、report review、Beat、worker 與 A2A dry-run 均完成驗收。腳本成功只代表 application containers 與 health 回復，不代表完整業務驗收完成。

## WP0／WP1 candidate shadow gate

建立候選 image 後，必須在隔離 Redis、Neo4j、Qdrant、PostgreSQL 與資料目錄執行：

```bash
python3 scripts/drill_wp01_candidate.py \
  --image kb-wp01-candidate:<commit> \
  --source-root /path/to/integration-worktree
```

Gate 會驗證 legacy health、v1 health/live/ready/version、既有 agent auth error contract，以及 web、search worker、ingest worker、Beat 全部維持 running。所有 shadow containers、network 與 volumes 在結束時清理。

## Level 2 data restore

只有資料污染、重複寫入或 registry 不一致時才進行。停止所有 writers，確認 checkpoint 是 maintenance checkpoint，再依序還原 PostgreSQL、Redis／SQLite、Neo4j、Qdrant 與 uploads。不同 checkpoint 的資料不得混用；完成節點、關係、point、report、task 與 citation 抽樣核對後才能解除 maintenance。
