# KM 最新進度與 GitHub／DGX 對帳 — 2026-10-14

> 本文件記錄進度文件發布當時的基線。本開發分支後續已補齊最新 source／tests／public-base build；接手開發請先讀 [最新交接指南](../handoff/PATTY_DEVELOPMENT_HANDOFF.md)，不要把本文歷史「source 尚未發布」當成此分支的現況。

本文件提供 Patty 審視 CSIT ↔ KM Integration v1 的最新 DEV 進度。依使用者本次授權，僅更新進度文件；不代表最新 integration source 已發布、Production 已部署，或完整 Phase 1 已驗收。

## 審查結論

**Progress documentation: UPDATED。GitHub source vs DGX: STALE / MISMATCH。**

DGX 已有 CSIT Integration v1 API、M2M inbound/outbound、獨立 worker、writers、受控 same-job resume，以及 Processing callback 的 source 修正。原 GitHub 10/02 source snapshot 沒有這批 integration 模組、部署檔與測試。本次文件更新不將這些未發布檔案納入 GitHub。

最新 Processing 修正已通過隔離測試，但尚未部署。真實 same-v3 job 已 Completed，Completed callback 成功；歷史 Processing callback 400 保留，不能將整個 callback lifecycle 宣稱為全程 PASS。

## 版本與來源

| 對象 | 本次核對的版本 | 判讀 |
|---|---|---|
| GitHub public source review | `agent/km-runtime-current-20261002`，source 基準 `88c0e0923acd777e0439095f810571ac94beed04`，2026-10-02 07:16:44 UTC | 292 個檔案；本次只追加進度文件，source 基準仍是此版本 |
| GitHub public main | `013ba04d29a46a877d9393f6dd01f9ba72993ffc`，2026-09-01 | 未包含最新整合 |
| GitHub private origin main | `54c1d24a95a0fc85a3b70a73b99f5f54a2300615`，2026-04-24 | 舊版主線 |
| DGX working tree | `/home/da40_ai_gb10/knowledge-base`；HEAD `ebcc9de00861d4e6a83641e3fbb7a8b853a684f1` | 分支 `agent/km-r0-r2-progress-review-20260813`；最新工作未形成 published source commit |
| 最新既有 GitHub status commit | `phase1-runtime-status`／`54b7ce844d471915260b6b0bbdd04e09e642901e`，2026-10-14 01:57:27 UTC | 只有 `status/current.json`，不是新的 source snapshot |

