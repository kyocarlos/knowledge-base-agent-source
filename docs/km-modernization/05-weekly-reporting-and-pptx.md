# AI KM 每週進度與主管版 PPTX 交接規格

## 1. 基準與節奏

每週四報告；GitHub 保存當週 PPTX、來源 JSON、Markdown 與 Evidence。需求與 Phase 一律以 `01_AI_KM_Phase規劃_v2.6.xlsx` 為準，歷史週次不得覆蓋。

- 週一：確認本週 Issue、WP、Gate、Owner、承諾與風險。
- 週二：更新 PR、測試、E2E、回滾與 Evidence。
- 週三 17:00（Asia/Taipei）：統計截止。
- 週三 17:10：Actions 產生候選 PPTX artifact。
- 週四：人工核對數字、版面與責任界線後報告。

## 2. Phase 與 WP（v2.6）

| Phase | WP |
|---|---|
| Phase 1 AI KM MVP | WP0～WP8；WP0／WP1 是正式化前置，不另稱 Phase 0 |
| Phase 2 Compile-Time RAG Enhancement | WP9、WP10A、WP10B |
| Phase 3 Agentic Knowledge Retrieval | WP11 |
| Phase 4 AI Analysis & Review | WP12 |
| Phase 5 Enterprise AI Evolution | WP13 |

週報必須分辨「Anderson 主責」「Patty 主責／Anderson 依 Contract 實作」「共同」。CSIT 內部進度不得計入 Anderson 的 AI KM 程式完成度；反之，缺少 Patty Contract 造成的阻塞要列入依賴與風險。

## 3. 進度計算

每個 WP 由 Evidence 支持：Contract 15、程式 35、Unit／Integration／Security 測試 25、E2E／驗收 15、PR Review／合併／文件／回滾 10。Phase 分數是所屬 WP 平均；全計畫為 15 個 WP 平均。無 PR、測試、驗收或合併證據不得為 100。

## 4. 唯一資料鏈

Issue 定義需求與驗收；PR 連結 Issue、commit、測試與回滾；`progress/evidence/WP*.md` 保存證據；`progress/data/YYYY-Www.json` 是數字唯一來源；Markdown 與 PPTX 必須一致。JSON 應保存 `source_baseline: 01_AI_KM_Phase規劃_v2.6.xlsx` 與 Owner／dependency。

## 5. 產生、失敗與驗收

```bash
npm ci
node scripts/generate_weekly_pptx.mjs --week 2026-W33 --validate
node scripts/generate_weekly_pptx.mjs --week 2026-W33
```

排程 `10 9 * * 3` 等於台北時間星期三 17:10。Actions 只上傳 artifact，不直接 commit。JSON／Markdown 不一致、PPTX 空檔、渲染溢出或 GitHub 證據未核對時必須停止，不得沿用舊簡報冒充本週。

驗收需確認：v2.6 Phase／Owner 正確、JSON 計算通過、固定 7 頁繁中、LibreOffice 可渲染、無溢出、歷史檔未被覆蓋。下一週複製前週 JSON 後，只更新新證據與承諾，不回寫歷史週數字。
