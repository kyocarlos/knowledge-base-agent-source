# KM ↔ CSIT 模式切換(real / sim / live)

同一套 KM(`km-csit-integration-api` + worker)可以對接真實 CSIT,也可以對接 CSIT 模擬器,用一支腳本切換。**KM 內沒有執行中的切換開關**(能改信任錨的端點是安全漏洞);切換 = 以另一組設定重建 api 與 worker 容器。

```bash
~/.km-control/csit-mode/csit-mode.sh status          # 目前模式、容器狀態、兩種模式各有多少工作在進行中
~/.km-control/csit-mode/csit-mode.sh sim             # 切到模擬器
~/.km-control/csit-mode/csit-mode.sh real            # 切回真實 CSIT
~/.km-control/csit-mode/csit-mode.sh live --confirm-real-data   # 模擬器當 CSIT,但 KM 寫入/刪除「正式資料」
~/.km-control/csit-mode/csit-mode.sh live-list [N]   # 唯讀:KM 在正式 schema 裡有哪些 CSIT 文件(含可貼進模擬器「以識別碼刪除」的 delete_spec)
~/.km-control/csit-mode/csit-mode.sh live-purge      # 請模擬器對它送進正式資料的每一份文件逐一送刪除通知
~/.km-control/csit-mode/csit-mode.sh reapply         # 以目前模式重建(例如 images.env 換了新映像)
```

`GET /health` 回報 `csitMode`(`real` | `sim` | `live`),模擬器的「測試連線」也會顯示。

## 兩種模式差在哪裡

| | real | sim |
|---|---|---|
| 入站信任(簽發者/公鑰) | CSIT 身分服務 `csit-identity-dev.duckdns.org:7443` | 模擬器 `https://csit-sim:8443/` |
| 出站 token、下載、回報 | `csit-dev-da40.duckdns.org:7444` | 模擬器 `https://csit-sim:8443` |
| 憑證信任 | 公開 CA | 公開 CA + 模擬器自簽 CA(合併成一個檔案,`SSL_CERT_FILE`) |
| PostgreSQL | `km_control` 的 `public` | `km_control` 的 `csit_sim`(連線 `search_path`,同一份 migration 再套一次) |
| 向量庫 | `km_csit_docs`(文件庫)、`knowledge_base`(測試報告) | `km_csit_docs_sim` |
| 檔案 | `/var/lib/km/data/csit-integration-v1` | `…/csit-integration-sim` |
| Neo4j / Timescale | 掛載 | **不掛載、不設定**(只做文件庫;模擬的刪除碰不到真實資料) |
| 搜尋快取 | 刪除時清除 | 不清 |
| 模擬器容器 | 不執行 | 執行(只有 sim 模式才有 token 端點) |

兩種模式的資料表、向量、檔案完全分開,切換不會讓一邊的待送回報被送去另一邊。

## live 模式:模擬器通知,但寫入正式資料
身分與 CSIT 位址和 sim 一樣是模擬器(所以真實 CSIT 此時得到 401);**資料落點和 real 一樣**:`public` schema、`knowledge_base`(測試報告 v1)、`km_csit_docs`(文件庫與 v2 來源)、`ai_km_knowledge_v1`(報告範本)、`/var/lib/km/data/csit-integration-v1`、Neo4j、TimescaleDB、搜尋快取清除。測試報告範本(`KM_CSIT_REPORT_TEMPLATES=1`)與 LLM 擷取都開。切換必須加 `--confirm-real-data`。

- **模擬器怎麼知道哪些是自己送的**:每份文件在通知 KM 時被標上 KM 當下的 `csitMode`(`kmModes`)。畫面「正式資料」頁、`POST /api/purge-live`、`csit-mode.sh live-purge` 只清有 `live` 標記的文件。
- **以識別碼刪除**(`POST /api/delete-by-id`,畫面同頁):可刪不是模擬器送的文件(例如真實 CSIT 先前送來的 2 份 v1 報告),貼 `live-list` 的 `delete_spec`。v2 來源要帶 KM 記錄的 `sha256` 與 `canonicalIngestionEventId`,不符 KM 會拒絕;KM 不認識的 id 只會留下 tombstone。KM 在 live 模式時,畫面會再問一次,API 要 `confirmLiveData:true`。
- **離開 live**:真實報告在 live 期間被模擬器的 Resolver 回 `CORRELATION_NOT_FOUND`,KM 把它們的 analysis 記成 Skipped;`csit-mode.sh` 離開 live 時只刪這種紀錄,避免之後真實 Resolver 上線時這兩份被略過。
- **前提**:報告範本要寫 TimescaleDB 的 `km_test` schema(`src/report_numeric/schema.sql`),伺服器上的 Timescale 目前沒有這個 schema,所以真正命中範本檔名(SIT-TR-WL-RvR / SIT-TR-WL-Throughput / SIT-TR-SC-NR-Throughput)的 xlsx 會在數值階段失敗;其他檔案走一般解析,已驗證。

## 守門
切換前檢查**目前模式**是否還有進行中的工作(Accepted/Processing 的工作與刪除、Pending/Delivering 的回報)。有就拒絕(結束碼 2),除非加 `--force`。切換期間 KM 的 CSIT 入口約 1 分鐘收不到通知;真實 CSIT 在 sim 模式下會得到 401。

## 一次性準備(已做過,可重複執行)
`setup-sim.sh`:建立 `csit_sim` schema 與資料表、`km_csit_docs_sim` 向量集合、模擬 KM 的 client secret、`sim.db.env`。

## 模擬器
- 畫面:`ssh -L 8765:127.0.0.1:8765 <server>` 後開 `http://127.0.0.1:8765/`(只綁伺服器的 loopback)。
- HTTPS(8443)只在 `km-control-private` 網路內可連。簽發 token、公鑰、client credentials、HTTPS 與 KM 的 `validate()` 規則一致,KM 的 `ClientCredentialsProvider` 與入站驗證在測試中直接驗過(`tests/csit_simulator/test_identity.py`)。
- 演練:`remote_drill.py`(同 `drill.py` 的檢查,對已部署的 KM;`--slow` 加上 CSIT 回報端中斷的情境,需要數分鐘)。

## 限制
- sim 模式:Neo4j、Timescale 都沒有設定(測試報告走一般解析、不寫圖譜與數值)。LLM 擷取在 sim 與 live 開啟,real 沒開。
- 嵌入模型快取在 `hf-cache`(掛進 worker),worker 重建不需要重新下載。
- live 與 real 共用 `public` 的待送回報:切換前的守門會擋住還有進行中工作的情況。
