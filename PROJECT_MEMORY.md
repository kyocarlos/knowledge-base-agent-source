# KM DEV developer handoff memory

Baseline date: 2026-10-14. Branch: codex/km-dev-handoff-20261014.
Read README.md and docs/handoff/PATTY_DEVELOPMENT_HANDOFF.md first.
Source comes from the latest DGX first-party working tree plus deployed DEV Control source; source-origins.json and source-manifest.json provide hashes and provenance.
Focused integration/Human OIDC/binding suite: 240 passed in the new public-base test build. Disabled API sandbox rebuilt from an empty database: health ok, integrationEnabled=false, worker not started.
Processing timestamps.startedAt fix is included in this source; it remains undeployed in the existing DGX runtime. Failed timestamps.failedAt stays a separately authorized follow-up.
Existing live same-v3 job is Completed; preserve historical callback failures and never re-resume or resend it to validate new source.
This branch contains no live credentials, runtime data or model cache. Build/development readiness is not Production release or whole Phase 1 acceptance. Read validation.json for exact build/test coverage.
The original DGX working tree/runtime was not changed by this isolated handoff. Credentials are supplied through external protected files, never committed.

## 2026-10-16：WiFi 知識專區版面移植與 TEST／DA40 完成驗收

使用者最後確認 WiFi 專區應沿用 `https://61.216.9.52:3030/chat-v2.html` 的深色網格、薄荷綠／青色與半透明卡片風格，而不是 localhost 8766 的淺色參考風格。在 branch `codex/cross-search-source-credentials-20261015` 完成 `/wifi8/` SPA；`chat-v2.html` 只將原 WiFi 入口改為同頁導向 `#/overview`，其畫面、WebSocket、搜尋與其他專區行為不變。

LLM 說明與結論：

- SPA 用單一設定表產生導覽，完成 overview、documents、AI Agent、jobs，串接文件分頁／篩選、目前／歷史版本、metadata、chunks、版本關係、BM25＋向量 RRF、Agent 引用／tool trace／stop reason 與具權限匯入。其他六頁明確標示「功能待移植」，無假資料或誤觸動作；舊 `/wifi8-import.html` 導向 `#/jobs`。
- 新增 session-protected overview、documents/detail/chunks、search、jobs API，保留 status、agent、packages 與 job detail；有長度／分頁／回傳量限制，不接受任意 SQL／path／collection，上傳 UI 以目前帳號權限判定。真實瀏覽器發現的 stale hash render 競態已用 render token 修正。
- Tests：WiFi import/search/agent/routes `24 passed`；JS syntax 與 diff check PASS。TEST Webwright 全綠：503／368／135／31,395、ELR 文件、detail/chunks/versions、NPCA 混合搜尋、Agent 與 5 引用、jobs、佔位頁、其他專區回歸、390/760/1024/1440 無溢位，console error/failed request 皆 0。DA40 job `wifi8-import-20261016T062515Z-282e90db` 已完成並切換 current：503 documents、368 current、94,528 segments、31,395/31,395 ready，active job none；DA40 獨立 Webwright overview 與 ELR Agent PASS。
- Source commits：`b67c223`、`98a01fc`、`2eee1ef`。TEST image ID `sha256:43efcaa708f...`，DA40 `sha256:01b62b8adfdb...`；runtime route SHA `c2ba0c5fc067...`。靜態使用 hash CSS/JS 並與 source SHA 一致。原 workers/Nginx 保持 running，Production 未修改。詳細 source/runtime/備份/回復記錄見 `docs/handoff/WIFI8_WORKSPACE_20261016.md`；evidence 位於 `/home/da40_ai_gb10/.km-control/wifi8-deploy-20261016/`。

最終狀態：**WiFi 知識專區已在 KM DEV TEST 與 DA40 完成版面、功能、部署與驗收；Production 未觸及。**

## 2026-10-14 canonical contract adoption source checkpoint

