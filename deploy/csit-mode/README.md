# KM ↔ CSIT 模式切換(真實 CSIT / CSIT 模擬器)

同一套 KM(`km-csit-integration-api` + worker)可以對接真實 CSIT,也可以對接 CSIT 模擬器,用一支腳本切換。**KM 內沒有執行中的切換開關**(能改信任錨的端點是安全漏洞);切換 = 以另一組設定重建 api 與 worker 容器。

```bash
~/.km-control/csit-mode/csit-mode.sh status          # 目前模式、容器狀態、兩種模式各有多少工作在進行中
~/.km-control/csit-mode/csit-mode.sh sim             # 切到模擬器
~/.km-control/csit-mode/csit-mode.sh real            # 切回真實 CSIT
~/.km-control/csit-mode/csit-mode.sh reapply         # 以目前模式重建(例如 images.env 換了新映像)
```

`GET /health` 回報 `csitMode`(`real` | `sim`),模擬器的「測試連線」也會顯示。

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

## 守門
切換前檢查**目前模式**是否還有進行中的工作(Accepted/Processing 的工作與刪除、Pending/Delivering 的回報)。有就拒絕(結束碼 2),除非加 `--force`。切換期間 KM 的 CSIT 入口約 1 分鐘收不到通知;真實 CSIT 在 sim 模式下會得到 401。

## 一次性準備(已做過,可重複執行)
`setup-sim.sh`:建立 `csit_sim` schema 與資料表、`km_csit_docs_sim` 向量集合、模擬 KM 的 client secret、`sim.db.env`。

## 模擬器
- 畫面:`ssh -L 8765:127.0.0.1:8765 <server>` 後開 `http://127.0.0.1:8765/`(只綁伺服器的 loopback)。
- HTTPS(8443)只在 `km-control-private` 網路內可連。簽發 token、公鑰、client credentials、HTTPS 與 KM 的 `validate()` 規則一致,KM 的 `ClientCredentialsProvider` 與入站驗證在測試中直接驗過(`tests/csit_simulator/test_identity.py`)。
- 演練:`remote_drill.py`(同 `drill.py` 的檢查,對已部署的 KM;`--slow` 加上 CSIT 回報端中斷的情境,需要數分鐘)。

## 限制
- sim 模式只涵蓋規格 v1.3 文件庫;Test Report v1 通知不在模擬範圍,sim 模式下 Neo4j、Timescale 都沒有設定。
- LLM 擷取在兩種模式都沒啟用(`documentType`=`Other`、摘要與關鍵字為空)。
- 模型權重會在 worker 啟動時從 HuggingFace 下載,所以 worker 重建需要對外網路。
