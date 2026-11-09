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

### 專區搜尋部署到 DA40 網頁服務(2026-11-06)
只部署 DA40(`km-da40-web-1`);TEST 網頁(`kb-web`)讀自己的向量庫與 Neo4j,CSIT 整合服務只寫 DA40 這一套,所以 TEST 看不到 CSIT 文件(要看到得讓 CSIT 同時寫兩邊,或讓 TEST 讀 DA40 的資料庫,後者破壞隔離,未做)。
- **映像**:`km-da40-web:csit-zones-20261106-on-open-files`,疊在原本的 `km-da40-web:open-files-20261031-on-feed-c7869ce` 上,只加四個檔案:`legacy_import/browse.py`、`web_api/legacy_routes.py`、`csit_integration_v1/zones.py` 與 `__init__.py`。部署前把原映像中的 `browse.py`、`legacy_routes.py` 與分支改動前的版本逐行比對,完全相同,所以不會蓋掉其他人的改動。
- **設定**:新增 `~/.km-control/compose/km-da40.csit-zones.image.override.yml`(只改 `services.web.image`),接在原有 7 個設定檔之後;以專案 `km-da40`、環境檔 `~/.km-control/planes/da40.env` 只重建 `web`(`--no-deps --no-build`)。其他服務未動。
- **備份與回滾**:`~/.km-control/csit-zones-web-20261106/`(`web.inspect.before.json`、原映像覆蓋檔)。回滾:把新覆蓋檔的映像改回 `km-da40-web:open-files-20261031-on-feed-c7869ce`,以同一組設定檔重建 `web`。
- **驗證**:容器 healthy、網路與環境變數數量與部署前相同、kb-nginx 連得到;用 FastAPI TestClient 掛上測試身分,在容器內呼叫 `/api/legacy/search` 與 `/api/legacy/answer`:八份內容不同的測試文件,各專區的搜尋只回該專區的文件(WiFi、產品驗證〔兩份測試報告〕、固網寬頻、認證、設備儀器、實驗室管理、Confluence/Jira/TestRail 各一份),同一個 MLO 問題換到認證專區只回認證文件;認證專區的問答回「已根據資料」並附來源檔名。測試文件已清除。
- **限制**:使用者要用 `/legacy/` 舊資料專區頁提問才會用到;前端各專區頁(範例資料)與專區文件清單(Neo4j Legacy 圖)沒有接上。

### 專區頁改讀真實資料(2026-11-06,DA40)
七個專區頁(行動通訊、固網寬頻、認證、產品驗證、設備儀器、實驗室管理、Confluence / Jira / TestRail 查詢)與知識中樞首頁不再用瀏覽器裡的範例資料,改讀 KM 的真實 API;WiFi 專區仍是原本的真實後端。

