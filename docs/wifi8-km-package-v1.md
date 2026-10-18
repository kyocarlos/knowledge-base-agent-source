# Wi-Fi8 → KM 匯出包契約 v1（`km.wifi8-package.v1`）

日期：2026-10-16

## 用途

把 Wi-Fi8 KM System 已整理好的文件中繼資料與全文段落，以「手動上傳匯出包」方式送進 KM 的 WiFi 知識專區（使用者決策：能登入 KM 者都可觀看；可送雲端 LLM；以手動上傳同步）。

## 產生方式（在 Wi-Fi8 機器上執行，唯讀）

```powershell
python src\Export-Wifi8KmPackage.py --output D:\exports\wifi8-km-package.zip
```

- 程式：Wi-Fi8 KM System 的 `platform/wifi8km/km_export.py` 與 `src/Export-Wifi8KmPackage.py`。
- 版本採用規則直接沿用 Wi-Fi8 的 `eligibility.apply_policy`（policy v5）與使用者確認的取代紀錄，KM 不自行重算。
- 非原機執行時（例如路徑不同的複本），需用 `--repository-root` 與 `--decisions-file` 指定，否則使用者確認的取代關係不會套用。
- 不修改 Repository、Catalog、全文索引或確認紀錄。

## 封裝內容（zip）

| 成員 | 內容 |
|---|---|
| `manifest.json` | schema、`package_id`、`content_sha256`、來源檔雜湊、排除政策、筆數、各成員 sha256 與大小 |
| `documents.jsonl` | 每份文件一列，依 `revision_id` 排序 |
| `segments.jsonl` | 每段一列，依 `revision_id`、`ordinal` 排序 |

相同輸入產生位元組完全相同的 zip（固定成員時間）；`package_id` 由內容雜湊決定，可用來判斷是否重複上傳。

### documents.jsonl 主要欄位

`revision_id`（主鍵）、`title`、`display_filename`、`primary_category_id`、`classification_path`、`document_role`、`publisher`、`working_group`、`confidentiality`、`topics`、`wfa_document_id`、`wfa_revision`、`version_label`、`version_series_id`、`document_family_id`、`document_date`、`lifecycle_status`、`supersedes`、`analysis_eligible`、`replacement_id`、`adoption_reason`、`source_sha256`、`relative_path`、`file_ext`、`source_urls`（僅 http/https）、`segment_count`、`text_status`（`indexed`／`not_indexed`／`stale_cache`）。

### segments.jsonl 欄位

`segment_id`、`revision_id`、`ordinal`、`kind`（`text`、`table_row`、`worksheet_row`、`ocr_text`、`notes`）、`location`（例如 `{"type":"page","page":3}`、`{"type":"worksheet","sheet":"…","row":12}`）、`text`。

## 排除政策

- `confidentiality` 為 `internal` 的文件與其段落（可用 `--exclude-confidentiality` 調整）。
- 不含郵件內文、郵件識別碼（`message_entry_id`）、本機路徑、Obsidian 筆記、原始檔、任何憑證。
- 全文快取的雜湊與 Catalog 不符時（`stale_cache`），該文件不帶段落，避免把舊版內容掛在新版名下。

## 匯入端（KM）必須遵守

1. 先驗證 `manifest.json` 與每個成員的 sha256／大小，不符即拒絕整包。
2. 以 `revision_id` 為冪等鍵；同一 `package_id` 重複上傳不得產生重複資料。
3. 預設檢索只用 `analysis_eligible=true`；查歷史版本時才納入被取代版本。
4. 引用需顯示文件標題、WFA 文件 ID／版本（若有）與 `location`。

## 2026-10-16 實測（DGX 上的 Repository 複本）

| 項目 | 數量 |
|---|---:|
| Catalog 記錄 | 510 |
| 匯出文件 | 503（排除 internal 7） |
| 有全文段落 | 492（未索引 11 份皆為 PNG 圖片） |
| 目前採用版本（`analysis_eligible`） | 368（套用 39 筆使用者確認的取代紀錄） |
| 段落 | 94,528 |
| 機密等級 | WFA-proprietary 355、public 148 |
| 檔案大小 | 約 10.4 MB |

匯出前後 Catalog、全文索引、確認紀錄的 sha256 均未變；包內無郵件識別碼、PST 或本機路徑字串。Wi-Fi8 匯出程式單元測試 7 項通過，既有 `test_eligibility.py` 12 項通過。

## v2（`km.wifi8-package.v2`，2026-10-18）：附上文件圖片，由 KM 轉成文字

使用者決策（2026-10-18）：表格以外，圖表與圖片也要能檢索；採「匯出包附上圖片，由 KM 處理」，看圖模型用 Sub2API（與 AI Agent 相同的資料邊界）。

