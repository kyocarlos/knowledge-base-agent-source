# CSIT 規格 v1.4 / v1.4.1 — KM DEV 部署記錄(2026-11-05)

部署到伺服器上唯一一套 CSIT 整合服務(`km-csit-integration-api` + `km-csit-v1-dev-worker-1`,DA40 與 TEST 共用,沒有各自的版本)。**目前模式:real(對真實 CSIT)。沒有收過真實 CSIT 的 v2 通知。**

| 項目 | 內容 |
|---|---|
| 映像 | `km-csit-integration:v14-spec141-20261105-on-v13b`、`km-csit-worker:v14-spec141-20261105-on-v13b`:疊加在運行中的 v1.3 映像上,只加入 14 個檔案(`v2_*` 五個新模組,以及 api / auth / config / pipeline / runtime / doclib_client / doclib_deletion / doclib_repository / doclib_worker 的修改)。worker 映像另裝 `pypdf`(PDF 加密偵測與頁數)。模擬器映像 `km-csit-simulator:20261105-v141` 已建好,real 模式不執行 |
| 基底 | v14 分支原本從 v1.3 提交 `c5d0585` 分出,沒有運行中映像裡的「以 Redis 清搜尋快取」修正。已把 `c1a079c`、`ff7ec42` cherry-pick 進來,再逐檔與運行映像比對,差異只剩本次的修改(含 `ReportAdapter` 掛點,預設不啟用) |
| Migration | `migrations/20261105_csit_integration_v2.sql` 套在 `km_control` 的 `public` 與 `csit_sim`:4 張新表(`km_csit_v2_jobs`、`_checkpoints`、`_changes`、`_analysis`)、2 個 sequence、`km_csit_deletion_jobs` 加 `api_version` 並放寬來源種類、`km_csit_v13_callbacks.kind` 加 4 個 v2 值。純加法,舊資料不變(v1 兩筆 Completed,其餘為 0) |
| nginx | `~/.km-control/nginx.runtime.conf` 原地新增三個精確路徑:`/api/integrations/csit/v2/document-jobs`、`/document-metadata-changes`、`/document-deletions`(inode 不變,`nginx -t` 通過後 reload) |
| 開關 | 未新增設定。沿用 `KM_CSIT_DOCLIB_ENABLED=true`(v2 路由與工作迴圈隨之啟用);`KM_CSIT_OUTBOUND_SCOPES` 未設,送出端仍用 v1.3 的 scope;`KM_CSIT_ANALYSIS_RESULTS_ENABLED` 未設(關閉) |
| 模式腳本 | `~/.km-control/csit-mode/`:`images.env` 指向新映像;`compose-sim.yml` 增加 sim 模式專用的 `KM_CSIT_OUTBOUND_SCOPES`(v1.3 + v2 的聯集)與 `KM_CSIT_ANALYSIS_RESULTS_ENABLED=true`;`setup-sim.sh` 套用新的 migration |
| 備份 | `~/.km-control/csit-v14-20261105/`:`control_db_before_v14.dump`、`nginx.runtime.conf.before-v14`、`images.env`、`compose-sim.yml`、`setup-sim.sh`、`api.inspect.before.json`、`worker.inspect.before.json` |
| 回滾 | 把 `images.env` 還原成備份的內容,`csit-mode.sh reapply`;nginx 以 `nginx.runtime.conf.before-v14` 原地寫回(`cat 備份 > 檔案`,保持 inode)後 reload;資料表可保留(舊程式與新約束相容) |

## 已驗證
- 離線匯入(`--network none`):api、worker、模擬器映像皆通過;worker 內 `pypdf` 5.9.0 可用;預設值(送出 scope 為 v1.3、analysis 關閉)正確;v2 合約檢查(事件與來源不符被拒、`reasonCode` 大小寫)正確
- `csit-mode.sh reapply` 後 api / worker 皆 healthy,`/health` 為 `integrationEnabled:true`、`csitMode:real`;日誌無錯誤
- 六條入站路由(三條 v1、三條 v2)經 nginx 皆回 401,證明到達 KM 且驗證生效
- 在**真實 PostgreSQL** 上、以部署後的 worker 映像,於臨時 schema 實跑新的資料層(收件、冪等重送、領取、失敗與 callback 排隊、標籤變更收件、v2 刪除收件、tombstone 擋重送),通過後整個臨時 schema 已刪除;`csit_sim` 與 `public` 的資料未動
- v1 / 文件庫 / 刪除 / callback / tombstone 筆數部署前後相同

## 尚未驗證 / 已知限制
- 沒有真實 CSIT 的 v2 通知:下載(vendor / equipment 路徑 CSIT 尚未開放)、Completed 回報、換版、標籤變更、v2 刪除只在本機以模擬器與假 CSIT 驗證過(84 項演練、147 項測試)
- 沒有以模擬器對已部署的 KM 做遠端演練(`remote_drill.py` 尚未涵蓋 v1.4 / v1.4.1,且需切到 sim 模式);要做需先擴充腳本
- 沒有有效的 CSIT→KM 入站 token,無法在伺服器上驗證 400 / 409 / 410 的 HTTP 行為
- 測試報告的 v2 `analysis-results` 保持關閉,等 CSIT 的 Correlation Resolver(任務 C)
- CSIT 的 7444:vendor / equipment 取檔(任務 B)、`metadata-changes/status`(C)、`deletions/status`(D)尚未開放
- 送出端 scope 尚未切到 v2 正式名稱(`csit.document.read`、`csit.km.status.write`、`csit.km.deletion-status.write`),要等雙方 M2M 合約測試後把 `KM_CSIT_OUTBOUND_SCOPES` 設成它們(加 `csit.ingestion.status.write` 直到 v1 回報停用)
- LLM 擷取仍未啟用;文件庫向量仍不在 KM 搜尋範圍;`kb_timeseries_da40` 帳號權限過大尚未輪替
