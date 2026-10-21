# Patty 開發交接與重建指南

## 分支與驗證範圍

開發分支：`codex/km-dev-handoff-20261014`。由 `a3f51993ca02bd6c7bccb3112f6b11ea76d7319b` 的既有 review snapshot 整理，納入 DGX working-tree 的第一方 Python／Vue source、DEV Control 容器內的正式 source、最新 Integration v1 與隔離測試。

`docs/handoff/source-origins.json` 保存來源對照；`docs/handoff/source-manifest.json` 保存交付檔案 SHA256。新分支是可 checkout 的開發來源；canonical adoption source commit `45108b1...` 已部署至 DGX 的 KM DEV Integration API 與停止中的 worker image；不代表完整平台、Production 或 Phase 1 全項驗收。詳見 [驗證與部署證據](CSIT_CANONICAL_ADOPTION_20261014.md)。

## 可重建範圍

- Integration API、worker、parser、writers、M2M auth、operator、Processing callback 修正與 migrations。
- Human OIDC、passwordless binding、Control source 及相關測試、前端頁面。
- 公開 Python 基底的 api／test／worker／control build target，不需要 DGX 本機的私有 images。
- 獨立 sandbox PostgreSQL／Timescale、Neo4j 與 test fixture 環境；沒有 live DB、documents、jobs、roles、grants、secrets 或 model cache。

其他既有 KM web／Vue／A2A source 亦保留；本輪完整重跑的是交接 focused suite，不宣稱所有 legacy tests、UI flow、整個既有平台 Compose 或所有外部服務都重新驗收。

## 前置需求

Linux／Docker Desktop Linux containers，Docker Engine 與 Compose v2；建置時可連公開 Python registry／package index。新電腦不需要 DGX 私有 runtime image。首次 worker build 會下載 PyTorch／Sentence Transformers；embedding model 的首次下載與 cache 需另安排。資料庫 image 與 Python image 的驗證版本見 build manifest。

```bash
git clone --branch codex/km-dev-handoff-20261014 --single-branch https://github.com/kyocarlos/knowledge-base-agent-source.git
cd knowledge-base-agent-source
git status --porcelain
python3 scripts/verify-handoff-source.py
bash scripts/test-csit-handoff.sh
```

`git status --porcelain` 應為空。測試 project 使用唯一名稱；DB／graph 無 host ports、網路 internal=true，HTTP auth/document/callback 使用 test transport，不會連 CSIT。測試 schemas、Graph、Timescale 與 storage 都在 disposable sandbox；EXIT trap 清理該 project。

## Disabled API sandbox

```bash
docker compose -p km-patty-sandbox -f deploy/csit-integration-v1/compose.yaml up -d --build --wait
endpoint="$(docker compose -p km-patty-sandbox -f deploy/csit-integration-v1/compose.yaml port api 8000)"
curl "http://$endpoint/health"
docker compose -p km-patty-sandbox -f deploy/csit-integration-v1/compose.yaml down
```

API 僅綁 localhost，預設自動選取空閒 host port，可用 `KM_HANDOFF_API_PORT` 改 port。預設 integration=false、worker 不啟動；metadata migration 僅在新的 sandbox DB 初始化。現有 DGX 的 production／DEV networks、volumes、container names 沒有被引用。

Dev PostgreSQL 的 trust auth 僅供這個無 host DB port 的 sandbox；不是 Production security configuration。保留 sandbox volume 可重開 API；只有確認要移除此專案資料時才加 `down --volumes`。

## Human Control 建置與設定

```bash
docker build -f deploy/csit-integration-v1/Dockerfile --target control -t km-patty-control:dev .
```

Entrypoint: `app.control_main:app`。最少設定 Control DB URL、三種 signing keys、instance public origins；參考 `config/km-control-auth.env.example` 與現有 control-plane templates。預設 OIDC disabled；正式 IdP／client 註冊資料與 secret 由維運方獨立供給，不在 GitHub。

Shared Identity 驗證身分；KM 仍以 `(iss,sub)` + manual approved binding/local grants 決定權限，不以 email 自動 bind、不複製 CSIT role、不提供任意 admin bypass。測試以臨時 SQLite／生成 signing keys 重現授權規則。

## 正式 DEV 設定與 worker

`config/csit-integration-v1.env.example` 僅是空白模板；使用外部受保護檔案，不能把真實 credentials 寫入 repo。

