# 需求追溯矩陣

## 1. 核心需求

| Req ID | 需求 | 工作包 | 主要驗收證據 |
|---|---|---|---|
| REQ-API-001 | `/api/v1`、統一 response/error、trace id、global exception | WP0 | API contract + middleware tests |
| REQ-API-002 | Router/Service/Repository/Adapter 分層 | WP0 | architecture test／review checklist |
| REQ-JOB-001 | 長工作走 Celery，固定 job 狀態與 queue | WP1 | queue routing integration tests |
| REQ-JOB-002 | retry/timeout/idempotency/trace 可配置 | WP1 | transient/non-retry/restart tests |
| REQ-KP-001 | 所有 parser 先產 Knowledge Package | WP2 | schema examples + pipeline test |
| REQ-KP-002 | source/version/ACL/citation/publish/routing 必填 | WP2 | validation negative tests |
| REQ-ROUTE-001 | CSIT/Qdrant/Neo4j/TimescaleDB 明確分流 | WP2 | routing decision tests |
| REQ-QD-001 | 一 Chunk 一 Point、deterministic ID、可 rebuild | WP3 | idempotency/rebuild tests |
| REQ-QD-002 | published/current/ACL mandatory filters | WP3, WP8 | permission golden set |
| REQ-QD-003 | embedding model/version/dimension 可追溯 | WP3 | payload + migration tests |
| REQ-CSIT-001 | CSIT 是文件、報告、版本、審核、權限 SOR | WP4, WP5 | adapter contract + publish E2E |
| REQ-CSIT-002 | AI KM 不直連 CSIT DB | WP4 | dependency/architecture test |
| REQ-REPORT-001 | engineer upload → review/reject/resubmit/approve/publish | WP5, WP9 | workflow + UI E2E |
| REQ-REPORT-002 | AI 不得核准正式報告 | WP5, WP8 | authorization negative test |
| REQ-TS-001 | 時序明細進 TimescaleDB，摘要與 reference 跨庫連結 | WP6 | bulk ingest/query/join tests |
| REQ-GRAPH-001 | 固定 ontology、canonical ID、MERGE、source/evidence | WP7 | ontology/upsert/source tests |
| REQ-GRAPH-002 | LLM 不得自由執行 Cypher，depth 有上限 | WP7, WP11 | invalid template/depth tests |
| REQ-SEC-001 | RBAC/ACL 在後端與每個 Tool 強制執行 | WP8, WP11 | cross-tool bypass suite |
| REQ-CIT-001 | 正式答案可追至文件/報告/版本/位置/時間 | WP8, WP11 | citation completeness metric |
| REQ-AUD-001 | query、upload、review、publish、tool call 可稽核 | WP1, WP5, WP8 | audit event contract tests |
| REQ-DI-001 | 文字/圖片/混合/Excel/表格走專用 pipeline | WP10A | format golden files |
| REQ-DI-002 | OCR 按需、Excel 不走 OCR、low confidence 可 review | WP10A | routing/confidence tests |
| REQ-AG-001 | Fast path 與 Agentic path 分離 | WP11 | latency/routing golden set |
| REQ-AG-002 | 五種受控 Tool、planner budget、evidence validation | WP11 | multi-source contract tests |
| REQ-A2A-001 | bridge 隔離、預設關閉、dry-run 不碰儀器 | 保留 35d8d56；WP9/WP11 回歸 | A2A existing tests + dry-run E2E |
| REQ-OPS-001 | secret 外部化、持久化、health/readiness、可回滾 | WP0, WP1, WP11 | config scan + restore test |
| REQ-UI-001 | Portal 提供 QA/Search/Report Center/基本 Dashboard | WP9 | browser E2E |

## 2. 來源檔案覆蓋

| 來源 | 已納入的規劃區域 |
|---|---|
| `01_AI_KM_Phase規劃_v2.2` | Phase 順序、MVP 範圍、工期、POC 沿用、架構原則 |
| `02_Enterprise_AI_KM_Compile-Time_RAG_plus_Agentic_RAG` | Compile-Time／Agentic 模組、五 Tool、驗收與導入順序 |
| `03_AI_KM_Document_Intelligence_Pipeline_v2.1` | 文件分流、13 階段 pipeline、Knowledge Package、MVP module gates |
| `04_AI_KM_Enterprise_Knowledge_Graph_v2.1` | ontology、relationships、Graph Tool、資料庫責任與 Agentic routing |
| `05_AI_KM_Qdrant_TimescaleDB_正式化設計_v1.0` | 四庫分工、payload、timeseries schema/API、實作順序 |
| `06_AI_KM_實際工作切法_v2.4` | CSIT Owner／AI KM Implementation Owner 邊界與各 Phase 分工 |
| Docker/Redis/Celery 規範 | WP1 queue、retry、timeout、idempotency、health、logging |
| FastAPI/REST API 規範 | WP0 專案骨架、response/error、trace、Swagger |
| Knowledge Package Schema 規範 | WP2 models、validation、routing、19 個最低案例 |
| Neo4j 規範 | WP7 ontology、source/evidence、ACL、rebuild、17 個最低案例 |
| Qdrant 規範 | WP3 collection、point/payload/chunk/filter/version/ACL、17 個最低案例 |
| 系統架構圖 | 分層、五 Tool、四庫、security、integration boundary |
| 系統流程圖 | upload/review/publish/query/analysis/feedback 的端到端流程 |

## 3. 建議 Gate 順序

`G0 API baseline → G1 Job reliability → G2 Package/Router → G3 Secure projections → G4 CSIT publish → G5 MVP E2E → G6 Compile-Time quality → G7 Agentic safety → G8 Analysis quality`

任何 Gate 未通過時，不得用 UI demo 或 HTTP 200 取代資料、版本、權限與重跑驗證。
