# CSIT 規格 v1.4 / v1.4.1 — KM DEV 部署記錄(2026-11-05)

部署到伺服器上唯一一套 CSIT 整合服務(`km-csit-integration-api` + `km-csit-v1-dev-worker-1`,DA40 與 TEST 共用,沒有各自的版本)。**目前模式:real(對真實 CSIT)。沒有收過真實 CSIT 的 v2 通知。**

| 項目 | 內容 |
|---|---|
| 映像 | `km-csit-integration:v14b-spec141-20261105`、`km-csit-worker:v14b-spec141-20261105`(遠端演練後再疊一層 `runtime.py` 的修正,見下方「遠端演練」;底層為 `…v14-spec141-20261105-on-v13b`):疊加在運行中的 v1.3 映像上,只加入 14 個檔案(`v2_*` 五個新模組,以及 api / auth / config / pipeline / runtime / doclib_client / doclib_deletion / doclib_repository / doclib_worker 的修改)。worker 映像另裝 `pypdf`(PDF 加密偵測與頁數)。模擬器映像 `km-csit-simulator:20261105-v141` 已建好,real 模式不執行 |
| 基底 | v14 分支原本從 v1.3 提交 `c5d0585` 分出,沒有運行中映像裡的「以 Redis 清搜尋快取」修正。已把 `c1a079c`、`ff7ec42` cherry-pick 進來,再逐檔與運行映像比對,差異只剩本次的修改(含 `ReportAdapter` 掛點,預設不啟用) |
| Migration | `migrations/20261105_csit_integration_v2.sql` 套在 `km_control` 的 `public` 與 `csit_sim`:4 張新表(`km_csit_v2_jobs`、`_checkpoints`、`_changes`、`_analysis`)、2 個 sequence、`km_csit_deletion_jobs` 加 `api_version` 並放寬來源種類、`km_csit_v13_callbacks.kind` 加 4 個 v2 值。純加法,舊資料不變(v1 兩筆 Completed,其餘為 0) |
| nginx | `~/.km-control/nginx.runtime.conf` 原地新增三個精確路徑:`/api/integrations/csit/v2/document-jobs`、`/document-metadata-changes`、`/document-deletions`(inode 不變,`nginx -t` 通過後 reload) |
| 開關 | 未新增設定。沿用 `KM_CSIT_DOCLIB_ENABLED=true`(v2 路由與工作迴圈隨之啟用);`KM_CSIT_OUTBOUND_SCOPES` 未設,送出端仍用 v1.3 的 scope;`KM_CSIT_ANALYSIS_RESULTS_ENABLED` 未設(關閉) |
| 模式腳本 | `~/.km-control/csit-mode/`:`images.env` 指向新映像;`compose-sim.yml` 增加 sim 模式專用的 `KM_CSIT_OUTBOUND_SCOPES`(v1.3 + v2 的聯集)與 `KM_CSIT_ANALYSIS_RESULTS_ENABLED=true`;`setup-sim.sh` 套用新的 migration |
| 備份 | `~/.km-control/csit-v14-20261105/`:`control_db_before_v14.dump`、`nginx.runtime.conf.before-v14`、`images.env`、`compose-sim.yml`、`setup-sim.sh`、`api.inspect.before.json`、`worker.inspect.before.json` |
| 回滾 | 把 `images.env` 還原成備份的內容,`csit-mode.sh reapply`;nginx 以 `nginx.runtime.conf.before-v14` 原地寫回(`cat 備份 > 檔案`,保持 inode)後 reload;資料表可保留(舊程式與新約束相容) |

## 遠端演練(2026-11-05,對已部署的 KM,sim 模式)
`remote_drill.py` 擴充為涵蓋 v1.3 + v1.4 + v1.4.1(模擬器為 CSIT,身分模式、HTTPS、簽章 token、KM 的真實解析器、真實 Qdrant `km_csit_docs_sim`,模擬器送給 KM 的 token 用 v1.4.1 的分端點 scope)。**84 / 84 通過**(含 `--slow` 的 CSIT 503 中斷情境):三種新來源各自的取檔路由、md / 圖片 / 加密 / 執行檔、換版(含 v1 寫入的舊測試報告與舊文件庫檔案)、標籤變更不重新取檔且回報 `appliedRevision`、v2 刪除七項清理、已刪版本再通知回 410、測試報告 v1 → Correlation Resolver → `analysis-results`(及 Resolver 未部署時不猜 id)、v2 回報 409 不重試、無文字檔案回 `EMPTY_EXTRACTION`。演練後已切回 real 模式(`last switch` 09:09 UTC),real 的資料筆數不變。