目前正式 DEV 的非秘密 contract：
- CSIT base URL：`https://csit-dev-da40.duckdns.org:7444`。
- Issuer：`https://csit-identity-dev.duckdns.org:7443/`（含尾斜線）。
- inbound audience `km.integration.dev`，allowed client `csit-km-ingestion-dev`，`principal_type=service`，scope `km.ingestion.submit`。
- outbound client `km-csit-integration-dev`，audience `csit.integration.dev`，scopes `csit.document.read csit.ingestion.status.write`。
- canonical contract 用 `project.number / case.number / task.number`，不是 `*.code`。

需要先準備並核定 DEV metadata DB、Qdrant collection/model dimensions、Neo4j database、Timescale DSN、storage root、numeric rules、service secret；確保所有 target 都指向核定 DEV。secret 檔案 0600／parent 0700，容器唯讀 mount。CSIT client credential 仍只留在 CSIT，KM 只持有自己的 outbound client credential。

Worker 建置：
```bash
docker build -f deploy/csit-integration-v1/Dockerfile --target worker -t km-patty-worker:dev .
```

`worker-compose.yaml` 是明確 opt-in overlay，要求外部 DEV settings／secret paths；預設 sandbox 不讀它。只有另行核定後才可 `--profile worker` 啟動；維持單一 worker。API 的 sandbox enabled=false 固定 gate 不應當作正式 DEV ingress；正式接入需以核定設定另行部署 API。本交接不提供 live job/retry 的自動執行命令。

Operator wrapper `scripts/csit-integration-operator.py` 依 SSH/Unix identity 對受保護 mapping 檔案映射至既有 KM admin，Repository backend 再驗 active/admin、identity、job state，以 atomic transaction/audit 執行 resume。這是特權管理能力，不是公開 HTTP/M2M route。新電腦不能沿用 DGX 的 mapping 或帳號資料；不要對已 Completed job 再 resume。

## 已知事項與接手優先順序

1. Processing 的 required `timestamps.startedAt` source 修正包含於分支，值取當次 Processing transition timestamp；此 fix 已進入 2026-10-14 的 KM DEV API image；實際 container 的離線 canonical 驗證 PASS。
2. 本次 canonical adoption 已在 source 加入 Failed callback required `timestamps.failedAt`，取值為 `last_error_at` 的真實 failure transition time；此 fix 已進入 KM DEV API/worker image；離線 canonical 驗證 PASS。新的 Live E2E 尚未執行。
3. 既有真實 v3 job 已 Completed，Completed callback 204；historical Processing callback 400 與舊 Failed callback rows 保留。不得用重送已 Completed job 驗證新 source。
4. graph／numeric writer 有隔離測試；真實那筆文件無 entities／recognized KPI，Neo4j／Timescale live 該筆為 N/A，不能宣稱所有 business 場景驗收。
5. 先跑 clean checkout regression／disabled API health；再整理對實際 DEV 的 deployment/rollback plan；Human OIDC 真正登入與 live integration 都須另行規劃 controlled acceptance。
6. 歷史進度文件保留原本當時的 source-stale 描述；本分支補齊開發 source，不追溯更改舊文件的歷史驗收事實。以本交接 manifest／commit 作新開發基線。

## 安全與資料邊界

本分支排除 runtime env、password/token/private key、private DB、原始或 parsed 文件、job-ledger、callback 原始 logs、protected evidence、pycache、backup source 與 celery state。設定 examples 不含真實秘密；tests 中固定字串／生成 JWT 均僅為測試 fixtures。

不要將整個 DGX working tree 直接 stage；它仍有其他工作、歷史資料與未整理檔。這次在獨立 checkout 整理／驗證／發布，原 source、runtime、job data 與 Production 未改。

## Build 驗證補充

API 與 worker 都有 resolved dependency lock；worker 使用 PyTorch 官方 CPU index 的固定 2.13.0，model loader 原本即使用 CPU。已確認該版 CPython 3.12 ARM64／AMD64 wheel 存在，本輪實際建置／測試環境為 DGX ARM64。AMD64 尚未實際執行本輪 suite；CI workflow 可重現。

Worker build／module import PASS 不代表已下載 embedding model 或連外部 writers 做新的 live E2E；model weights、核定 revision、DEV service credential 與 downstream provisioning 仍由接手維運方準備。LangChain 未安裝的訊息來自既有 optional GraphRAG import；本分支 focused pipeline 不使用該 optional 路徑。
