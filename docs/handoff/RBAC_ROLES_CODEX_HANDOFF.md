# KM Phase 1 RBAC 角色（Engineer / Manager / Admin）— Codex 開發交接

- 日期：2026-10-16
- 基準分支：`codex/cross-search-source-credentials-20261015`（交接時遠端 head `09f2bca`）
- 規劃來源：`KM_Modify/01_AI_KM_Phase規劃_v2.6.xlsx`（不在本 repo，路徑位於 DGX `/home/da40_ai_gb10/knowledge-base/KM_Modify/`）
  - 「Phase 1 詳細內容」H 群組：**Basic RBAC / ACL — Engineer、Manager、Admin 權限；不同角色只能執行被授權操作**
  - 「實際工作分工」P1 治理：**RBAC / Citation / Audit / Query Log — 權限不能靠 Prompt；回答必須可追溯**（預計 2026-12-17）
  - 架構原則：**AI 不自動核准報告**；**LLM 不直接連資料庫**
- 本文件只涵蓋 **RBAC 角色**。Citation、Query/Answer Log、文件層 ACL（Qdrant `access_roles`）不在本次範圍，見「範圍外」。

## 1. 目標

在 KM 資料平面（da40 / test 兩區）建立 Engineer / Manager / Admin 三種角色，並由**伺服器端**依角色限制可執行的操作。前端隱藏按鈕只是體驗，不能當作權限控制。

成功標準：

1. 每個資料區的授權（grant）都帶有三種角色之一，舊資料可無痛遷移。
2. 每個寫入或管理類端點都由共用 dependency 依「權限 → 角色」對照表檢查，未授權回 403；未登入回 401。
3. 對照表是設定／資料驅動，不寫死在各端點內。
4. 角色變更立即生效（下一個 request 就生效），並寫入 `km_audit_events`。
5. Webwright 以真實登入走過三種角色的允許／拒絕流程。

## 2. 現況（已查證程式碼，2026-10-16）

### 2.1 角色只有 `user` / `admin`，而且資料平面沒有用來授權

| 位置 | 現況 |
|---|---|
| `src/km_control.py:24` | `GRANT_ROLES = frozenset({"user", "admin"})` |
| `src/km_control.py:102` | `issue_entry_session(user_id, instance_id, role, epoch)`：`km_entry_session` 內含 `role` claim，有效 15 分鐘 |
| `src/km_control.py:441` | `validate_entry_claims`：每個 request 都比對 Control DB 的 grant，role 不一致即拒絕（所以改角色後舊 token 會立刻失效，需重新進入資料區） |
| `src/km_control.py:176` | `km_users.is_admin`：**Control 平面**（帳號管理）的管理員旗標，與資料區角色是兩回事 |
| `src/control_auth_routes.py:60` | 管理 API 的 role 欄位只允許 `^(user|admin)$` |
| `src/control_auth_routes.py:108` | Control 管理端點檢查 `is_admin` |
| `src/web_api/instance_auth_routes.py:54-68` | `InstanceAuthMiddleware`：只驗證「有登入且 grant 有效」，把 claims 放進 `request.state.km_identity`；**沒有任何端點讀 `role` 做授權** |
| `src/km_dev_upload/auth.py`、`src/web_api/cross_search_bridge.py` | 同樣只驗身分，不看角色 |

DEV Control DB 唯讀查詢（2026-10-16）：`km_instance_grants` 中 active grant 為 da40 `user` × 4、test `user` × 8，沒有 `admin`。

### 2.2 報告審核用的是靜態 Bearer token，不是使用者角色

- `src/web_api/report_routes.py:175`（approve）、`:223`（reject）呼叫 `authenticate_report_reviewer`。
- `src/test_reports/auth.py:133`：比對 `KB_REVIEWER_TOKEN_HASHES_JSON` 的 token hash，回傳 `reviewer_id`。
- 所以「主管核准」目前等於「持有 reviewer token 的人」，無法對應到 KM 使用者或 Manager 角色。

### 2.3 一般登入者可以呼叫的管理類端點（依程式碼判斷，未做 runtime 驗證）

3030 Nginx（`deploy/dev-3030/nginx.runtime.conf`）把 `/api/`、`/da40/api/` 轉給資料平面 web；根路徑 `/admin/*` **沒有**對外轉送。經 `/api/` 可到達、且除了登入外沒有其他檢查的寫入端點包括：

