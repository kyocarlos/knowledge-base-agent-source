# KM DEV 文件刪除整合盤點與補強（2026-11-13）

回覆 CSIT「KM DEV｜接續最後交接，優先處理文件刪除整合」。範圍僅 KM 端；未修改 CSIT、NAS、Production，未動 KM-DOC-000024 等四筆 Failed Job，未做 Failed→Processing 恢復，未啟用 CSIT KmDeletion，未改 .patch／PNG 解析。

## 1. KM 刪除 API 目前已完成與尚缺

盤點基準：KM 工作分支（基於 `269a5c0`）。GitHub 上沒有比它更新的 CSIT 整合程式（只有本分支在 `670e7c8` 之後有 CSIT 整合變更）。

| 項目 | 狀態 | 位置／證據 |
|---|---|---|
| `POST /api/integrations/csit/v1/document-deletions`，HTTP 202 | 已完成 | `doclib_api.py`；測試 `test_deletion_202_idempotent_and_conflict` |
| 持久化刪除工作後才回 202，同一交易寫墓碑並取消同來源進行中的工作 | 已完成 | `DocLibRepository.submit_deletion` |
| 冪等：同 `deletionRequestId` 回同一個 `kmDeletionJobId`；同 ID 不同資源回 409；`Idempotency-Key` 須等於 body id | 已完成 | 同上 |
| 授權：Shared Identity 服務 Token＋scope 檢查；未啟用時 503 | 已完成 | `authorize()`、`KM_CSIT_DOCLIB_ENABLED` |
| 背景清理（獨立 worker 迴圈、租約、重試、終態 Failed） | 已完成 | `DocLibWorker.delete_one` |
| 精確清理指定文件：Metadata、儲存副本、擷取文字、Chunks、Qdrant（以 `document_file_id` 精確過濾，只刪該檔）、Neo4j 關聯、搜尋快取 | 已完成 | `DeletionExecutor`；測試 `test_verified_deletion_removes_only_the_targeted_same_name_file` |
| 清理後重新查詢每個儲存，有殘留就不算完成 | 已完成 | `CLEANUP_NOT_VERIFIED`；測試 `test_unverifiable_cleanup_is_never_completed` |
| 刪除墓碑：晚到的、進行中的 Ingestion 不能重新索引；同檔重送回 `DOCUMENT_DELETED` | 已完成 | `test_late_ingestion_and_in_flight_job_cannot_resurrect_deleted_file` |
| `POST /api/integrations/km/v1/document-deletion-status` Callback（Processing→Completed、有序、同 callbackId 重送） | 已完成 | `doclib_client.py`、`build_deletion_callback`；七項皆 Deleted／NotPresent 才可 Completed |
| v2 路由 `/api/integrations/csit/v2/document-deletions` 與 v2 Callback | 已完成 | `v2_api.py`（本次不使用，未改） |

**本次盤點發現並補上的缺口**

1. **刪除 Callback 的授權範圍**：v1 刪除 Callback 需要 `csit.km.deletion-status.write`（CSIT Runtime 8fe25c60）。DEV 的對外 Token 沒有要求它，所以 KM 不會送這個 Callback。不能直接加進 `KM_CSIT_OUTBOUND_SCOPES`：CSIT 身分伺服器的 `scopes_supported`（2026-11-13 唯讀查詢）目前沒有登記這個範圍，一加入，整個 Token 請求會被拒絕，連帶所有一般 Callback 失敗。
   → 補上：刪除 Callback 使用自己的 Token（一般範圍＋`KM_CSIT_DELETION_CALLBACK_SCOPES`），一般 Callback 的 Token 不受影響；身分伺服器不給這個範圍時，只有刪除 Callback 失敗。預設為空，DEV 暫不開啟。
2. **快取清理未再次驗證**：七項之一的快取只清除、沒有再查。
   → 補上：清除後再掃描搜尋快取，仍有提到該文件的項目就不回報 `cleanupVerified=true`。
3. **「已接收但分析失敗」的文件缺少測試**：程式路徑原本就支援，但沒有測試證明。
   → 補上 4 組情境測試（見第 4 節）。

**尚缺（非 KM 可解）**：CSIT 身分伺服器尚未登記 `csit.km.deletion-status.write`；CSIT 端 `KmDeletion.Enabled=false`。

## 2. 本次修改與 Commit

分支 `agent/csit-deletion-readiness-20261113`（基於 `f21f90e`，本機提交，未推送）。

| Commit | 內容 |
|---|---|
| `6403f04` | 刪除 Callback 專用 Token 範圍（`ClientCredentialsProvider.headers(scopes=)`、`KM_CSIT_DELETION_CALLBACK_SCOPES`）、快取清除後再驗證、10 個隔離測試、override 註記 |

`.patch`／PNG 解析、v2 路由、其餘程式沒有改動。

## 3. KM DEV 部署結果

| 項目 | 值 |
|---|---|
| 程式碼 commit | `6403f04` |
| API 映像 | `km-csit-integration:6403f04-del-20261113`，ID `sha256:a24b64472532…` |
| Worker 映像 | `km-csit-worker:6403f04-del-20261113`，ID `sha256:73e80cc3c66c…` |
| 前一版（可回復） | `269a5c0-ocr-20261112`（API `sha256:f94dfb7080e3…`、Worker `sha256:c259fac9cb0f…`） |
| 建置 | 由 `git archive 6403f04` 乾淨建置，映像 revision label 皆為 `6403f04` |
| 套用 | `csit-mode.sh reapply`，未使用 `--force`；套用前進行中工作與待送 Callback 皆為 0；模式維持 real |
| 備份 | `images.env.before-6403f04`、`compose-real.override.yml.before-6403f04`；回復＝還原 `images.env` 後 `reapply` |
| 設定變更 | 無（`KM_CSIT_DELETION_CALLBACK_SCOPES` 預設空，DEV 暫不開啟，原因見第 1、6 節） |

