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

## 2026-10-23：知識專區導覽調整（來源分支 `codex/frontend-style-20261023`）

使用者指定 GitHub branch `codex/frontend-style-20261023`、起始提交 `af67d4d67b23c14d65c451d79a22e999132c9f7a` 與 `docs/codex-frontend-style-brief.md`，要求依資料讀取並開始修改。當前工作區原先只有空白 Git metadata，已設定該 repository 為 `origin` 並 checkout 指定 branch；使用者要求將修改提交並供遠端 DGX Claude 取得，工作範圍不包含部署。

使用者先前明確要求左側 CSIT 知識專區改名為「CSIT雜項專區」、在「4G/5G 知識專區」下增加「CPE知識專區」和「Smallcell知識專區」，並新增「設備預約知識專區」。在 `frontend/chat-v2.html` 完成：左側導覽呈現兩個 4G/5G 縮排子專區；新增設備預約頂層入口；`knowledgeZones` 加入四個專區對應名稱與查詢情境，沿用原有 KM 查詢流程，更新 CSIT 顯示名稱和助手提示。390 px 實測發現原聊天欄位超出卡片，已在行動版 CSS 限制聊天容器寬度並讓訊息換行。沒有改 API、WebSocket、WiFi CSS/JS 或後端資料處理。

`docs/handoff/source-manifest.json` 需同步 `frontend/chat-v2.html` 與本記憶檔的 SHA-256。Playwright 使用既有 Microsoft Edge 開啟本機 HTML：1280 px 下四個新／改名專區皆可切換並更新查詢範圍；CPE 鍵盤 Enter 切換成功；390 px 下 viewport/document 寬度同為 390，聊天訊息與輸入列均在卡片內；page errors 為 0。這不是已部署站台驗收。提交前嘗試執行 handoff verifier 與簡報列出的 pytest suite：來源 verifier 在 Windows checkout 列出大量未修改檔案 hash mismatch；確認 repository 設定 `core.autocrlf=true`，例如 README manifest hash 為 `e656c7...`、工作副本為 `15d076...`，屬於 CRLF/LF 差異；本次 chat-v2.html 工作副本 hash 與 manifest 相符。Bundled Python 沒有安裝 `pytest`（`No module named pytest`），故 pytest suite 未執行。未進行已部署站台的 runtime 驗收或部署；交接內容須明示這些限制。

將已暫存的 Git index 以 `core.autocrlf=false` 匯出至暫存目錄，再執行原始 `scripts/verify-handoff-source.py`，結果 `SOURCE MANIFEST PASS: 575 files`；`git diff --cached --check` 亦通過。暫存檢查目錄已移除。