演練發現並修掉三個問題:
1. **worker 重建要重新下載嵌入模型,且曾卡住**(下載停在 67 MB,工作一直 Accepted)。現在模型快取 `~/.km-control/csit-mode/hf-cache`(從 TEST 區的快取複製,782 MB)掛進 worker(real 與 sim 的 compose 都加了),重建不再下載。這同時消除了 real 模式重建 worker 時的同一風險
2. **sim 的 `csit_sim` schema 缺 `km_audit_events`**:v1 worker 領取測試報告工作時會讀它,缺表使每次領取失敗(`metadata store unavailable`)。已在 `csit_sim` 建立空表(`LIKE public.km_audit_events`,不放寬 search_path),`setup-sim.sh` 已加入
3. **換版時,舊的 v1 測試報告向量在 sim 模式沒被停用**(報告 collection 與文件庫 collection 同名時被我排除了)。已修 `runtime.py` 並加測試;`public` 的真實設定中兩者不同名,不受影響

備註:部署時把備份資料夾裡的 `compose-sim.yml`、`setup-sim.sh` 的「部署前」版本誤覆蓋成新版(其他備份沒有);舊版即 git 提交 `2fe62cc` 的內容,另備份了 `compose-simulator.yml.before`、`compose-real.override.yml.before`、`compose-sim.yml.before-hf`。

## 模擬器模式的 LLM 抽取(2026-11-05,使用者授權複製金鑰)
sim 模式的 worker 現在用 KM 同一個 LLM 閘道(sub2api,`gpt-5.6-luna`)產生 `documentType`、`summary`、`keywords`:映像 `km-csit-worker:v14c-llm-20261105`,`compose-sim.yml` 設 `KM_CSIT_DOCLIB_LLM=1`、`KM_CSIT_LLM_BASE_URL`、`KM_CSIT_LLM_MODEL`、`KM_CSIT_LLM_API_KEY_FILE`,金鑰檔 `~/.km-control/csit-mode/llm/api-key`(權限 600,內容複製自 `kb-web` 的 `KM_SUB2API_API_KEY`,以唯讀檔案掛載、不放環境變數),並加 `host.docker.internal`。實測:模擬器上傳一份 SOP 文字檔,KM 回 `documentType=SOP`、摘要與 18 個關鍵字(KM 會檢查每個關鍵字真的出現在文件中),`warnings` 為空。**real 模式沒有啟用**(`compose-real.override.yml` 未動):啟用會把 CSIT 的真實文件送給模型,需另行決定。測試報告走 v1 一般解析,沒有 LLM。

## 已驗證
- 離線匯入(`--network none`):api、worker、模擬器映像皆通過;worker 內 `pypdf` 5.9.0 可用;預設值(送出 scope 為 v1.3、analysis 關閉)正確;v2 合約檢查(事件與來源不符被拒、`reasonCode` 大小寫)正確
- `csit-mode.sh reapply` 後 api / worker 皆 healthy,`/health` 為 `integrationEnabled:true`、`csitMode:real`;日誌無錯誤
- 六條入站路由(三條 v1、三條 v2)經 nginx 皆回 401,證明到達 KM 且驗證生效
- 在**真實 PostgreSQL** 上、以部署後的 worker 映像,於臨時 schema 實跑新的資料層(收件、冪等重送、領取、失敗與 callback 排隊、標籤變更收件、v2 刪除收件、tombstone 擋重送),通過後整個臨時 schema 已刪除;`csit_sim` 與 `public` 的資料未動
- v1 / 文件庫 / 刪除 / callback / tombstone 筆數部署前後相同

