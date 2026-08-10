# 基準程式現況與差距分析

## 1. 基準 commit 摘要

`35d8d56` 新增隔離的 `km_a2a_bridge`：

- 預設 disabled，transport 僅 `mock` 或 `sdk-dry-run`。
- HTTPS Agent Card discovery、同 origin 驗證、獨立 outbound credential。
- allowlisted profile、固定 job、run idempotency、SQLite journal。
- A2A task 與 test/report/ingest 三種業務狀態分離。
- 測試涵蓋 contract、HTTP API、service、SDK transport。

這是一個正確的安全基線，但它只涵蓋外部測試委派的 Mock／Dry-run control plane，不等於整體 AI KM 正式化。

## 2. 可沿用能力

| 能力 | 現有位置 | 評估 |
|---|---|---|
| FastAPI Web API | `src/web_api/__init__.py` | 可沿用路由與前端契約，但檔案過大、缺統一 envelope／trace／exception 架構。 |
| Redis／Celery | `docker-compose.yml`, `src/web_api/tasks.py` | 已有 search／ingest worker；須改為可配置 queue、retry、timeout 與 durable job state。 |
| Qdrant client | `src/vector_store/__init__.py` | 已有 embedding、upsert、search；payload、ACL、version、collection 策略不符合新規格。 |
| Neo4j／GraphRAG | `src/ingest.py`, `src/graphrag/*`, `src/test_reports/canonical_graph.py` | 已有 MERGE 與報告圖譜基礎；ontology、source evidence、constraint、ACL、受控 query 需統一。 |
| Excel report validation | `src/test_reports/excel_contract.py` | 可作 Phase 1 固定 Parser 起點；仍需 Knowledge Package、unit/range、schema error code 與 Timescale routing。 |
| Report review workflow | `src/web_api/report_routes.py`, `src/test_reports/registry.py` | 已有 upload、pending review、approve/reject、ingest；須與 CSIT SOR 邊界重新定位。 |
| Idempotent ingest | `src/ingest_conflict_protection.py`, `src/ingest_registry.py` | 可沿用 hash／registry 思路；需升級成跨庫 publish ledger／compensation。 |
| Vue Portal | `frontend/src/*` | 已有 Search、Upload、Report Review、Admin；可漸進調整，不需重建。 |
| A2A dry-run bridge | `km_a2a_bridge/*` | 保持隔離；後續只接受受控 Automation Tool，不與核心資料 contract 混寫。 |

## 3. 主要差距

| Gap | 現況證據 | 目標 | 風險 | 對應 WP |
|---|---|---|---|---|
| GAP-001 正式 FastAPI 分層 | `src/web_api/__init__.py` 集中大量 model、route 與邏輯 | `app/api/core/schemas/services/repositories/adapters/workflows/tools` | 難測試、contract 漂移 | WP0 |
| GAP-002 統一 response／trace／error | 端點回應格式不一致，A2A bridge 另有風格 | `/api/v1` envelope、global handler、trace propagation | 無法跨服務追查、可能洩漏錯誤 | WP0 |
| GAP-003 Job contract | `tasks.py` 有硬編碼 concurrency、TTL、query hints；Celery Beat 預設啟動 | 可配置 queue、固定 state、retry policy、timeout、idempotency | 卡死、重複、不同環境不一致 | WP1 |
| GAP-004 Knowledge Package | 尚無共同 Pydantic model／validator | schema 1.0、dictionary、citation、ACL、routing、publish | 各 Parser／DB 欄位分裂 | WP2 |
| GAP-005 Data routing | ingest 同時直接建立 Neo4j／Qdrant 投影 | validation 後產生唯一 routing plan | 錯誤資料直接進正式索引 | WP2 |
| GAP-006 Qdrant 正式化 | collection=`knowledge_base`；payload 無強制 published/current/ACL；point id 依 doc name/index | `ai_km_knowledge_v1`、deterministic id、schema validator、filter builder、rebuild | 草稿／舊版／未授權內容外洩 | WP3 |
| GAP-007 CSIT SOR | 本地 report registry 管正式審核狀態 | CSIT Adapter／Contract；本地 registry 僅技術 job／cache | 兩套正式狀態分裂 | WP4 |
| GAP-008 Publish ledger | approve 後直接派 ingest；無完整跨庫 compensation | validated → approved → staged projections → verify → published | 部分成功造成跨庫不一致 | WP5 |
| GAP-009 TimescaleDB | compose、migration、repository、API 均缺 | test_run／metric_sample hypertable／summary／query API | KPI 被轉文字、無可信趨勢分析 | WP6 |
| GAP-010 Neo4j ontology | Generic Entity、Document/TextUnit 與 canonical report graph 並存 | 固定 ontology、canonical ids、evidence、MERGE、constraints、templates | 同義節點、任意 relation、ACL 繞過 | WP7 |
| GAP-011 RBAC／ACL | agent/reviewer token 局部存在；search path 缺共同 authorization context | 統一 identity、deny-by-default、tool-level filter | 資料外洩 | WP8 |
| GAP-012 Citation／audit | sources 有部分 metadata；缺標準 citation object 與 query/tool audit | 文件／報告／sheet/cell/time range 可追溯 | 回答不可驗證 | WP8 |
| GAP-013 CSIT/OpenClaw tools | 已有 upload/A2A 雛形，尚未納入五種 Tool contract | 固定 CSIT、Vector、Graph、Timeseries、Automation Tool | LLM 直接呼叫底層 | WP9, WP10 |
| GAP-014 Agentic RAG | auto/basic/deep/vector/hybrid 以規則與模式切換 | intent、fast/agentic selector、planner、router、evidence、context、citation | 無多來源證據鏈、成本不可控 | WP10 |
| GAP-015 測試與 CI 基線 | repo 未宣告 pytest dependency；目前環境無法執行 pytest | lock/dev dependency、unit/integration/contract/security/golden gates | 無可靠回歸基線 | WP0 持續 |
| GAP-016 部署可攜性 | compose 有主機絕對路徑、預設密碼與硬編碼服務 | env-driven profiles、persistent volumes、health/readiness、secret 外部化 | 換機／session／runtime 失敗 | WP1, WP11 |

## 4. 必須保留的既有行為

- 現有 chat/search/ingest/UI 在每個 migration 階段仍可使用。
- report upload 的 `environment + run_id` idempotency 與 approve/reject 邏輯不可回歸。
- A2A bridge 維持 default disabled、dry-run only；不可因新 Automation Tool 誤開真實儀器。
- 新版 Qdrant／Neo4j projection 未驗證前，不刪除既有 collection／graph。
- 既有 API 若改版，必須有相容 adapter、deprecation 記錄與 consumer test。

## 5. 基線驗證狀態

- 壓縮包 13 份檔案已完整讀取；兩張 PNG 已視覺核對。
- Git checkout 與指定 commit 一致。
- 嘗試執行 `python -m pytest -q`，環境回報 `No module named pytest`；此為基線工具缺口，不代表測試通過或失敗。
