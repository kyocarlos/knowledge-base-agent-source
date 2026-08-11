# Codex 分階段實作計畫（v2.6／Anderson）

## 執行模型

本計畫只描述 Anderson 主責或共同負責的 AI KM 工作。每個 WP 使用獨立 branch／PR；外部 Contract 未提供時只做 port、fake adapter 與 contract test。WP0／WP1 是 Phase 1 前置工作，不再另設 Phase 0。

## Phase 1：AI KM MVP（Production Ready，12～16 週）

### WP0 — FastAPI／REST API 與測試基線

- 主實作 application factory、Router、Swagger、統一 response／error、trace、Exception、typed config 與相容層。
- 建立 deterministic Unit／contract／security test command。
- Gate：舊 UI／API smoke、trace、secret-safe error、分層與 contract tests 通過。

### WP1 — Docker／Redis／Celery／環境正式化

- 主實作可配置 queue、Job state、retry、timeout、idempotency、worker restart、持久化與 health。
- 移除硬編碼主機路徑、弱預設密碼與不必要的 production Beat。
- Gate：queue routing、retry/non-retry、restart、persistence、backup/restore 測試。

### WP2 — CSIT Adapter 與 Phase 1 新功能入口

- 依 Patty 的 Contract 實作 Document、Test Plan、Report、Approval、User／ACL Client／Adapter。
- 實作設備查詢／預約填單與系統驗證申請／進度查詢入口；所有正式寫入與狀態都回到 CSIT。
- Gate：consumer contract、timeout、permission、version conflict、Booking collision 與 Request state tests；架構檢查確保不直連 CSIT DB。

### WP3 — OpenClaw 與 Report Workflow Adapter

- 主實作 AI KM／OpenClaw Report Upload、Test Result、Status Tool／Adapter。
- AI KM 同步 CSIT 的 draft／review／reject／resubmit／approve／publish 狀態；AI 不得核准。
- Gate：同一 report_id／test_run_id 可追蹤；重試不重複；主管核准負向測試。

### WP4 — Excel Parser 與基本 RAG 正式化

- 主實作正式 Excel Parser／Schema Validator，缺欄、型別、格式錯誤時拒絕。
- 整理 MarkItDown、Chunk、Embedding；保留 source，禁止整份文件單一 Chunk，全部可重跑。
- Gate：代表性報告 golden files、negative schema、chunk/source/idempotency tests。

### WP5 — Qdrant／Neo4j 基本檢索

- 依 Patty 的最低 Payload／ACL／Version 規格實作 Qdrant Collection、Upsert、Search 與 Filter。
- 依最低 Ontology／Source 規格實作 Neo4j Node、Relationship、MERGE 與受控 Cypher Template。
- Gate：同 ID＋version 重跑不重複；Draft／無權限查不到；graph 不把全文當知識節點。

### WP6 — TimescaleDB 基礎

- 依 Patty 的 Schema／KPI／Tag／test_run_id 邊界實作 Hypertable、Repository、bulk ingest 與 Query API。
- Gate：interval／aggregation／ACL／idempotency／容量基線；時序明細不塞入 Qdrant／Neo4j。

### WP7 — RBAC／Citation／Audit 與 Portal

- 共同完成 AuthContext、deny-by-default Filter、Citation、Audit／Query／Answer Log。
- Anderson 主實作 Search／QA／Report Center／Basic Dashboard 與 AI KM API 串接；Portal 不直連 CSIT DB。
- Gate：cross-tool bypass、citation traceability、audit、Portal E2E。

### WP8 — Phase 1 整合與驗收

- Anderson 主導 AI KM Unit Test，協助 Integration／Acceptance／Golden Test。
- Gate：文件／報告搜尋、OpenClaw、Booking、Validation Request、report review/publish、RBAC、Citation、Timescale 與舊功能回歸完整通過。

## Phase 2：Compile-Time RAG Enhancement（10～14 週）

### WP9 — WiFi Benchmark 基礎

- 依 Patty 的比較欄位、口徑與資料來源，主實作轉檔、資料整理、圖表與 AI KM 查詢入口。
- 只交付基礎查詢／繪圖；AI 自動分析與 Recommendation 留在 WP12。

### WP10A — Document Intelligence

- File Type Detector、Vision／OCR／Image、Table／Excel Pipeline。
- Excel／table 不以 OCR 取代 Parser；保留 page／cell／bounding source 與 low-confidence review。

### WP10B — Knowledge Package／Validation／Routing／Projection 正式化

- 依 Patty 規格實作 Package Model／Serializer、Validation、Router／Adapter。
- 實作 Entity Extraction／Normalize／MERGE、Qdrant Payload／Filter／Rebuild。
- 完成 Document → Package → Validation → Routing → DB；invalid data 不可進正式 mutation job。

## Phase 3：Enterprise Agentic Knowledge Retrieval（8～12 週）

### WP11 — 受控 Agentic RAG

- Intent → Fast／Agentic Selector → Planner → Router → Registry／Executor → Evidence Validator → Context／Citation。
- 只使用白名單 CSIT、TimescaleDB、Neo4j、Qdrant、OpenClaw Tool；禁止自由 SQL、Cypher、SSH。
- Gate：budget、stop condition、timeout、ACL、evidence/citation golden set；簡單問題不進 Planner。

## Phase 4：AI Analysis & Review（8～12 週）

### WP12 — Analysis／Review／Evaluation

- Root Cause、Advanced Benchmark、Similar Case／Recommendation、AI Report Review／Summary、Evaluation Runner。
- 每個結論區分 evidence、inference、confidence；AI 不改變 CSIT approval。

## Phase 5：Enterprise AI Evolution（12～24+ 週，條件式）

### WP13 — Workflow／Multi-Agent／Predictive

- Orchestration、Multi-Agent、Predictive／Trend、Auto Benchmark／主動補測建議。
- 只有歷史資料、單 Agent 品質、KPI 與人工治理達門檻才啟動。

## Definition of Done

1. 連結 Req ID、Owner、ADR 與前置 Contract。
2. API／Schema／migration／config 版本化，無秘密、硬編碼路徑或越界 DB 存取。
3. Unit＋integration＋contract／security tests 驗證版本、權限、重跑與失敗模式。
4. 有向後相容、migration、rollback、Evidence 與未完成項目。
5. PR Review／Gate 未完成時不得宣稱 100%。
