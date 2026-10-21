# CrossSearch 使用者本人三大系統帳密：DEV 部署計畫

- 日期：2026-10-15
- 來源分支：`codex/cross-search-source-credentials-20261015`（base `baeacc34c075555ae7fd5089c3ebfdb162524661`，尚未 commit）
- 目標環境：DEV（`https://61.216.9.52:3030`，主機 spark-7546）
- 性質：計畫文件。每個「需授權」階段都要使用者另行同意才執行；Production 不在範圍內。

## 1. 目前 DEV 實況（2026-10-15 唯讀查證）

| 元件 | 現況 | 本次影響 |
|---|---|---|
| Control Auth `km-control-3030-control_auth-1` | 映像 `km-control-auth:oidc-admin-binding-20261006`（`sha256:508557055fe9…`），compose 專案 `km-control-3030`，設定 `.km-control/oidc-passwordless-20261006/runtime-compose.json`，網路 `km-control-private`，restart `unless-stopped` | 換映像、加 2 個 env、加公鑰唯讀掛載 |
| Control DB | `km-control-db`（PostgreSQL），應用角色 `km_control_app` 擁有所有 `km_*` 表、可在 public 建表；已套用 migration `20261006_oidc_admin_binding`；`km_source_credentials` 不存在 | 新增 1 張表（純新增，不改既有表） |
| Nginx `kb-nginx` | 設定 `.km-control/nginx.runtime.conf`（唯讀掛載），靜態頁 `/srv/knowledge-base-production-rebaseline-20260829-v3/.frontend-build-runtime-user8/` | 新增 `location = /source-credentials.html`；新增 1 個靜態頁；`login.html` 加 1 個連結 |
| `login.html`（runtime） | SHA-256 `09ef9d1d6f164a68…` = baeacc34 版本 + 10/15 RD2 hostname 篩選 | 以 runtime 版本為基礎只加連結，保留 RD2 篩選 |
| CrossSearch 測試區 | `km-cross-bridge-test`（`km-cross-bridge:20261014`）、`km-cross-api-test`／`km-cross-worker-test`（`km-cross-search:20261014`），zone=`test`，`KM_CROSS_SEARCH_SOURCES=km`，以 `docker run --env-file .km-control/cross-search-20261014/deploy/test.*.env` 啟動，未經 Nginx 對外 | 換映像；worker 加私鑰唯讀掛載 |
| 其他 | KM CSIT Integration（`km-csit-integration-api`／worker）處於 ARMED 等待 CSIT 事件 | 不動；Nginx 採 graceful reload |

## 2. 設計重點（部署相關）

- Control Auth 只拿**公鑰**（只能加密寫入）；只有 CrossSearch worker 拿**私鑰**。bridge 與 web 都沒有金鑰。
- 新表未建立前，新版 Control Auth 的帳密 API 回 503，**登入、OIDC、資料區選擇不受影響**（已在隔離 Postgres 驗證）。所以「先部署程式、後套用 DB」或反過來都安全；本計畫採「先 DB 後程式」。
- 第一次部署 CrossSearch 時維持 `KM_CROSS_SEARCH_SOURCES=km`，外部來源關閉，行為與現在相同；開啟外部來源另外授權。

## 3. 階段與步驟

所有證據放在新目錄 `/home/da40_ai_gb10/.km-control/cross-search-credentials-deploy-20261015/`（0700，含 secret 的檔案 0600），沿用 10/06 OIDC 部署的 before／build／log／validation JSON 格式。

### 階段 A：準備（不影響 runtime，可直接執行）

1. 建立部署目錄，備份到 `before/`：
   - `runtime-compose.json`。
   - runtime `login.html`、`nginx.runtime.conf`。
   - 三個 CrossSearch 容器的 inspect（只存映像、網路、指令，不存 env 值）。
   - Control DB 的 schema-only dump。
   - 現行映像 ID 清單。
