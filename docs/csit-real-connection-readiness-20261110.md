# KM ↔ 真實 CSIT 對接:KM 端就緒狀態(2026-11-10)

目的:通知 Patty 開始配合前,KM 自己要先完成的事、做到哪、還缺什麼。DEV 環境,不碰 Production。CSIT 端的 `KmIntegration.Enabled` 由 CSIT 決定何時打開,KM 先就緒。

## 一、KM 端已完成(程式在 repo,尚未部署的標明)

| 項目 | 狀態 |
|---|---|
| 依 v1.4.1 實作 v2 路由、事件白名單、失敗碼、409 策略、換版、metadata 變更、刪除七項證明 | 已部署(API `v14b-spec141`) |
| 專區:第 9 個專區、導覽助理、分類對應(CSIT 分類優先於 LLM)、PPTX/MD、技術標籤、CPE 關鍵字 | 已部署 |
| 外送 token 檢查可設定:`KM_CSIT_OUTBOUND_STRICT=false` 時只檢查規格有定的項目(issuer、audience、exp、scope 包含要求的),`principal_type`/`client_id`/`sub` 有才比對 | **已部署(DEV,2026-11-10)** |
| 收件端:scope 是 JSON 陣列也能讀;`KM_CSIT_SERVICE_MARKER_REQUIRED=false` 可不要求服務標記(核准的 client 清單仍檢查) | **已部署(DEV,2026-11-10)** |
| TestReport 換版(v2 `TestReportCommitted`):KM 尚未能取代數值庫的舊版,現在明確回 `Failed / REPLACEMENT_NOT_SUPPORTED`(不可重試),舊版維持現行 | **已部署(DEV,2026-11-10)** |
| 真實模式設定檔 `compose-real.override.yml`(伺服器 `~/.km-control/csit-mode/`,備份 `.before-20261110`;repo 副本 `deploy/csit-integration-v1/`) | 已更新,真實模式未啟用所以尚未生效 |

真實模式設定檔補上的項目(原本只有 v1.3 的三個變數,切過去會悄悄少掉這些):報告範本 `KM_CSIT_REPORT_TEMPLATES=1`、LLM 擷取(`KM_CSIT_DOCLIB_LLM` 與 LLM 連線、金鑰檔掛載、`host.docker.internal`)、`KM_CSIT_ANALYSIS_RESULTS_ENABLED=false`、`KM_CSIT_OUTBOUND_STRICT=false`、外送 scope。合併後的設定已用 `docker compose config` 驗證(只列非機密鍵)。

## 二、驗證(2026-11-10)

- Windows 本機:分類、PPTX、keeper、legacy、zone_pages 等 250 項通過。
- Linux(伺服器上用 worker 映像 + 拋棄式 Postgres 容器,事後已刪除)跑整個 `tests/csit_v1`:**520 通過、4 略過、6 失敗**。
  - 1 項是我先前加技術標籤造成的(`clean_semantic` 回傳多一個鍵),測試已修正。
  - 其餘 5 項:`test_neo4j_real_concurrent_upsert`、`test_timescale_real_retry_no_duplicates`(需要真實 Neo4j / Timescale)、`test_zone_regression.test_existing_zone_grant_selection`(讀伺服器的租戶設定,容器內沒有)。與這次修改無關,但我沒有在改動前的程式上重跑來證明它們原本就失敗。
- 沒有對真實 CSIT 做任何呼叫,只讀了它公開的 discovery 與 JWKS。

## 三、真實 CSIT 身分伺服器現況(只讀 discovery,2026-11-10)

- issuer `https://csit-identity-dev.duckdns.org:7443/`,token endpoint `/connect/token`,JWKS 1 把金鑰,簽章 RS256,支援 client_credentials 與 client_secret_basic。
- 這些與伺服器上受保護環境檔(`KM_CSIT_ENV_FILE`)裡的設定一致。
- `scopes_supported` 只有 `km.ingestion.submit`、`csit.document.read`、`csit.ingestion.status.write`(加上身分管理用的)。**v1.4.1 的 v2 scope 沒有列出**:`km.ingestion.write`、`km.metadata.write`、`km.deletion.write`、`csit.km.status.write`、`csit.km.deletion-status.write`。
- `claims_supported` 只有 `aud exp iat iss sub`;`principal_type`、`client_id` 是否在實際 token 裡要看實際 token(discovery 不會列)。
- 影響:KM 若要求未註冊的 scope,整個 token 請求可能失敗,連 v1 取檔都不能用。因此真實模式的外送 scope 目前只要已註冊的兩個(`csit.document.read`、`csit.ingestion.status.write`),先測 TestReport v1 與文件專區 v1。v2 回報要等 CSIT 註冊 v2 scope 後再加。

## 四、仍需 CSIT(Patty)確認或提供

1. 註冊 v2 scope(上節),並確認 KM 的 client(`km-csit-integration-dev`)與 CSIT 的 client(`csit-km-ingestion-dev`)已核發、secret 已放進 KM 的受保護檔。
2. 提供一個真實 token 的欄位清單(不含 token 本身):是否有 `principal_type`、`client_id`、`sub`,`scope` 是字串或陣列,`aud` 的值。
3. CSIT→KM 的 TLS:KM 入口 `https://km-dev-da40.duckdns.org:3030` 的憑證 CSIT 端是否信任;KM→CSIT 的 7444 是否為公開信任憑證(若是私有 CA,KM 要掛 CA)。
4. 7444 白名單:任務 A(已開)、B(vendor / equipment 取檔)、C(metadata 狀態、Correlation Resolver)、D(v2 刪除狀態)各開到哪。
5. 分類名稱:真實 CSIT 的第一至三層名稱是否與 `CSIT文件中心_KM主題對應表.xlsx` 一致。
6. CPE 機種清單與關鍵字。
7. 測試樣本檔與測試窗口。

