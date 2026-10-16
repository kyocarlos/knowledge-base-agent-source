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