- **後端**:`src/web_api/zone_routes.py` 與 `src/zone_pages/`(`catalog.py`、`views.py`、`digest.py`、`agent.py`)。`/api/zones/<專區>/` 提供頁面原本呼叫 `/api/wifi8/*` 的同樣格式:總覽、文件清單(類型與來源篩選、歷史版本)、文件詳情與版本、段落、搜尋、動態與週報、問答(非同步工作、事件串流、結果、回饋)、附加檔案(沿用 WiFi 專區的暫存、2 小時、不進知識庫)。文件從 CSIT 寫入的向量集合依 `topic_zone` 取回,換版後的舊版標為歷史;**待分類的文件列在產品驗證專區裡**(總覽會有「N 份文件待分類」提醒)。
- **問答**:先搜尋該專區的段落(含使用者附加的檔案),再由模型依段落回答並標 `[S1]`;引用只列答案實際用到的段落;每個數字都到引用的段落裡核對,找不到的列在 `grounding.flagged`;資料裡找不到時不引用、也不呼叫模型編答案。
- **週報**:本週(7 天)新增的文件列出標題與摘要;重點由一次模型呼叫整理,每個專區、每週、每組文件只做一次並快取,等模型回來前先用文件標題,頁面不用等。
- **寫入端**:CSIT 文件的資料點多帶 `document_type`、`summary`、`keywords`、`indexed_at`(換版時 `superseded_at`),頁面才有類型、摘要、日期可顯示(`doclib_metadata.zone_fields`、`writers.py`、`v2_pipeline.py`、`report_numeric/vector.py`)。
- **前端**:`scripts/build_zone_live.js`(可重複執行)把七個專區頁改載入 `zones-live.<hash>.js`(各專區名稱與文字、不含範例文件,並把 `/api/wifi8/*` 呼叫導向 `/api/zones/<專區>/*`),知識中樞首頁改成每個專區都讀自己的總覽與動態;範例文件與假後端不再載入。
- **映像與檔案**:worker `km-csit-worker:v14i-pagemeta-20261106`;網頁服務 `km-da40-web:zone-pages-20261106c`(疊在 `csit-zones-20261106-on-open-files` 上,只重建 `web`;伺服器上 `web_api/__init__.py` 與我的分支不同,所以只在它原有內容上加兩行註冊路由,沒有整份覆蓋);前端檔案複製到 nginx 目錄(`zones-live.a4fe03eda854.js`、`hub.c868255c359b.js`、七個專區頁、`hub/islands.html`)。
- **備份與回滾**:前端 `~/.km-control/zones-live-frontend-backup-20261106/`(把檔案複製回去即可);網頁服務 `~/.km-control/csit-zones-web-20261106/`(`web.inspect.before-pages.json`、上一版覆蓋檔),回滾時把 `km-da40.csit-zones.image.override.yml` 的映像改回 `km-da40-web:csit-zones-20261106-on-open-files`;worker 回滾把 `images.env` 的 worker 映像改回 `v14h-llmzones-20261106` 後 `csit-mode.sh reapply`。
- **驗證**:本機用真實的專區路由配假資料,在瀏覽器點過認證專區的總覽、文件清單、文件詳情、問答(含引用、數值核對、回饋按鈕)與知識中樞首頁,頁面只呼叫 `/api/zones/*`。伺服器上以模擬器送 8 份內容不同的文件,在網頁容器內呼叫路由:各專區的文件數、類型、來源、日期正確(產品驗證專區有兩份測試報告),詳情與段落、搜尋、週報(模型整理的重點)、4 個問答(認證、Small Cell 換手、設備校驗、無關問題)都正常,附加檔案設定開啟。測試文件已清除,Timescale 與三個向量集合皆為 0。
- **限制**:TEST 網頁讀自己的資料庫,看不到 CSIT 文件;專區頁沒有圖片與圖表段落(CSIT 文件沒有抽圖);週報要等有本週新增文件才有內容;問答的文件權限目前是「登入者皆可看」;沒有對 CSIT 文件的「已移除」事件(刪除後資料點直接消失,動態裡不會有紀錄)。附加檔案實際上傳沒有在伺服器上點過,只確認設定與路由。

## Handover 彙總段落與多對象檢索（2026-11-06）

問題：問「NG 和 Xn 換手的結果有什麼差別？」時，檢索回傳的 8 段全是 NG（Xn 段落與 NG 段落只差標題兩個字，語意向量分不開），且報告只印最大值、沒有成功率或平均值，模型回答「找不到 Xn」。

- B（`src/report_numeric/chunks.py`）：每個測試項目多寫一段「依逐次數據彙總」（次數、換手成功／總數、換手前後延遲與下行吞吐量的平均／最小／最大、ping 遺失合計），再多寫一段 Xn 與 NG 並列的比較段落（同次數的 Xn、NG 相鄰）。數值由入庫時從逐次資料計算，段落內註明來源。
- A（`src/zone_pages/catalog.py`）：`spread()` 找出問題中提到、且候選段落也提到的名稱（NG、Xn、型號…，最多 4 個），每個名稱至少帶 3 段，不足時換掉排名最低且無人需要的段落。只有一個名稱或沒有段落提到的名稱時結果不變。
- 部署：worker `km-csit-worker:v14j-handoveragg-20261106`（images.env 備份 `~/.km-control/agg-20261106/images.env.before`，`csit-mode.sh reapply`）；DA40 web `km-da40-web:zone-pages-20261106e`（override 備份 `~/.km-control/agg-20261106/override.before`，還原則把 image 改回 `…20261106c`）。
- 既有報告不會自動補彙總段落：需先刪除再重新上傳。
- 回答規則（`src/zone_pages/agent.py`）：比較時差距約 2% 以內或在逐次量測的正常波動內，寫「差距很小」而不下優劣結論；樣本只有幾次時，成功率差一兩次也不下結論。DA40 web 為 `km-da40-web:zone-pages-20261106f`（還原則把 override 的 image 改回 `…20261106e`）。