User authorized the exact CSIT-System commit 3a9ae52f04625aeee5fd01e7a3565f5972fc9122 as the only current Integration v1 wire authority, requested all listed drift fixes, KM DEV deployment, deployed-runtime deterministic offline verification, integration disabled, and no new Live E2E. Remote identity spark-7546/da40_ai_gb10 and clean branch baseline b3aa002556c7905e3d91691420dbcdc7b7f19ba1 were confirmed. No password is retained.

Four exact schemas were fetched from the pinned raw commit; SHA-256/byte parity passed. Source now uses UUID types, required nullable reference number/name, positive sizeBytes, a single production callback builder with Failed.failedAt=last_error_at, a six-column nullable migration, principal_type=service defaults, a canonical schema test suite, valid UUID fixtures, legacy/current contract labels, push-triggered CI gate, and an offline verifier module packaged into the API image. Final complete isolated suite passed 261 tests plus the packaged offline verifier. The real DEV API is still the old image sha256:396b9c03... with KM_CSIT_ENABLED=false and healthy; worker image sha256:da1178eb... is OFF. Real KM Control DB public.km_csit_ingestion_jobs has one Completed job; six lineage columns are NOT NULL. No new job, callback, Live E2E, or DEV deployment has occurred yet. Next: source commit/push/CI, then controlled DB migration/API+stopped worker image deployment with rollback evidence and actual runtime offline verification.

## 2026-10-14：KM ↔ CSIT Integration v1 canonical contract adoption 與 KM DEV 部署完成

使用者指定 CSIT-System commit `3a9ae52f04625aeee5fd01e7a3565f5972fc9122` 的 `contracts/csit-km-integration-v1/` 四份 JSON Schema 為唯一 current Integration v1 wire authority，要求修正全部列出的 drift、CI hard gate、full tests、DEV 部署與實際 runtime code deterministic offline verification；integration 必須 disabled，不能執行新 Live E2E。SSH 使用者 `da40_ai_gb10`，主機 `spark-7546`，使用者本次提供密碼驗證；密碼未寫入任何檔案或記憶。

LLM 說明與結論：
1. 在隔離 checkout `/home/da40_ai_gb10/.km-control/patty-dev-handoff-20261014/source` 的 `codex/km-dev-handoff-20261014` branch，從 baseline `b3aa002556c7905e3d91691420dbcdc7b7f19ba1` 完成 source。四份 schema 直接從 CSIT 固定 commit 取得，保留原始位元組；`UPSTREAM.json` 記錄 repository/commit/path/四份 SHA-256。sync script 對固定 commit 原件做 byte/hash parity，四份 PASS，不使用 latest/main。
2. IngestionRequest 的 eventId/documentId/project.id/case.id/task.id 改為 Pydantic UUID，JSON dump 是 UUID string；Reference number/name 是 required nullable，允許空字串；Document.sizeBytes 最小 1，原有 filename/path/MIME 安全驗證保留。六個內部 lineage `*_code`/`*_name` 欄位透過正式 migration 改為 nullable；wire 仍為 `number`。測試證明 null 從 schema/model validation 經 repository 到 request_payload 和 lineage 均原樣保存。
3. 新增唯一 `build_callback_payload`，實際 Repository._outbox 與 tests 共用。Processing 維持 `updatedAt`/`startedAt`，Completed 維持 `updatedAt`/`completedAt`，Failed 改為 `updatedAt`/真實 `last_error_at` 的 `failedAt` 並帶 error.code/message。移除先前期待缺少 failedAt 的錯誤測試。Shared Identity 預設只修 `principal_type=service`，未改 credential、client 註冊、scope、audience 或 token endpoint。舊 Manifest contract 檔案與路徑保留並明確標示 LEGACY；current tests/CI 不引用它。
4. Source code commit `bbc6039a142a8359fe7a3361deb7e715e12092f2` 已推送至指定 branch。完整隔離 CSIT v1/Human OIDC/Binding/相關 KM regression **261 passed**，packaged offline verifier PASS；GitHub push CI run `https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/38524774749` success。交接 source manifest 420 files 在 code commit 通過；本次最終文檔與記憶更新後再刷新驗證。
5. 由該 source commit 建立 API image `sha256:1555da50b77c7609cb82d9d8246c2a029689deabae677227698105fb5c001d84` 與 worker image `sha256:57157596cc082146e0c30730ae65d7edf99d264afe054a4f1c30bd1255aa05d9`，皆有 image revision label。兩個 image 在 `--network none` 的 offline verifier PASS。DEV metadata DB `km_control.public` 已套用六欄 nullable migration，原有 1 Completed job 與 callbacks Delivered 1/Failed 3 均保留不變。
6. 實際 DEV API container `fb635e28c242f58a14b49cad058e99878df4ced57c3f8745c2fd4a3d4859c68e` 運行中/healthy，health 為 `status=ok, integrationEnabled=false`，KM_CSIT_ENABLED=false。worker container `ce7f0d85564a6fa3ff960ed210df1fb53c250388808c9f16468e9075feef8230` 使用新 image，狀態 created/OFF，KM_CSIT_ENABLED=false。running API container 直接執行 production offline verifier PASS，10 個 deployed source/schema 檔案 hash 與 branch source 相同。原 DEV Compose 僅替換兩個 image tag，受保護 override、原 Compose 備份、前後 runtime/DB/health/CI evidence、rollback 指引存放 `/home/da40_ai_gb10/.km-control/csit-canonical-20261014/`，未記錄 secret。
7. 沒有發出新 ingestion/document pull/callback、沒有新 job、沒有重送或 resume 既有 Completed job、沒有執行 Live E2E。Human OIDC 真實登入、CSIT live callback 與 graph/numeric 業務場景仍待後續受控驗收；本次不能宣稱 Integration v1 完成或 Production acceptance。

