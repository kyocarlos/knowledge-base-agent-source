# WP0/WP1 安全啟動、重啟與部署手冊

`restart_kb.sh` 是目前真實 Knowledge Base 的生命週期工具。它把只讀觀察、一般重啟與新版部署分開，避免每次操作都重新建置或刪除資料服務。

## 安全原則

- 無參數預設只執行 `--status`，不修改容器。
- `--restart` 只重啟 Web、Search Worker、Ingest Worker、Beat 與 nginx。
- Redis、Neo4j、Qdrant、PostgreSQL 不會被刪除或重建。
- 有 active、reserved、scheduled 或 queued Celery 任務時拒絕重啟與部署。
- `--deploy` 必須先有可驗證 checkpoint，候選版本 Gate 失敗會回復舊 image 與前端。
- 不提供略過任務檢查的 force 選項。

## 部署環境

從範本建立 Git 不追蹤且權限為 `0600` 的正式環境檔：

```bash
install -m 600 config/wp01-deployment.env.example config/wp01-deployment.env
```

填入受控秘密後，以 `--env-file` 載入：

```bash
./restart_kb.sh --restart --env-file config/wp01-deployment.env
```

必要設定至少包括：

- `NEO4J_PASSWORD`
- `KB_REPORT_DB_PASSWORD`（也可由 `config/report-ingest.env` 提供）

不得把真實密碼、Agent token 或 Reviewer token提交到 Git。

## 只讀觀察

```bash
./restart_kb.sh
# 或
./restart_kb.sh --status
```

檢查內容包括：

- WP0 legacy health 與 `/api/v1` live、ready、version。
- WP0 統一 error envelope、Trace ID 與 Agent 401邊界。
- WP1 兩個 Celery nodes、search/ingest queue、JobConfig與Beat。
- legacy `chat.html`、WebSocket、Qdrant與Ollama。
- active、reserved、scheduled及Redis queue數量。

可用環境變數覆蓋位置：

```bash
KB_INTERNAL_BASE_URL=https://127.0.0.1:3030
KB_EXTERNAL_URL=https://kb.example.internal
KB_FRONTEND_BUILD_DIR=/opt/kb/runtime/frontend
KB_BACKUP_ROOT=/srv/kb-backups
```

## 一般重啟

一般重啟不build image，也不更新程式：

```bash
./restart_kb.sh --restart --env-file config/wp01-deployment.env
```

執行順序：

1. 載入並驗證環境設定。
2. 執行 `docker compose config --quiet`。
3. 確認背景任務完全清空。
4. 只重啟 application services。
5. 執行完整 WP0/WP1及legacy Gate。

任何 preflight 失敗都會在容器操作前停止。

## 部署新版

程式變更完成、已Review且準備正式部署時使用：

```bash
./restart_kb.sh \
  --deploy \
  --confirm-deploy DEPLOY_WP01 \
  --env-file config/wp01-deployment.env
```

部署會：

1. 檢查工作樹、環境與任務狀態。
2. 呼叫 `scripts/pre_wp01_backup.py` 建立完整checkpoint。
3. 在staging目錄建置前端。
4. 建置並標記 `kb-wp01-candidate:<commit>-<timestamp>`。
5. 保留資料服務，只recreate application services。
6. 執行 WP0/WP1、WebSocket、Qdrant與Ollama Gate。
7. 成功後標記 `kb-wp01-live:<commit>-<timestamp>`。
8. 失敗時還原舊前端並呼叫 `scripts/rollback_pre_wp01.py`。

若已有同一維護窗口建立且驗證過的checkpoint，可指定：

```bash
./restart_kb.sh \
  --deploy \
  --confirm-deploy DEPLOY_WP01 \
  --env-file config/wp01-deployment.env \
  --checkpoint "$HOME/kb-pre-wp01-backups/<checkpoint>"
```

`--allow-dirty` 只適用於已人工審查但尚未commit的緊急候選版本；一般部署不得使用。

## 驗證與排障

執行腳本測試：

```bash
python3 -m unittest -v tests.test_restart_kb_script
bash -n restart_kb.sh
```

任務未清空時，先觀察，不要直接重啟：

```bash
docker exec kb-celery-search \
  celery -A src.web_api.tasks.celery_app inspect active
docker logs --tail 100 kb-celery-search
docker logs --tail 100 kb-celery-ingest
```

正式回退細節另見 `docs/pre-wp01-backup-and-rollback.md`。
