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
- **(2026-11-06 已處理)TimescaleDB 的 `km_test` schema 已套用 `schema.sql`(7 張表,純新增;回滾 `DROP SCHEMA km_test CASCADE`);範本報告仍未用真實範本檔實測。** 原先的限制:TimescaleDB 沒有 `km_test` schema:命中範本檔名的 xlsx 會在數值階段失敗。要先在 Timescale 套用 `src/report_numeric/schema.sql`(新增 schema,未做,需要決定);這個驗證也還沒用真實範本檔做過。
- `ai_km_knowledge_v1` collection 尚不存在,範本報告第一次寫入時才會建立。
- 一般 v1 報告刪除後,`km_csit_ingestion_jobs` 的列仍是 `Completed`(原有行為,向量與檔案已清)。
- 沒有 live 期間的 `KM_CSIT_REPORT_TEMPLATES=1` 實測;`live-list` 與 `delete_spec` 對 v1 報告用 `documentId` 當 `sourceEntityId`(KM 只用 documentId 與 version 清理)。

### 範本報告實測與刪除缺陷(2026-11-06)
用 `SIT-TR-NR-Throughput-NCQ2200B2V-EV-V10.xlsx` 的副本(改名 `SIT-TR-SC-NR-Throughput-NCQ2200B2V-EV-V10.xlsx`,原檔未動)經模擬器以 Test Report 送入 live:命中 `cellular_throughput` 範本,Completed;Timescale `km_test` 寫入 `test_run` 1、`report_package` 1(`metric_dictionary` 由寫入程式補 11 筆,不隨報告刪除),Neo4j +5 節點,`ai_km_knowledge_v1` 建立並寫入 6 點。這份檔案的表格內容沒被範本辨識(measurements 0),但整條路徑已走過。

**發現並修掉兩個刪除缺陷**(`doclib_deletion.py`,映像 `km-csit-worker:v14e-tpldel-20261106`,測試 `tests/csit_v1/test_template_deletion.py` 4 項):
1. 範本資料以報告名稱當 `document_id`(`SIT-TR-…-V10`、版本 `V10`),CSIT 的 id 只在 `source_record_id`(`<documentId>:v<version>`);刪除用 CSIT id 找不到,卻回報 `cleanupVerified:true`。現在 Qdrant、Timescale、Neo4j 都以 `source_record_id` 解析範本身分,並在刪除前先解析好,驗證階段才不會漏看。
2. 數值清理把任何含 "does not exist" 的錯誤當成「資料表不存在」而略過(`version` 整數對文字欄位的型別錯誤也被吞掉,舊的 `km_csit_numeric_points` 表也不存在),導致後面的範本刪除根本沒執行。現在只認 PostgreSQL 的 `42P01`/`3F000`,每個表群各自一個交易。
real 模式收到範本報告也受影響,同一份程式已修。

修正後重新刪除:Timescale 各表(除 `metric_dictionary`)為 0、`ai_km_knowledge_v1` 0 點。**殘留**:測試建立的共用節點 `Product NCQ2200B2V` 與 `Firmware NCQ2200B2V_STD_V0.0.0_230206`(依設計不隨報告刪除),Neo4j 節點數 6240,比測試前多 2。

### Handover 報告範本 `cellular_handover`(2026-11-06)
新增範本:檔名以 `SIT-SR-SC-NR-Handover` 開頭的 xlsx(NG/Xn Handover,Small Cell)。實作:`src/report_numeric/parser.py`(`_handover*`)、`metric_dictionary.json`(12 個新指標)、`chunks.py`(`_handover_chunks`)、`query.py`(類型與指標白名單);測試 `tests/csit_v1/test_handover_template.py`(11 項)。既有 `cellular_throughput` 解析輸出與修改前逐位元相同。映像 `km-csit-worker:v14f-handover-20261106`。

