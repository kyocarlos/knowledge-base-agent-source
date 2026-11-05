> **已回覆(2026-11-05)**:本文件的 11 題已由 CSIT 以 v1.4.1 定案(見 `CSIT_KM_v1.4.1_Anderson_11題正式回覆.md`)。KM 端的處理見 `csit-v14-implementation-record-20261105.md`。以下保留原提問僅供對照;其中 scope 名稱 `csit.documents.read` 以 v1.4.1 的 `csit.document.read`(單數)為準。

# CSIT × AI KM 介接規格 v1.4：KM 端待 CSIT 確認事項

KM 端已依 v1.4 規格完成實作，目前僅在內部測試，尚未部署到 DEV。以下是規格未寫死、需要 CSIT 確認的項目。
**第 1～5 題會影響能否上線**，第 6～11 題為格式與細節確認。

---

## 一、測試報告的 v2 分析結果（§5.4 `analysis-results`）

| # | 問題 |
|---|------|
| 1 | `sourceEntityId` 規格寫「來源 `ModuleCaseFile.Id`」，但現行 v1 `ingestion-jobs` 送來的資料沒有這個欄位（v1 也不接受額外欄位）。它是否等於 v1 的 `documentId`？若不是，請提供取得方式（在 v1 資料補欄位，或另給對照）。 |
| 2 | `csitJobId` 規格寫「使用對應 Outbox.Id」。這是否就是 v1 資料裡的 `eventId`？還是另一個 ID？ |

> 第 1、2 題確認前，KM 的這項功能先關閉，不會送錯 ID。

## 二、DEV 7444 通道

| # | 問題 |
|---|------|
| 3 | 請開放以下路徑給 KM（只開精確路徑與 method，不整段放行）。 |

| 方向 | Method | 路徑 |
|------|--------|------|
| KM→CSIT | GET | `/api/integrations/km/v1/vendor-files/{id}/content` |
| KM→CSIT | GET | `/api/integrations/km/v1/equipment-documents/{id}/content` |
| KM→CSIT | POST | `/api/integrations/km/v2/document-jobs/status` |
| KM→CSIT | POST | `/api/integrations/km/v2/document-metadata-changes/status` |
| KM→CSIT | POST | `/api/integrations/km/v2/document-deletions/status` |
| KM→CSIT | POST | `/api/integrations/km/v2/analysis-results` |

## 三、權限範圍（scope）

| # | 問題 |
|---|------|
| 4 | 規格 §3.2 的 scope 名稱是「建議」。請確認正式採用哪一組。 |

- CSIT→KM：`km.ingestion.write`、`km.deletion.write`、`km.metadata.write`
- KM→CSIT：`csit.documents.read`、`csit.km.status.write`、`csit.km.deletion-status.write`

目前 KM 收件端同時接受 v1.3 的 `km.ingestion.submit` 與上述新名稱；送出端仍使用 v1.3 名稱。確認後 KM 再切換。

## 四、換版事件

| # | 問題 |
|---|------|
| 5 | 規格只列四種 `eventType`：`VerificationApplicationAttachmentArchived`、`VendorFileArchived`、`EquipmentDocumentArchived`、`EquipmentAttachmentArchived`。若測試報告或文件專區的新版本也要走 v2 `document-jobs`，事件名稱是什麼？目前 KM 遇到其他名稱會回 400。 |

## 五、檔案格式

| # | 問題 |
|---|------|
| 6 | **圖片（PNG/JPG）**：KM 目前沒有 OCR 或視覺分析。收到圖片會回 `Failed`，錯誤碼 `UNSUPPORTED_FORMAT`。這樣可以嗎？或希望回 `Completed`（`method=None`、`chunkCount=0`）？ |
| 7 | KM 目前能解析：txt、csv、md、pdf、docx、xlsx、pptx。ZIP 與不明副檔名一樣建立工作，但回 `Failed`（`UNSUPPORTED_FORMAT`）。是否接受？ |
| 8 | 其他錯誤碼：加密文件 `ENCRYPTED_DOCUMENT`、損毀檔 `CORRUPT_FILE`、執行檔內容 `MALWARE_DETECTED`、雜湊不符 `SHA256_MISMATCH`、超過大小 `FILE_TOO_LARGE`。CSIT 端顯示這些碼有問題嗎？ |

## 六、其他

| # | 問題 |
|---|------|
| 9 | **`reasonCode`（v2 刪除）**：規格只舉例 `SourceDeleted`、`VersionSuperseded`、`AdministrativeCleanup`「等」。可否給完整清單？目前 KM 接受任何 1～128 字元的值。 |
| 10 | **分析結果內容**：KM 的 LLM 抽取尚未啟用，所以 `documentType` 會是 `Other`，摘要與關鍵字為空；`sourceSpecific` 只填 KM 實際讀到的內容（例如 Excel 工作表名稱），其餘為空值。CSIT 端有沒有哪個欄位必須有值？ |
| 11 | KM 在 `document-jobs/status` 收到 409 時會依退避時間重送（最多四次）。CSIT 端是否預期這個行為？ |

---

## 附：KM 端行為摘要（供對照）

- 所有正式入庫的檔案都會建立 KM 工作，不因副檔名拒收；讀不了的檔案以 `Failed` 加錯誤碼回報。
- 同一來源版本只允許一個有效的 ingestion；同檔名或同 SHA256 但不同來源的附件各自獨立。
- 換版：新版本分析並建立索引成功後才停用舊版索引；新版失敗時舊版不受影響。
- 分類／標籤變更：只更新索引欄位，不重新下載；依 `sourceRevision` 順序處理，舊版或相同版回 409，Completed 時回報 `appliedRevision`。
- 刪除：精確到文件版本並寫入 tombstone；`sha256` 或 `canonicalIngestionEventId` 與已分析版本不符時回 409；七項清理證明全部核對後才回 Completed。
- HTTP 狀態：契約錯誤 400、非 JSON 415、tombstone 410、找不到文件 404、衝突 409。
