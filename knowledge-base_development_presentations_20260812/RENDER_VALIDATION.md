# 簡報渲染驗證

驗證日期：2026-08-12（Asia/Taipei）

## 結果

- 正式簡報：21 份，共 131 頁（第 21 份已由 7 頁擴充為 17 頁）。
- 週報範本：1 份，共 7 頁。
- PPTX ZIP 結構驗證：22/22 通過。
- LibreOffice 24.2 實際開啟並轉換 PDF：22/22 通過。
- 產生的 PDF 均存在且為非空檔案。
- PPTX 內部 slide XML 數量與 PDF 頁數逐檔一致。
- 擴充版 `AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx` 已再次以 LibreOffice 24.2 渲染為 17 頁 PDF；WP0 第 6～9 頁與 WP1 第 10～15 頁為逐條變更台帳。已核對 80 個編號完整且唯一，所有欄位在頁面邊界內，頁碼為 1/17 至 17。

## 驗證方式

1. 從 Git 全部分支與歷史提交取得每個簡報路徑最後一次提交的版本。
2. 使用 ZIP 完整性測試驗證 PPTX 容器。
3. 計算 `ppt/slides/slide*.xml` 取得預期投影片數。
4. 使用 LibreOffice headless 模式逐份開啟並輸出 PDF。
5. 使用 `pdfinfo` 取得 PDF 頁數並核對預期投影片數。

PDF 僅作本機驗證，未放入分享目錄，以免分享包體積不必要增加。來源 commit、原始路徑、檔案大小與 SHA-256 詳見 `presentation_manifest.csv`。