**Wi-Fi8 端（`platform/wifi8km/km_images.py`、`km_export.py`）**
- 新成員 `images.jsonl`：每張圖一列，含 `image_id`（圖片位元組的 sha256）、`revision_id`、`ordinal`、`location`（docx 段落／表格、pptx 投影片、pdf 頁、單獨圖片檔 `{"type":"image"}`）、`caption`（docx 鄰近的 Figure/Table/圖/表 標題，或投影片標題）、`extension`、`width`、`height`。
- 圖片檔 `images/<sha256>.<png|jpg>`：同一張圖只存一份。檔名就是校驗碼，`images.jsonl` 已列在 `files` 中並納入 `content_sha256`，所以圖片也在匯出包身分內，不必逐檔列在 manifest。
- 正規化規則：
  - 小於 160×100 或 40,000 像素的圖不匯出（圖示、標誌、項目符號）；PDF 先讀宣告尺寸，太小就不解碼。
  - 200KB 以下的 PNG／JPEG 保留原檔。
  - 較大的圖長邊縮到 1600；256 色以內存 PNG，其餘轉 JPEG q85（透明鋪白），取較小者。
  - WMF／EMF 只有 Windows 的 Pillow 能轉換，其他環境記為 `unsupported_format`。
  - 同一文件內重複的圖只留第一次出現的位置。
- `manifest.counts` 新增 `images`、`image_files`、`image_bytes`、`images_skipped`（依原因計數）；`documents.jsonl` 新增 `image_count`。可用 `--no-images` 停用。

**KM 端**
- `package.py` 同時接受 v1、v2。v2 會驗證每個 `images/` 檔的 sha256 與檔名一致，且與 `images.jsonl` 完全對應；多一個、少一個或被竄改都拒收整包。
- 匯入流程新增第一階段 `describe`：
  - 逐批把尚未有說明的圖送到看圖模型，產出「【圖中文字】逐字抄錄＋【圖片說明】繁中說明」。
  - 結果依 `image_id` 快取在該區 `/app/data/wifi8/image-text/`，圖片存在 `/app/data/wifi8/images/`。快取鍵含 provider、模型、推理強度與提示版本，任一項改變就重新描述；兩區資料隔離，各自快取。
  - 失敗的圖在同一個工作中不再重試（每張圖有 1 次即時重試），下一個匯入工作會再試。
  - 失敗比例超過 `KM_WIFI8_IMAGE_MAX_FAILED_RATIO`（預設 5%）時整個工作失敗，目前版本繼續服務。
- 每張有內容的圖成為一個獨立段落，排在該文件文字段落之後：
  - 段落文字為 `【圖片】<caption>` 加上模型說明；標示如「第 2 頁・圖 1」；payload 帶 `image`、`image_id`。
  - 文字段落的 ID、順序與向量都不變，只有新的圖片段落需要計算向量。
  - 模型回答「無內容」的圖不建段落。
- `GET /api/wifi8/images/{image_id}`：需要登入，而且只提供目前版本有段落的圖。文件段落與混合檢索會顯示縮圖和轉出的文字。
- 設定（web 與 ingest worker 必須相同）：
  - `KM_WIFI8_IMAGE_DESCRIBER`：`openai` 或 `off`。
  - `KM_WIFI8_IMAGE_MODEL`、`_BASE_URL`、`_API_KEY_ENV`：預設沿用 `KM_LLM_PRIMARY_*`。
  - `KM_WIFI8_IMAGE_REASONING_EFFORT`：預設 `low`。
  - `KM_WIFI8_IMAGE_TIMEOUT_SECONDS=120`、`_RETRIES=1`、`_BATCH_SIZE=8`、`_CONCURRENCY=4`：單步最壞約 2 輪 × 2 次 × 120 秒，低於 Celery 600 秒軟上限。
  - 同一份匯出包在圖片設定改變後會重新匯入。

**實測（2026-10-18，DGX 上的 Repository 複本）**
- 1,655 處圖片、1,361 個不重複圖檔，共 106MB；整包 112MB，低於上傳上限 200MB。
- 跳過：太小 43,583、同文件重複 482、WMF／EMF 120、PDF 解碼失敗 4。
- 匯出約 7 分鐘，主要花在 PDF。
- 同一份 Repository 在 DGX 上算出的目前版本是 367 份，Windows 的匯出包是 368 份；差異是一組 IEEE 802.11bn 白皮書 v01／v02 的取代判斷。DGX 能讀到原檔並比對出 98% 重合，Windows 端標為「待確認」。用原版匯出程式和 pypdf 4.3.1／5.1.0 都得到相同結果，可見與圖片無關。正式資料仍以 Windows 匯出為準。