## 尚未驗證 / 已知限制
- 沒有真實 CSIT 的 v2 通知:下載(vendor / equipment 路徑 CSIT 尚未開放)、Completed 回報、換版、標籤變更、v2 刪除只以模擬器驗證過(本機 84 項演練、147 項測試;已部署 KM 的 sim 模式 84 項演練)
- 模擬器的 CSIT 不是真實 CSIT:真實 CSIT 的身分服務、7444、真實檔案與核准流程都沒有在這次驗證中出現
- 沒有有效的 CSIT→KM 入站 token,無法在伺服器上驗證 400 / 409 / 410 的 HTTP 行為
- 測試報告的 v2 `analysis-results` 保持關閉,等 CSIT 的 Correlation Resolver(任務 C)
- CSIT 的 7444:vendor / equipment 取檔(任務 B)、`metadata-changes/status`(C)、`deletions/status`(D)尚未開放
- 送出端 scope 尚未切到 v2 正式名稱(`csit.document.read`、`csit.km.status.write`、`csit.km.deletion-status.write`),要等雙方 M2M 合約測試後把 `KM_CSIT_OUTBOUND_SCOPES` 設成它們(加 `csit.ingestion.status.write` 直到 v1 回報停用)
- LLM 擷取仍未啟用;文件庫向量仍不在 KM 搜尋範圍;`kb_timeseries_da40` 帳號權限過大尚未輪替

## live 模式:模擬器通知、寫入正式資料(2026-11-06)
依需求新增第三種模式 `live`(`csit-mode.sh live --confirm-real-data`,見 `deploy/csit-mode/README.md`)。使用者決定:允許測試報告來源、接 Neo4j 與 TimescaleDB、可刪任意 ID、提供一鍵清除。

| 項目 | 內容 |
|---|---|
| 映像 | worker `km-csit-worker:v14d-reports-20261106`(v14c-llm 加上 `src/report_numeric`、`src/wifi8`(稀疏向量用的 lexical)、`report_adapter.py`;三種模式共用,報告範本只在 `KM_CSIT_REPORT_TEMPLATES=1` 時啟用)、模擬器 `km-csit-simulator:20261106-live`。api 映像不變 |
| 檔案 | `~/.km-control/csit-mode/`:`compose-live.yml`(新)、`csit-mode.sh`(live、live-list、live-purge、離開 live 時清 analysis Skipped)、`images.env`、`live_drive.py`(驅動模擬器 API 的小工具)。備份:`~/.km-control/csit-v14-20261105/csit-mode.sh.before-live`、`images.env.before-live` |
| 模擬器 | 通知時標上 KM 的 `csitMode`;`POST /api/delete-by-id`、`POST /api/purge-live`(皆要 `confirmLiveData:true`)、`GET /api/km/mode`;畫面新增「正式資料」頁與 LIVE 標示 |
| 目前狀態 | **live 模式運作中**(切換時間 2026-11-06 01:08 UTC);真實 CSIT 在此期間得到 401 |

### 在伺服器上驗證(live 模式,真實儲存)
- 4 個來源(文件庫、廠商、驗證申請附件、設備)各送一份:全部 Completed,LLM 回 `documentType=SOP`;`public` 出現 4 筆工作、`km_csit_docs` 4 點、檔案寫進 `csit-integration-v1`。
- **以識別碼刪除**(模擬器 reset 後,用 `live-list` 的規格):4 份全部 Verified,七項清理 `chunks/metadata/vectorIndex/storedCopies/extractedText=Deleted`,`km_csit_docs` 回 0。
- **一鍵清除**:再送 4 份後 purge,4 份 Verified;重複 purge 不會重送(`alreadyDeletedOrDeleting`)。
- **測試報告 v1**(一般 xlsx):Completed,向量進 `knowledge_base`(1 點)、`analysis` 回報經模擬器 Resolver 送出;purge 後 Verified,`knowledge_base` 回 0。Neo4j 全部節點數(6238)與真實的 2 份 v1 報告(Completed)前後不變。
- 模擬器測試:`tests/csit_simulator/test_simulator_live.py` 9 項,模擬器測試共 46 項通過。

### 已知限制
- **TimescaleDB 沒有 `km_test` schema**:命中範本檔名的 xlsx 會在數值階段失敗。要先在 Timescale 套用 `src/report_numeric/schema.sql`(新增 schema,未做,需要決定);這個驗證也還沒用真實範本檔做過。
- `ai_km_knowledge_v1` collection 尚不存在,範本報告第一次寫入時才會建立。
- 一般 v1 報告刪除後,`km_csit_ingestion_jobs` 的列仍是 `Completed`(原有行為,向量與檔案已清)。
- 沒有 live 期間的 `KM_CSIT_REPORT_TEMPLATES=1` 實測;`live-list` 與 `delete_spec` 對 v1 報告用 `documentId` 當 `sourceEntityId`(KM 只用 documentId 與 version 清理)。
