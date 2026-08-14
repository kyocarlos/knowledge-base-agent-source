# AI KM 每週進度與主管版 PPTX 交接規格

## 1. 基準與節奏

每週四報告；GitHub 保存當週 PPTX、來源 JSON、Markdown 與 Evidence。需求與 Phase 一律以 `01_AI_KM_Phase規劃_v2.6.xlsx` 為準，歷史週次不得覆蓋。

主管 review 用的正式簡報固定另存於 `docs/` 根目錄，命名為：

```text
docs/AI-KM-Phase1-Weekly-YYYY-Www-v2.6.pptx
```

例如：`docs/AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx`。`progress/presentations/` 保存流程用週報版本；兩者必須來自同一份 JSON，內容數字一致。

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

`source_baseline` 指向的原始檔也必須存在於 Git，且由規劃 Owner 核對。若原始 Excel 缺失，週報仍可產生標示阻塞的候選 artifact，但不得宣稱規劃來源 Gate 或 WP 正式驗收完成，也不得從 Markdown／JSON 反向猜測或重建原始 Excel。

## 5. 產生、發布、失敗與驗收

```bash
npm ci
node scripts/generate_weekly_pptx.mjs --week 2026-W33 --validate
node scripts/generate_weekly_pptx.mjs --week 2026-W33
```

排程 `10 9 * * 3` 等於台北時間星期三 17:10。Actions 只上傳 artifact，不直接 commit。JSON／Markdown 不一致、PPTX 空檔、渲染溢出或 GitHub 證據未核對時必須停止，不得沿用舊簡報冒充本週。若來源 Excel 缺失，必須在 JSON、Markdown、Evidence 與 PPTX 風險頁一致標示。

正式發布採人工核准，避免排程工作流直接覆蓋歷史：

1. Actions 在週三 17:10 產生候選 artifact。
2. 負責人下載候選 PPTX，核對 JSON、Markdown、Evidence、頁數、渲染與進度數字。
3. 通過核對後，以新的 ISO week 檔名提交至 `docs/AI-KM-Phase1-Weekly-YYYY-Www-v2.6.pptx`，不得修改既有週次檔案。
4. 同一 commit 必須包含該週 JSON、Markdown、Evidence 變更，並在 commit/PR 描述填入報告日期、統計截止時間與產生依據。
5. GitHub review 以該週 `docs/` 簡報、`progress/` 來源資料及 PR 為同一組審查單位。

下一週只建立新的 `YYYY-Www` JSON、Markdown、Evidence 與 PPTX；禁止覆蓋 W33 或其他歷史版本。若候選失敗，保留前週正式版本，修正後重新產生同一週候選，不可把前週檔案改名冒充新週。

驗收需確認：v2.6 Phase／Owner 正確、JSON 計算通過、固定 7 頁繁中、LibreOffice 可渲染、無溢出、歷史檔未被覆蓋。下一週複製前週 JSON 後，只更新新證據與承諾，不回寫歷史週數字。