**最終狀態：READY FOR CLEAN LIVE E2E。** 這代表 KM DEV code/schema/migration/image/disabled runtime/CI 已準備好做下一次受控的新事件驗收；integration 繼續 disabled，worker OFF。公開詳細證據：`docs/handoff/CSIT_CANONICAL_ADOPTION_20261014.md`。正式 source commit `bbc6039a...` 與實際 image revision 一致；之後的文檔記憶 commit 不改變 deployed code identity。

### 2026-10-14 callback builder canonical guard follow-up — source verified, deployment pending
Final audit found the production callback builder could serialize a Failed payload with blank error.code or error.message if handed an invalid internal IntegrationError. The builder now validates every built callback with its exact vendored canonical JSON Schema before Repository._outbox writes it. Four new tests prove blank/whitespace Failed fields are rejected at the production builder. Full isolated suite and packaged verifier reran: 265 passed, offline PASS. Existing deployed DEV images remain revision bbc6039 pending this follow-up code commit, CI and controlled image replacement. No Live E2E or new job/callback was executed.

### 2026-10-14 follow-up final: production callback builder schema gate deployed
The four new negative tests exposed malformed internal Failed error fields before outbox insertion. Production `build_callback_payload` now validates every callback payload with the exact vendored canonical schema and FormatChecker, including nonblank Failed error fields. Code commit `45108b1fb4a4672945d99238080f75069929f2ec` was pushed; full isolated suite 265 passed and packaged offline verifier PASS; GitHub CI run 38527129749 success. New API image sha256:64c88c2b463a798034a6e18ff45d9665cfcd48cdc7da65ec270d480f9aa6df33 and worker image sha256:d9613774ed05764314f2cce85f370fe1b3e34f4c30688d892ed15d2bddcb2c58f passed network-none offline verification and are deployed to KM DEV. API container 137abd9c24cbb5635084a8d4bcc05e0e285099ca4c4eea67645d8933291fccf71 is running/healthy, health status=ok/integrationEnabled=false; worker container 6f02a948ec07505c4daeb90048544b74d3195711839712b8feb62c88be4217a91 is created/OFF. Both have KM_CSIT_ENABLED=false and the code revision label 45108b1. The actual running API offline verifier PASS and ten source/schema SHA-256 values match checkout. `km_control.public` still has 1 Completed job, callbacks 1 Delivered/3 historical Failed, and all six lineage columns nullable. No new Live E2E, job, callback, or completed-job replay. Protected evidence and rollback paths are at `/home/da40_ai_gb10/.km-control/csit-canonical-20261014/`. Final status: READY FOR CLEAN LIVE E2E, with integration disabled and worker OFF; no Production acceptance claim.