Smoke Test（已部署的容器）：API 與 worker healthy；`KM_CSIT_MODE=real`；一般對外 Token 範圍不變（`csit.document.read`、`csit.ingestion.status.write`、`csit.km.status.write`）；刪除路由未帶 Token 回 401；API 與 worker 日誌無錯誤。部署後唯讀確認：KM-DOC-000024 與 KM-ING-000017／000018／000020 仍為 Failed 且更新時間未變；208 筆 Callback 全為 Delivered；既有 58 筆刪除工作未變動。

## 4. 刪除測試與 Callback 驗證結果

全部以隔離 PostgreSQL 與替身 CSIT／Qdrant 執行，未碰任何真實資料或 CSIT。

新增 10 項：

| 測試 | 驗證內容 |
|---|---|
| 已接收但分析失敗（`UNSUPPORTED_DOCUMENT_FORMAT`，未下載、無索引） | 刪除 Completed、`cleanupVerified=true`；七項中 metadata=Deleted，其餘六項經查核為 NotPresent；失敗紀錄保留但內容清空；墓碑建立，同檔重送回 `DOCUMENT_DELETED` |
| 失敗工作留下儲存副本 | `storedCopies=Deleted`，目錄移除 |
| 已接收尚未開始的工作 | 被取消、不會再開始；刪除 Completed、無下載、無索引 |
| KM 從未收到過的來源 | 刪除 Completed、七項皆 NotPresent，之後同檔 Ingestion 被墓碑拒絕 |
| 快取仍有殘留 | 不回報 Completed，工作標 `CLEANUP_NOT_VERIFIED` 重試 |
| 快取已清除且查核無殘留 | `cache=Deleted`、`cleanupVerified=true` |
| 刪除 Callback 專用範圍 | 下載與一般 Callback 用一般 Token；刪除 Callback 用「一般＋刪除」範圍；全部 Delivered |
| 未設定刪除範圍 | v1 刪除 Callback 保留為 Pending（`M2M_SCOPE_MISSING`），一般 Callback 照常 Delivered |
| Token 依範圍集合分別取得與快取 | 兩種範圍各請求一次、各自快取 |
| 身分伺服器不給刪除範圍 | 只有刪除 Token 失敗（`M2M_SCOPE_MISSING`），一般 Token 不受影響 |

既有測試（含 v1.3 刪除、精確刪除、晚到 Ingestion、墓碑、Callback 重試矩陣）全部通過。

回歸：`tests/csit_v1` 與 `tests/csit_simulator` 共 **615 通過**、4 略過、5 失敗；部署前基準（`269a5c0`，同一指令）為 605 通過、4 略過、同樣 5 失敗（Neo4j 與 Timescale 真實連線各 1、區域專區授權選擇 3，需正式資料，與本次無關）。新增 10 項即為差額。另在已部署的 worker 映像內再跑刪除、.patch／PNG、Callback 重試與文件庫測試，69 項全部通過。

## 5. 是否已具備與 CSIT 執行真實刪除 E2E 的條件

KM 端程式與 DEV 部署已就緒，但**目前還不能執行真實刪除 E2E**，缺以下 CSIT 端條件：

1. CSIT 身分伺服器登記 `csit.km.deletion-status.write`（2026-11-13 唯讀查詢 `scopes_supported` 尚無此範圍）。
2. CSIT 啟用 `KmDeletion.Enabled`。
3. CSIT 呼叫 `POST /api/integrations/csit/v1/document-deletions` 使用的服務 Token 須帶 `km.ingestion.submit`（KM 此路由接受的範圍）。

上述 1 完成後，KM 只需把 `KM_CSIT_DELETION_CALLBACK_SCOPES=csit.km.deletion-status.write` 加入 DEV 設定並 `reapply`，不需再改程式。

建議的 E2E 順序：先用一筆新建、未涉及四筆 Failed 的測試文件走 Ingestion→刪除；再對 KM-DOC-000024 送刪除單（`deletionRequestId` 為 CSIT 既有刪除單）。KM 預期結果：Processing→Completed，七項中 metadata=Deleted、其餘 NotPresent，Job 仍保留 Failed 紀錄但內容清空。

## 6. 尚未完成的阻礙

1. CSIT 尚未登記 `csit.km.deletion-status.write`，KM 無法取得送刪除 Callback 所需的 Token（KM 端不能繞過，也未要求 CSIT 放寬）。
2. CSIT `KmDeletion.Enabled=false`。
3. 若 CSIT 在第 1 點完成前就送刪除單：KM 會接收、清除並驗證，但 Callback 會被保留，重試約 21 分鐘後成為終態 Failed（Callback 重試窗口在上一份交接已說明）；清除本身不受影響。建議 CSIT 等第 1 點完成後再啟用。
4. 本次只盤點到 repo 內的 v1.3 第 7 節刪除契約；repo 內找不到標示為「v1.2 Appendix B」的文件，驗收是對照 CSIT 這次列出的各項要求。若 Appendix B 另有欄位或狀態碼要求，請提供原文以便逐項比對。
5. 搜尋快取的清除是整批清除 `search:*`（既有設計）；快取查核只掃描文字內容是否含該文件 ID。
