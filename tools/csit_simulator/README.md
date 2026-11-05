# CSIT 模擬器(規格 v1.3 + v1.4)

一套有操作介面的「CSIT 文件管理系統」模擬:你在畫面上上傳文件、核准、歸檔、派送給 KM、刪除,同時看到 KM 在每個時間點收到什麼、回了什麼、
回報的內容是否符合規格。不連 CSIT 資料庫。

## 最快試法(本機完整流程,不需要 KM 環境)

```bash
pip install pgserver "psycopg[binary]" uvicorn fastapi httpx pydantic jsonschema pyjwt cryptography qdrant-client neo4j openpyxl
python -m tools.csit_simulator.demo
```

會起:內嵌 PostgreSQL + **真實的 KM 路由與 worker**(向量庫為記憶體版、認證用固定 bearer、documentType/摘要/關鍵字用規則式替身,
加 `--llm` 改用 KM 的 LLM)+ 模擬器畫面,並開啟 `http://127.0.0.1:8765/`。每次啟動都是乾淨狀態。

## 畫面

| 頁面 | 內容 |
|---|---|
| 文件專區 | 上傳(含 L1/L2/L3 分類)。預設停在「待核准」,**每一步手動按**:主管核准 → NAS 歸檔 → 派送給 KM。點文件看流程條、提示(對應規格章節)、規格判定、KM 回傳的 AI Metadata、時間線、這份文件的 API 往返 |
| API 流量 | 兩個方向的每一次 HTTP:方法、路徑、狀態碼、耗時,展開可看完整 Request / Response JSON |
| KM 內部觀察 | (僅 demo)KM 的工作表、向量庫、刪除工作、tombstone、回報 outbox、本機儲存檔案,對照 CSIT 這邊看到的 |
| 情境與設定 | KM 位址與 token、測試連線、「KM 回報時 CSIT 端故障」、清除資料 |

文件層級的情境注入:下載內容被改動(SHA256 不符)、截斷、前 N 次 503、403、404、派送用錯誤 token、通知寫錯 sha256、不帶 Idempotency-Key。
另有「重送(同工作)」驗冪等、「新工作重送」、「再派送上傳通知(已刪除的文件,應被拒絕)」。

## 對外部 KM(DEV)驗證

已部署的 KM 要用「身分模式」:見 `deploy/csit-mode/README.md`(`--identity`、HTTPS、模式切換腳本、`remote_drill.py`)。下面是只用固定 bearer 的簡易方式。

```bash
python -m tools.csit_simulator serve --km-base-url https://<KM> --token <DEV bearer> --port 8765 --data-dir ./sim-data
```

KM 端要把 CSIT 的 base URL 指到模擬器、並接受同一個 bearer。此模式沒有「KM 內部觀察」,請用「API 流量」。

## 規格 v1.4(/v2/)

上傳時「來源」可選:文件專區(v1.3 流程,不變)、驗證申請附件、廠商檔案、設備附件。後三種走 v1.4:

- **派送**:核准 → NAS 歸檔 → 送 `POST /api/integrations/csit/v2/document-jobs`(schemaVersion 2.0、`eventId` 與 `csitJobId` 分開、`source`、`document.approval`、`supersedes`,`Idempotency-Key`=`eventId`)。
- **KM 取檔的位置**:模擬器自己的路由,KM 以「設定的 CSIT 位址 + 檔案 ID」去抓,**不會**照通知裡的 `downloadUrl` 走(規格要求只用逐檔授權路由)。
  驗證附件 `GET /api/integrations/km/v1/documents/{id}/versions/{v}/content`、廠商 `…/vendor-files/{id}/content`、設備 `…/equipment-documents/{id}/content`。每個來源只能從自己的路由取到,詳情頁會顯示「KM 取檔位置」。
- **KM 回報**:`document-jobs/status`、`document-metadata-changes/status`、`document-deletions/status`、`analysis-results`。判定:欄位與 `result`(v2、`sourceSpecific`、method 含 Visual/None)、`Idempotency-Key`=`callbackId`、回報帶回的識別值與原通知逐字相同、終態後不可再來、`appliedRevision`=`sourceRevision`、刪除的 `resource` 與請求相同。
- **換版**:上傳時選「取代舊版本」,通知帶 `supersedes`;可驗證 KM 在新版完成後才停用舊索引、新版失敗時舊索引不動。
- **改標籤(v2)**:`POST …/document-metadata-changes`,`sourceRevision` 每次遞增;「送舊修訂」按鈕用舊修訂再送,KM 應回 409。
- **v2 刪除**:`POST …/v2/document-deletions`(含 `sha256`、`canonicalIngestionEventId`、`scope=DocumentVersion`);對已刪版本再送上傳通知,KM 應回 410。
- `--scope-style v14`:送給 KM 的 token 用 v1.4 的分端點 scope(`km.ingestion.write` 等);`--identity` 模式可簽發 v1.4 的外送 scope 名稱(`csit.documents.read` 等)。`--public-url` 設定通知裡 `downloadUrl` 顯示的位址。
- 未涵蓋:Test Report 的 v1 通知與其 v2 `analysis-results` 的發起端(只接收並檢查格式)。

## 模擬器的判定(依規格 v1.3 獨立撰寫,不 import KM 程式)

欄位齊全(含 Completed.result 全部 key)、時間戳三鍵、callbackId 冪等(同內容 204、不同內容 409)、終態後不可再收狀態、Processing 不可重複、
關聯 ID 與 202 一致、刪除七項清理只能是 Deleted/NotPresent 且 `cleanupVerified=true`。CSIT 流程也照規格:未核准、未入 NAS 不會通知 KM;
KM 驗證刪除完成後,CSIT 才移除自己的檔案。

## 自動化演練與測試

```bash
TEST_DATABASE_URL=postgresql://user:pass@host/db python -m tools.csit_simulator.drill   # 66 項(v1.3 + v1.4),真實 HTTP
python -m pytest tests/csit_simulator -q
```

## 尚未涵蓋

- 真實 M2M:`--identity` 模式已提供自簽的 JWKS 與 client credentials(給 KM 信任模擬器用);仍不是 CSIT 真實的身分服務。
- 7444 TLS 入口與 allowlist。
- Test Report v1 通知、v1.3 §8 / §9.2 的提案介面。