[固定 source snapshot](https://github.com/kyocarlos/knowledge-base-agent-source/tree/88c0e0923acd777e0439095f810571ac94beed04) · [既有 10/14 runtime status](https://github.com/kyocarlos/knowledge-base-agent-source/blob/54b7ce844d471915260b6b0bbdd04e09e642901e/status/current.json)

10/14 status JSON 本身標示 `STALE`；`git.head`、release commit／digest 等欄位為 null，version endpoint 為 401。它記錄的是 kb-web／Celery services，沒有 CSIT Integration v1 API／worker，不能用來證明本輪 integration source 與 runtime 同步。

## GitHub 與 DGX 逐檔對帳

以 10/02 snapshot 的 292 個 blob 和 DGX 專案目錄逐檔比對 Git blob hash：

| 結果 | 檔案數 |
|---|---:|
| 同路徑且內容一致 | 200 |
| 同路徑但內容不同 | 54 |
| 該 DGX 專案路徑沒有此檔 | 38 |

這不是整台 DGX 的部署遺失檔案數。Control／OIDC 的部分 source 與建置紀錄另存在受保護 runtime build 目錄，不能把專案路徑缺檔解讀為服務不存在，也不能把本目錄直接當成完整可重建的部署來源。

DGX Git status 另有 67 個 tracked changed entries、198 個 untracked entries（normal 模式含目錄彙總）；這是原工作樹總量，不是本次新增檔數。本次未 stage 或發布這批內容。

GitHub snapshot 的 `src/csit/` 是既有 read-only manifest/pull adapter，文件仍記載未送 ingest acknowledgement。它與目前正式 event → ingestion job → document pull → callback 的 Integration v1 是不同程式路徑。

## DGX 最新 Integration v1 範圍

以下目前在 DGX source／記錄中存在，但不在原 10/02 GitHub snapshot：

- `src/csit_integration_v1/`：API、JWT service auth、config、models、repository、M2M client、worker/runtime、pipeline、writers、operator。
- `deploy/csit-integration-v1/`：Compose、API Dockerfile、worker Dockerfile。
- `migrations/20261007_csit_integration_v1.sql`、graph／numeric migrations。
- `config/csit-integration-v1.env.example`、numeric rules、`docs/csit-integration-api-v1-km-dev.md`。
- `scripts/csit-integration-operator.py`、`tests/csit_v1/` 的 contract/auth/worker/writers/operator/callback tests。

已完成且有留存證據的 DEV 工作：

1. inbound service authentication、outbound M2M 與 canonical `project.number / case.number / task.number` contract 對齊；safe contract probe 通過 authentication/schema，disabled gate 回 503，沒有新增 job。
2. 正式 same-v3 job 透過一次受控 same-job resume 完成正常 pipeline；document GET 200、Completed callback 204。
3. relational checkpoint、storage、Qdrant 已有該筆真實文件的寫入證據。该文件沒有萃取 entity／relationship 或 recognized numeric KPI，所以 Neo4j／TimescaleDB 該筆為 N/A／0；不能外推為所有 graph/KPI 場景驗收完成。
4. Processing callback 歷史 400 已定位為缺少 required `timestamps.startedAt`；KM source 修正只新增該 Processing timestamp 映射。歷史 HTTP 400 response body／trace 未保留，未杜撰 CSIT 實際 error text。
5. Human OIDC 與 binding 的較新 source/build/evidence 在受保護部署目錄另有記錄；原 10/02 dossier 的 OIDC disabled 描述是當時狀態，不是 10/14 的完整現況。

## Source、測試與 live runtime 必須分開

| 項目 | 2026-10-14 核對結果 |
|---|---|
| Processing 修正 source | `Repository._outbox` 增加 Processing 的 `timestamps.startedAt`，值來自當次 transition 的 `updated_at` |
| DGX repository.py SHA256 | `5c31959ff7b9fd42e649c073512a0dd35d44cf30e04d63ed2347e038ac5103f1` |
| Live API repository.py SHA256 | `fe5058aa713909417c5ca5b4e54463451baf0c7f72cc5b3c457a95d4a219344e`；仍無 startedAt mapping |
| 修正部署／GitHub source 發布 | 未部署／未發布；本次只發布文件 |
| 留存隔離測試結果 | Integration 210 + Human OIDC 7 + Binding 23 = **240 passed、0 failed** |
| 本次 review 是否重跑測試 | NO；核對 10/14 已保存測試 log |
| API runtime | `km-csit-integration:v1-operator-resume-20261014`；running／healthy；`KM_CSIT_ENABLED=false` |
| API image SHA256 | `396b9c03dc409375a70028727354e09946081b7bcd54f8a2dbf7c54686eb853b` |
| Integration worker | `km-csit-worker:v1-operator-resume-20261014`；exited／OFF |
| Worker image SHA256 | `da1178eb0994b3eb308ab18ff7d62ed7a0eb8970687ce8340667629d6c94ca53` |
| KM DEV ingestion jobs | 1，狀態 Completed；Accepted=0、Processing=0 |
| Callback delivery rows | Delivered=1、Failed=3；保留歷史紀錄 |

Stopped worker container 仍保有先前 `KM_CSIT_ENABLED=true` 的環境值，但它沒有執行；API 的值為 false。不得將 stopped container 的 env 值解讀為 worker 已 ON。

## 未完成與 Patty 審視重點

- **最新 Integration source 尚未發布：** 本文件補齊進度，不補齊 source release provenance。後續 source review 必須使用經整理的 source/tests/deploy snapshot，保留既有工作，不把整個 dirty tree、資料、DB、secrets 或 runtime evidence 原件直接發布。
- **Processing fix 尚未部署：** source/tests PASS 不等於 live callback 已重測。本輪沒有再 resume 已 Completed job、重送 callback 或建立新 job。
- **Failed callback 缺 `timestamps.failedAt`：** 使用者明確限定只修 Processing，Failed 問題維持另案。Failed regression PASS 只證明原行為未變，不能宣稱 Failed contract 已修。
- **source/build 不在單一路徑：** Control/OIDC 與 integration 的部署來源須整理可重建的 build/source 對照；working-tree HEAD 無法代表 dirty changes 或各部署 image。
- **驗收範圍：** 本次是一筆 DEV integration 流程與已列出測試的證據；不等於完整 Phase 1、所有 GraphRAG/KPI/權限場景或 Production acceptance。

## 證據與本次操作範圍

本次讀取 DGX 的 AGENTS.md、PROJECT_MEMORY.md、Git status、實際 source hash、protected regression/source-runtime records、DEV container metadata，以及 integration DB 的唯讀 status/count。完整歷史 payload、私有文件與 protected 原件維持內部保存；公開文件只保留必要 metadata 與結果。

本次僅發布此進度文件與舊 dossier 的導覽連結。未改 application source、runtime、worker、資料庫、CSIT、Shared Identity、DNS、UniFi 或 Production；未呼叫 business API、建立 job、重送 v3/callback。GitHub 文件 commit 依使用者本次新增授權執行，之前各輪「no commit/push」仍保留為其原始歷史事實。
