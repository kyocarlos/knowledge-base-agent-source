# WP0／WP1 v2.6 差異評估表

盤點基準：`agent-source/agent/km-plan-v2.6-anderson`，commit `55c1b08b08870705bd471ab63f070ce39b1360be`。

分類只能使用：`A` 完全符合可保留；`B` 功能保留但校正規格／命名／Owner／Phase；`C` 需補程式或測試／驗收；`D` 超出 Anderson／KM 責任；`E` 無 GitHub 證據。

| WP | 項目 | 分類 | GitHub 證據 | 處理 |
|---|---|---|---|---|
| WP0 | FastAPI shell、v1 router、response/error/trace/exception | A | `2c46c834`、PR #2 backend success | 保留程式與歷史 |
| WP0 | legacy Portal/chat/search/report/review/ingest/A2A 相容層 | A | PR #2 tests 與相容性 test files | 保留，不重構 |
| WP0 | Phase、REQ／ADR 與 Owner 追溯 | B | PR #2 舊編號；v2.6 `REQ-API-001` | 文件校正，不改寫 commit |
| WP0 | CI overall、review、merge、正式 E2E | C | Actions `31405151388` 曾因 shallow checkout 導致 `fatal: bad object`；修正後 `31466582947` 三個 job 全部成功；reviews 空；未 merge | CI 缺口已關閉，仍須 review、merge 與正式 E2E artifact |
| WP0 | CSIT Web／DB／Workflow／商業邏輯 | D | v2.6 responsibility baseline | 列 Patty／跨組依賴，不納入 WP0 |
| WP0 | v2.6 原始 Excel | E | branch/tree 無該 `.xlsx` | Owner 提供後再關來源 Gate |
| WP1 | typed config、queue、status、retry、trace、idempotency | A | `2a4ba2af`～`7cfa1d6e`、CI backend success | 保留程式與測試 |
| WP1 | worker restart、持久化與 health 修正 | A | `0dad72bd`、`7cfa1d6e`、CI success | 保留，不重做 |
| WP1 | Phase、REQ 與責任歸類 | B | v2.6 `REQ-JOB-001` | 改列 Phase 1 前置 |
| WP1 | PR／review／merge、正式故障與 backup/restore | C | GitHub 查無 WP1 PR；無正式演練 artifact | 建 PR 並補驗收 |
| WP1 | CSIT Schema／Workflow／商業狀態 | D | v2.6 responsibility baseline | 由 Patty 提供 Contract |
| WP1 | 隔離 runtime 原始紀錄與 v2.6 Excel | E | GitHub 無 run artifact；tree 無 Excel | 不以文字聲明替代正式證據 |

## 保全與整合決策

1. 驗收分支從 v2.6 規劃 commit 建立，再非破壞性 merge WP1；WP1 已包含 WP0 程式歷史。
2. 另外保留 WP0 workflow commit `19d0751e`，避免因 WP1 分支較早分叉而遺失。
3. 不修改已通過測試的 runtime 程式；補正集中在追溯、Evidence、週報、PPTX 與 Gate。
4. 不採用只綁定舊分支名稱的 weekly push／PR trigger；候選簡報使用現有 `workflow_dispatch`／schedule artifact 流程。
5. 不建立、猜測或反向產生缺失的 v2.6 Excel；由規劃 Owner 提供原檔後另行核對。

## 驗證中發現的殘餘風險

- `npm audit` 對週報工具回報 2 個 high advisory，來源是 `pptxgenjs` 間接使用的 `image-size`；建議修正涉及 major downgrade，不在本驗收 PR 強制處理。
- frontend lockfile 回報 3 moderate、4 high advisories，涵蓋既有 Vite／ws／Monaco 依賴；frontend build 成功不代表 dependency security gate 通過，應另開相容性可驗證的升級 PR。
- Python 測試有既有 `langchain-community` sunset deprecation warning；不影響本次 83 tests，但需排入後續技術債。

## 本次驗收證據

- 整合後完整 pytest：83 passed。
- compileall、Compose config、shell syntax、frontend production build：通過。
- W33 JSON schema／權重／Phase／program 計算與 Markdown token：通過。
- PPTX 從同一 JSON 連續產生兩次；除 `docProps/core.xml` 產生時間外，解壓後內容一致。
- LibreOffice 成功渲染為 7 頁、16:9 PDF；逐頁 PNG 人工檢查無文字溢出、遮蔽、空白頁或不可辨識小字。
- v2.6 驗收分支 CI：WP0 run `31466582947` 與 WP1 run `31466582953` 的 backend、frontend、repository-hygiene 共六個 job 全部成功。
