# AI KM 每週進度資料庫

本目錄保存每週主管報告的完整產生鏈：

- `data/`：唯一數字來源，不可回寫歷史週。
- `weekly/`：人類可讀週報。
- `evidence/`：WP commit、PR、CI、測試與驗收證據。
- `evidence/WP0-WP1-v2.6-gap-assessment.md`：WP0／WP1 對 v2.6 的 A～E 差異與保全決策。
- WP1 最新 closure 證據包含 application idempotency shadow 與 system recovery coverage matrix；PENDING 項目不得視為系統 restore PASS。
- `presentations/`：已人工審查、可直接下載的歷史 PPTX。
- `templates/`：固定 7 頁版型基準。

正式流程與計分規則見 [`../05-weekly-reporting-and-pptx.md`](../05-weekly-reporting-and-pptx.md)。

唯一正式規劃基準為 [`01_AI_KM_Phase規劃_v2.6.xlsx`](../01_AI_KM_Phase規劃_v2.6.xlsx)，SHA-256=`4c5a4782e727b5675add29027a5a09192966f126baa5ca648d89b22c333fba46`。週報、JSON、Evidence 與 PPTX 的 Phase/WP 數字必須回溯此 Excel；不得以衍生 Markdown 反向重建或取代 Excel。
