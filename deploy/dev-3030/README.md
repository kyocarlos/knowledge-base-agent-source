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
| 10-15 10:13 | `0b05fc6a945a` → `e0fea1036996` | 213 → 221 | 只在 km-dev-da40.duckdns.org 封鎖 RD2（13:50 已隨 RD2 移除一併刪除） |
| 10-15 11:43 | `93a0cfef85e5` | 222 | 新增 `/source-credentials.html`（不需資料區 session） |
| 10-15 12:20 | `28ae70e26023` | 241 | `/api/auth/login-url`（含 `/da40`、`/rd2`）一律回傳目前網址的 `/login.html` |
| 10-15 13:50 | `c2e3670788b0` | 218 | RD2 完整移除：刪除 rd2 upstream、RD2 封鎖 map／if、`/rd2/api/` 與 `/rd2/api/auth/login-url` 路由 |

## 注意

- 檔內 `km-dev-da40.duckdns.org` 與 `:3030` 是 DEV 專用值，不可直接用於其他環境。
- `kb-login.override.yml` 的 web 段落會被下方的 `kb-web.chat-runtime.override.yml` 覆蓋。

## TEST plane compose（kb-web、kb-celery-ingest、kb-celery-search、kb-nginx）

2026-10-15 查證：這些容器建立時使用的 `/tmp` compose 檔與 env 檔（`/tmp/km-ui-upload-image.override.yml`、`/tmp/codex-chatv2-secure-fix/deploy/legacy-test/docker-compose.chat-runtime.yml`、`/tmp/km-chat-image.override.yml`、`/tmp/km-test-compose.env`）已在 10-04 主機重開機後消失。容器靠 restart policy 持續運作，但無法以原設定重建。

已從執行中容器反推重建，並以「compose config-hash 與容器 label 完全相同」驗證（4 個服務皆一致，`up --dry-run` 皆為 Running，不會重建）：

| 檔案 | 位置 | 內容 |
|---|---|---|
| `compose/kb-web.chat-runtime.override.yml` | git + `.km-control/compose/` | web 映像 `km-chat-v2-secure:418610dc-202610021610`、`OPENCLAW_CHAT_CONFIG_PATH`、以 TEST chat runtime 檔取代 `~/.openclaw` 掛載 |
| `compose/kb-test-workers.image.override.yml` | git + `.km-control/compose/` | 兩個 worker 映像 `km-test-web:c8884f72` |
| `kb-test.env` | 只在 `.km-control/compose/`（0600，不進 git） | compose 實際引用的 25 個變數值（取自執行中容器） |

操作一律透過 `scripts/dev-kb-test-compose.sh`。它固定使用基礎 runtime 目錄的 `docker-compose.yml`、`rollback-images.yml`、`.km-control/kb-login.override.yml`、`.km-control/planes/test-worker.override.yml` 與上述兩個 override，並有以下保護：
- runtime override 必須與 git 內容一致，否則拒絕執行。
- 會變更容器的子指令必須明確指定服務，且只允許 `web`、`celery_ingest_worker`、`celery_search_worker`、`nginx`。
- 禁止 `down`。

範例：
- 對帳：`scripts/check-dev-compose-drift.sh`（4 個服務 config-hash 全一致才輸出 MATCH）
- 預覽重建：`scripts/dev-kb-test-compose.sh up -d --no-deps --dry-run web`

## 共用基礎設施 compose（kb-redis、kb-report-registry、kb-timescaledb）

原本的 `/tmp/km-v26-ci-cd-20260915-main-r2`（redis、report_registry）與 `/tmp/phase1-timescaledb-infrastructure-override.yml`（timescaledb；`/srv/...rebaseline-20260829-v3/docker-compose.yml` 沒有此服務）都已遺失。資料在 `knowledge-base_redis_data`、`knowledge-base_report_registry_data`、`knowledge-base_timescaledb_data` 具名 volume，不受影響。

| 檔案 | 來源 | 驗證 |
|---|---|---|
| `compose/kb-redis-registry.compose.yml` | knowledge-base commit `680034c6`（分支 `agent/km-v26-ci-cd-validation-20260915-r2`）的 redis、report_registry 定義原樣抽出 | config-hash 與容器一致（fede19cda196／ba2c2b400ec1） |
| `compose/kb-timescaledb.compose.yml` | knowledge-base commit `3e2c64aa` 的 timescaledb 定義原樣抽出 | config-hash 與容器一致（6995cff0bb35） |

兩份檔案都是獨立檔，不需要其他基礎檔；專案目錄位置不影響 hash。密碼由 `/home/da40_ai_gb10/.config/knowledge-base/wp01-deployment.env`（0600）提供。

操作一律透過 `scripts/dev-kb-infra-compose.sh`，只允許 `redis`、`report_registry`、`timescaledb`，需明確指定服務，禁止 `down`。`scripts/check-dev-compose-drift.sh` 會一併對帳這 3 個服務。

