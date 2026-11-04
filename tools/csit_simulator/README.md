# CSIT 模擬器(規格 v1.3)

扮演 CSIT,對 KM 演練文件專區寫入與刪除。KM 的每個行為都會依規格逐項判定(通過 / 不符),不連 CSIT 資料庫。

## 啟動

```bash
python -m tools.csit_simulator serve --km-base-url http://<KM>:<port> --token <DEV bearer> --port 8765
```

開 `http://127.0.0.1:8765/`:選檔或輸入文字 → 送出 → 看時間線與判定;可重送(驗冪等)、刪除、注入故障。

## 模擬器做的事

| 方向 | 內容 |
|---|---|
| CSIT→KM | `POST /api/integrations/csit/v1/document-library/jobs`、`POST .../document-deletions`(帶 `Idempotency-Key`) |
| KM→CSIT | `GET /api/integrations/km/v1/document-library/files/{id}/content`(可注入:內容被改、截斷、503×N、403、404)、`POST .../document-library/ingestion-status`、`POST .../document-deletion-status` |

收到 KM 回報時檢查:欄位齊全(含 Completed.result 全部 key)、時間戳三鍵、callbackId 冪等(同內容 204、不同內容 409)、
終態後不可再收狀態、Processing 不可重複、關聯 ID 與 202 一致、刪除七項清理只能是 Deleted/NotPresent 且 `cleanupVerified=true`。

## 本機端到端演練(26 項)

```bash
TEST_DATABASE_URL=postgresql://user:pass@host/db python -m tools.csit_simulator.drill
```

起模擬器 + 真實 KM 路由與 worker(向量庫用記憶體版、認證用固定 bearer),全程走真實 HTTP。

## 尚未涵蓋

- 真實 M2M(JWKS、client credentials、audience/scope):這版用固定 bearer。
- 7444 TLS 入口與 allowlist。
- Test Report v1 的通知(`ingestion-jobs`)與 v1.3 §8、§9.2 提案中的介面。
