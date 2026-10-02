# KM v2.6 Phase 1 整合審查 Dossier

**審查基準日：** 2026-10-02（台灣時間）
**範圍：** v2.6 Phase 1 實際工作分工 P1-WP01～P1-WP18、KM 三資料區（DA40/RD2/TEST）、目前 DEV 上傳／搜尋隔離驗收、OIDC 與 GitHub review 交付狀態。
**用途：** 提供 Patty 與 KM 團隊快速核對已完成範圍、證據、依賴與待驗收項目。這是整合審查摘要，不是整體 Phase 1 完工或正式 release acceptance 聲明。

## 結論

截至 2026-10-02，KM 已有可運作的 DA40、RD2、TEST 三區服務與入口，並完成本次 4G/5G 原始 Excel 上傳及向量／圖資料區隔離的實際驗證。TEST Qdrant 持久化卷已補上；三區 worker 的 TimescaleDB 連線已確認指向各自資料庫。這些結果補足了先前「上傳攝入前被拒」的阻塞。

不過，現有證據只證明這批原始報告經 KM 上傳流程進入其文件索引與 task tracking 路徑，不能外推為 CSIT 正式工作流、標準化量測資料、完整 RAG ACL、GraphRAG ontology、OIDC 或 Phase 1 全項驗收完成。正式身分提供者資料尚缺，OIDC 維持關閉；P1-WP04～WP08 的 CSIT API／流程工作也尚待對口交付或共同驗收。

## 對 Patty 的審查入口

