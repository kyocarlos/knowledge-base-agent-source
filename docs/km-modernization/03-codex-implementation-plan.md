# Codex 分階段實作計畫

## 執行模型

每個 Work Package 必須獨立 PR，依順序完成。只有前一個 Gate 通過，下一個 WP 才可修改 production path。若外部 contract 尚未提供，先做 port、fake adapter 與 contract test，不得猜欄位。

## Phase 0：正式化基座

### WP0 — FastAPI contract 與測試基線（P0，1～2 週）

**目標**：建立正式應用骨架，但不重寫既有 RAG。

**新增／調整**

- 新增 `app/main.py`、`app/api/v1/router.py`、`app/core/{config,logging,exceptions,security,trace}.py`。
- 新增 `app/schemas/common.py`：`ApiResponse[T]`、`ApiError`。
- 新增 `/api/v1/health`、`/api/v1/version`、live／ready 擴充點。
- 將現有 `src.web_api:app` 先以 compatibility router mount，逐步抽離。
- 新增 dev/test dependency 與 deterministic test command；不要將測試工具只留在個人環境。

**驗收**

- 每個 response 與 log 有同一 trace id。
- 未處理例外不回傳 stack、path、secret。
- Router 不直接連 DB／Qdrant／Neo4j／CSIT。
- 舊 UI 與 report agent contract smoke test 通過。

### WP1 — Docker／Redis／Celery／Config 正式化（P0，1～2 週）

**目標**：可重現、可配置、可追蹤的背景工作底座。

**新增／調整**

- 將 `MAX_CONCURRENT_PROCESSING`、TTL、timeout、retry、queue 全部移入 typed config。
- 建立共用 Job model：`queued/running/succeeded/failed/retrying/cancelled`。
- 建立 `default/document/indexing` queue；現有 `search/ingest` 先保留 alias，再遷移。
- `trace_id` 從 API 傳到 Celery；分類 transient／non-retryable error；最多有限次 retry。
- Celery Beat 改為 opt-in profile；移除不必要的 production 預設啟動。
- compose 移除主機硬編碼路徑與弱預設密碼；以 env、named volume、profile 表達。

**驗收**

- queue routing、retry、non-retry、timeout、worker restart、idempotency integration test。
- container 重建不遺失正式資料。
- `.env` 不入 Git；log 不含 token／完整敏感 payload。

## Phase 1：Production-ready MVP

### WP2 — Knowledge Package 1.0 + Validation + Data Routing（P0，2～3 週）

**目標**：鎖定所有後續資料庫共用 contract。

**建議檔案**

- `app/domain/knowledge_package/{models,enums,dictionary,validator,routing}.py`
- `app/schemas/knowledge_package.py`
- `tests/unit/knowledge_package/*`
- `tests/fixtures/knowledge_packages/{document,report,image}.json`

**必要模型**

- source、document、metadata、text/table/image content、test_context、version、acl、citation、processing、routing、publish。
- 統一 ID dictionary、document type allowlist、unit/range rules、validation error code。
- `document_id + document_version + checksum` conflict／idempotency。

**Gate**：規格列出的 19 個最低案例全通過；任何 invalid package 不會排出 DB mutation job。

### WP3 — Qdrant projection v1（P0，2～3 週）

**目標**：從 validated package 建立可重建、權限安全的向量索引。

**新增／調整**

- collection `ai_km_knowledge_v1`；模型／dimension 由 config 定義。
- Point ID = deterministic UUID(document_id, version, chunk_id)。
- Payload model 完整包含 source、version、citation、ACL、embedding version。
- Chunk 依 section／paragraph／table／caption；起始 400～700 target tokens、900 max、50～100 overlap，全部可配置。
- Backend 強制 `published && is_current`，再疊 ACL 與 validated business filter。
- 建立 payload index、rebuild、shadow validation、version switch；禁止先刪舊 collection。

**Gate**：17 個最低案例與 permission golden set 全通過；同資料重跑 point count 不增加。

### WP4 — CSIT Adapter 與正式 API Contract（P0，2～4 週；依外部 API）

**目標**：把 CSIT 與 AI KM 內部切開。

**介面**

- Document、Report、Test Plan、Approval Status、User/ACL。
- timeout、retry、error mapping、trace propagation、contract version。
- AI KM 不得存取 CSIT DB；local report registry 降級為 technical job/cache 或移除。

**Gate**：consumer-driven contract tests；CSIT unavailable／timeout／permission／version conflict 明確失敗。

### WP5 — Report Publish Workflow／Ledger（P0，2～3 週）

**目標**：保留現有工程師上傳與主管審核，改為 CSIT SOR 與跨庫一致發布。

**狀態**

`draft → validated → pending_review → rejected | approved → publishing → published | publish_failed`

**規則**

- Engineer upload：固定 Excel schema validation 後送 CSIT pending review。
- Manager direct upload：仍需 schema validation，但依 CSIT 權限可直達 approved。
- Approved 才產生 Qdrant／Neo4j／Timescale reference projection jobs。
- ledger 保存 job、package、source version、各 projection 狀態、retry、compensation 與 audit。

**Gate**：reject/resubmit/version、partial failure/retry、duplicate publish、permission、AI cannot approve 全通過。

### WP6 — TimescaleDB foundation（P0，2～3 週）