## 五、KM 仍未做、不阻擋第一輪對接的

- TestReport 換版寫入數值庫(等 CSIT 任務 C 定出換版事件的內容再做)。
- 只有檔名前綴符合已註冊範本的 XLSX 報告才算數值與畫圖。
- 舊資料匯入與 CSIT 送來文件的跨庫去重。
- 專區頁的技術標籤篩選;導覽助理依名稱找 CSIT 送來的文件。
- 單一 worker 與 50MB 上限對大量首次匯入的影響。

## 六、切到真實模式的步驟(尚未執行,需你明確同意)

1. 部署 API 與 worker 的新映像(含上表三項尚未部署的修改)。部署前確認 `csit-mode.sh status` 無進行中的工作。
2. 確認受保護環境檔的 client 憑證、secret 檔已就緒(只查存在與權限,不讀內容)。
3. `csit-mode.sh real`(會停掉模擬器、換成真實身分與位址;進行中的工作會被擋,除非 `--force`)。
4. 通知 Patty 開始;由 CSIT 打開 `KmIntegration.Enabled` 後,先送一份 TestReport v1 與一份文件專區 v1(各格式),再逐項做 v2。
5. 回復:`csit-mode.sh live --confirm-real-data`(回到模擬器扮演 CSIT);設定檔備份 `compose-real.override.yml.before-20261110`。

## 七、部署紀錄(2026-11-10)

- API 映像 `km-csit-integration:v14c-auth-20261110`(FROM `…v14b-spec141-20261105`,`Dockerfile.api2`,疊加 `auth.py`、`config.py`);worker 映像 `km-csit-worker:v14t-auth-20261110`(FROM `…v14s-classify-pptx-20261110`,`Dockerfile.worker16`,疊加 `auth.py`、`config.py`、`v2_pipeline.py`)。換之前容器內三個檔案與修改前的提交逐位元相同。API 映像裡的 `v2_pipeline.py` 與 repo 不同(較舊),API 不跑管線,所以沒有動它。
- 用 `csit-mode.sh reapply` 切換(無進行中的工作),`images.env` 備份 `images.env.before-v14t`。仍是 live(模擬器)模式,真實模式沒切。
- 換映像前,在 Linux 以新 worker 映像加拋棄式 Postgres 跑整個 `tests/csit_v1`:521 通過、4 略過、5 失敗(同樣的環境因素:真實 Neo4j / Timescale 兩項、租戶設定三項)。
- 換映像後:兩個容器 healthy,日誌無 traceback;6 條收件路由無 token 各回 401(表示路由到得了 KM 且認證在作用);worker 設定讀到 `outbound_strict=True`、`service_marker_required=True`(live 模式的行為沒變,放寬只在真實模式的設定檔裡開)。
- 回復:`images.env.before-v14t` 還原為 `images.env`,再 `csit-mode.sh reapply`。

## 八、依 CSIT 2026-11-10 回覆的修改(尚未部署)

- 專區判定不再使用 LLM:`resolve_zone` 拿掉「LLM 建議的專區」與「LLM 判斷為 TestReport」兩步。剩下的規則都來自 CSIT 資料(TestReport 來源、分類對照表、第一層等於專區名、附件來源所屬專區),其餘進「待分類」。LLM 的建議存成 `zone_suggestion`。
- 真實模式設定檔的 `KM_CSIT_OUTBOUND_STRICT` 改回 `true`(伺服器上未生效的那份仍是 `false`,部署時同步)。
- 測試:Windows 上相關 255 項通過;需要 Postgres 的 20 項在 Windows 無法執行(`TEST_DATABASE_URL`),部署前要在 Linux(worker 映像加拋棄式 Postgres)再跑整個 `tests/csit_v1`。
- 影響:對照表未決定的文件(研討會、Broadband Forum 等)會進待分類。CSIT 文件庫目前沒有待分類的審查頁。

### 部署紀錄(2026-11-10,第八節的修改)

- worker 映像 `km-csit-worker:v14u-zone-csit-20261110`(FROM `…v14t-auth-20261110`,`Dockerfile.worker17`,疊加 `zones.py`、`doclib_metadata.py`;容器內雜湊與 repo 一致)。API 映像不變(不跑專區判定)。以 `csit-mode.sh reapply` 換上,換之前無進行中的工作;`images.env` 備份 `images.env.before-v14u`。仍是 live 模式。
- 換之前在 Linux 以新映像加拋棄式 Postgres 跑整個 `tests/csit_v1`:520 通過、4 略過、5 失敗(與上一輪相同的環境因素:Neo4j／Timescale 各一、租戶設定三項)。測試容器與網路已刪除。
- 伺服器上的真實模式設定檔 `KM_CSIT_OUTBOUND_STRICT` 已改為 `"true"`(備份 `compose-real.override.yml.before-strict-20261110`),真實模式仍未啟用。
- 換後驗證:worker healthy、日誌無錯誤;容器內 `resolve_zone`:無分類的文件庫檔案、LLM 說是 TestReport 或指定專區 → `unclassified／none`;TestReport 來源 → 產品驗證專區;外部認證資料 → 認證;6 條收件路由無 token 各回 401。
- 回復:`images.env.before-v14u` 還原為 `images.env`,再 `csit-mode.sh reapply`;設定檔還原用 `compose-real.override.yml.before-strict-20261110`。
