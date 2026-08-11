# 需求追溯矩陣（v2.6）

## 核心需求

| Req ID | 需求 | Owner | WP | 主要驗收證據 |
|---|---|---|---|---|
| REQ-API-001 | FastAPI 分層、統一 response/error/trace/exception | Anderson | WP0 | contract、middleware、architecture tests |
| REQ-JOB-001 | Docker／Redis／Celery、queue、retry、timeout、idempotency | Anderson | WP1 | restart、routing、persistence tests |
| REQ-CSIT-001 | AI KM 只經正式 API／Adapter 存取 CSIT | Patty Contract；Anderson Client | WP2 | consumer contract＋no-direct-DB test |
| REQ-BOOK-001 | AI KM 提供設備查詢／填單，正式 Booking 由 CSIT 保存 | Patty SOR；Anderson Entry | WP2 | same-booking、collision、permission E2E |
| REQ-VALREQ-001 | AI KM 協助填驗證申請與查進度，正式 Workflow 在 CSIT | Patty SOR；Anderson Entry | WP2 | request state、permission、UI E2E |
| REQ-OPENCLAW-001 | Report Upload／Result／Status 經受控 Tool／Adapter | 共同 | WP3 | tool contract、idempotency tests |
| REQ-REPORT-001 | review／reject／resubmit／approve／publish 狀態一致 | Patty SOR；Anderson Sync | WP3 | workflow E2E |
| REQ-REPORT-002 | AI 不得正式核准 | Patty Rule；Anderson Enforcement | WP3, WP7 | authorization negative test |
| REQ-PARSER-001 | Excel 報告固定 Schema，錯誤拒絕 | Anderson | WP4 | golden＋negative files |
| REQ-RAG-001 | MarkItDown／Chunk／Embedding 正式化且可重跑 | Anderson | WP4 | source、chunk、idempotency tests |
| REQ-QD-001 | 基本 Qdrant Search 具 Payload、Version、ACL | Patty Spec；Anderson Code | WP5 | filter、duplicate、draft/ACL tests |
| REQ-GRAPH-001 | 基本 Neo4j GraphRAG 具 Ontology、Source、MERGE | Patty Spec；Anderson Code | WP5 | ontology、source、duplicate tests |
| REQ-TS-001 | 時序明細進 TimescaleDB | Patty Schema；Anderson Code | WP6 | bulk ingest、query、ACL tests |
| REQ-SEC-001 | RBAC／ACL 在後端與 Tool 強制執行 | 共同 | WP7, WP11 | cross-tool bypass suite |
| REQ-CIT-001 | 答案可追至文件／報告／版本／位置／時間 | 共同 | WP7, WP11 | citation completeness |
| REQ-UI-001 | Portal 提供 QA／Search／Report Center／Dashboard | Anderson | WP7 | browser E2E |
| REQ-P1-TEST-001 | Phase 1 Unit／Integration／Acceptance／Golden Test | 共同 | WP8 | Gate report |
| REQ-BENCH-001 | 基礎 Benchmark 轉檔／整理／繪圖／查詢在 Phase 2 | 共同 | WP9 | schema、query、chart tests |
| REQ-DI-001 | 文字／圖片／混合／Excel／表格走專用 Pipeline | Anderson | WP10A | format golden files |
| REQ-KP-001 | 統一 Knowledge Package／Validation／Routing 在 Phase 2 | Patty Spec；Anderson Code | WP10B | schema、negative、routing tests |
| REQ-REBUILD-001 | Qdrant／Neo4j 可重建且無重複 | Patty Rule；Anderson Code | WP10B | rebuild／count／lineage tests |
| REQ-AG-001 | Fast／Agentic 路徑、Planner budget、白名單 Tool | Anderson／共同 | WP11 | routing、安全、成本 golden set |
| REQ-AN-001 | Root Cause／Benchmark／Recommendation 附證據與信心 | 共同 | WP12 | business golden set |
| REQ-EVO-001 | Multi-Agent／Predictive 只在資料與 KPI 達門檻後啟動 | 共同 | WP13 | readiness decision＋evaluation |

## 來源覆蓋

| 來源 | 規劃用途 |
|---|---|
| `01_AI_KM_Phase規劃_v2.6.xlsx` | 唯一最新 Phase、工期、範圍、Owner、分工與時點基準 |
| v1.0 技術規範 | Contract、Schema、測試細節；不得改變 v2.6 Phase／Owner |
| v2.1 Document／Graph 設計 | Phase 2 詳細設計 |
| 系統架構／流程圖 | 分層、Tool、四庫、安全與端到端流程 |

舊版 Phase 規劃檔及其引用均不得再作為需求來源。

## Gate 順序

`G0 API → G1 Job → G2 CSIT／Booking／Request → G3 Report／OpenClaw → G4 Basic RAG／Data Stores → G5 Governance／Portal／P1 Acceptance → G6 Benchmark／Compile-Time → G7 Agentic Safety → G8 Analysis Quality`

任何 Gate 未通過時，不得以 Demo、HTTP 200 或程式已存在取代資料、版本、權限、重跑與失敗模式驗證。
