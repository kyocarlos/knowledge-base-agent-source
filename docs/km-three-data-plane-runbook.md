# KM Test／DA40／RD2 資料平面部署與切換

## 不可省略的安全界線

一個 Compose project 只代表一個 KM 入口：`km-test`、`km-da40`、`km-rd2`。不得以相同的 volume、Redis、PostgreSQL、Neo4j、Qdrant、TimescaleDB、檔案根目錄或 secrets 建立兩個入口。瀏覽器、Agent 與外部系統不可直接連資料庫。

目前執行中的資料與服務指定為 **Test**。此指定不是資料移轉：既有 Neo4j、Qdrant、TimescaleDB、report registry、Redis、uploads、staging 與 assets 均保留。DA40/RD2 起始為空白，任何資料匯入另須單位歸屬核准。

## 建置順序

1. 先部署 `deploy/control-plane/docker-compose.control.yml`，建立獨立 Control DB、Control Auth HTTPS 入口與私有 `km-control-private` network。Control DB 不可帶入任何資料區的業務資料或資料庫憑證。
2. 以 `scripts/km_control_admin.py` 透過受保護 prompt 或 stdin 建立唯一初始 Control 管理員；此帳號核准 self-registration、授權資料區與停用帳號。不可把密碼寫入 env 範例、網址或 log。
3. 在 maintenance window 建立新的 Test checkpoint，驗證 Neo4j nodes/relationships、兩個 Qdrant collection point counts、Timescale rows、report registry rows 與檔案 checksums；先完成完整 application login/WebSocket shadow restore。
4. 用 `deploy/tenant-isolation/test.env.example` 建立 Test secrets/env，設定 `KM_CONTROL_DB_URL`、Control HTTPS origin 與獨立 entry-session signing key。將既有 Qdrant snapshots 還原到有持久 Docker volume 的 Test Qdrant。保留舊 snapshot 與原 container，直到資料比對相符。
5. 執行 `python scripts/verify_tenant_isolation.py deploy/tenant-isolation/test.env deploy/tenant-isolation/da40.env deploy/tenant-isolation/rd2.env`，確認 project、port、資料庫名稱與帳號皆不重複；再僅建立 Test shadow stack。通過 Control 註冊/核准/選區、WebSocket、搜尋、上傳、下載、worker 與還原演練後，才在受控切換窗口把既有入口導向 Test stack。
6. 以同一模板建立空白 DA40，再建立空白 RD2。一般使用者一律由 Control DB 管理；原本每區 `km_accounts` 僅能作為不對外的一次性 break-glass 維運帳號，不能建立一般使用者登入。

## 防呆與復原

- `KM_INSTANCE_ID` 必須是 `test`、`da40` 或 `rd2`；啟動時檢查 Neo4j、Qdrant、TimescaleDB、registry、Redis 和三個檔案根目錄設定。缺少任何一項即拒絕服務。
- CSIT 只連至固定 Control Auth 登入網址，不傳遞 username、password、cookie、token、instance 或 redirect target。KM 帳號僅在 Control Auth 提交並以強雜湊保存。
- Control session 只可選取已核准入口；Control 只產生 60 秒、一次性且目標綁定的 opaque code。資料區 callback 消費該 code 後才設置自己的 15 分鐘 session。
- 登入 session 具有 `iss=km-control`、target audience、`sub`、`instance_id`、角色、到期時間、token ID 與 session epoch；DA40 session 用於 RD2/Test 時回應 401。每個 HTTP 請求與 WebSocket accept 均重新檢查 Control DB 的帳號、epoch 與 grant，撤銷立即生效。
- 每個 data plane 使用獨立 Redis broker，因此 Celery queue 名稱可相同但物理上不相通。Cache 額外使用 `km:<instance>:` key prefix。
- 重攝入寫入前必須使用 `--instance-id` 且與 `KM_INSTANCE_ID` 相同；未指定或不一致時拒絕執行。不得對目前 Test 直接執行全域清除。
- 每個入口都需保存 checkpoint manifest、image archive、Neo4j logical export、Qdrant snapshots、Timescale/report-registry dumps、Redis、SQLite 與檔案 checksum。Qdrant snapshot 必須複製到容器外。

## 驗收證據

對每一入口記錄 health、登入、`/api/auth/me`、WebSocket、搜尋、報表、下載與 ingest worker 結果。建立 Test/DA40/RD2 各一筆 sentinel record，交叉以三種帳號搜尋、下載、讀取 task 與開啟 WebSocket；任何跨入口結果均為失敗。最後在刪除 shadow Qdrant container 的情境下，從外存 snapshot 還原兩個 collection 並核對 point counts。
