# KM DEV 3030 入口 Nginx 設定

`nginx.runtime.conf` 是 DEV 主機（spark-7546）`kb-nginx` 容器**實際載入**的設定，對外入口為
`https://61.216.9.52:3030` 與 `https://km-dev-da40.duckdns.org:3030`。

- 主機位置：`/home/da40_ai_gb10/.km-control/nginx.runtime.conf`
- 容器掛載：`kb-login.override.yml` 以唯讀單檔掛載到 `/etc/nginx/nginx.conf`
- 靜態頁：`/srv/knowledge-base-production-rebaseline-20260829-v3/.frontend-build-runtime-user8` → `/usr/share/nginx/html`
- 憑證：`/home/da40_ai_gb10/nginx_certs` → `/etc/nginx/certs`（不在版本控制內）

與 `deploy/legacy-test/nginx.3030-login-gateway.conf` 的關係：後者是 cutover runbook 的影子閘道範本（單一資料區、upstream `web`），且列在交接檔案清單中，**不是** DEV 現況，請勿互相覆蓋。

## 修改與上線步驟

1. 先在此目錄修改並 commit，再部署。
2. 預先檢查語法（不影響線上）：
   `docker cp deploy/dev-3030/nginx.runtime.conf kb-nginx:/tmp/candidate.conf && docker exec kb-nginx nginx -t -c /tmp/candidate.conf`
3. 備份線上檔，然後**原地覆寫**：`cat deploy/dev-3030/nginx.runtime.conf > /home/da40_ai_gb10/.km-control/nginx.runtime.conf`
   - 單檔 bind mount 綁定的是 inode。若用換名方式替換，容器會繼續讀到舊檔。
4. 執行 `docker exec kb-nginx nginx -t`，通過才執行 `docker exec kb-nginx nginx -s reload`。失敗時以備份原地覆寫還原。
5. 執行 `scripts/check-dev-nginx-drift.sh` 確認三方一致，並依 AGENTS.md 以 Webwright 在 `https://61.216.9.52:3030` 驗收。

## 對帳

`scripts/check-dev-nginx-drift.sh` 比對三者的 SHA-256：本檔、主機 runtime 檔、容器 `/etc/nginx/nginx.conf`。全部一致時輸出 `MATCH`，否則輸出 `MISMATCH` 並以非 0 結束。路徑可用環境變數覆寫。

## 修改歷程（依 `.km-control/*` 部署證據整理）

| 時間（+08） | SHA-256 前 12 碼 | 行數 | 內容 |
|---|---|---|---|
| 10-02 | `4506f0d9172c` | 129 | contract-clarification 前的基準 |
| 10-05 | `6d53bd19b603` | 129 | contract clarification |
| 10-07 09:00 | `3f3a827cbc1c` | 133 | CSIT Integration v1 ingestion 路由 |
| 10-07 09:43 | `4012a10af349` | 144 | KM DEV upload |
| 10-07 10:03 | `77953a2bdf5d` | 188 | DEV chat search bridge |
| 10-07 10:54 | `b362c0f6d2a4` | 207 | DEV upload 未登入導回登入頁 |
| 10-15 10:13 | `0b05fc6a945a` → `e0fea1036996` | 213 → 221 | 只在 km-dev-da40.duckdns.org 封鎖 RD2 |
| 10-15 11:43 | `93a0cfef85e5` | 222 | 新增 `/source-credentials.html`（不需資料區 session） |
| 10-15 12:20 | `28ae70e26023` | 241 | `/api/auth/login-url`（含 `/da40`、`/rd2`）一律回傳目前網址的 `/login.html` |

## 注意

- 檔內 `km-dev-da40.duckdns.org` 與 `:3030` 是 DEV 專用值，不可直接用於其他環境。
- `kb-login.override.yml` 的 web 段落已被其他 compose 檔覆蓋；kb-web 目前疊了 6 個 compose 檔，其中 3 個位於 `/tmp`。此目錄只納入 Nginx 設定。