## C：專區問答查資料庫算數值（2026-11-06）

產品驗證專區的問題若需要統計（某幾次到某幾次的平均、中位數、p95、成功次數、跨測試項目比較），先用一次模型呼叫把問題轉成查詢計畫 JSON（設備、模式 xn/ng、次數 2/10/100、指標、from_no/to_no），計畫經白名單驗證後交給固定 SQL 範本 `report_numeric.query.handover_stats`（唯讀連線、statement_timeout 8 秒、只看 access_roles 含 CSIT_ENGINEER 且已發布的報告），結果成為編號段落「測試數據彙總」放在檢索段落之前，回答照一般段落引用並通過數值依據檢查。模型不寫 SQL；計畫為 needed=false、資料庫不可用、設備不存在或參數被拒絕時，不加任何段落，回答退回只靠檢索段落。

- 程式：`src/zone_pages/stats.py`（計畫、白名單、渲染）、`src/report_numeric/query.py`（`handover_stats`）、`src/zone_pages/agent.py`（`with_stats`）、`src/web_api/zone_routes.py`（只對 verification 專區啟用）。
- DA40 web：`km-da40-web:zone-pages-20261106g`（override 備份 `~/.km-control/agg-20261106/override.before-g`，還原則改回 `…20261106f`）。web 映像原有的 `report_numeric/query.py` 是不含 Handover 的舊版，這次只覆蓋該檔。
- 驗證：「Xn 100 次第 40～60 次平均換手後延遲」答 30.95 ms；「NG 100 次換手後延遲中位數與 p95」答 31／49.5 ms，皆與 Timescale 原始資料重算一致。
- 範圍：目前只有 cellular_handover 有統計範本；Throughput／RvR 等類型尚未接入。

## C 擴充：Throughput／RvR／蜂巢式 Throughput 與日後新報告（2026-11-06）

把 Handover 專用的統計改成通用範本 `src/report_numeric/stats.py`（取代 `query.handover_stats`）：
- 所有報告類型共用 `test_measurement` 的條件欄位（band、center_freq_mhz、bandwidth_mhz、channel、direction、attenuation_db、angle_deg、traffic_mode、protocol、statistic、time_slot），所以只有一個固定 SQL。每種類型的差別只在「哪些條件一定不能平均掉」，登記在 `SERIES`：wifi_throughput＝頻段／頻寬／方向／協定；wifi_rvr＝頻段／頻寬／方向／衰減／角度；cellular_throughput＝頻段／中心頻率／頻寬／時槽／方向／協定／單雙向／統計類型；cellular_handover＝測試項目代碼。其餘條件（例如 channel）只在被要求時才分組。
- **日後新進來的報告**：`SERIES` 沒登記的類型一律套用最嚴格分組（所有條件都分開），不會算出混在一起的平均；可查的類型、設備、指標、條件值、測試項目全部由 `catalog()` 即時從資料庫讀出並放進給模型的提示，所以新報告進來不用改程式。要讓新類型的結果更精簡，才需要在 `SERIES` 補一行。
- 計畫的每個名稱都要在 catalog 裡（資料庫沒有的值會被丟掉，不猜）；SQL 的識別字只來自常數、值全部綁定參數；唯讀連線、statement_timeout 8 秒。查無資料時會明說「資料庫中沒有符合此查詢的數據」，不讓模型用別的條件代替。
- `src/zone_pages/agent.py`：資料庫彙總段落可超過一般段落的 700 字上限（`limit`）。
- DA40 web：`km-da40-web:zone-pages-20261106i`（還原則把 override 的 image 改回 `…20261106g`，備份在 `~/.km-control/agg-20261106/`）。
- 驗證：在一個交易裡寫入伺服器上現成的 `SIT-TR-WL-Throughput-PKE3540J`、`SIT-TR-WL-RvR-NCM1150D2`、`SIT-TR-SC-NR-Throughput-SCU5050` 報告，以真實模型問四種題型，數值都由資料庫彙總段落提供、沒有被標為找不到依據，最後 rollback。注意：第一次探測腳本沒有先開交易，`write_package` 自己 commit 了一筆 SCU5050 測試報告（csit_id `p`），已確認並只刪除該筆（test_run 回到 1 筆、量測 1792 筆）。以後驗證腳本一定先開交易再寫入。

