# AI KM 每週進度與主管版 PPTX 交接規格

## 1. 目的與節奏

每週四向主管報告，GitHub 在報告前保存可下載的當週 PPTX、來源 JSON、週報 Markdown 與 Evidence。檔名使用 ISO week，歷史檔不得覆蓋。

- 週一：確認本週 Issue、WP、Gate、承諾與風險。
- 週二：更新 PR、測試、E2E、回滾與 Evidence。
- 週三 17:00（Asia/Taipei）：統計截止；截止後的新證據列入下週。
- 週三 17:10：GitHub Actions 產生候選 artifact。
- 週四：人工核對數字、版面與風險後，使用 repository 中已審查的歷史 PPTX 報告。

## 2. Phase 與 WP

| Phase | WP |
|---|---|
| Phase 0 正式化基座 | WP0、WP1 |
| Phase 1 Production-ready MVP | WP2～WP9 |
| Phase 2 Compile-Time RAG | WP10A、WP10B |
| Phase 3 Agentic RAG | WP11 |
| Phase 4 AI Analysis & Review | WP12 |
| Phase 5 Enterprise Evolution | WP13 |

## 3. 進度計算

每個 WP 的滿分為 100，五類分數只能由 Evidence 支持：

| 類別 | 權重 |
|---|---:|
| 規格與 Contract | 15 |
| 程式實作 | 35 |
| Unit／Integration／Security 測試 | 25 |
| E2E 與驗收證據 | 15 |
| PR Review、合併、文件與回滾 | 10 |

WP 分數為五類實得分加總；Phase 分數為該 Phase 所有 WP 的算術平均；全計畫分數為 WP0～WP13 共 15 個 WP（WP10A、WP10B 分開）的算術平均。沒有 PR、測試、驗收或合併證據時不得為 100。規劃完成不等於實作完成。

## 4. Issue、PR、Evidence 與週報

Issue 定義需求與驗收；PR 連結 Issue、commit、測試與回滾；`progress/evidence/WP*.md` 保存可稽核證據；`progress/data/YYYY-Www.json` 是數字唯一來源；Markdown 與 PPTX 都必須與 JSON 一致。任何外部證據需使用永久 URL 或完整 commit SHA。

## 5. 產生與觸發

安裝依賴後執行：

```bash
npm ci
node scripts/generate_weekly_pptx.mjs --week 2026-W33 --validate
node scripts/generate_weekly_pptx.mjs --week 2026-W33
```

Actions 支援 `workflow_dispatch`，輸入 ISO week；排程為 `10 9 * * 3`，即 UTC 星期三 09:10、Asia/Taipei 星期三 17:10。Actions 只上傳 artifact，不直接 commit，以免未審查覆蓋歷史版本或形成無限循環。人工下載、逐頁核對後，透過 PR 加入 `presentations/`。

## 6. 失敗處理

- JSON schema、必要欄位、分數或 Markdown 一致性失敗：停止產生，不得沿用舊簡報冒充本週產物。
- PPTX 不存在或為空：Actions 失敗，保留 log，修正資料或產生器後重跑。
- 渲染或文字溢出：修正模板／內容，再由同一 JSON 重產。
- 截止後證據：不得回填本週數字，列入下一週。
- GitHub API 不可用：Evidence 標示未核對，該項不得得滿分。

## 7. 驗收條件

1. JSON 驗證、加權總和、Phase 與全計畫計算通過。
2. Markdown、PPTX 與 JSON 的 WP/Phase 數字一致。
3. 固定 7 頁、繁體中文、頁碼與樣式一致。
4. LibreOffice 可開啟並渲染每頁；無溢出、遮蔽、不可辨識小字。
5. PPTX 存在且非空，當週檔名唯一，既有歷史檔不被覆蓋。
6. Actions 手動與排程設定通過語法檢查，產物以 artifact 交付審查。

## 8. 產生下一週

1. 複製前週 JSON 為新的 ISO week，更新報告日、統計區間、證據與承諾。
2. 新增 `weekly/YYYY-Www.md`，不得修改前週歷史資料。
3. 執行 `--validate`，再產生候選 PPTX。
4. 執行渲染與逐頁檢查，確認數字一致。
5. 透過獨立 PR 提交 JSON、Markdown、Evidence 與經審查 PPTX。
