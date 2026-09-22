# KM TimescaleDB 正式前驗證 Runbook

本文件只適用於已核准的正式前 KM 主機。不可在 Production、真實 CSIT、正式
CSIT 憑證或既有資料庫上執行。

## 導入前閘門

1. 紀錄目標主機、`docker compose config` 結果、現有 KM image／container identity、
   可用磁碟與既有 health／ingest baseline；若任一項無法取得，停止。
2. 由 secret manager 注入 `KB_TIMESERIES_DB_PASSWORD`、pgAdmin 登入資訊、
   `KM_TIMESERIES_MIGRATION_URL`、`KM_TIMESERIES_DATABASE_URL` 與
   `KM_TIMESERIES_READONLY_PASSWORD`；不得回顯其值。
3. 執行 `python scripts/preflight_timeseries_preprod.py`。它不連線、不寫入資料，
   只檢查必要 secret 是否存在、pgAdmin port、磁碟與 receiver 測試範圍。

## 受控導入與驗證

1. 以受控 migration 帳號執行 `python scripts/apply_timeseries_migrations.py`，再執行
   `python scripts/provision_timeseries_readonly.py`。兩者可重跑；API／worker 不會建表。
2. 使用既有 compose 啟動獨立 `timescaledb` 與 localhost-only `pgadmin`；不要公開
   5050，也不要在既有 report registry 上安裝 Timescale extension。
3. 演練期間才設定 receiver：`KM_CSIT_NOTIFICATION_ENABLED=true`、一次性測試 token、
   `KM_CSIT_NOTIFICATION_ELIGIBILITY=test-allow` 與隔離 receipt SQLite。僅可傳送固定
   checksum 測試 Excel；正式 CSIT 與正式 S2S 一律維持未設定。
4. 驗證 receipt、重複／衝突、恢復、parser、既有 ingest、Neo4j、Qdrant、Search、
   `metric_sample` hypertable、報告 API/UI provenance 與 pgAdmin `SELECT`/拒絕 `INSERT`。
   `202` 僅代表 receipt；全部 stores 和 Search provenance 均成功才算演練完成。

## 回滾與清理

先停用 receiver、撤銷一次性 token，停止 consumer。保留既有 KM registry、檔案、
Neo4j 與 Qdrant；僅在確認 run-id 屬於測試資料後刪除對應 Timescale rows 與隔離 volume。
每個 store 必須獨立查詢 residual count；HTTP 200 或 compose down 不等於 residual 為零。
記錄 sanitized evidence、base/head、image identity、migration 清單、測試結果與 residual。
