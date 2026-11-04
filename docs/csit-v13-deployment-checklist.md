# CSIT 規格 v1.3 — KM DEV 部署清單

適用:`feature/csit-spec-v13-doclib-20261104` 的 KM 端實作(文件專區寫入、驗證式刪除)。
**目標只限 KM DEV**,不碰 Production、Shared Identity、既有 Test Report v1 契約。所有新功能預設關閉。

> 狀態說明:下列步驟依 repo 內現有的 `deploy/csit-integration-v1/` 與 `deploy/dev-3030/` 整理。DGX 上實際的主機名、資料庫名、
> compose 檔位置、容器名稱我沒有親眼確認,標 **〔確認〕** 的項目要以現場為準。每個「執行」步驟都會改動外部環境,需要你點頭才做。

## 0. 變更範圍(部署前先看)

| 類別 | 內容 |
|---|---|
| 新增資料表 | `km_csit_doclib_jobs`、`km_csit_doclib_checkpoints`、`km_csit_deletion_jobs`、`km_csit_tombstones`、`km_csit_v13_callbacks` + 2 個 sequence |
| 新增路由 | `POST /api/integrations/csit/v1/document-library/jobs`、`POST /api/integrations/csit/v1/document-deletions` |
| 新增出站呼叫 | `GET /api/integrations/km/v1/document-library/files/{id}/content`、`POST …/document-library/ingestion-status`、`POST …/document-deletion-status` |
| 既有程式的小改 | v1 worker 遇到已刪除的報告版本會略過;`Settings` 新增 `doclib_enabled`;`runtime.py` 啟動新 worker |
| 不改 | Test Report v1 路由、callback 格式、既有資料表 |

## 1. 部署前必須先解決(否則部署了也收不到)

- [ ] **nginx 要新增兩個 location。** `deploy/dev-3030/nginx.runtime.conf` 目前只放行精確路徑 `/api/integrations/csit/v1/ingestion-jobs`,
  新路由會被擋掉(404)。這項**尚未寫入 repo**,要加:
  ```nginx
  location = /api/integrations/csit/v1/document-library/jobs {
    client_max_body_size 64k; access_log off; error_log /dev/null crit;
    proxy_pass http://km-csit-integration-api:8000;
    proxy_http_version 1.1; proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto $scheme;
  }
  location = /api/integrations/csit/v1/document-deletions {
    client_max_body_size 64k; access_log off; error_log /dev/null crit;
    proxy_pass http://km-csit-integration-api:8000;
    proxy_http_version 1.1; proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto $scheme;
  }
  ```
  只開這兩條精確路徑,不要放行整個 `/api/integrations/csit/`。
- [ ] **M2M 認證要先就緒。** v1 文件寫著 Shared Identity 的 `client_credentials` 客戶端仍待核發。沒有它,真實 CSIT 打不進來,
  KM 也拿不到出站 token。這是外部相依,不是部署能解決的。
- [ ] **出站 scope 待 CSIT 確認。** 目前新端點沿用 `csit.document.read`、`csit.ingestion.status.write`,規格沒有另定 scope。
- [ ] **CSIT 端的對應:** 其 KM base URL 指向 DEV、其 7444 allowlist 放行三個 KM→CSIT 路徑(規格 §10 說目前只放行部分路徑)。

## 2. Migration(管理管道執行,不是程式自動跑)

檔案:`migrations/20261104_csit_document_library_v1.sql`(單一 `BEGIN…COMMIT`,全為 `CREATE … IF NOT EXISTS`,可重複執行)。

1. 先備份 DEV Control PostgreSQL(或至少確認有最近的備份)。**〔確認〕資料庫名稱與連線方式**
2. 在 DEV Control DB 以管理角色執行該檔。
3. 驗證:
   ```sql
   SELECT table_name FROM information_schema.tables
   WHERE table_name IN ('km_csit_doclib_jobs','km_csit_doclib_checkpoints','km_csit_deletion_jobs','km_csit_tombstones','km_csit_v13_callbacks');
   -- 應回 5 列
   SELECT sequencename FROM pg_sequences WHERE sequencename IN ('km_csit_doclib_job_seq','km_csit_deletion_job_seq');
   -- 應回 2 列
   ```
