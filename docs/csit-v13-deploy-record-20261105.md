# CSIT 規格 v1.3 — KM DEV 部署記錄(2026-11-05)

部署到伺服器上唯一一套 CSIT 整合服務(`km-csit-integration-api`,連 DA40 的 Qdrant/Neo4j,對外經 3030 nginx)。沒有獨立的 TEST 版。**目前是探測階段:新路由已註冊,功能仍關閉。**

| 項目 | 內容 |
|---|---|
| 映像 | `km-csit-integration:v13-doclib-20261105-on-45108b1`、`km-csit-worker:v13-doclib-20261105-on-45108b1`:疊加在運行中的 `v1-canonical-45108b1` 上,只加入 `doclib_*` 模組與 api/config/repository/worker/runtime 的小改。運行映像比本分支基底舊(沒有 `report_adapter`),所以 `runtime.py` 以映像內的版本為底,只套 v1.3 的部分(沒有帶入報告範本)。worker 映像另裝 `redis`,供驗證式刪除清除搜尋快取 |
| Migration | `migrations/20261104_csit_document_library_v1.sql` 套在 `km_control` 的 `public`:5 張新表、2 個 sequence,擁有者為執行角色 `km_control_app`,不需另外授權;v1 資料(2 筆 Completed)不變 |
| nginx | `~/.km-control/nginx.runtime.conf` 新增兩個精確路徑:`/api/integrations/csit/v1/document-library/jobs`、`/document-deletions`(原地寫入保持 inode,`nginx -t` 後 reload) |
| 開關 | api:`KM_CSIT_DOCLIB_ROUTES=1`、`KM_CSIT_DOCLIB_ENABLED=false`(以 `compose-v13-probe.yml` 覆蓋);`KM_CSIT_ENABLED=false` 不變;worker 仍是 Created(未啟動) |
| 備份 | `~/.km-control/csit-v13-20261105/`:`control_db_before_v13.dump`、`nginx.runtime.conf.before-v13`、`api.inspect.before.json`、`worker.inspect.before.json` |
| 回滾 | 在 `~/knowledge-base/deploy/csit-integration-v1` 以 `~/.km-control/csit-canonical-20261014/compose-rollback-builder-gate.yml` 重建 api(見該目錄 `ROLLBACK.md`);nginx 還原 `nginx.runtime.conf.before-v13`(原地寫入);資料表可保留 |

## 已驗證(探測階段)
- 三條路由經 3030 nginx 皆回 401(證明路由到達 KM);`/health` 為 `integrationEnabled:false`;v1 筆數不變,doclib 表為空
- 兩個新映像離線匯入通過;worker 映像可匯入 `redis`

## 未做(需要人員決定)
- **未啟用。** 整合在 2026-10-15 驗收後被凍結(FROZEN,worker OFF),`readiness` 標註「HUMAN / DBA CONFIRMATION REQUIRED」:worker 掛載的 DA40 Timescale 帳號 `kb_timeseries_da40` 是共用且權限過大的帳號,尚未輪替。啟用會同時重新啟動 v1 測試報告通道
- 沒有有效 M2M token,無法驗證 422、503 與實際收件;沒有跟真實 CSIT 對測
- 啟用還需要:`KM_CSIT_ENABLED=true`、`KM_CSIT_DOCLIB_ENABLED=true`、`KM_CSIT_DOCLIB_REDIS_URL=redis://km-da40-redis-1:6379/0`(未設定時不清搜尋快取)、啟動 worker(`--profile m2m-ready`)
