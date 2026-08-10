# 規格真實來源與架構決策

## 1. 規格優先序

來源文件存在 Phase 編號與 MVP 範圍不完全一致的情況。實作時採以下優先序：

1. 安全、權限、正式資料來源、人工核准等不可逆治理規則。
2. `06_AI_KM_實際工作切法_v2.4`：最新版責任分工與交界。
3. `01_AI_KM_Phase規劃_v2.2`：最新版整體 Phase 與工期基準。
4. 五份 v1.0 技術規範：模組 contract 與驗收細節。
5. `03`／`04` v2.1 架構設計：Document Intelligence 與 Knowledge Graph 詳細設計。
6. `02` 架構核心：概念與長期目標；若 Phase 編號衝突，服從第 2、3 項。

## 2. 已鎖定的架構決策

| ID | 決策 | 實作含義 |
|---|---|---|
| ADR-001 | CSIT 是唯一 System of Record | 文件、報告、版本、核准、權限以 CSIT 為準；AI KM 只透過正式 API／Adapter 存取。 |
| ADR-002 | Knowledge Package 是統一中介契約 | Parser → Package → Validation → Routing；禁止 Parser 直接寫任何知識庫。 |
| ADR-003 | 四庫分工不可混用 | CSIT 管主資料；Qdrant 管語意 Chunk；Neo4j 管正式實體關係；TimescaleDB 管時序明細。 |
| ADR-004 | 先 MVP、後底層重構 | FastAPI、Docker、Redis、Celery、MarkItDown、既有 RAG／GraphRAG 可沿用，但須包入正式 contract。 |
| ADR-005 | GraphRAG 是一個受控 Tool | 長期主架構是 Agentic RAG；Neo4j 不再兼任全文、向量與時序資料庫。 |
| ADR-006 | 正式資料只在 Published 後可檢索 | Draft／Validated／Approved 不進 production Qdrant；一般查詢固定套用 `published && current`。 |
| ADR-007 | 權限不能依賴 Prompt 或前端 | Backend／Gateway 在每個 Tool 執行前建立 ACL filter；任何路徑都不可繞過。 |
| ADR-008 | AI 不得核准正式報告或知識 | Manager approval 永遠是人工決策；AI 僅可摘要、檢查與建議。 |
| ADR-009 | LLM 不直接控制資料庫或設備 | SQL／Cypher／Automation 全部經 allowlisted Tool 與參數驗證。 |
| ADR-010 | 所有長工作使用可靠 Job Contract | `job_id`、`trace_id`、固定狀態、有限 retry、timeout、idempotency、audit 必須一致。 |
| ADR-011 | 索引可由正式來源重建 | Qdrant／Neo4j 是 projection；rebuild 不得造成重複或先刪正式舊版造成空窗。 |
| ADR-012 | A2A bridge 保持隔離、預設關閉 | commit `35d8d56` 的 mock／SDK dry-run 邊界保留；未通過 Gate 不納入 production Compose。 |

## 3. 已辨識的來源衝突與裁決

### D-001：Document Intelligence 應在 Phase 1 或 Phase 2？

- `01 v2.2`：Phase 1 沿用 MarkItDown；完整 File Type／Vision／Table Pipeline 放 Phase 2。
- `03 v2.1` 與 `02` 的部分頁面：把完整 Document Intelligence 描述為 MVP 必要。
- 裁決：Phase 1 只做正式報告所需的固定 Excel Parser、來源／版本／ACL、Knowledge Package 最小契約與 routing 骨架；通用 Vision／OCR／Layout／Mixed Document 放 Phase 2。

### D-002：Phase 1 是否包含設備預約與系統驗證申請？

- `06 v2.4`：列為 P1 CSIT 新功能。
- `01 v2.2`：若併入 Phase 1，另加 3～5 週緩衝。
- 裁決：列為 `P1-OPTIONAL`，不得阻塞核心 AI KM MVP；需由 CSIT Owner 確認是否啟動。

### D-003：Qdrant collection 名稱

- 新規格要求 `ai_km_knowledge_v1`。
- 現有程式使用 `knowledge_base`。
- 裁決：不得原地改名。新增版本化 collection 與雙讀／reindex／切換程序，驗證完成後再切換 alias 或設定。

### D-004：Knowledge Package schema 版本

- `03` 稱 Knowledge Package v2.1；v1.0 規範的 JSON 使用 `schema_version: 1.0`；Qdrant 規格也使用 1.0。
- 裁決：程式 contract 首版使用 `1.0`；文件版號不等於 JSON schema 版號。後續 breaking change 才升 schema。

### D-005：FastAPI URL 與 response 格式

- 新規格要求 `/api/v1` 及統一 envelope。
- 現有 `/api/agent/v1`、`/api/admin/v1`、search/task routes 已被前端與 agent 使用。
- 裁決：先建立共用 response/error/trace 元件；既有端點加相容層與 deprecation 計畫，不做一次性破壞式改名。

## 4. 開工前仍需業務確認

| ID | 問題 | 預設值 | 影響 |
|---|---|---|---|
| OQ-001 | Phase 1 是否納入設備預約與驗證申請？ | 否，列獨立 optional track | 若納入，估計增加 3～5 週且主要修改在 CSIT repo。 |
| OQ-002 | CSIT API 的正式 OpenAPI／認證方式何時提供？ | 先用 port/interface + fake adapter | WP4 無法完成真實整合驗收。 |
| OQ-003 | Phase 1 ACL 的角色、部門與 private 高權限角色清單？ | `internal/department/private`，deny-by-default | 影響 Qdrant、Graph、Report 與 Portal 測試集。 |
| OQ-004 | Timescale raw sample retention、壓縮與容量目標？ | raw 6 個月、7～30 日後壓縮，摘要長留 | 影響 migration、policy 與容量測試。 |
| OQ-005 | Production embedding model／dimension？ | 保持既有模型直到 reindex Gate | 影響 collection migration。 |
| OQ-006 | Phase 1 Portal 沿用 Vue 還是另建 UI？ | 沿用現有 Vue，外科式擴充 | 避免 Portal 重寫阻塞後端。 |