4. 確認 API / worker 使用的資料庫角色對這 5 張表有 SELECT、INSERT、UPDATE、DELETE,對 2 個 sequence 有 USAGE
   (v1 當時是「不增加既有角色權限」,新表若是以管理角色建立,角色可能沒權限 → 部署後會 503)。
   ```sql
   GRANT SELECT,INSERT,UPDATE,DELETE ON km_csit_doclib_jobs,km_csit_doclib_checkpoints,km_csit_deletion_jobs,km_csit_tombstones,km_csit_v13_callbacks TO <runtime_role>;
   GRANT USAGE ON SEQUENCE km_csit_doclib_job_seq,km_csit_deletion_job_seq TO <runtime_role>;
   ```
   (`km_csit_v13_callbacks.sequence` 是 identity 欄位,隨表授權即可。)

**回滾:** 這 5 張表與 2 個 sequence 都是新增,先關開關(§4)後可整批 `DROP`;不影響 v1 表。

## 3. 環境變數

API 容器與 worker 容器**都要**有 `KM_CSIT_DOCLIB_ENABLED`。其餘沿用 v1 已有設定(見 `config/csit-integration-v1.env.example`)。

| 變數 | 值 | 說明 |
|---|---|---|
| `KM_CSIT_DOCLIB_ENABLED` | `true` | 新功能總開關;`false` 時收件端回 503、不註冊 worker |
| `KM_CSIT_DOCLIB_QDRANT_COLLECTION` | 例 `km_csit_docs` | 文件專區專用向量 collection;不設則沿用 `KM_CSIT_QDRANT_COLLECTION` |
| `KM_CSIT_DOCLIB_LLM` | `1` 或不設 | `1`=documentType/summary/keywords 由 KM 主要 LLM 擷取;不設則這三項保持空 |
| `KM_CSIT_DOCLIB_ROUTES` | `1`(選用) | 僅在 `ENABLED=false` 時仍想註冊路由(回 503)用來探測 |
| 既有必要項 | `KM_CSIT_ENABLED=true`、`KM_CSIT_DB_URL`、`KM_CSIT_CSIT_BASE_URL`、`KM_CSIT_AUTHORITY`、`KM_CSIT_AUDIENCE`、`KM_CSIT_OUTBOUND_AUDIENCE`、`KM_CSIT_JWKS_URI`、`KM_CSIT_TOKEN_URL`、`KM_CSIT_CLIENT_ID`、`KM_CSIT_SECRET_FILE`、`KM_CSIT_SERVICE_CLIENTS`、`KM_CSIT_STORAGE_ROOT`、`KM_CSIT_QDRANT_COLLECTION` | worker 已有的 M2M 與儲存設定;`KM_CSIT_CSIT_BASE_URL` 與 JWKS/token URL 必須是 HTTPS |
| 既有選用項 | `KM_CSIT_NEO4J_*`、`KM_CSIT_TIMESCALE_DSN_FILE`、`KM_CSIT_MAX_FILE_SIZE`、`KM_CSIT_RETRY_DELAYS`、`KM_CSIT_CALLBACK_RETRY_DELAYS` | 刪除 Test Report 時需要 Neo4j 與 Timescale;只刪文件專區檔案時不需要 |

建議先 **`KM_CSIT_DOCLIB_ENABLED=false`、`KM_CSIT_DOCLIB_ROUTES=1`** 部署一輪做探測(§5 A),再切 `true`。

## 4. 部署步驟(順序)

1. **程式:** 確認 `feature/csit-spec-v13-doclib-20261104` 已合併或可部署的 commit(目前尚未 push)。
2. **映像:** 重新 build `deploy/csit-integration-v1/Dockerfile` 的 `api` 與 `worker` target(`src` 有新增 9 個 `doclib_*` 模組)。
   映像不含 migrations,不影響 §2。
3. **migration(§2)** 完成並驗證。
4. **nginx(§1)** 更新 `nginx.runtime.conf` 並重載,先 `nginx -t`。
5. **以 `DOCLIB_ENABLED=false`、`ROUTES=1`** 啟動 API,做 §5 A。
6. **改 `DOCLIB_ENABLED=true`**,重啟 API 與 worker(worker 走 `worker-compose.yaml` 的 `worker` profile,需要
   `KM_CSIT_ENV_FILE`、service secret、Neo4j / Timescale secret 路徑)。**〔確認〕現場 worker 目前是否在跑、用哪個 env file**
7. 做 §5 B、C、D。

**回滾:** 把 `KM_CSIT_DOCLIB_ENABLED=false` 並重啟 API 與 worker → 新路由回 503、新 worker 不啟動;v1 不受影響。
映像可退回上一版;資料表保留(內含稽核資料)。

## 5. 驗證步驟