- **辨識**:文件編號 `SIT-SR-SC-NR-Handover-<型號>-<階段>-V<版本>`(版本可含小數與字尾,如 V13.5a);`SIT-SR-…` 其他類型(如 Thermal)不命中。
- **讀的內容**:Small Cell A 的型號、韌體、硬體、頻段、NPI 階段(序號與 MAC 不讀);Small Cell B 放 `dut.peer_cell`;「2.7」的兩個小基站設定、鄰區、衰減器與 SS-RSRP 的 near/far 設定點(`test_condition`);Purpose / Scope / Test Procedure 文字;摘要頁每個區塊(Round trip=2 次、10 次、100 次)的判定、換手成功率與三個最大值(忽略 Example 欄);Xn 與 NG 兩個明細頁每次換手的前後延遲、前後吞吐量(下行)、成功與否、ping 遺失數、報告印出的有正負號變化量(絕對值欄不重複存)。分頁重複的區塊標題視為同一區塊的延續。
- **指標**:`latency_rtt_before_ho` / `_after_ho`(ms)、`throughput_before_ho` / `_after_ho`(Mbps)、`ho_success`(1/0)、`ping_loss_count`、`latency_variation`、`throughput_variation`、`ho_success_rate`、`max_throughput_variation`、`max_latency_variation`、`max_ping_loss_count`。測試案例 id `cellular_handover:<xn|ng>:<2|10|100>`,`sample_index` 為第幾次換手。
- **實測**(`SIT-SR-SC-NR-Handover-SCU2060-EV-V13.5a.xlsx` 的副本,live 模式):Completed;`test_measurement` 1816 筆(224 次換手 × 8 + 24 筆摘要)、`test_item_result` 6、`test_condition` 38、`ai_km_knowledge_v1` 54 點;抽查 Xn 第 100 次(延遲 32→45、吞吐量 638→649)與來源儲存格一致。以模擬器清除後 Timescale、向量庫皆為 0,`cleanupVerified:true`。
- **殘留**:依設計不隨報告刪除的 Neo4j 共用節點(`Product SCU2060`、其 `Firmware`、6 個 `TestCase`),節點數 6246,比基準 6238 多 8。
- **假設**:「Center Frequency 4.85」視為 GHz(同區塊 ARFCN 723332 = 4849.98 MHz 相符);吞吐量方向記為 dl(測試指令為 iperf3 Client - DL);RF 發射功率、ARFCN 等未標單位的設定不加單位。

### 依 L1 分區抽取(2026-11-06)
CSIT 通知文件後,KM 依文件的第一層分類(L1)決定它屬於哪個專區,並把結果寫在寫入的每個資料點上(Qdrant payload:`zone_id`、`topic_zone`、`zone_basis`;範本報告的 Neo4j `Document` 節點加 `topic_zone`)。八個專區就是 KM 左側導覽的名稱:WiFi 知識專區、行動通訊知識專區、固網寬頻知識專區、認證知識專區、產品驗證專區、設備儀器專區、實驗室管理專區、Confluence / Jira / TestRail 查詢專區。

| 情況 | 專區(`zone_basis`) |
|---|---|
| 測試報告(v1 一般、v1 範本、v2 換版) | 產品驗證專區,不論分類填什麼(`source_type`) |
| L1 名稱就是八個專區之一(忽略大小寫與空白;舊名稱 4G/5G 知識專區、認證與法規知識專區、設備預約知識專區、實驗室與測試環境知識專區也認得) | 該專區(`classification`) |
| 沒有可用的 L1:驗證申請附件 | 產品驗證專區(`source_default`) |
| 沒有可用的 L1:廠商檔案、設備附件 | 設備儀器專區(`source_default`) |
| 沒有可用的 L1:文件庫檔案 | 待分類(`none`),不猜 |

分類變更通知(metadata change)會依新的 L1 重新標記專區。程式 `src/csit_integration_v1/zones.py`;寫入點:`doclib_pipeline.py`、`v2_pipeline.py`(含 `metadata_payload`)、`writers.py`、`report_numeric/vector.py`、`report_numeric/graph.py`;測試 `tests/csit_v1/test_zones.py`(25 項)。映像 worker `v14g-zones-20261106`、模擬器 `20261106-zones2`。

**模擬器**:L1 下拉是上述八個專區(L2/L3 為範例);選「測試報告」時 L1 鎖定為產品驗證專區(伺服端也強制);選驗證申請附件、廠商、設備附件時 L1 預設為各自的專區;畫面顯示「KM 會把文件抽取到…」,文件列表顯示 `KM 分區 →`。模擬器自己保留一份相同規則當獨立檢驗(`expected_zone`),測試比對兩邊對每個 L1 與來源的結果相同;`remote_drill` 新增一項檢查,KM 在 L1 被改成設備儀器專區後必須把資料點的專區一起改掉。

