# AI KM 正式化規劃入口

本目錄以 `01_AI_KM_Phase規劃_v2.6.xlsx` 為最新規劃基準，聚焦 Anderson 負責的 AI KM 實作。舊版 `01_AI_KM_Phase規劃_v2.2` 已退役，不得再作為 Phase、工期、範圍或責任分工依據。

## 文件閱讀順序

1. [`01-source-of-truth-and-decisions.md`](01-source-of-truth-and-decisions.md)：v2.6 優先序、不可違反邊界與架構決策。
2. [`02-current-state-gap-analysis.md`](02-current-state-gap-analysis.md)：基準程式可沿用能力與缺口。
3. [`03-codex-implementation-plan.md`](03-codex-implementation-plan.md)：依 v2.6 Phase 1～5 執行的 WP 計畫。
4. [`04-requirements-traceability.md`](04-requirements-traceability.md)：需求、Owner、WP 與驗收證據。
5. [`05-weekly-reporting-and-pptx.md`](05-weekly-reporting-and-pptx.md)：每週主管報告與 PPTX。
6. [`06-v2.6-anderson-scope.md`](06-v2.6-anderson-scope.md)：附件 v2.6 的 Anderson／AI KM 責任基準。

## 最新 Phase 基準

| Phase | 名稱 | Anderson／AI KM 重點 | 建議工期 |
|---|---|---|---|
| Phase 1 | AI KM MVP（Production Ready） | POC 正式化、API、環境、CSIT Adapter、OpenClaw、報告 Parser、基本 RAG／Qdrant／Neo4j、TimescaleDB、治理、Portal、測試 | 12～16 週 |
| Phase 2 | Compile-Time RAG Enhancement | Benchmark 基礎、Document Intelligence、Knowledge Package、Validation、Routing、資料庫正式化與端到端 Pipeline | 10～14 週 |
| Phase 3 | Enterprise Agentic Knowledge Retrieval | Intent、Fast／Agentic Selector、Planner、Router、Tool、Evidence、Context／Citation | 8～12 週 |
| Phase 4 | AI Analysis & Review | Root Cause、Benchmark Analysis、Similar Case、Recommendation、Report Review、Evaluation | 8～12 週 |
| Phase 5 | Enterprise AI Evolution | Workflow、Multi-Agent、Predictive AI、Trend、Auto Benchmark／補測建議 | 12～24+ 週，條件式 |

Phase 1 已明確包含設備預約與系統驗證申請單的 AI KM 查詢／填單入口；正式資料、Web、DB、Workflow 與審核仍由 CSIT／Patty 負責。Benchmark 基礎功能位於 Phase 2，AI 自動分析位於 Phase 4。

## Anderson 的責任界線

- Anderson 是 **AI KM Implementation Owner**。
- 主責既有 POC 正式化、FastAPI、Docker／Redis／Celery、Parser、RAG、Chunk／Embedding、Qdrant／Neo4j／TimescaleDB 工程實作、Portal、Agentic RAG 與 Unit Test。
- 不修改 CSIT 內部程式、CSIT DB Schema、CSIT Workflow 或既有 CSIT 商業邏輯。
- 只依 Patty 提供的 CSIT API Contract、Knowledge Package Schema、Payload、Ontology、Tool Contract 與驗收案例實作。
- Qdrant／Neo4j／TimescaleDB 的「怎麼存、存什麼、怎麼驗」由 Patty 鎖定；Anderson 負責把規格做成可維護、可重跑且有測試的程式。

## Codex 開工規則

- 一次只執行一個 WP，每個 WP 使用獨立 branch／PR。
- WP0／WP1 是 Phase 1 的正式化前置工作，不再另稱 Phase 0。
- 外部 Contract 未提供時只做 port、fake adapter 與 contract test，不猜測 CSIT 欄位。
- AI KM 不直連 CSIT DB；Parser 不直接自由寫入各資料庫；LLM 不得自由執行 SQL、Cypher、Shell、SSH 或設備命令。
- 每個 PR 必須列出需求 ID、Owner、影響檔案、Contract／migration、設定、測試、回滾與未完成項目。