2. 產生金鑰 `km-src-20261015`（X25519）：
   - `/home/da40_ai_gb10/.km-control/source-credential-keys/private/km-src-20261015.pem`：0600，只掛給 CrossSearch worker。
   - `/home/da40_ai_gb10/.km-control/source-credential-keys/public/km-src-20261015.pem`：0644，只掛給 Control Auth。
   - 私鑰不進 Git、不輸出、不寫入記憶。另外要確認私鑰的備份方式：私鑰遺失時，所有已存帳密都要由使用者重新輸入，資料本身不會外洩。
3. 建置映像（沿用 10/06 的 overlay 做法，只覆蓋變更檔）：
   - `km-control-auth:source-credentials-20261015`：`FROM km-control-auth:oidc-admin-binding-20261006`，COPY `km_credentials/`、`src/km_control.py`、`src/control_auth_routes.py`。
   - `km-cross-bridge:source-credentials-20261015`：使用 `Dockerfile.cross-bridge`。
   - `km-cross-search:source-credentials-20261015`：使用 `cross_search/Dockerfile`。
   - 記錄每個映像 ID，以及覆蓋檔案的 SHA-256。
4. 映像驗證（`--network none`）：
   - 在新 Control 映像內跑測試：新 25 項，加上既有 control／instance 45 項。
   - 完整 sandbox（`scripts/test-cross-search-credentials-sandbox.sh`）PASS。
5. Migration 預演：用 `before/` 的 DEV schema 建立一次性 DB，套用 `migrations/20261015_km_source_credentials.sql` 兩次，確認都成功。

### 階段 B：DEV Control DB migration（需授權）

1. 以 `km_control_app` 身分，在 `km-control-private` 網路上套用 migration。輸出存 `migration-apply.log`，連線字串不落檔。
2. 驗證：
   - `km_source_credentials` 存在。
   - `km_control_schema_migrations` 有 `20261015_km_source_credentials`。
   - 既有表的列數不變。
   - 現行 Control Auth 的 `/me` 與登入不受影響。
3. 回復：舊程式不會讀這張表，可以保留不動；若要移除，執行 `DROP TABLE km_source_credentials` 並刪除該版本列（此時表內尚無資料）。

### 階段 C：Control Auth 換版（需授權；登入入口中斷約數秒）

1. 複製 `runtime-compose.json` 成新檔（0600），只改三項：
   - 映像改為新 tag。
   - 新增 `KM_SOURCE_CREDENTIAL_KEY_ID=km-src-20261015`、`KM_SOURCE_CREDENTIAL_PUBLIC_KEY_FILE=/run/secrets/km-source-credentials/km-src-20261015.pem`。
   - 新增公鑰唯讀掛載。
2. `docker compose -p km-control-3030 -f <新檔> up -d control_auth`。不要加 `--remove-orphans`，以免動到 `control_db`。
3. 驗證（比照 10/06 `runtime-validation.json`）：
   - 容器 healthy、映像 ID 正確、env 與掛載正確。
   - `/login.html` 200、`/_control/api/auth/me` 401、`/oidc/availability` 200、admin API 401、`/oidc/binding.html` 200。
   - OIDC discovery／JWKS PASS。
   - 新 API 未登入時回 401。
   - 容器內 `/run/secrets` 只有公鑰。
4. 回復：用 `before/runtime-compose.json` 與原映像重建。原映像保留不刪。

### 階段 D：Nginx 與頁面（需授權；Nginx graceful reload）

1. `nginx.runtime.conf` 在 `control-admin.html` 那行旁邊新增：
   `location = /source-credentials.html { try_files /source-credentials.html =404; add_header Cache-Control "no-store" always; }`
   這頁不需要資料區 session，頁面本身改由 Control session 保護，未登入時 API 回 401，頁面會導回登入頁。
