# RCA 後端上線規劃(產品驗證專區)

狀態:**規劃,尚未執行任何伺服器動作。** 前端(選單、頁面)已在 2026-11-04 上線,頁面目前顯示「RCA 後端尚未啟用」。

## 1. 已確認的事實(依 repo 內容)

| 項目 | 內容 |
|---|---|
| 入口 | `deploy/dev-3030/nginx.runtime.conf` 內 `location /api/ { proxy_pass http://$web_upstream; }`,所以 `/api/rca/v1/*` **不需要改 nginx**,會直接到 web 容器(`kb-web` 或 `km-da40-web-1`,依 cookie 選資料區) |
| 身分 | `InstanceAuthMiddleware` 驗證登入 cookie 後設定 `request.state.km_identity`(含 `sub`、`role`、`instance_id`);未登入的 API 請求回 401 |
| 報告資料 | `km_test` schema,在各資料區自己的 TimescaleDB(`kb-timescaledb`、`km-da40-timescaledb-1`);RCA 只做唯讀查詢 |
| LLM | wifi8 助理是用 Celery 在 `kb-celery-search` / `km-da40-celery_search_worker-1` 執行,不在 web 行程內 |
| 部署慣例 | web 映像以日期加 commit 當 tag(例如 `km-chat-v2-secure:open-files-20261031-…`),以 compose override 切換;回滾是改回上一個 tag |

## 2. 沒能確認的事(需要現場唯讀檢查)

我嘗試唯讀查詢 DGX 上的 `km_test`(筆數、報告清單)時,被權限分類器擋下(「Production Reads」),**我沒有繞過**。以下幾點因此未知,規劃以「待確認」標示:

1. 哪一個資料區(test 或 da40)的 TimescaleDB 有 `km_test`,裡面有幾份報告、是哪些設備與韌體。
2. 產品驗證專區在線上實際連到哪個 web 容器。
3. web 容器是否已有連 TimescaleDB 的設定,以及主要 LLM 是否可在該容器使用。
4. 先前部署的 `~/.km-control/csit-report-assistant-20261021` 實際內容(可能代表測試報告助理已有一部分上線)。

你可以自己在 DGX 執行下列唯讀指令貼給我,或在 Claude Code 設定加入唯讀的 Bash 權限規則,我再查:

```bash
for c in kb-timescaledb km-da40-timescaledb-1; do echo "== $c"; docker exec $c sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*), min(test_date), max(test_date) from km_test.test_run"'; done
docker exec kb-timescaledb sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select product_id, report_type, firmware_version, test_date from km_test.test_run order by product_id, test_date"'
docker inspect kb-web km-da40-web-1 --format '{{.Name}} {{range .Mounts}}{{.Destination}} {{end}}'
ls ~/.km-control/csit-report-assistant-20261021
```

## 3. 這次先補強的程式(已在本機完成並測試)

- **啟動安全:** 原本建立 router 時就會讀資料庫設定,缺設定會讓整個 web 應用啟動失敗。已改成每次請求才連線,缺設定只讓 RCA 回 503。
- **註冊受開關控制:** 只有 `KM_RCA_ENABLED=1` 時才把 RCA 路由接進主應用程式,而且註冊失敗只記錄、不影響啟動。開關為預設關閉時,應用程式與現在完全相同(有測試驗證)。
- 23 項測試通過(含「預設不註冊」「缺資料庫設定回 503」「開關開啟才出現三條路由」)。

## 4. 建議的分階段上線

**原則:先上沒有 LLM 的比較功能,LLM 分析之後再上。** 比較只是幾個唯讀 SQL 查詢,幾毫秒完成;LLM 分析要等幾十秒,不能佔住 web 行程。

### 階段 A:比較功能(不含模型)

