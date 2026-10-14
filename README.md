# Patty KM DEV 開發交接

本分支整理 DGX 最新第一方 source，納入 CSIT Integration v1、Human OIDC/passwordless binding、tests、migrations 與可公開重建的 Docker targets。它是開發交接基線，不是 live deployment 或 Production release。

開始前先讀 [交接與重建指南](docs/handoff/PATTY_DEVELOPMENT_HANDOFF.md)。原平台介紹移至 [legacy platform README](docs/handoff/LEGACY_README.md)。

## 快速驗證（新電腦，Docker Engine + Compose v2）

```bash
git clone --branch codex/km-dev-handoff-20261014 --single-branch https://github.com/kyocarlos/knowledge-base-agent-source.git
cd knowledge-base-agent-source
python3 scripts/verify-handoff-source.py
bash scripts/test-csit-handoff.sh
```

此命令建立唯一命名的獨立內部網路與 disposable PostgreSQL/Timescale、Neo4j，只使用測試 fixtures／fake HTTP transport，不連 CSIT 或 live writers；執行後清除該測試專案。

## Disabled API sandbox

```bash
docker compose -p km-patty-sandbox -f deploy/csit-integration-v1/compose.yaml up -d --build --wait
endpoint="$(docker compose -p km-patty-sandbox -f deploy/csit-integration-v1/compose.yaml port api 8000)"
curl "http://$endpoint/health"
docker compose -p km-patty-sandbox -f deploy/csit-integration-v1/compose.yaml down
```

預期 health: `status=ok`、`integrationEnabled=false`。Worker 維持 OFF。本機初始化新的空白 sandbox DB，不會匯入 DGX 的 job/文件/帳號。若要移除 sandbox 資料，僅對此 project 使用 `down --volumes`。

Processing 的 `timestamps.startedAt` 與 Failed 的 `timestamps.failedAt` 修正已包含於本分支，並以 CSIT 固定 commit 的四份 canonical schema 驗證。此版本仍待受控部署與 deployed-runtime 離線驗證。

## Build 驗證補充

API 與 worker 都有 resolved dependency lock；worker 使用 PyTorch 官方 CPU index 的固定 2.13.0，model loader 原本即使用 CPU。已確認該版 CPython 3.12 ARM64／AMD64 wheel 存在，本輪實際建置／測試環境為 DGX ARM64。AMD64 尚未實際執行本輪 suite；CI workflow 可重現。

Worker build／module import PASS 不代表已下載 embedding model 或連外部 writers 做新的 live E2E；model weights、核定 revision、DEV service credential 與 downstream provisioning 仍由接手維運方準備。LangChain 未安裝的訊息來自既有 optional GraphRAG import；本分支 focused pipeline 不使用該 optional 路徑。