| 端點 | 位置 | 說明 |
|---|---|---|
| `PUT /api/skills/{skill}/files/{file}` | `src/web_api/__init__.py:3704` | 改寫 Skill 檔案 |
| `POST /api/upload/tasks/clear` | `src/web_api/__init__.py:3159` | 清除攝入任務歷史 |
| `POST /api/upload`、`/api/upload/json`、`/api/upload/ingest`、`/api/ui/upload/ingest` | `src/web_api/__init__.py:2683-2833` | 上傳與攝入 |
| `GET /api/admin/stats` | `src/web_api/__init__.py:2285` | 系統狀態（唯讀） |

Codex 必須先用 `grep -nE '@(app|router)\.(get|post|put|delete|patch)\(' src/web_api` 列出完整清單，逐一分類，不要只依上表。

### 2.4 相關的既有問題（不在本次範圍，但要知道）

- **登出不會撤銷 session**：`POST /api/auth/logout`（`src/web_api/instance_auth_routes.py:93`）和 Control 的 logout 只刪 cookie，不遞增 `session_epoch`。登出前被複製出去的 `km_entry_session`，15 分鐘內仍可使用（2026-10-16 mock Confluence E2E 已重現，證據在 DGX `.km-control/mock-confluence-e2e-20261016/`）。使用者尚未決定修法，**本次不要順手修改**。
- `docs/phase1-status-manifest.json` 停在 2026-09-03，是 **STALE**；本次不要求更新，但 WP16 狀態不得標為完成。

## 3. 建議設計（Codex 可調整，但需說明理由）

### 3.1 角色與權限對照（資料驅動）

新增設定檔，例如 `config/km-rbac.yaml`（路徑可經 env `KM_RBAC_POLICY_FILE` 覆寫）：

```yaml
schema: km.rbac-policy.v1
roles: [engineer, manager, admin]
legacy_role_map: {user: engineer, admin: admin}
permissions:
  kb.query:          [engineer, manager, admin]
  report.upload:     [engineer, manager, admin]
  report.review:     [manager, admin]      # approve / reject
  report.publish:    [manager, admin]
  upload.task_clear: [admin]
  skills.write:      [admin]
  system.admin:      [admin]
```

- 權限名稱、角色名稱都只出現在設定檔與共用模組，端點只宣告「需要哪個 permission」。
- 設定檔缺失或格式錯誤時 **fail closed**（啟動失敗或所有受保護端點 503），不可默默放行。
- Manager 是否能同時上傳、Engineer 能否看待審清單等細節，見第 5 節「待決策」。

### 3.2 資料庫遷移（Control DB）

- 依 `src/km_control.py` 既有慣例（`CREATE TABLE IF NOT EXISTS` + `km_control_schema_migrations`）新增 migration：
  - `km_instance_grants.role`：`user` → `engineer`；`admin` 保持不變。
  - 加上允許值限制（CHECK 或程式驗證，與既有風格一致）。
- `GRANT_ROLES` 改成由 policy 讀取，或至少集中定義一處。
- 遷移必須可重跑（idempotent），並提供回復方式（回寫 `user`）。
- 遷移後，所有現存 entry session 的 `role` claim 會與 DB 不一致，使用者需重新進入資料區；這是預期行為，請在交付說明中寫明。

### 3.3 伺服器端檢查

- 新增共用模組（例如 `src/web_api/rbac.py`）：`require_permission("report.review")` 這種 FastAPI dependency，從 `request.state.km_identity["role"]` 取角色並查 policy。
- `InstanceAuthMiddleware` 維持只做驗證；授權交給 dependency，避免在 middleware 寫路徑判斷。
- 報告審核：approve/reject 改成接受「Manager/Admin 的使用者 session」，`reviewer_id` 記為 KM `user_id`。既有 reviewer token 是否保留（給 CSIT/自動化用）屬於待決策，保留時必須另外標示來源（`reviewer_kind=token|user`）。
- 不得把權限判斷交給 LLM 或 prompt（規劃原則）。

### 3.4 管理介面與稽核

- `src/control_auth_routes.py:60` 的 role pattern、`frontend` 的 Control 管理頁（`control-admin.html`）角色下拉選單，改為三種角色。
- grant 變更已寫 `grant_changed` 稽核；確認新角色值正確寫入。新增「403 被拒」稽核事件時要控制量（建議只記管理類端點）。
- 前端依 `/api/auth/me` 回傳的 `role` 隱藏無權限按鈕（例如審核頁、Skill 編輯），但這只是體驗。

## 4. 限制與禁止事項