## 2026-10-26：WiFi 專區深色介面優化分支

依使用者確認的深色網格、薄荷綠／青色方向，建立 `codex/wifi8-ui-polish-20261026`，以 `codex/wifi8-ui-20261026` 為基礎，調整 WiFi 專區共用樣式、窄螢幕導覽與 AI 面板繁中標籤。只修改 `frontend/wifi8/` 的 index、JS、CSS；`frontend/chat-v2.html` 與後端未變更。串流、回饋、新對話、分頁 sessionStorage 還原、LaTeX 轉純文字、引用與圖片縮圖程式及 `/api/wifi8/*` 路由均保留。新資產名稱為 `wifi8.267a4eaaedb8.js`、`wifi8.cf74a2f34cff.css`，雜湊按 Git blob bytes 計算，`index.html` 已更新。

驗證：`node --check` 通過；新檔名 SHA-256 前 12 碼與 Git blob 相符；API 路由字串和基線一致；既有功能標記齊全；`git diff --check` 通過。GitHub 分支已建立並推送，程式碼提交 `c49eaa543fbea8556c6679e9c79ca48988793cf1`。未部署至 TEST／DA40；後續由使用者部署並進行瀏覽器實測。
### 2026-10-26 後續：移除研發中樞左側技術知識專區

使用者要求移除截圖紅框中的左側導覽項目。已在 `frontend/chat-v2.html` 移除 `data-knowledge-zone="technical"` 導覽連結一行，其餘 CSIT、WiFi、4G/5G 子專區與設備預約入口未動。檢視差異確認只有該導覽連結被移除；`git diff --check` 通過。待提交並推送至 `codex/wifi8-ui-polish-20261026`，不觸及 TEST／DA40 部署。
### 2026-10-26 後續：新增 Confluence／Jira／TestRail 查詢專區

使用者要求在 chat-v2 左側 Knowledge zones 主功能列表加入「Confluence / Jira / TestRail 查詢專區」。已新增可點選入口、專區查詢上下文與 TestRail 範例提問；選取機制沿用既有 `data-knowledge-zone` 事件處理，既有聊天請求會包含該專區的名稱與 context。未改後端或新增外部連線，實際可查資料仍取決於既有 KM 助理與知識庫來源。靜態程式檢查確認入口、設定與上下文流程接通，`git diff --check` 通過。待推送至既有 `codex/wifi8-ui-polish-20261026` 分支；尚未部署。
### 2026-10-26 後續：頁首標題同步目前知識專區

使用者指出頁首仍顯示「研發知識中樞」，希望隨左側 Knowledge zones 選擇同步。已為 h1 加入 `knowledgePageTitle`，並在既有 `selectKnowledgeZone` 中以所選 zone 的 label 更新 textContent；DOMContentLoaded 的初始 CSIT 選取也會設定為「CSIT雜項專區」。因此其他使用既有知識區切換流程的專區同樣會顯示各自名稱，WiFi 入口仍依既有流程導向 WiFi SPA。靜態檢查確認所有 zone label 與頁首更新接點存在，`git diff --check` 通過。待推送至 `codex/wifi8-ui-polish-20261026`；未部署。
## 2026-11-17：CSIT 設備 AI 綜合分析完整實作（CSIT requirement doc）

Patty 轉交的 CSIT 需求文件要求一次完成單檔技術擷取、LLM 錯誤處理、設備跨文件綜合分析、可靠工作流程與 callback、測試與驗收，並在有核准部署程序時直接部署到 KM DEV。CSIT 指定的工作分支 `feature/csit-spec-v14-20261105` 實際上是 11/5 的舊 zone 分類需求、已併入 main，與本次無關；改用新分支 `feature/equipment-aggregate-analysis-20261117`，從 CSIT-System 在 Patty 指定的 baseline commit `d4d11f05486efe2be2ca74f8ab4f3808060500a1` 直接取得 `EquipmentAggregateAnalysisContracts.cs`、`EquipmentAggregateAnalysisService.cs`、`KmAnalysisCallbackController.cs`、`KmAnalysisContracts.cs`（含 `KmAnalysisMetadataValidator`）、`EquipmentKmMetadataProjection.cs` 等真實契約逐欄核對，不是自行設計的格式。