## 報告分類補強與反問（2026-11-06）

- **分類（worker）**：原本只看檔名前綴（`SIT-TR-WL-RvR`、`SIT-TR-WL-Throughput`、`SIT-TR-SC-NR-Throughput`、`SIT-SR-SC-NR-Handover`）。現在檔名不是這四個前綴、但以 `SIT-` 開頭的 xlsx，會看頁籤特徵（`parser.CONTENT_SIGNATURES`：`4.n Xn/NG Handover`、`3.n RvR_`、`4.n x.xGHz Test`、`4. Performance Test`）；只有頁籤剛好指向一種類型才採用，指向零種或兩種就維持一般文件路徑。已註冊前綴仍以檔名為準，若頁籤顯示另一種類型，會在報告的 issues 記一筆 `report_type_mismatch`。`ReportAdapter.matches(job, path)` 與 pipeline 把下載後的檔案路徑傳進來。
  - 例：`SIT-TR-NR-Throughput-…`（少了 SC）與 `SIT-TR-XX-Whatever-…` 的 SCU5050 報告都被分為 cellular_throughput，解析出與原檔相同的 512 筆量測；`NCQ2200B2V`（EN-DC 版面：`4.1 5GNR_Eth`、`4.2 EN-DC_Eth`…）沒有註冊的範本，仍走一般文件路徑；非 `SIT-` 開頭的檔案不看頁籤。
  - worker 映像 `km-csit-worker:v14k-classify-20261106`（images.env 備份 `~/.km-control/agg-20261106/images.env.before-k`，`csit-mode.sh reapply` 即可還原）。
- **反問（web）**：統計規劃步驟可回傳 `clarify`（候選報告類型）。程式驗證：候選必須在資料庫現有類型內、至少兩種、問題若點名設備則該設備必須同時屬於這些類型（只屬於一種就直接用那一種）。成立時不查資料、不呼叫回答模型，直接回「請問要查哪一種？」，每個選項成為一個追問（原問題＋「（WiFi 吞吐量）」），並把前一個提問帶進規劃，所以使用者只回「WiFi」也能接續。提示規則：單純問「吞吐量」只在 WiFi 吞吐量與 5G 吞吐量之間選；只有提到 RvR／衰減／角度／距離才算 RvR；只有提到換手才算換手；已說 WiFi 或 5G 就只在該技術內選。
  - DA40 web：`km-da40-web:zone-pages-20261106k`（override 備份 `~/.km-control/agg-20261106/override.before-j`）。
  - 驗證（真實報告、交易內寫入後 rollback）：「吞吐量平均是多少？」→ 反問 5G／WiFi；「WiFi 的…」「5G 的…」→ 直接回答；「吞吐量平均是多少？」之後回「WiFi」→ 直接回答；點名 RvR 與換手 → 直接回答。

## 回答要交代依據、規劃不放棄（2026-11-06）

手動測「吞吐量平均是多少?」（DA40 只有一份 Handover 報告）時，回答沒說明是哪種報告、哪個設備、哪份文件，而且只列了部分組合。原因：規劃步驟回傳 `needed: true` 但 `report_type` 留空，程式放棄查詢，模型改用檢索到的零散段落（含入庫時寫的彙總段落）拼出答案，並自己挑了 5 組。
- `src/zone_pages/stats.py`：規劃要數字但沒選類型時，資料庫只有一種類型就用它，有多種就反問；規劃不得自行加入問題沒問的條件，且某類型的 `statistic` 只有一個值時丟掉該篩選；資料庫彙總段落第一行是「資料來源：<類型>報告 <文件編號>（設備 <型號>）」並帶 `scope`。
- `src/zone_pages/agent.py`：用了資料庫彙總（引用 S1）的回答，由程式在最前面加「**依據：…**」（不靠模型寫）；提示規則要求統計數值只引用彙總、依條件分組列表、缺值寫「—」、問題沒指定時列出全部組合並用追問建議縮小範圍。
- DA40 web：`km-da40-web:zone-pages-20261106m`（備份 `~/.km-control/agg-20261106/override.before-l`，還原則改回 `…20261106k`）。
- 驗證：同一題連問三次，三次都走資料庫彙總，列出 6 組（Xn/NG × 2/10/100 次）的換手前後下行吞吐量與變化平均，最前面都有依據行；表格數值與 Timescale 重算一致（例如 Xn 100 次前後皆 456.7、Xn 10 次換手前 462.5）。

