# 規格真實來源與架構決策

## 1. 規格優先序

1. 安全、權限、正式資料來源與人工核准等不可逆治理規則。
2. `01_AI_KM_Phase規劃_v2.6.xlsx`：最新 Phase、工期、範圍、實際工作分工與 Owner 基準。
3. 五份 v1.0 技術規範：模組 Contract 與驗收細節；不得改變 v2.6 的 Phase 或 Owner。
4. `03`／`04` v2.1 設計：Document Intelligence 與 Knowledge Graph 詳細設計。
5. `02` 架構核心：概念與長期目標。

納管的 v2.6 原檔位於 [`01_AI_KM_Phase規劃_v2.6.xlsx`](01_AI_KM_Phase規劃_v2.6.xlsx)，SHA-256=`4c5a4782e727b5675add29027a5a09192966f126baa5ca648d89b22c333fba46`。已核對八個工作表；其中「實際工作分工」與「分工摘要」標題殘留 `v2.4`，視為同一 v2.6 工作簿的內部標籤差異，需由規劃 Owner 後續澄清，但不改變本檔作為唯一基準。

舊版 Phase 規劃與獨立的 `06_AI_KM_實際工作切法_v2.4.xlsx` 均已由 v2.6 完整整合取代，視為停用文件，不得保留為規格來源或再行引用。Phase、工期、範圍、實際工作分工與 Owner 一律只以 `01_AI_KM_Phase規劃_v2.6.xlsx` 為準。

## 2. Owner 與系統邊界

| 角色 | 定位 | 主責 | 不負責 |
|---|---|---|---|
| Patty | CSIT Owner＋AI KM Architecture Owner | CSIT 全部開發；API；Booking；Validation Request；核心 Schema／Ontology／Payload／Tool Contract；整合與最終驗收 | 不必代寫全部 AI KM 工程實作 |
| Anderson | AI KM Implementation Owner | POC 正式化；FastAPI；環境；Parser／RAG；三個資料庫工程；Portal；Agentic RAG；Unit Test | CSIT 內部程式、DB Schema、Workflow、商業邏輯 |
| 共同 | 系統整合與 AI 能力落地 | OpenClaw、RBAC／Citation／Audit、Integration Test、AI Analysis、Evaluation | 避免兩邊各自建立一套正式資料 |

所有交界一律使用 Contract。CSIT 是正式資料與交易的 System of Record；AI KM 提供智慧查詢、分析與自然語言入口。

## 3. 已鎖定決策

| ID | 決策 | 實作含義 |
|---|---|---|
| ADR-001 | CSIT 是唯一 System of Record | 文件、報告、版本、核准、Booking、Validation Request 與權限以 CSIT 為準；AI KM 只透過正式 API／Adapter 存取。 |
| ADR-002 | Phase 1 先交付可用 MVP | 沿用 FastAPI、Docker、Redis、Celery、MarkItDown、RAG／GraphRAG，外科式正式化，不先全面重構。 |
| ADR-003 | 設備預約與系統驗證申請單納入 Phase 1 | Anderson 只實作 KM 查詢／填單入口；Patty 負責 CSIT Web、DB、Service、Workflow、權限與正式狀態。 |
| ADR-004 | Benchmark 分兩階段 | 基礎轉檔／整理／繪圖／查詢在 Phase 2；AI 比較、解釋與 Recommendation 在 Phase 4。 |
| ADR-005 | Knowledge Package 與完整 Routing 在 Phase 2 | Phase 1 只保留 MVP 所需最低 payload／source／ACL／version Contract；統一 Package、Validation、Routing 與 rebuild 在 Phase 2 完成。 |
| ADR-006 | 四庫分工不可混用 | CSIT 管正式主資料；Qdrant 管語意 Chunk；Neo4j 管實體關係；TimescaleDB 管時序明細。 |
| ADR-007 | 權限不能依賴 Prompt 或前端 | Backend／Gateway 在每個 Tool 執行前強制 identity、ACL 與 published/current filter。 |
| ADR-008 | AI 不得核准正式報告或申請 | Manager approval 永遠是人工決策；AI 只可摘要、檢查、查詢與協助填單。 |
| ADR-009 | LLM 不直接控制資料庫或設備 | SQL、Cypher、Automation 全部經 allowlisted Tool、參數驗證、預算與停止條件。 |
| ADR-010 | 索引與工作可重跑 | Job 有 retry／timeout／idempotency／audit；Qdrant／Neo4j projection 可由正式來源重建。 |
| ADR-011 | A2A bridge 保持隔離、預設關閉 | 未通過 Gate 不納入 production Compose，不因新 Automation Tool 開啟真實設備。 |

## 4. v2.6 對舊規劃的正式裁決

- 取消「Phase 0」商業 Phase；WP0／WP1 改列 Phase 1 前置工作。
- 設備預約與系統驗證申請單不再是 optional track，均為 Phase 1 必做整合。
- Knowledge Package、通用 Document Intelligence、Schema Validation、Data Routing 與資料庫正式化放在 Phase 2。
- Benchmark 基礎移至 Phase 2；Phase 4 僅做進階 AI 分析。
- Phase 1 工期採 12～16 週；Phase 2 採 10～14 週。

## 5. 開工前依賴

| ID | 依賴／待確認 | Owner | 未取得時的處理 |
|---|---|---|---|
| DEP-001 | CSIT OpenAPI、認證、錯誤碼與狀態 Contract | Patty | Anderson 只做 port、fake adapter 與 contract test。 |
| DEP-002 | Booking 衝突、權限與狀態規則 | Patty | 不建立 AI KM 自有 Booking 狀態。 |
| DEP-003 | Validation Request 欄位、Workflow、權限 | Patty | 不猜欄位、不直連 CSIT DB。 |
| DEP-004 | ACL 角色、部門、project/private 規則 | Patty | deny-by-default。 |
| DEP-005 | Qdrant Payload、Neo4j Ontology、Timescale Schema | Patty | Anderson 不自行更改核心 Schema。 |
| DEP-006 | Benchmark 欄位、口徑與 CSIT 資料來源 | Patty | Phase 2 先做可替換 Adapter，不硬比較不同條件。 |