LLM 說明與結論：

1. 單檔技術擷取（doclib_metadata.py / v2_pipeline.py / v2_worker.py）：`technical` 的 11 個字串陣列欄位與 `measurements`、以及 EquipmentAttachment 的 `sourceSpecific.specifications/capabilitySummary/limitations` 改為實際從文件內容擷取，每一項技術事實都要求在原文中逐字出現才保留（不得猜測）。過程中發現兩個會被 CSIT 拒收的格式問題並修正：`measurements[].value` 依 CSIT 的 `KmAnalysisMetadataValidator.ValidTechnical` 必須是字串而非數字；`sourceSpecific.specifications` 依 CSIT 的 `EquipmentKmMetadataProjection` 必須是 `{field,value}` 物件而非句子字串（句子字串會被其 `Specification()` 直接丟棄）。
2. LLM 錯誤處理（doclib_llm.py / doclib_metadata.py）：新增 HTTP 429/5xx/timeout/連線錯誤的重試與退避（含 Retry-After），區分可重試與不可重試錯誤；重試用盡後拋出 `IntegrationError`，交給既有 job 層重試機制（`fail_job`/`retry_delays`），不再被 `except Exception` 整個吞掉後靜默回報空陣列成功。回覆無法解析成 JSON 時加一次修正提示重試，仍失敗則用明確標記讓 warnings 說出真正原因。
3. 設備跨文件綜合分析（equipment_aggregate.py / equipment_aggregate_models.py）：新增 `POST /api/integrations/csit/v1/equipment-aggregate-analyses`（預設關閉，`KM_CSIT_EQUIPMENT_AGGREGATE_ENABLED=true` 才啟用），依 CSIT manifest 的 FileId/Version/Sha256/KmJobId 核對 KM 自己已完成的單檔分析結果，識別不符就排除、從不假裝匹配；文件描述一致就合併並帶上所有來源 evidence，不一致就列入 conflicts 從不自行挑值；AnalysisResultId 原樣回報 CSIT 給的值，EvidenceId 由 KM 自行產生；沒有任何文件有技術內容時結果為空，不會裝成分析成功。
4. 可靠工作流程與 callback（equipment_aggregate_repository.py，新表 `km_csit_equipment_aggregate_requests`）：沿用既有 lease/attempt_count/next_retry_at 去重與重試模式，callback 透過既有 `km_csit_v13_callbacks` outbox 發送（Idempotency-Key=callbackId），沒有另建機制。`doclib_client.py` 新增 CSIT 409 回覆的五種分類（feature_disabled/callback_id_conflict/stale_or_mismatched_manifest/request_already_failed/stale_manifest），全部判定不可重試。
5. 測試：`tests/csit_v1/` 在隔離容器（無網路、用完即丟的測試 Postgres）跑了 **614 passed**，另 5 個既有失敗（neo4j/timescale 需要真實服務、test_zone_regression 缺少模組）已確認在 main 上同樣存在，與本次改動無關。涵蓋三份文件整合、跨文件矛盾、無技術內容文件、SHA256/KmJobId 不符排除、429/5xx/timeout/無效JSON 重試與退避、409 五種分類、worker lease 過期後被接手重啟恢復、lease 被搶走後 LeaseLost、重試耗盡轉 Failed、M2M 未授權(401)與 scope 不符(403)。**未做**：需要 CSIT 實際部署其契約才能跑的真實 CSIT×KM E2E（不屬於 KM 單方可完成的範圍，依規範不得用 Mock PASS 宣稱已完成）。
6. KM DEV 部署：對真實 `km_control` 資料庫 `public` schema 執行受控 migration（新表/序號/索引，callback outbox 的 kind check 增加 `equipment_aggregate`），確認既有 22 筆 v2 jobs、220 筆 callbacks 不受影響；`csit-mode.sh status` 確認部署前 `real` 模式 in-flight=0 才動手。用既有 Dockerfile（`~/knowledge-base/deploy/csit-integration-v1/Dockerfile`、`Dockerfile.worker`）以 commit `556643b` 建置新影像 `km-csit-integration:556643b-equipment-aggregate-20261117`、`km-csit-worker:556643b-equipment-aggregate-20261117`，更新 `~/.km-control/csit-mode/images.env`（舊值備份於 `images.env.before-556643b-equipment-aggregate-20261117`，容器 inspect 備份於 `~/.km-control/equipment-aggregate-deploy-20261117/`），用既有 `csit-mode.sh reapply` 換上新影像。部署後 health 正常、既有 `/api/integrations/csit/v1/ingestion-jobs`、`/api/integrations/csit/v2/document-jobs` 行為與之前完全一致（401 無效 token），新入口已存在且走同一套認證（401），in-flight 仍是 0，worker/api 日誌無新錯誤。新功能因預設關閉，對現有真實 CSIT 對接流量零行為改變。