## 固定的反問順序：技術 → 報告種類 → 案子 → 才查資料（2026-11-06）

取代前面「模型覺得有歧義才反問」的做法（`clarify`）。任何需要報告數據的問題（吞吐量、延遲、RSSI、通過率、換手成功率…）都照同一個順序，由程式（`zone_pages/stats.py` 的 `next_step`）決定還缺什麼，模型只負責從句子抽出技術、報告種類、設備、指標、條件：
1. **技術**：句子沒說 WiFi 或 5G，且沒點名報告種類或設備 → 反問「WiFi 還是 5G」（不管資料庫現在有哪些類型；選項固定有 WiFi、5G，再加資料庫裡其他技術）。
2. **報告種類**：沒點名種類時用該技術的一般種類（`<技術>_throughput`）；但若問的指標不在該種類（例如通過率只在 RvR）或該技術沒有一般種類，列出該技術有的報告請使用者選。點名 RvR／換手、或點名只屬於一種報告的設備，則直接決定種類。
3. **案子（設備）**：該種類有兩個以上設備且句子沒點名、也沒說「全部設備」 → 反問，選項是各設備加「全部設備」；只有一個設備就不問（依據行會寫明）。
4. 三者齊了才查資料庫。每個選項是一個追問（原問題＋「（選項）」），所以下一輪的句子是完整的；使用者改成手打短答時，前面最多 3 個提問會一起交給規劃。
- 程式端補強（`with_hints`）：設備名（完整型號，或含數字的片段如 `PKE3540J` 對應 `PKE3540J-D223`）、「全部設備」、WiFi／5G 關鍵字，由程式直接從句子找出來，不只靠模型抽取（實測模型曾漏掉括號裡的短型號）。
- 日後新技術（例如 `pon_throughput`）自動套用同一順序；新報告種類不用改程式。
- DA40 web：`km-da40-web:zone-pages-20261106o`（備份 `~/.km-control/agg-20261106/override.before-n`，還原則改回 `…20261106m`）。
- 驗證（真實報告，交易內寫入後 rollback）：「吞吐量平均是多少？」→ 問 WiFi 或 5G →（WiFi）→ 問兩個案子或全部 →（PKE3540J）→ 直接答；「延遲平均是多少？」「RSSI 平均是多少？」同樣先問技術；「通過率（WiFi）」→ 請選報告種類（只有 RvR）；點名設備與條件的問題直接答。

## 案子名稱與依據行補強（2026-11-06）