| 步驟 | 做什麼 | 對真實系統的影響 | 回滾 |
|---|---|---|---|
| A1 | **建唯讀資料庫角色**(只在有 `km_test` 的那個 TimescaleDB):`CREATE ROLE km_rca_ro LOGIN PASSWORD '…'; GRANT USAGE ON SCHEMA km_test TO km_rca_ro; GRANT SELECT ON ALL TABLES IN SCHEMA km_test TO km_rca_ro;` | 資料庫新增一個角色,不動任何資料 | `DROP OWNED BY km_rca_ro; DROP ROLE km_rca_ro;` |
| A2 | 把連線字串放成檔案 secret(權限 600),掛進 web 容器 `/run/secrets/km-rca-dsn:ro`(compose override 新增一個唯讀掛載) | 容器設定變更(下一步一起套用) | 移除掛載 |
| A3 | 建新的 web 映像(只增加 `compare.py`、`rca.py`、`rca_routes.py` 和 `__init__.py` 的註冊),**tag 用新名稱**,舊映像保留 | 無(尚未切換) | 不適用 |
| A4 | 先在**測試用資料區**(不是 demo 用的那個)以新映像、`KM_RCA_ENABLED=0` 重建 web 容器,確認啟動正常、既有功能不變 | 該資料區 web 容器重啟,約幾秒到十幾秒中斷 | 改回舊 tag 重建 |
| A5 | 同一容器改 `KM_RCA_ENABLED=1`、`KM_RCA_DSN_FILE=/run/secrets/km-rca-dsn`、`KM_RCA_ROLES=…` 再重建 | 同上再來一次 | 設回 `0` 或舊 tag |
| A6 | 驗證(見 §5) | 唯讀 | — |
| A7 | 確認無誤後,對另一個資料區重複 A3–A6(如果兩邊都需要) | 同上 | 同上 |

**影響範圍:** 重建 web 容器時,該資料區所有專區(不只是產品驗證專區)的使用者會短暫斷線約數秒。建議在沒有 demo、沒有人使用的時段進行,並且先確認舊映像 tag 還在。

### 階段 B:LLM 原因分析

需要另外設計,不建議直接把現在的 `/analyze` 放上去:

- 模型回答要 30 到 90 秒,在 web 行程內同步等待會佔用 web 工作執行緒。
- 做法:仿 wifi8 助理,改成 Celery 任務(`search` 佇列)加輪詢,在 `kb-celery-search` / `km-da40-celery_search_worker-1` 內執行。這代表**這兩個 worker 容器的映像也要更新並重啟**。
- 在這之前,頁面的「比較並分析可能原因」按鈕在線上應該隱藏或停用,避免使用者按到 503。

階段 B 的前置需求:真實 LLM 可用、至少 2 到 3 組已知根因的案例當驗收標準、以及你對輸出格式與信心等級的確認。

## 5. 階段 A 的驗證步驟

1. 開關關閉(A4):`/health` 正常;其他專區(WiFi、認證、行動通訊)頁面與問答照常;`GET /api/rca/v1/runs` 回 404。
2. 開關開啟(A5)但未登入:`/api/rca/v1/runs` 回 401。
3. 登入後 `GET /api/rca/v1/runs` 列出報告;`POST /compare` 選兩份**同類型**報告回傳差異。
4. 故意選不同類型的報告、選不存在的 ID、選 1 份:各回 422 與明確訊息。
5. 資料庫連線設錯時:RCA 回 503,**其他功能不受影響**。
6. 在 DB 檢查:`pg_stat_activity` 只有 `km_rca_ro` 的短連線,沒有寫入。
7. 前端頁面:登入後打開「RCA 分析」,搜尋、勾選、比較,看差異表與來源儲存格是否與報告 xlsx 相符(抽查 3 筆)。

## 6. 需要你決定的事

1. **誰能用 RCA?** 目前是「該資料區登入的任何帳號」,看到的報告限於 `access_roles` 含 `CSIT_ENGINEER` 的。要不要改成需要特定權限(例如像 wifi8 那樣由 KM Control 授權)?
2. **哪個資料區?** 依 §2 的檢查結果決定先上 test 還是 da40。
3. **上線時間:** 建議不在有 demo、有人使用的時段;demo 下週,你要在 demo 前還是後?
4. **階段 B 要不要做,什麼時候做。**
5. 允許我做唯讀檢查(§2),或你貼結果給我。

## 7. 風險摘要

| 風險 | 程度 | 緩解 |
|---|---|---|
| 重建 web 容器造成短暫中斷 | 中 | 離峰時段、先在測試資料區、舊映像 tag 保留、可立即回滾 |
| 新程式讓 web 應用啟動失敗 | 低 | 開關預設關閉、註冊失敗只記錄、已有測試 |
| RCA 查詢拖慢資料庫 | 低 | 唯讀角色、單次最多 6 份報告、查詢走索引、連線逾時 5 秒 |
| 看到不該看的報告 | 中 | `access_roles` 過濾、需登入;權限模型待你決定(§6-1) |
| 模型誤導使用者 | 中(階段 B) | 已有驗證機制與「待驗證」標示;階段 B 前不上線 |