已知現況（為保持 hash 一致而原樣保留，未修改）：
- `kb-redis` 與 `kb-report-registry` 定義中沒有 `restart`，容器 restart policy 為 `no`，主機重開機後**不會自動啟動**。kb-redis 是共用 Redis，建議另行評估改為 `unless-stopped`（變更後需重建容器）。
- `kb-report-registry` 自 2026-09-16 起為停止狀態。

## 容器 label 說明

compose 只在建立容器時寫入 `config_files`、`working_dir` label，所以上述容器重建前，label 仍會指向已不存在的 `/tmp` 路徑。判斷能否正確重建，請以 `check-dev-compose-drift.sh` 的 config-hash 比對為準。

## da40 資料區與 Control DB compose

`/tmp/km-3030-control-cutover-clean`（da40 instance compose 與 Control DB 的 control-auth compose）已遺失。遺失的基礎檔與 git 中的 `deploy/tenant-isolation/docker-compose.instance.yml`、`deploy/legacy-test/docker-compose.control-auth.yml`（commit `6e8617b`，與本分支目前版本相同）一致。

| 組 | 檔案組合（依序） | env |
|---|---|---|
| da40 | instance.yml、`.km-control/planes/da40.override.yml`、Codex CSIT 換版包的 `km-da40-runtime-supplement.yml` 與 `km-ui-ddl-free-images.override.yml`（不在 git，以 SHA-256 鎖定） | `.km-control/planes/da40.env` |
| control-db | control-auth.yml、`.km-control/control-auth.override.yml` | `.km-control/control-3030.env` |

runtime 副本放在 `.km-control/compose/tenant-isolation/`、`.km-control/compose/legacy-test/`。操作一律透過 `scripts/dev-km-plane-compose.sh <da40|control-db> ...`：
- runtime 副本須與 git 一致；外部檔以 SHA-256 鎖定。
- 變更類指令只允許該組服務：da40 為 web、兩個 worker、neo4j、qdrant、redis、report_registry、timescaledb；control-db 只允許 `control_db`，`control_auth` 由 Control Auth 的 runtime-compose.json 管理。
- 需明確指定服務，禁止 `down`。

### 已知漂移（如實記錄，未修正）

1. ~~da40 `celery_search_worker` 映像漂移~~：2026-10-15 已依使用者決定改用新映像重建（`04086d0f60ba` → `02c62b78338e`，即 `km-test-web:c8884f72` 目前指向的映像）。新映像的 `tasks.py` 與搜尋路徑關鍵檔，與 da40 web／ingest 目前使用的版本相同。重建前佇列為 0；重建後設定 hash 不變，除映像外的環境變數、指令、掛載、網路、重啟策略皆相同；正式入口 da40 搜尋成功。舊映像保留標籤 `km-da40-search:approved-04086d0f` 可供退回。
2. **da40 search worker 的 `KM_CONTROL_PUBLIC_ORIGIN` 仍為 3030 合併前的 `:3031`**，由 Codex 的 supplement 釘住；worker 只檢查此值為 https，無功能影響。

3. ~~da40 資料區無法連線 Ollama~~：2026-10-15 已修正。`docker-compose.instance.yml` 的 web、celery_search_worker、celery_ingest_worker 加入 `extra_hosts: ["host.docker.internal:host-gateway"]`（與 TEST plane 相同）；同時加在兩條部署路徑共用的 `.km-control/planes/da40.override.yml`，避免 Codex 以 `github-verified-clone` 範本重建時把修正蓋掉。兩路徑算出的 config-hash 相同。三個容器已重建，皆可解析 `host.docker.internal` 並取得 Ollama `/api/tags` 200。
4. **主機 Ollama 全域容量限制（非 da40 設定問題）**：`/etc/systemd/system/ollama.service.d/override.conf` 設為 `OLLAMA_NUM_PARALLEL=1`、`OLLAMA_MAX_LOADED_MODELS=1`。當其他工作長時間佔用模型時（2026-10-15 觀察到 `qwen3.6:27b` 持續約 50 分鐘以上），da40、TEST 與主機本身對 `gemma4:12b` 的請求都會排隊逾時；da40 搜尋會在 Celery 10 分鐘軟性時限後改用備援回答。

## RD2 已移除（2026-10-15）

DEV 只保留 da40 與 test。移除內容：
- Control Auth `KM_ENABLED_INSTANCE_IDS` 改為 `test,da40`，移除 `KM_RD2_PUBLIC_ORIGIN`。
- 以既有撤銷流程撤銷 rd2 授權（km-admin、km-rd2；兩帳號保留其他資料區授權）。
- nginx 刪除所有 rd2 規則；`login.html` 移除 RD2 篩選。
- 刪除 8 個 `km-rd2-*` 容器、8 個 `km-rd2_*` volume 與 `km-rd2_default` 網路。

volume 已在停機狀態下冷備份，檔案數與位元組數逐一核對一致。備份與移除前的設定、移出的 rd2 設定檔都在 `.km-control/rd2-decommission-20261015/`（0700）。

## 其他仍依賴已遺失 /tmp 檔的容器（2026-10-15 掃描，尚未處理）

- `km-ts-report-ci-*`：CI 測試殘留，來自 `/tmp/km-ts-report-v1-20260921-Jv6Zxt`
