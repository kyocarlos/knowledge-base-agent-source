# KM DEV developer handoff memory

Baseline date: 2026-10-14. Branch: codex/km-dev-handoff-20261014.
Read README.md and docs/handoff/PATTY_DEVELOPMENT_HANDOFF.md first.
Source comes from the latest DGX first-party working tree plus deployed DEV Control source; source-origins.json and source-manifest.json provide hashes and provenance.
Focused integration/Human OIDC/binding suite: 240 passed in the new public-base test build. Disabled API sandbox rebuilt from an empty database: health ok, integrationEnabled=false, worker not started.
Processing timestamps.startedAt fix is included in this source; it remains undeployed in the existing DGX runtime. Failed timestamps.failedAt stays a separately authorized follow-up.
Existing live same-v3 job is Completed; preserve historical callback failures and never re-resume or resend it to validate new source.
This branch contains no live credentials, runtime data or model cache. Build/development readiness is not Production release or whole Phase 1 acceptance. Read validation.json for exact build/test coverage.
The original DGX working tree/runtime was not changed by this isolated handoff. Credentials are supplied through external protected files, never committed.

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