2. 靜態頁目錄新增 `source-credentials.html`。`login.html` 以 runtime 版本為基礎，只加一個連結（保留 RD2 篩選），先寫入暫存檔再以原子方式替換。
3. 執行 `nginx -t`，通過後才 `nginx -s reload`。
4. 驗證（依 AGENTS.md，以 Webwright 在 `https://61.216.9.52:3030/` 測試，需使用者提供的測試帳號）：
   - 登入後看到連結，可連結、更新、移除帳密，API 回應不含密碼。
   - 登出後頁面導回登入頁；再登入時帳密仍在。
   - 在 `km-dev-da40.duckdns.org` 上 RD2 仍隱藏。
   - 原有入口仍正常：chat-v2、dev-upload、control-admin、OIDC。
   - console／network 無錯誤。
5. 回復：還原 `before/` 的 conf 與兩個靜態頁，然後 `nginx -t`、reload。

### 階段 E：CrossSearch 測試區換版（需授權；只影響未對外的 test zone）

1. 依原本的 `--env-file`、網路與名稱重建三個容器，換成新映像；worker 另外以唯讀方式掛載私鑰目錄，並設定 `KM_SOURCE_CREDENTIAL_PRIVATE_KEY_DIR`。維持 `KM_CROSS_SEARCH_SOURCES=km`。
2. 驗證：
   - KM-only 查詢結果與換版前一致（回歸）。
   - 外部來源仍回 `source not enabled`。
   - `/health` 正常。
   - bridge 容器內沒有私鑰。
3. （可選，需另外同意）**DEV 模擬來源 E2E**：
   - 在 `km-control-private` 網路啟動 `km-cross-mock-sources-test`，使用 sandbox CA 的 TLS 憑證。
   - test zone 暫時設成三個 mock 來源。
   - 用專用測試帳號跑 driver：5 人並行、needs_relink、撤權等案例。
   - 完成後還原為 `km`，並移除 mock 容器與測試帳號的帳密。
4. 回復：依 `before/` 的 inspect 資料，以原映像 `km-cross-*:20261014` 重建。

### 階段 F：不在本計畫內，需各自另外授權

- 接真實 Confluence／Jira／TestRail：需要正式 base URL、CA、容器到內網的可達性、TestRail project scope，並由使用者以本人帳號實測。
- 建立 da40 zone 的 CrossSearch 容器（`deploy/da40.*.env` 已存在但未啟用）。
- chat 入口接 CrossSearch（Nginx 對外路由與前端整合）。
- 輪替舊 graphrag／AnythingLLM 的明碼帳密。
- 登出時遞增 `session_epoch`（目前登出只清 cookie）。

## 4. 風險與注意事項

- **登入短暫中斷**：階段 C 重建 Control Auth 約數秒。建議選低使用時段；CSIT integration 不經過 Control Auth，不受影響。
- **蓋掉 RD2 修改**：`login.html` 必須以 runtime 版本為基礎修改，並在驗收清單中檢查 RD2 仍隱藏。
- **私鑰遺失**：已存帳密全部無法解密，使用者需重新輸入，資料不會外洩。需確認私鑰備份放在哪裡、由誰保管。
- **Control DB 單點**：新表與既有帳號在同一個 DB，備份與還原策略沿用 Control DB 現行做法。
- **GitHub 狀態**：程式尚未 commit。部署前應先 commit 並記錄 approved source commit（AGENTS.md 第 6 條）；否則 runtime 會與 GitHub `MISMATCH`。

## 5. 執行前需使用者提供／決定

1. 是否同意先 commit 到 `codex/cross-search-source-credentials-20261015`；要不要 push 另外決定。
2. 階段 B～E 是否同意，以及執行時段。
3. 用於 3030 驗收的 KM 測試帳號（至少 2 個，需有 test 資料區授權）。
4. 私鑰備份的位置與保管人。
5. 階段 E-3（DEV 模擬來源 E2E）是否要做。