Source commit：`556643b6f04083b3fd2cd1eded295fa26a0cc429`，分支 `feature/equipment-aggregate-analysis-20261117`（已推送 origin，**尚未**併入 main）。

**最終狀態：KM DEV 的 `km-csit-integration-api`/`km-csit-v1-dev-worker-1` 已換上含設備跨文件綜合分析功能的新影像並驗證無回歸，功能本身預設關閉待雙方驗收。尚未併入 main、尚未與真實 CSIT 做過這個新功能的真實端對端測試。**

## 2026-11-17：RCA 指標好壞方向（km_test.metric_dictionary.higher_is_better）
- 正式 DA40 的 km_test.metric_dictionary 原本 24 筆 higher_is_better 全為 NULL（比較只能標示 changed）。已填入 23 筆，total_count 刻意維持 NULL（只是筆數）。
- True：throughput、throughput_before_ho、throughput_after_ho、throughput_variation、rsrp、rsrq、rssi、sinr、ho_success、ho_success_rate、pass_count、pass_rate。
- False：fail_count、handover_duration、latency_rtt、latency_rtt_before_ho、latency_rtt_after_ho、latency_variation、max_latency_variation、max_ping_loss_count、max_throughput_variation、ping_loss_count、udp_lost_ratio。
- 這是工程慣例預設值，尚未經 CSIT 領域人員確認（尤其 latency_variation／throughput_variation 這類換手前後差值）。值只存在資料庫，重建資料庫需重新套用。
- 驗證：用唯讀 RCA 連線比較 2 份 wifi_throughput 報告，directions_defined=23，diffs 出現 improvement／regression（regression 85 筆）。CSIT 連動不受影響（in flight=0，api／worker healthy）。
- 還原：UPDATE km_test.metric_dictionary SET higher_is_better = NULL;
- 後續：src/report_numeric/query.py:150 仍寫死「higher_is_better 尚未定義」提示，尚未調整。

## 2026-11-17：RCA 歷史雜訊門檻（分支 rca-noise-threshold，commit ef63784 + 95e19d0，尚未併入 main）
- 比較與重點範圍的「顯著差異」門檻，改為「固定門檻」與「同產品、同報告類型歷史報告自然波動的 3 倍（中位數／MAD）」中較大者；歷史只會讓判斷更保守。少於 5 份歷史報告時沿用固定門檻，並在 pack.noise 與 findings.noise 說明。新增 src/report_numeric/noise.py，改 compare.py／findings.py／rca.py（提示新增 noise 說明）／rca_service.py／rca_routes.py（共用 compare.build_pack）。
- 部署：疊加映像 km-da40-web:rca-noise-95e19d0（底 km-da40-web:llm-usage-0e9a163）、km-test-web:rca-noise-95e19d0（底 km-test-web:llm-backup-86afb14），override 檔 ~/.km-control/compose/km-da40.rca-noise.image.override.yml，只重建 web 與 celery_search_worker。
- 驗證：新測試 11 筆通過；正式報告實測結果與部署前完全相同（132 筆顯著差異）。目前每個產品只有 1 份報告，所以此功能暫不會生效，等同一產品累積到 6 份以上才啟動。
- 還原：以 llm-profiles（web）與 llm-backup（worker）override 為最後一個檔重新 up 即回到 llm-usage-0e9a163／llm-backup-86afb14。
- 已知既有問題：tests/zone_pages/test_zone_pages.py::test_the_page_endpoints_answer_in_the_wifi_pages_shapes 在 main 上本來就失敗，與本次無關。