### A. 部署後、開關仍關閉(不寫入任何資料)
- [ ] `GET /health` 回 200,`integrationEnabled` 與預期一致。
- [ ] 無 token `POST …/document-library/jobs` → **401**(證明路由已通過 nginx 並到達 KM;若是 404 代表 nginx 沒生效)。
- [ ] 有效 token + 壞 body → **422**,回應不含你送的值。
- [ ] 有效 token + 合法 body → **503**(開關關閉,資料庫無新列)。
- [ ] v1 回歸:`POST …/ingestion-jobs` 行為與部署前相同。

### B. 開關開啟後的上傳(用模擬器 `serve --km-base-url https://<DEV KM>:3030`,或 CSIT 實際送)
- [ ] 合法通知 → **202**,body 為 `{csitJobId,kmJobId:"KM-DOC-…",status:"Accepted"}`。
- [ ] 重送同一 `csitJobId` → 202、**同一個** `kmJobId`;DB 只有一列。
- [ ] KM 向 CSIT 下載檔案成功;故意讓 sha256 不符 → 該 job `Failed`、`SHA256_MISMATCH`、`retryable=false`、**Qdrant 無向量**。
- [ ] 回報順序:`Processing` → `Completed`(或 `Failed`),CSIT 端不會看到狀態倒退。
- [ ] `Completed.result` 含規格 §5 全部 key;`indexing.indexId` 非空、`chunkCount` 與 Qdrant 實際筆數一致。
- [ ] Qdrant 該 collection 中,點位 payload 帶 `document_file_id`、`source_type=DocumentLibraryFile`。
- [ ] 三種格式(PDF、DOCX、XLSX)各一份。**註:**沒有文字層的掃描 PDF 會 `EMPTY_EXTRACTION` 失敗,這是設計行為。
- [ ] 若啟用 LLM:`documentType` 為允許值、`keywords` 都出現在原文中。

### C. 刪除
- [ ] `POST …/document-deletions`(DocumentLibraryFile)→ **202**、`kmDeletionJobId:"KM-DEL-…"`;`km_csit_tombstones` 有一列。
- [ ] 回報 `Completed`,`cleanupVerified=true`,七項皆為 `Deleted` 或 `NotPresent`。
- [ ] 同名兩份只刪指定那份(另一份仍可查詢)。
- [ ] 刪除後再送同一 `documentFileId` 的上傳通知 → **409**(`DOCUMENT_DELETED`),Qdrant 無新向量。
- [ ] 已知限制:問答的檔案型快取無法依文件清除;`cache` 只清 Redis 搜尋快取。如 CSIT 要求該項可驗證,要先與對方確認。
- [ ] Test Report / 驗證附件的刪除路徑需要 Neo4j 與 Timescale 已設定;**尚未用真實資料驗證**,請另行小量試刪。

### D. 失敗情境(對應規格 §11.1)
- [ ] KM 下載端點回 503 兩次後恢復 → 靜默重試,最終 `Completed`,不重複建立 job。
- [ ] CSIT 回報端回 503 → KM callback 持久化重試,順序不亂。
- [ ] 重啟 worker(執行中途)→ job 由 lease 逾時後接手,不重複、不遺失。

### E. 觀察用 SQL
```sql
SELECT km_job_id,status,phase,attempt_count,last_error_code,next_retry_at FROM km_csit_doclib_jobs ORDER BY created_at DESC LIMIT 20;
SELECT kind,status,payload->>'status' AS cb,attempt_count,last_error_code FROM km_csit_v13_callbacks ORDER BY sequence DESC LIMIT 20;
SELECT km_deletion_job_id,status,phase,last_error_code FROM km_csit_deletion_jobs ORDER BY created_at DESC LIMIT 20;
SELECT * FROM km_csit_tombstones ORDER BY created_at DESC LIMIT 20;
```
日誌不得出現 token、密碼、檔案內文、NAS 路徑(規格 §3)。

## 6. 風險與已知限制

- 新程式只在本機以內嵌 PostgreSQL、記憶體向量庫、固定 token 驗證過;**真實 M2M、真實 Qdrant / Neo4j / Timescale、真實 PDF/DOCX 解析、真實 LLM 都沒有驗證過。**
- 既有測試有 49 項在本機(Windows)失敗,改動前就存在,至少一部分來自 Windows 的密鑰檔權限檢查;部署用的 Linux 映像內應再跑一次 `tests/csit_v1`。
- 規格 §8(更新)、§9.2(`analysis-results`)是待批准提案,**本次未實作**。
- Vendor、Equipment 來源不在範圍內。