**伺服器驗證(live 模式)**:7 份文件——文件庫檔案選行動通訊(→ 行動通訊知識專區)、文件庫檔案不選 L1(→ 待分類)、廠商檔案不選 L1(→ 設備儀器專區)、設備附件選認證(→ 認證知識專區)、驗證申請附件不選 L1(→ 產品驗證專區)、一般 xlsx 測試報告與 Handover 範本報告(L1 選 WiFi,模擬器改成產品驗證專區)。KM 寫入的 `topic_zone` 與模擬器預期完全一致;把「待分類」那份的 L1 改成認證知識專區後,資料點的專區同步變成認證知識專區。清除後 Timescale、三個向量集合皆為 0。

**限制**:目前只是把專區寫在資料上;各專區頁面搜尋時要用 `topic_zone` 過濾(以及文件庫的 `km_csit_docs` 尚未納入 KM 搜尋範圍)是另外的工作。Neo4j 只有範本報告的 `Document` 節點帶專區。清除後 Neo4j 又留下依設計不隨報告刪除的 8 個共用節點(`Product SCU2060`、其 `Firmware`、6 個 `TestCase`),節點數 6246。

### 專區改由 KM 的 LLM 依內容決定(2026-11-06,取代上一節的 L1 規則)
CSIT 不會規範文件類型,也不分類到 KM 專區,所以專區完全由 KM 判斷:取文字之後同一次 LLM 呼叫(`documentType`、`summary`、`keywords`)多回一個 `zone`。規則依序為:
1. **測試報告一律產品驗證專區**:CSIT 的 `TestReport` 來源,或 LLM 判斷 `documentType=TestReport` 的任何文件,不論技術(`zone_basis` = `source_type` / `document_type`);
2. 其他文件進 LLM 指名的專區(`llm`),依內容主題、不看檔名;
3. LLM 沒結果(不可用或不確定,回「無法判斷」)時才參考 CSIT 帶來的 L1 名稱(`classification`);
4. 再來是附件來源的歸屬(驗證申請附件 → 產品驗證專區,廠商檔案與設備附件 → 設備儀器專區,`source_default`);
5. 否則「待分類」,不猜(`none`)。
CSIT 的分類變更通知不再改專區。程式:`zones.py`、`doclib_metadata.py`(提示詞與 `zone_fields`)、`doclib_pipeline.py`、`v2_pipeline.py`。

**專區頁面怎麼搜得到**:`src/legacy_import/browse.py` 的 `ZoneSearch.search(..., csit_zones=[…])` 除了舊資料,再從 CSIT 文件所在的集合(`km_csit_docs`、`knowledge_base`、`ai_km_knowledge_v1` 內的 CSIT 點)依 `topic_zone` 取回,排除已被新版取代的,兩邊以排名合併(RRF);`src/web_api/legacy_routes.py` 的 `/api/legacy/search`、`/answer` 帶入該專區的名稱與舊名稱(`csit` 頁面 = 產品驗證專區)。**這部分在 repo 的網頁服務程式裡,尚未部署到伺服器上的 KM 網頁服務**;伺服器上只部署了 CSIT 整合服務(worker 映像 `v14h-llmzones-20261106`、模擬器 `20261106-zones3`)。專區文件清單(Neo4j 的 Legacy 圖)仍不含 CSIT 文件。

**模擬器**:不再決定專區;L1 仍可選(八個專區名稱,範例 L2/L3),只是帶給 KM 的參考;畫面說明專區由 KM 讀內容決定,只有「測試報告」來源會顯示 `KM 分區 → 產品驗證專區`。

**伺服器驗證(live 模式,真實 LLM)**:8 份文字內容不同的文件,KM 的判斷與預期一致:Wi-Fi 7 規範 → WiFi 知識專區;5G Small Cell 換手測試報告(以文件庫檔案送)→ 產品驗證專區(`document_type`);Wi-Fi RvR 測試報告(以廠商檔案送)→ 產品驗證專區(`document_type`);XGS-PON 技術 → 固網寬頻知識專區;NCC/CE 認證流程 → 認證知識專區;頻譜分析儀手冊(廠商檔案)→ 設備儀器專區;實驗室環境介紹 → 實驗室管理專區;Jira/TestRail 週報 → Confluence / Jira / TestRail 查詢專區。在 worker 內以 `ZoneSearch` 對真實 Qdrant 查詢:各專區的問題只回該專區的文件,同一個問題換到別的專區查不到對方的文件。清除後三個向量集合與 Timescale 皆為 0。
測試:`tests/csit_v1/test_zones.py` 34 項、`tests/legacy_import/test_browse.py` 增加 5 項;csit_v1 其餘失敗與基準相同(17,皆為需要資料庫的既有項目)。