## 2026-11-18：CSIT v2 equipmentId 改為文字編號（修正設備附件刪除 HTTP 400，分支 agent/csit-v2-equipment-id-string-20261118，commit 4aa54cc，已推送 origin，尚未併入 main）
- 原因：`v2_models.py` 的 `V2Source.equipmentId` 與 `V2Resource.equipmentId` 是 `Optional[UUID]`，但 CSIT 送的是既有設備編號（`ApparatusFile.ApparatusId`，例如 A202611010810254176647，22 字元，不是 UUID）。重現結果：`resource.equipmentId`、`uuid_parsing`，API 回 400 `INVALID_CSIT_CONTRACT`。API 日誌與 kb-nginx 日誌在保留期間內沒有該筆真實請求，所以欄位是用同一份 payload 在部署前的程式碼重現確認，不是讀日誌。
- 修正：`equipmentId` 改為文字（1 到 128 字元、不得含控制字元），原樣保存在 request_payload、resource、清理執行檢視與 callback 回聲，不轉成 UUID；UUID 形狀的值仍可用（當文字）。其他欄位與文件類型不變。DB 的 `km_csit_deletion_jobs.source_type` 約束（DEV 實測）已包含 VendorFile／EquipmentAttachment，無需 migration。
- 測試：拋棄式 Postgres 上跑 tests/csit_v1、tests/csit_simulator、tests/test_csit_equipment_synthesis.py，713 通過；新增 3 組測試（含編號 A202611010810254176647 經 document-jobs 與 document-deletions 回 202 且儲存值不變）。另外 6 筆失敗（test_timescale_real_retry_no_duplicates、test_invalid_required_timestamp_rejected、CORRUPT_FILE 一筆、test_existing_zone_grant_selection 三筆）在未修改的 main 上同樣失敗，與本次無關。
- 部署（KM DEV）：部署前 in flight=0。用既有 Dockerfile（~/knowledge-base/deploy/csit-integration-v1）以 4aa54cc 建 `km-csit-integration:4aa54cc-equipment-id-20261118`（sha256:d3a95ad2cbffbdf2b4783b9925bf11bcd10d089a94bdcd4ab67a0e954bd8cfff）、`km-csit-worker:4aa54cc-equipment-id-20261118`（sha256:ff592373d0627d753a1ffa32b1ab973077334cb98a7dc1f2d55157bdd81ab201）。images.env 舊值備份 `~/.km-control/csit-mode/images.env.before-4aa54cc-equipment-id-20261118`，容器 inspect 備份 `~/.km-control/equipment-id-deploy-20261118/`，用 `csit-mode.sh reapply` 換上。注意：映像由 main 後續 commit 建成，所以 worker 影像也帶入 RCA 雜訊門檻的 report_numeric 檔案（只影響 RCA 讀取端，不在 CSIT 入庫路徑）。
- 驗證：API／Worker healthy、in flight 0；兩個容器內以 A202611010810254176647 驗證 v2 刪除請求皆通過；經 kb-nginx 所有 csit 路由無 token 皆回 401；`KM_CSIT_EQUIPMENT_AGGREGATE_ENABLED` 仍為 false。沒有重送 CSIT 那筆真實刪除工作。
- 還原：`cp ~/.km-control/csit-mode/images.env.before-4aa54cc-equipment-id-20261118 ~/.km-control/csit-mode/images.env && ~/.km-control/csit-mode/csit-mode.sh reapply`（回到 556643b-equipment-aggregate-20261117）。