- [GitHub review branch：agent/km-runtime-current-20261002](https://github.com/kyocarlos/knowledge-base-agent-source/tree/agent/km-runtime-current-20261002)
- 本文件：`docs/reviews/km-v2.6-phase1-review-dossier-20261002.md`
- 審查基準 source snapshot：`a433431`（本 dossier commit 將接在該分支之後）。此分支是供檢視的乾淨 source snapshot，尚非 main 的合併 PR 或 release provenance。

## 版本規劃與編號

原始 v2.6 工作分工表列出 18 項 Phase 1 工作。此處使用 `P1-WP01`～`P1-WP18` 對照該表及 `docs/phase1-status-manifest.json` 的工作編號。歷史文件中的「WP0／WP1」有時指交付包或驗收包，不等同於 P1-WP01／P1-WP02；KM-001～KM-014 是跨工作項的治理／架構議題，也不是 WP 編號。

排程日期是計畫日期，不代表該日已驗收。下表狀態為本 dossier 對截至基準日證據的整合判讀，並非原始 Excel 或舊 status manifest 的欄位值。

## P1-WP01～P1-WP18 現況

| ID | 工作範圍 | 截至 2026-10-02 的判讀 | 主要證據與未完成事項 |
|---|---|---|---|
| WP01 | Git、Branch、PR、Review（計畫 2026-08-12） | 部分完成 | GitHub 有 2026-10-02 KM source snapshot branch 可 review；它不是合入 main 的 PR／正式 release lineage。需 Patty review 並決定後續整併方式。 |
| WP02 | FastAPI／REST（08-14） | 已有實作，範圍驗收有限 | KM REST/API 已支援目前 portal 與上傳路徑；需以 CSIT 正式 API contract 完成端到端共同驗收。 |
| WP03 | Docker、Redis、Celery、環境設定（08-21） | DEV runtime 有效，非正式環境驗收 | 10/02 三區 web／worker 與資料庫服務在運行，健康檢查回 200。部署版本與 GitHub snapshot 不應視為同一 release provenance。 |
| WP04 | CSIT 程式與 API（08-26） | 待 CSIT／Patty 交付或共同驗收 | 未以正式 CSIT API 的真實資料流完成驗收；KM 本地功能不能替代 CSIT 端證據。 |
| WP05 | API Contract（09-02） | 部分／待簽認 | KM 有內部 API 與既有整合規格；正式 CSIT contract、版本／錯誤語意與雙方簽認仍需補齊。 |
| WP06 | 文件、測試計畫／報告／核准 API（09-11） | 部分 | 歷史 WP1 有受控 upload→approve→ingest runtime acceptance；該驗收不代表 CSIT approval API 已整合或目前 release 已重跑。 |
| WP07 | 設備預約（09-25） | 未完成／待 CSIT 流程 | 尚無足以證明 KM 與正式設備預約流程端到端整合的證據。 |
| WP08 | 系統驗證表（計畫 10-09） | 尚未驗收 | 基準日早於計畫日期；須依雙方確認的驗證表和測試資料執行並留存結果。 |
| WP09 | OpenClaw 報告上傳、測試結果／狀態（10-20） | 部分，真實整合待驗 | 有歷史 dry-run／KM-side 路徑紀錄，未證明正式 CSIT/OpenClaw source-of-truth 流程端到端通過。 |
| WP10 | Upload→Review→Reject→Publish（10-29） | KM-local 路徑部分可用 | 10/02 KM UI 上傳已完成；仍需驗證以 CSIT 為權威來源的完整 review、reject、publish 狀態與同步流程。 |
| WP11 | Excel parser／schema（10-29） | 原始檔攝入通過；標準 schema 部分 | 15/15 次本次上傳完成，報告進入 KM 文件索引；`km_ui_report_measurements` 為 0，故尚未證明已解析成標準量測／KPI 記錄。 |
| WP12 | RAG、MarkItDown、切 chunk、embedding（11-09） | 基礎路徑有證據，規格驗收部分 | 文件索引與檢索可用；formal ACL/filter contract、collection dimension 與 no-match／過濾證據仍未完整關閉。 |
| WP13 | Qdrant 向量搜尋（11-18） | 三區隔離情境通過；全規格部分 | DA40/RD2/TEST 各自資料區的正向與跨區負向檢查通過；正式 payload ACL／向量過濾與完整 acceptance 範圍仍待補。TEST Qdrant 已有持久化卷。 |
| WP14 | Neo4j GraphRAG（11-27） | 文件層索引隔離通過；GraphRAG 部分 | 三區文件的正向與跨區負向查詢通過；本次報告沒有建立 Entity／relationship，ontology 與關聯推理尚未驗收。 |
| WP15 | TimescaleDB 時序資料（12-08） | 連線與 task tracking 通過；KPI 部分 | 三區 worker 連到各自 TimescaleDB；此次有 `km_ui_uploads` task audit，但報告量測資料為 0，canonical KPI schema／hypertable 尚未證明。 |
| WP16 | RBAC、Citation、Audit、Query log（12-17） | 區域入口控制部分通過 | 控制帳號、session 與區域 grants 有隔離證據；OIDC disabled，且 CSIT identity、完整 citation／query audit 規格尚未共同驗收。 |
| WP17 | Portal Search／QA／Dashboard（12-31） | 上傳與搜尋可用；介面／完整功能部分 | Portal 登入、上傳、依區搜尋可用；頁首仍固定顯示 DA40，即使選 RD2／TEST；dashboard 全面驗收未完成。 |
| WP18 | 單元／整合／驗收／Golden tests（2027-01-14） | 有歷史測試與實際 E2E；全套部分 | 歷史 WP11 有 41 tests 通過的 disposable runtime 記錄，WP1 有受控 E2E；本次主機未安裝 pytest，未重跑 focused suite，也無完整 golden-test 閉環證據。 |

## 2026-10-02 三區上傳與隔離驗收

### 已確認

- 來源目錄為 `D:\Source_Code\know-ledge\測試報告範例檔案\data\raw\4G_5G`。本次五個 Excel 檔各上傳至 DA40、RD2、TEST，共 15 次；15 次皆完成攝入狀態。TEST 先前一次 SCU2140 嘗試失敗，修正設定後重試成功；統計的 15/15 是本次最終成功批次。
- Qdrant 與 Neo4j 的文件路徑隔離檢查均符合預期：在資料所在區可找到，在其他區查不到。
- 依照只保留單一 canary 的測試要求，DA40 留下 SCU5050，RD2 留下 SCU2140；TEST 沒有保留 canary。DA40 查 SCU5050 有結果、RD2 查相同內容無結果；RD2 查 SCU2140 有結果。
- TEST Qdrant 使用持久化 Docker volume `km-test_qdrant_storage`；重啟後仍可讀到 `knowledge_base` 4,073 points 與 `kb_syntheses` 9 points。
- TEST、DA40、RD2 worker 的 TimescaleDB 連線各自指向 TEST、DA40、RD2 資料庫。

### 驗收邊界

- `km_ui_uploads` 有本次 task 狀態紀錄，但 `km_ui_report_measurements` 為 0。這批是原始報告文件攝入，不是標準化 KPI／量測資料攝入驗收。
- 已驗證的是這次路徑下的文件檢索與資料區負向隔離，不是對所有 API、使用者角色與所有向量／圖 query 路徑的完整安全性證明。
- 尚未完成「只有 RD2 grant 的帳號」在實際 OIDC／角色綁定下的整套可見性驗收；也未測試所有不同權限組合。
- Portal 頁首固定顯示 DA40 是已知 UI 問題，雖不改變本次依選區查詢的結果，仍需修復並驗收。
- 原始報告、query 輸出、DB dump、備份檔、登入憑證與私有 runtime 設定不納入 GitHub dossier。需在受控環境對照 runtime 證據時，使用團隊內部留存資料；不要把原始敏感報告複製到公開 review 分支。

## OIDC 與身分整合

KM 已有 OIDC Authorization Code + PKCE S256、state／nonce、token exchange、ID token 驗證、claims mapping 與 `(iss, sub)` binding 的程式路徑，並已建立 DEV HTTPS callback route。基準日 runtime `/oidc/availability` 回報 `enabled:false`，因此**目前不能宣稱 OIDC 可登入或身分隔離驗收完成**。

啟用前尚需 Identity Provider 管理方提供正式 Issuer URL、Authorization Endpoint、Token Endpoint、JWKS URI、Client ID、`client_secret_basic` client secret；KM 維運方需在受保護設定注入 `KM_OIDC_BINDING_SIGNING_KEY`，並與 IdP 管理方核對 redirect/logout URI 與 claim mapping。所有密鑰只可經受控 secrets 管道設定，不得提交至此 repo。取得設定後仍須執行真實 IdP 登入、綁定／拒絕案例與角色授權驗收。

## GitHub review artifact 與 provenance

現有 review branch 提供 Patty 閱讀目前 KM source/config 與部分歷史文件的入口；新增本 dossier 後，也提供 v2.6 WP01～WP18 的整合進度摘要。branch 是乾淨 source snapshot，且與正式主線的 Git 歷史／release lineage 未完成合併整理。故 Patty 可以在該 branch review 內容，但不能把 branch 存在本身解讀成 PR 已 merge、所有變更已進 production 或 Phase 1 已簽收。

舊版 `docs/phase1-status-manifest.json` 反映較早基線（WP01/02/12/13/14 source validated、WP03/09/11/17/18 runtime validated、WP04～08/10/15/16 planned）；它沒有反映 10/02 新增驗收，也不應作為當前狀態。此 dossier 是人工整合判讀，後續應由工作負責人確認狀態、補上可分享的證據連結，並決定是否同步更新 machine-readable manifest。

## 建議 Patty 優先 review 的決策點

1. 確認 WP04～WP08 的 CSIT owner、正式 API/contract、UAT 資料集與交付日期，尤其設備預約與系統驗證表的驗收責任。
2. 確認 WP09～WP11 的 source-of-truth 與文件生命周期：CSIT/OpenClaw 的 report、review/reject/publish 狀態如何對接 KM，並定義原始文件與標準量測解析的完成條件。
3. 核定 WP12～WP16 的安全與資料模型驗收標準：ACL filter、GraphRAG ontology、Timescale KPI schema、OIDC claim-to-grant mapping、citation 與 query audit。
4. 確認本次三區隔離驗收是否接受為 DEV 文件路徑證據，以及尚需哪些 role-only、API-level 與 golden tests 才能簽署完整隔離驗收。
5. 決定如何將 snapshot branch 整理成具共同 Git ancestry 的 PR／review 流程，並為每項已完成工作附上可追溯 commit、runtime build 與測試紀錄。

## 主要限制與判讀方式

- 文件中的「通過」僅限定在明確寫出的測試路徑與環境，不推論至未測的權限、API、GraphRAG、KPI 或正式 production。
- 部分 10/02 runtime 結果來自已核對的遠端服務狀態、資料庫路徑／計數與操作記錄摘要；敏感原始資料沒有發布在 GitHub。Patty 若要簽署正式驗收，仍需在受控環境查看完整內部證據。
- 舊歷史測試結果保留其原始日期和範圍，不代表 10/02 branch 或 runtime 已重現同一結果。
- 目前不能將 v2.6 Phase 1 判定為完成；較準確的描述是：KM 平台與三資料區隔離已有實際進展及局部驗收證據，跨 CSIT 工作流、OIDC 身分、標準化資料模型及完整 WP acceptance 仍有明確待辦。