手動測時，回答沒有交代案子，追問「案子名稱是甚麼」只答出文件標題。原因與處理：
1. **名稱沒存進 Timescale**：CSIT 通知有 project、case、task 的 id／編號／名稱（控制庫 `km_csit_ingestion_jobs` 有存），但 `km_test.test_run` 只留 `project_id`（＝專案編號，如 PRJ-001）。現在 worker 把 `project_name`、`case_code`、`case_name`、`task_code`、`task_name` 也寫進 `test_run`（`schema.sql` 以 `ADD COLUMN IF NOT EXISTS` 加欄位，每次寫入都會重跑，可重複執行；`report_adapter` 從通知取值，`parser`、`timescale` 寫入）。新欄位可為空，回復映像時不必移除欄位。已用 `backfill_names.py`（一次性）依控制庫同一份通知補上既有那筆報告（SCU2050）；目前模擬器送的是固定名稱「模擬專案／模擬測試案例／模擬測試任務」，真實 CSIT 會送真實名稱。
2. **目錄與依據行**：`report_numeric.stats.catalog` 讀出案子名稱等（用 `to_jsonb(r) ->> '…'`，資料庫還沒有欄位時也能回答）。資料庫彙總的依據行改為「案子 名稱（編號），測試案例 …，設備 …，<種類>報告 <文件編號>」；反問案子的選項為「設備・案子名稱」，句子裡提到案子名稱且唯一對應一個設備時也能認出。
3. **「找不到…」開頭的回答不再整段被丟掉**：原本只要開頭是「在這個專區的資料裡找不到」就不收引用，導致依據行消失、數值核對全部顯示找不到。現在只有不到 120 字的純「找不到」才不引用。
4. **互相矛盾的選擇不再疊加**：選了某技術但該技術沒有資料時，新的選項會取代原本的「（WiFi）」，不再變成「（WiFi）（5G 換手）」。
5. **問案子、專案、測試案例、任務的問題**（不論是否要數據）會多一段「報告基本資料」（`info_passages`），所以「剛剛的數據的案子名稱是甚麼？」答「模擬專案（PRJ-001）」。
6. 數值核對容許尾端 0（`454.0` 對應資料的 `454`）。
- 映像：worker `km-csit-worker:v14l-projectnames-20261106`（備份 `~/.km-control/agg-20261106/images.env.before-l`）、web `km-da40-web:zone-pages-20261106r`（備份 `…/override.before-p`，還原則改回 `…20261106o`）。
- 反問的回答不再顯示成「沒有依據」（依據核對面板原本顯示 0/2 紅字）：`NO_CLAIMS`；選報告種類的選項會取代「（5G）」而不是疊成「（5G）（5G 換手）」。web 映像 `km-da40-web:zone-pages-20261106s`（備份同 `override.before-p`，還原改回 `…20261106o`）。

## 5G Throughput 報告因測試項目重複被拒絕（2026-11-06）

`SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.xlsx` 上傳後 KM 失敗（`STORAGE_UNAVAILABLE`，重試 3 次）。用同名同大小（1498645 B）的檔案在交易內重現：`UniqueViolation test_measurement_pkey`。
- **原因**：報告的 Test Case 4（摘要頁表頭是「4\*」，註記「\*test with Kyocera K5G-C-100A」，用另一台終端測）與 Test Case 6 的頻段、中心頻率、頻寬、時槽完全相同；解析器只用這四項組測試項目代碼，兩者撞成同一個代碼，量測主鍵重複（25 組），整份報告被資料庫拒絕。另外摘要頁的「4\*」欄因為不是純數字被略過。如果硬寫入，兩台終端的數值還會被平均在一起。
- **解析器**（`parser.py`）：認得「4\*」並記下註記；同一份報告裡條件相同的測試項目，代碼加上 `#case<編號>` 區分（條件不同的不動），星號案例的名稱帶註記（`Test Case 4 (*test with Kyocera K5G-C-100A)`），並在報告 issues 記 `same_conditions`。
- **資料庫主鍵**（`timescale.measurement_key`）：加入來源儲存格，同一個條件重複出現的報告不會再整份被拒絕。
- **統計**（`report_numeric/stats.py`）：5G Throughput 的不平均條件加入 `test_case_id`，不同終端的案例不會被平均在一起。
- **錯誤分類**（`report_adapter.py`）：資料庫拒絕報告內容（唯一鍵、數值範圍、檢查條件）改回 `REPORT_REJECTED`、不重試；資料庫連不上才維持可重試的 `STORAGE_UNAVAILABLE`。
- 驗證：同一份檔案在交易內寫入成功（512 筆，原本略過摘要頁 Case 4 時是 505 筆），rollback 後 `test_run` 仍 1 筆。KM 對「同一份文件、同一版本」的重送（含「重送(同工作)」）只會回傳原本失敗的工作，所以要刪除失敗那筆後重新上傳（新的 documentId）。
- 映像：worker `km-csit-worker:v14m-cases-20261106`（備份 `~/.km-control/agg-20261106/images.env.before-m`）、web `km-da40-web:zone-pages-20261106t`（備份 `…/override.before-t`，還原改回 `…20261106s`）。
- 已知：這份報告的 Test Case 9～16 是範本殘留的假資料（頻段「Band2」、數值 9～16 Mbps），目前仍會被寫入並標記 `unparsed_band`，之後問 5G 吞吐量會一起列出。
- **重傳後驗證（SCU2060 n79 V13.8）**：KM 兩筆工作都 Completed（原失敗那筆與新上傳那筆，對應同一份報告）；Timescale 512 筆量測，Test Case 4（`…#case4`，名稱帶 Kyocera 註記）與 Test Case 6（`…#case6`）分開；向量庫 67 段、全在產品驗證專區。專區問答暴露兩個問題並修正：
  1. 測試項目代碼現在含 `#`、`@`、`+`，查詢端原本的格式檢查會拒絕，丟出的錯誤被吞掉，統計段落整個消失，模型只剩文件段落、把 Case 4 答成找不到 → 格式規則改為 `^[\w:.@+#*, \-/()]{1,160}$`。
  2. 假資料（Test Case 9～16，頻段 Band2、值 9～16 Mbps）因代碼字母排序在前，加上最多 120 組，把真資料擠掉 → 查詢改為頻率不明的項目排最後、上限 240 組、彙總段落上限 12000 字；問「平均」時，若該類型有多種統計（自己的平均、峰值、逐次值）且問題沒提到峰值／最大／最小，只取報告自己的平均（`default_statistic`）。「Test Case 4」這類字樣不再觸發「報告基本資料」段落。
  - web 映像 `km-da40-web:zone-pages-20261106u`（備份 `…/override.before-t`，還原改回 `…20261106t`）。
  - 驗證：問「吞吐量平均是多少？（5G 吞吐量）」列出 Case 1～8（對照報告摘要頁數值一致，例如 Case 1 下行 TCP 單向 705、Case 4 為 430、Case 6 為 483）與排在最後的 Band2 假資料；問 Case 4 與 Case 6 分別得到 430／483 Mbps，與資料庫一致。
