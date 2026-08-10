# AI KM 正式化規劃入口

本目錄把 `KM_Modify` 的 13 份規劃／規範素材，對照基準 commit
`35d8d56a713d7436b8db2fc81ae4b96e8c13516a`，整理成 Codex 可依序執行、可驗收、可回滾的修改計畫。

## 文件閱讀順序

1. [`01-source-of-truth-and-decisions.md`](01-source-of-truth-and-decisions.md)：規格優先序、不可違反的邊界、已辨識衝突與待決策事項。
2. [`02-current-state-gap-analysis.md`](02-current-state-gap-analysis.md)：目前程式可沿用能力與缺口。
3. [`03-codex-implementation-plan.md`](03-codex-implementation-plan.md)：逐工作包、逐檔案、逐 Gate 的執行計畫。
4. [`04-requirements-traceability.md`](04-requirements-traceability.md)：需求到工作包與驗收證據的追溯矩陣。

## 基準與範圍

- 程式基準：commit `35d8d56`（`feat: add isolated KM A2A delegation bridge`）。
- 第一優先：Phase 1 Production-ready MVP；保留既有 POC 能力，先建立正式 API、背景工作、報告流程、資料契約、資料庫邊界、RBAC、Citation 與 Audit。
- 後續順序：Phase 2 Compile-Time RAG → Phase 3 Agentic RAG → Phase 4 AI Analysis → Phase 5 Enterprise Evolution。
- 本次提交只加入規劃文件與專案記憶，不修改 production runtime、資料庫或部署設定。
- `KM_Modify` 原始 Office／圖片檔未加入 Git；本目錄是已去重、可追溯的實作基準。

## Codex 開工規則

- 一次只執行一個 Work Package（WP），每個 WP 使用獨立 branch／PR。
- 先完成該 WP 的 contract、migration／初始化腳本與測試，再接 UI 或整合。
- 不得把所有 Phase 合併成一次大型重寫。
- 不得在沒有 CSIT API Contract 的情況下猜測 CSIT 欄位或直接連 CSIT DB。
- 不得讓 Parser 直接寫 Qdrant／Neo4j／TimescaleDB。
- 不得讓 LLM 產生可直接執行的 SQL、Cypher、Shell、SCPI 或設備命令。
- 所有正式查詢必須有 authentication context、ACL、published/current filter、trace_id 與 audit evidence。
- 每個 PR 必須列出：需求 ID、影響檔案、migration、設定、測試、回滾方式、未涵蓋項目。

## 建議第一個實作 PR

從 `WP0` 開始：建立 `app/` 正式 FastAPI 骨架、統一 response/error、trace middleware、設定管理、health/version，以及測試與相容層。不要先改寫 RAG 或 A2A bridge。