1. 全程繁體中文（說明、commit 訊息、文件）；程式碼、識別字、錯誤訊息保持原文。
2. 避免硬編碼：角色、權限、路徑、URL 都走設定。
3. 不得寫入或印出任何密碼、token、私鑰；測試帳號密碼由使用者另外提供，**不要猜**。
4. 不得刪除 `km_audit_events`。
5. 不得改動 CSIT 端程式、Shared Identity/OIDC 設定，不得修改共用 Ollama。
6. 不得改動 `.km-control/csit-post-acceptance-freeze-20261015/rotation-execution-package-20261015/` 下的 CSIT 檔案。
7. 部署到 DEV（3030）前需使用者核准；Production 不在範圍。
8. 不順手重構無關程式；登出撤銷問題另案處理。

## 5. 待決策（開工前請向使用者確認）

1. 角色名稱是否就用 `engineer / manager / admin`？舊 `user` 是否全部對應 `engineer`？
2. 規劃寫「CSIT 權限來源」：Phase 1 角色是由 KM 管理員在 Control 管理頁手動指派，還是要從 CSIT／Shared Identity claim 對應？（建議 Phase 1 先手動指派，保留 claim mapping 擴充點。）
3. 角色是「每個資料區各自一個」（現有 grant 結構，da40 可以是 manager、test 是 engineer），還是全域一個？（建議沿用每區一個。）
4. 既有 reviewer Bearer token 要保留、改為只給系統帳號，還是移除？
5. Engineer 能否看到「待審報告」清單？Manager 能否編輯 Skill？

## 6. 驗收

### 6.1 自動測試（pytest）

- policy 載入：正常、缺檔、格式錯誤（fail closed）。
- 遷移：`user→engineer`、重跑不變、回復。
- 每個受保護端點 × 三種角色 × 未登入：預期 200/202 / 403 / 401。
- 角色變更後舊 token 被拒（沿用 `validate_entry_claims` 行為）。
- approve/reject 以 Manager session 成功、Engineer 403，`reviewer_id` 為使用者 id。
- 測試在隔離環境執行，例如：

```bash
docker run --rm --network none -v "$PWD":/work:ro -w /work \
  -e PYTHONPATH=/work -e PYTHONDONTWRITEBYTECODE=1 <test-image> \
  python -m pytest tests/<新測試> -q
```

  全套件在此環境有既有的環境性失敗基線；請以「改動前 vs 改動後的失敗清單差異」判斷回歸，不能只看總數。

### 6.2 實際環境（Webwright 優先，Playwright 備援）

入口 `https://61.216.9.52:3030/chat-v2.html`（主要驗證入口 `chat.html` 亦需確認可用）。測試帳號（`km-clude1`、`km-clude2`、`km-clude3`）由使用者提供密碼；分別指派 engineer / manager / admin 後：

1. Engineer：可提問、可上傳；審核頁不可用，直接呼叫 approve API 回 403。
2. Manager：可核准／退回測試報告，退回需填原因。
3. Admin：可清除任務歷史、可編輯 Skill。
4. 改變角色後重新整理：舊 session 需重新進入資料區，權限依新角色生效。
5. 檢查 console error 與 failed request，截圖保存。
6. 測試資料以可識別前綴建立，結束後精準清除，稽核紀錄保留。

### 6.3 部署與回復（需使用者核准後才執行）

- 受影響元件：Control Auth 映像、test 區 `kb-web`、da40 區 `km-da40-web-1`，可能含 3030 Nginx 靜態頁。
- 部署設定在 `deploy/dev-3030/compose/` 與 DGX `.km-control/compose/`，兩者必須一致；部署後執行 `scripts/check-dev-compose-drift.sh` 必須全部 MATCH。
- 每一步保留前一版映像 tag 與 Control DB 備份，回復方式寫入交付說明。
- 交付時需附：source commit、映像 tag／digest、runtime 驗證結果、回復證據，並更新 `PROJECT_MEMORY.md`。若 GitHub 與 runtime 不一致，標示 `MISMATCH` 或 `STALE`。

## 7. 範圍外（另案）

- Query / Answer Log 與上傳／審核／發布的完整稽核（WP16 其餘部分）。
- Qdrant 文件層 ACL（`access_roles`、`visibility`，見 `src/km_spec_contract.py:30`）與查詢前過濾。
- Citation 精確定位（page/section、sheet/cell）。
- 登出撤銷 session。
- 設備預約、系統驗證申請單（等待 CSIT 契約）。