**目標**：把 iPerf／PHY／RF／KPI 時序數據從 Qdrant／Neo4j 分離。

**資料與 API**

- migrations：`test_run`、`metric_sample` hypertable、`test_run_summary`。
- index `(test_run_id, metric_name, time)`；summary unique `(test_run_id, metric_name)`。
- `/api/v1/timeseries/test-runs|metrics|compare|trend`。
- retention/compression/continuous aggregate 先設 config 與 migration，依 OQ-004 啟用。

**Gate**：bulk ingest、interval query、aggregation、ACL、idempotency、capacity baseline。

### WP7 — Neo4j ontology v1 與受控 Graph Service（P0，2～4 週）

**目標**：由 Generic GraphRAG 遷移到可重建的正式 knowledge graph。

**Phase 1 節點**：Product、Firmware、TestCase、TestRun、TestResult、Report、Document。

**規則**

- unique constraints、canonical ids、normalization、unresolved entity queue。
- Node／relationship 全部有 source／lineage；`ai_inferred` 未 review 不作正式 evidence。
- MERGE upsert；大量文字、向量、interval sample 不進 graph。
- query templates、validated parameters、default depth 2、max 3、source ACL check。

**Gate**：17 個最低案例、rebuild、duplicate、unpublished、depth、ACL 全通過。

### WP8 — RBAC／Citation／Audit／Query Log（P0，2～3 週）

**目標**：所有查詢路徑共用治理層。

**新增**

- `AuthContext(user_id, roles, department, projects)` 與 deny-by-default policy。
- Citation object 支援 document/report/version/page/section/sheet/cell/time range。
- Audit event：trace、actor、action、tool、filters、sources、result、latency、error；不記 secret／完整敏感內容。
- permission golden set 與 cross-tool bypass tests。

**Gate**：任一 Vector／Graph／Timeseries／CSIT route 無 identity 或 ACL 不符均無法取得 evidence。

### WP9 — Portal、OpenClaw 與 MVP 整合（P0/P1，2～4 週）

**目標**：交付可正式使用的 Search／QA／Report Center／Dashboard。

**規則**

- 沿用 Vue；Portal 只呼叫 AI KM／CSIT API，不直接碰 DB。
- OpenClaw 只經固定 Adapter／Tool 進行 report upload、result/status。
- A2A bridge 維持隔離、disabled、dry-run only；本 WP 不開 real mode。

**Gate**：工程師 upload → manager reject/resubmit/approve → publish → authorized search/citation 的真實 UI E2E；同時驗證既有 chat/search/ingest 回歸。

## Phase 2：Compile-Time RAG（8～12 週）

### WP10A — Document Intelligence

- File Type Detector；Text、Vision/OCR、Layout、Table/Excel 專用 pipeline。
- OCR 只按需；Excel／table 禁止以 OCR 取代 parser。
- low-confidence 人工確認、來源 bounding/page/cell 追蹤。
- package validation 前不建立 production index。

### WP10B — Entity normalization／ontology mapping／rebuild

- alias dictionary、master data resolution、graph mutation plan。
- Qdrant metadata/index rebuild；Neo4j rebuild；publish ledger compensation。

**Phase 2 Gate**：各格式 golden files 可重跑、可追溯、無重複；圖片與表格資訊不遺失。

## Phase 3：Agentic RAG（8～12 週）

### WP11 — 受控五 Tool 與 Orchestrator

- Tool contracts：CSIT Query、Vector Search、Graph Query、Time-Series、Automation。
- Intent Classifier → Fast/Agentic Selector → Planner → Router → Executor → Evidence Validator → Context Builder → LLM → Citation Builder → Evaluator。
- 規則優先；planner 有 step/token/timeout/tool budget；禁止自由 SQL/Cypher/SSH。
- Automation query 與 execute 分開；高權限 execute 需明確確認。

**Gate**：intent/routing/evidence/citation golden set；簡單問題不進 planner；低信心追問或 no-answer；未授權／舊版 evidence 排除。

## Phase 4：AI Analysis & Review（8～12 週）

### WP12 — Root Cause／Benchmark／Similar Case／Recommendation

- 每個結論區分 evidence、inference、confidence。
- 比較前驗證 product/firmware/band/test condition/metric 口徑。
- AI report review 只檢查缺漏與異常，不改變 CSIT approval。
- 建立 Answer Evaluation runner 與業務 Golden Set。

## Phase 5：Enterprise Evolution（12～24+ 週，條件式啟動）

### WP13 — Multi-Agent／Predictive／Proactive Workflow

只有資料量、單 Agent 品質與商業 KPI 達門檻才啟動；必須先定義模型目標、準確率、誤報成本、人工核准與停止條件。不得為了架構展示提早導入。

## 每個 PR 的 Definition of Done

1. 連結需求 ID 與 ADR。
2. API/schema/migration/config 版本化，無硬編碼秘密或主機路徑。
3. Unit + integration + contract/security tests；測試真正驗證版本、權限、重跑與失敗模式。
4. 向後相容／migration／rollback 說明。
5. README、OpenAPI、example env 更新。
6. 不修改該 WP 以外的無關模組。
7. 本地檢查成功；若因外部依賴未驗證，明確標記 blocker，不宣稱完成。