- **範本殘留的假資料不再寫入**：5G Throughput 範本附帶的填充案例（SCU2060 的 Test Case 9～16：頻段 Band2，吞吐量與摘要延遲全部等於案例編號，效能頁的接收訊號強度與封包遺失是 0）。`parser._drop_placeholder_cases`：一個案例的吞吐量與摘要延遲平均（至少 3 筆）全部等於它自己的案例編號時，整個案例（含它所有儲存格）不寫入，並在報告 issues 記 `placeholder_cases`（說明是哪幾個案例）、同時移除這些案例的 `unparsed_band` 提示。判斷刻意保守：只看這兩類欄位、必須全部等於案例編號、至少 3 筆。
  - 驗證（伺服器上的真實報告）：SCU2060 512 → 256 筆（少了 8 個案例 × 32 筆）；SCU5050（有真實的 Band2 資料）512 筆、WiFi Throughput 126 筆、RvR 682 筆都不變。
  - worker 映像 `km-csit-worker:v14n-filler-20261106`（備份 `~/.km-control/agg-20261106/images.env.before-n`，`csit-mode.sh reapply` 即可還原）。已經寫進去的那份 SCU2060 仍含假資料，要刪除後重新上傳才會套用。

## Project is always asked (案子先確認)

- The project (案子, by CSIT number, else name, else document) is now what is counted, not the device model: two projects with the same device are asked about, never mixed.
- A project is recognised in the question by its name, number or document id; the choice restricts the query by document (`measurement_stats(documents=...)`), and "全部案子" (or 全部設備/全部專案) lifts it.
- A device that belongs to several projects asks which; one project alone is not asked, but the answer's 依據 line names it.
- A question about a report's content with no number to compute (吞吐量/換手/RvR/Test Case/測試結果 …) goes through the same technology → kind → project questions; a question about the projects themselves (案子/測試案例/任務) is not asked. Limit: after the project is chosen the document search is not filtered to it, only the question text carries the name.
- Web image `km-da40-web:zone-pages-20261106w` (rollback: `…v`, backup `override.before-w`).

## Device asked after the project; simulator can name the project

- After the project is settled, a project that holds several reports of the kind asked about (several devices) asks which device (options per device, same device twice told apart by document, plus 全部設備). A device, a document id or 全部設備 in the question settles it; one report alone is not asked.
- Simulator (`tools/csit_simulator`): a TestReport upload can carry `project`, `case`, `task` as `{number, name}` (UI: three pairs of fields when the source is 測試報告, defaulting to PRJ-001 / CASE-001 / TASK-001); blank falls back to the demo values.
- Images: web `km-da40-web:zone-pages-20261106x` (rollback `…w`, backup `override.before-x`); simulator `km-csit-simulator:20261107-project-fields` (rollback `km-csit-simulator:20261106-zones3`, backup `images.env.before-sim10`; recreate with the compose-simulator.yml of `~/.km-control/csit-mode`, KM_MODE_DIR set, `--no-build --pull never`). The simulator's data lives in `sim-data`, kept across the recreate.

## Handover reports: summary verdict, Handover Result, duration (2026-11-09)

- **Problem**: the two real handover reports (SCU2050, SCE2200) had 0 verdicts. The summary parser knew one layout only; SCE2200's per-handover sheet (new template: "Handover Result" Pass/Fail, "Handover Duration", a "copy raw data" table to the right) was mis-mapped, and its centre frequency is written in kHz (4849980), which overflowed the integer column (`REPORT_REJECTED`); its Small Cell B rows hold two values per row, which collided on one condition id.
- **Code**: `parser.py` (`_handover_summary` reads "3.n Xn Handover" / "Xn, N2 Handover Test" / "Intra-Band Test" + "Handover Mode"; NT blocks and unlabelled non-"Max." rows are not read; `_handover_columns` reads the first table only; `_centre_mhz` GHz/MHz/kHz; a repeated condition name on one sheet gets `_2`), new metric `handover_duration` (ms) in `metric_dictionary.json`, `query.py`, `zone_pages/stats.py`, `chunks.py`. Tests: `tests/csit_v1/test_handover_template.py` (20 items).
- **Images**: worker `km-csit-worker:v14q-handover-cond-20261109` (chain v14o → v14p → v14q on `v14n-filler-20261106`; images.env backup `~/.km-control/agg-20261106/images.env.before-o`), web `km-da40-web:zone-pages-20261109y` (override backup `override.before-y`; roll back by setting the image to `…20261106x`). Overlay sources `~/.km-control/agg-20261106/ov11`.
- **Verified live**: SCE2200 re-uploaded through the simulator, Completed; Timescale holds 2 verdicts (Xn, NG 100 times: pass), `ho_success_rate` 2, and 200 each of latency before/after, throughput before/after, `ho_success`, `handover_duration`, ping loss; `measurement_stats` on the web container returns the new metric.
- **Open**: the SCU2050 handover report ingested earlier still holds the old result (no verdicts); replacing it means deleting that simulator document (`fd8f5010…`) and uploading again, which was not done.

## Wi-Fi numbers are listed per channel (2026-11-09)

- **Problem**: "列出 CHS3320N 的 2.4G 所有 Throughput 測試數據" answered with average / min / max / median / p95 over Ch1, Ch6 and Ch11 ("n=3"), because `channel` was an optional dimension grouped on only when asked. The channels are different tests (one value each), so those statistics meant nothing and the report's channels never appeared.
- **Change** (`zone_pages/stats.py`): for `wifi_rvr` / `wifi_throughput`, `default_channels` adds `channel` and `center_freq_mhz` to `group_by` unless the question names a channel or asks for them taken together (整體、合併、所有通道平均…). An attenuation sweep (one value per attenuation) renders as one line per metric listing the values by attenuation under "Ch1（2412 MHz）", as the report's table does; no n / min / max for single values. Tests in `tests/zone_pages/test_stats.py` (2 new, 1 updated).
- **Image**: web `km-da40-web:zone-pages-20261109z` (override backup `~/.km-control/agg-20261106/override.before-z`; roll back by setting the image to `…20261109y`). Worker unchanged.
- **Checked on the real database** (CHS3320N RvR, 2.4GHz, 20MHz, downlink): the three channel lines equal the Excel table (Ch1 389.6 … 77.8, Ch6 421.8 … 144.4, Ch11 424.8 … 130). Values print with four significant digits, so 164.45 shows as 164.4 where Excel shows 164.5.
- **Not done**: the report's "Test Case_n" numbers are not stored (the parser keeps a case code such as `wifi_rvr:2.4GHz:20MHz` and the name "2.4GHz - 20MHz 衰減掃描"); showing them needs a parser change and a re-upload. The 5G reports were not reviewed for the same kind of merging.
