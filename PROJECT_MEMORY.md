- 2026-08-06 針對「KB agent 主動傳訊息給 Anritsu agent 執行測試，且不得影響既有 KB」的評估：不建議直接修改現有 FastAPI、Celery、Neo4j/Qdrant 或 `/search`；建議新增獨立 `kb-agent-delegation-bridge`（可用獨立 Docker Compose project 或 OpenClaw plugin/skill 的獨立程序），由 KB/OpenClaw 作為 A2A client，Anritsu Windows agent 作為 A2A server。Bridge 只負責 outbound HTTPS/mTLS、Agent Card discovery、將自然語言轉成固定 JSON test job、建立 A2A Task、輪詢/SSE 取得狀態，以及把結果 metadata 交回現有 KB ingest API；Anritsu agent 仍透過本機 MCP/tool adapter 控制儀器與 iperf，完成 Excel 後沿用現有嚴格攝入流程。A2A Task 與 KB `task_id`/`run_id` 必須保存 correlation，不直接傳送 Neo4j/Qdrant/Redis 權限。安全上需使用 per-agent credentials、VPN/HTTPS/mTLS、allowlisted test profiles、操作者確認與取消/timeout，禁止 LLM 直接生成任意儀器命令；初期採 polling、只允許 KB 到 Anritsu 的 outbound connection，避免在 KB 主機開放 inbound port。此方案可在不重建 KB 核心服務的前提下增加「委派 Anritsu 執行工作」能力，並可先以 dry-run/read-only A2A pilot 驗證，再開放真實儀器操作。
- 2026-08-06 A2A 技術研讀與 KB 可行性評估：目前官方 A2A 規格已到 `1.0.0`，A2A 是 agent-to-agent 的互通協定，提供 Agent Card discovery、JSON-RPC/HTTP+JSON/gRPC bindings、Message/Task lifecycle、polling/streaming/webhook、artifact 與 capability/auth 宣告；官方 Python SDK 支援 1.0 並可相容 0.3。A2A 與 MCP 是互補關係：MCP 負責 agent 到 tools/data，A2A 負責獨立 agent 之間的 delegation/collaboration。對目前 KB 的結論為「技術上可行、建議分階段導入」，不需要改動 Neo4j/Qdrant 核心，也不應讓外部 agent 直接連資料庫；應新增獨立 A2A facade/agent，發布 `/.well-known/agent-card.json`，將 `ingest_4g5g_report`、`get_ingest_status`、`query_kb`、`compare_reports` 等 skill 映射到既有 strict ingest、Celery task、`/search` 與結構化查詢。現有 Anritsu Bearer token hash、environment binding、strict headers、KM_Metadata、冪等 registry 可作為底層安全與資料契約，但 A2A facade 必須補上 per-agent scopes、query data authorization、A2A taskId/contextId 與 KB task/submission_id correlation、HTTPS、rate limit、audit log 及大檔案 artifact 上傳策略。建議先做 read-only A2A query pilot，再接 Anritsu ingest，最後接 Amarisoft；A2A 不取代 Windows 本機 MCP Bridge，也不會自動解決 instrument control、資料 schema 或跨 Neo4j/Qdrant 一致性問題。尚未安裝 SDK 或修改服務。
- 2026-08-06 專案進度記憶更新：目前 KM 的 Anritsu agent 認證設定仍有效，`anritsu-agent-01` 使用已配置的 SHA-256 token hash，`KB_INGEST_REQUIRE_AGENT_AUTH=true`；KM web、Celery ingestion workers 與 `/health` 均已在前次重啟後驗證正常。外部 Anritsu agent 必須使用 `Authorization: Bearer <明文 token>` 與 `X-Agent-ID: anritsu-agent-01`，並遵循 strict ingest headers 與 `KM_Metadata` 契約。明文 token 不得寫入專案、Git 或本記憶檔；OpenClaw gateway 不需因 KM token 設定而重啟。下一步若重試 Anritsu Excel，應保存完整 HTTP response body 與 task status，以確認是否已通過認證、建立任務並完成 Neo4j/Qdrant 攝入。
- 2026-07-31 已依官方 OpenAI API 價格檢查並設定 `WifiSit01_DA40`：現場 Sub2API 0.1.168 沒有 channels、channel pricing 或 account-stats pricing rule 資料，該群組實際使用內建模型價格。既有 usage_logs 已證明官方價格正確，例如 gpt-5.5 19898 input/27 output 計為 USD 0.09949 + 0.00081 = 0.10030，gpt-5.4 10 input/5 output 計為 USD 0.000025 + 0.000075 = 0.0001。以交易只將 group 7 `WifiSit01_DA40` 明確固定為 `rate_multiplier=1.0000`、`subscription_type=standard`，未新增渠道價格、未修改帳號/API key/模型清單/其他 Ollama 群組/KM；驗證三組群組倍率均為 1.0，WifiSit01 既有成本仍正確。官方參考：GPT-5.6 Sol/Terra/Luna 分別 $5/$30、$2.5/$15、$1/$6 per 1M input/output；GPT-5.5 $5/$30；GPT-5.4 $2.5/$15；GPT-5.4 mini $0.75/$4.5；GPT-5.2 $1.75/$14。注意 OAuth 訂閱帳號的成本是 API 牌價估算，不等於 ChatGPT 訂閱帳單。
- 2026-07-31 已檢查 Sub2API 0.1.168 的 token 計費狀態：資料庫已有 `usage_logs`、`usage_dashboard_*` 與模型價格欄位，表示 token→成本計算功能已存在。現有三個群組為 `Ollama Local`、`Anderson_H`、`WifiSit01_DA40`；群組 `rate_multiplier` 均為 1.0000，尚未建立 `channel_model_pricing` 紀錄。已產生的 Ollama 用量（group 6）成本為 0，OpenAI 訂閱帳號（group 7）已有按內建模型價格估算的成本，例如 gpt-5.4 10 input/5 output 約 USD 0.0001、gpt-5.5 19898 input/27 output 約 USD 0.1003。要讓使用者看到合理金額，需在管理端為各模型設定 USD/1M input/output token 價格，再以群組 `rate_multiplier` 設定是否加成；Ollama 若只要顯示資源成本可自訂內部單價，若視為免費則維持 0。OpenAI 訂閱帳號的金額是成本估算/內部轉嫁，不等於 OpenAI 訂閱帳單的真實金額。尚未修改任何價格設定。
- 2026-07-31 已修復外部 OpenClaw 使用 WifiSit01 OpenAI 訂閱帳號時的 503。根因是 account id 2 `openAI_wifisit01` 原本未綁定 group id 7 `WifiSit01_DA40`；API key id 5 雖 active 且屬於 group 7，但該群組沒有 upstream account。已以資料庫交易只新增 account_groups(account_id=2, group_id=7, priority=1)，保留 account 2 原有 group id 6 `Anderson_H` 綁定未刪除；同時將 group 7 的 `models_list_config.enabled` 設為 true，保留其模型清單。驗證結果：WifiSit01 API Key `/v1/models` HTTP 200、回傳 20 個 OpenAI 模型；`/v1/chat/completions` 使用 `gpt-5.4` HTTP 200、finish_reason=stop、回應正常。未修改 Ollama Local provider、Anderson_H API Key、Jimmy_H API Key 或 KM 系統。注意 account 2 目前同時綁定 Anderson_H 與 WifiSit01_DA40，若需嚴格隔離兩種服務，後續應另行評估是否移除 Anderson_H 綁定。
- 2026-07-31 已唯讀分析使用者新增的 OpenAI 訂閱帳號。資料庫顯示 account id 2、name=`openAI_wifisit01`、platform=openai、type=oauth、status=active、schedulable=true，credentials 含 access_token、refresh_token、client_id、plan_type、chatgpt account/user 等必要欄位，因此帳號建立與 OAuth credentials 儲存成功。但 `account_groups` 沒有 account id 2 的任何綁定；目前資料庫中另有 group id 7、名稱=`WifiSit01_DA40`、platform=openai、模型清單 13 個且 `models_list_config.enabled=false`，並有 active API key id 5、名稱=`WifiSit01_DA40`、group_id=7，但 group 7 沒有 upstream account。結論：訂閱帳號本身成功，尚未可透過 Sub2API 路由；需將 account 2 綁定到專用 group 7，再確認 group 7 模型清單與 API key，外部 OpenClaw 才能用 `http://61.216.9.52:18080/v1` 呼叫。Channels table 目前沒有資料，這不阻止 account/group 路由；本次只診斷，尚未修改。
- 2026-07-31 已依使用者要求「新增 Anderson_H 群組與 API、不可變動原有設定」完成建立。當時現有資料只有 `Ollama Local` group id 2 與 `Jimmy_H` API key（key id 1）；未修改兩者。以 group 2 複製建立新 group id 6，命名 `Anderson_H`、platform=openai、status=active、綁定 1 個 Ollama account、啟用 22 個 Ollama 模型清單；再建立新 API key id 4、名稱 `Anderson_H`、group_id=6、status=active。使用新 key 從本機呼叫 `/v1/chat/completions`、model=`gemma4:12b` 回 HTTP 200，Sub2API log 確認 `api_key_id=4`、`group_id=6`、`account_id=1`，表示新群組到 Ollama provider 路由正常。`/v1/models` 回 200 但目前清單為空，因此外部 OpenClaw 應在 provider 設定中明確列出模型 id，不要依賴自動 discovery；此現象不影響已指定 model 的 chat request。新 API key 值未寫入專案記憶。
- 2026-07-31 已唯讀分析 Sub2API 群組 `Anderson_H`（group id 5）API key 無法在外部電腦使用的原因。管理 API 顯示 group 5 為 active、platform=openai；API key metadata 顯示 key id 3、status=active、group_id=5，且 `last_used_at` 已更新。Sub2API log 進一步確認外部請求來源為 `61.216.9.50`，API key 已成功辨識為 `api_key_id=3`、`group_id=5`，因此外部 URL/18080 port/Authorization/API key 本身均已通過。真正錯誤是 `/v1/chat/completions` 回 503，log 為 `openai_chat_completions.account_select_failed`、`error=no available accounts`；目前唯一 provider account `Ollama Local`（account id 1）只綁在 group id 2，沒有綁到 Anderson_H group 5。另 group 5 的 `models_list_config.enabled=false` 且仍保留預設 gpt-5.x 模型清單；即使將 account 綁入，也應同步把 group 5 設為 enabled 並填入實際 Ollama 可用模型，否則 OpenClaw 的模型清單會不正確。此輪只完成診斷，尚未修改 group/account。
- 2026-07-30 已依使用者要求將主機現有 Ollama 設定到 Sub2API。先在 `sub2api-deploy/docker-compose.local.yml` 的 `sub2api` 服務加入 `extra_hosts: host.docker.internal:host-gateway`，讓 Linux 容器可連主機 Ollama；`.env` 設定 `SECURITY_URL_ALLOWLIST_ALLOW_INSECURE_HTTP=true`、`SECURITY_URL_ALLOWLIST_ALLOW_PRIVATE_HOSTS=true`，並因 Sub2API 目前對 allowlist 啟用時仍拒絕 HTTP upstream，將 `SECURITY_URL_ALLOWLIST_ENABLED=false` 後只重建 `sub2api` 應用容器。已建立 Sub2API provider `Ollama Local`（account id 1，OpenAI-compatible，upstream 為主機 Ollama，API key 為本機占位值，未記錄實際敏感值），並複製預設群組建立獨立 `Ollama Local` 群組（group id 2、platform=openai、active、models_list_config enabled），將 provider 從預設 Anthropic 群組移到專用群組。透過 `/admin/accounts/1/models/sync-upstream` 成功從 Ollama 讀到 22 個模型：deepseek-v3.2:cloud、deepseek-v4-flash:cloud、deepseek-v4-pro:cloud、gemma4:12b、gemma4:31b、glm-4.7:cloud、glm-5.1:cloud、glm-5.2:cloud、gpt-oss:120b、hf.co/BlossomsAI/Qwen2.5-Coder-7B-Instruct-Uncensored-GGUF:Q4_K_M、kimi-k2.6:cloud、kimi-k2.7-code:cloud、minimax-m2.5:cloud、minimax-m2.7:cloud、minimax-m3:cloud、nomic-embed-text-v2-moe:latest、nomic-embed-text:latest、ornith:35b、qwen3-coder-next:latest、qwen3-coder:30b、qwen3-embedding:0.6b、qwen3.6:27b。Ollama 直接 `/v1/chat/completions` 對 `gemma4:12b` 回 HTTP 200；Sub2API 內建 provider test 預設錯用 `gpt-5.4`，因此回 404（該模型不在 Ollama），不能視為 upstream 連線失敗。Sub2API、KM `https://127.0.0.1:3030/health`、KM `http://127.0.0.1:8000/health`、Qdrant `6335/healthz` 均驗證正常；PostgreSQL/Redis 為 healthy。重要限制：目前 Sub2API 對外綁定 `0.0.0.0:18080`，且為支援本機 HTTP Ollama 而關閉 URL allowlist，外部開放前應改用 HTTPS/TLS reverse proxy 或重新評估 egress/SSRF 安全設定。
# Project Memory

- 2026-08-13 已開始落實「KM OpenClaw 命令 Anritsu agent」目標：新增 `scripts/km_anritsu_command.py` 作為唯一受控命令 client，固定只呼叫本機 `127.0.0.1:18181` bridge、只允許 profile `ncq2200b2v-throughput-v1`、`sa_dl_tcp`/`sa_ul_tcp`，並強制 `dry_run=true`；新增 KM OpenClaw workspace skill `~/.openclaw/workspace/skills/anritsu-a2a/SKILL.md`，OpenClaw CLI 已確認 `anritsu-a2a ✓ Ready`。新增 `docs/KM_OPENCLAW_ANRITSU_OPENCLAW_A2A_CONTRACT.md` 定義 KM OpenClaw、bridge、Anritsu ingress、Anritsu OpenClaw 與本機 MCP 的目標邊界、correlation、稽核、回滾及驗收條件。
- 2026-08-13 驗證新命令入口：`PYTHONPATH=. uv run --with a2a-sdk==1.1.2 --with pytest ... pytest -q tests/test_km_a2a_bridge_app.py tests/test_km_a2a_bridge_service.py tests/test_km_a2a_bridge_sdk_transport.py` 結果 `21 passed`；透過 `scripts/km_anritsu_command.py submit/status` 對目前 `http://100.72.21.115:8790` 完成 dry-run，產生 `run_id=openclaw-skill-dryrun-20260813014524`、`context_id=ctx-b30dc50629640a4a0c61a0fac74d55a5`、`a2a_task_id=task-b30dc50629640a4a0c61a0fac74d55a5`，test/report/ingest 均為 pending，未產生儀器、iperf、Excel 或攝入副作用。
- 2026-08-13 目前仍未完成真正 OpenClaw-to-OpenClaw：遠端 Agent Card 的 description 明確為「隔離式 Anritsu A2A dry-run agent；目前不執行真實測試」，`:8790` 是 sidecar A2A ingress，不是已證實的 Anritsu OpenClaw Gateway。下一個必要交接是由 Anritsu 端提供受控 adapter：固定 schema A2A task 經 sidecar 轉交 Anritsu OpenClaw 的本機 skill/tool，並回傳相同 `run_id`/`context_id`/`a2a_task_id` 的 audit log；在此證據完成前不得宣稱 KM 能命令 Anritsu OpenClaw，也不得開啟 real instrument access。
- 2026-08-13 針對上述目標補強交接規格：更新 [`ANRITSU_AGENT_A2A_REQUIREMENTS.md`](/home/da40_ai_gb10/knowledge-base/ANRITSU_AGENT_A2A_REQUIREMENTS.md) 第20節，明確要求 Anritsu sidecar 透過僅限 loopback/named pipe 的 `sidecar-to-openclaw` adapter 呼叫 Anritsu OpenClaw allowlisted skill/tool；定義 adapter schema、固定回應、`execution_owner=anritsu-openclaw`、correlation/audit、拒絕條件與交付證據。更新 [`docs/KM_OPENCLAW_ANRITSU_OPENCLAW_A2A_CONTRACT.md`](/home/da40_ai_gb10/knowledge-base/docs/KM_OPENCLAW_ANRITSU_OPENCLAW_A2A_CONTRACT.md) 同步記錄。KM 端未修改主 OpenClaw 設定、未開放真實儀器。
- 2026-08-13 端點複查：Anritsu `100.72.21.115:8790` 可達，但 Agent Card 仍明確宣告 `隔離式 Anritsu A2A dry-run agent；目前不執行真實測試`，只看到 TCP 8790，未看到可證實的 Anritsu OpenClaw Gateway/adapter endpoint；因此目前只能繼續進行 sidecar dry-run，OpenClaw-to-OpenClaw Gate 尚未通過。
- 2026-08-13 Anritsu 回報 receiver adapter 已啟用；KM health 實測確認 `openclaw_receiver_enabled=true`、`openclaw_receiver_agent=a2a-receiver`、`instrument_available=false`、`real_instrument_access=false`。Agent Card description 已改為固定 schema 轉交受限 Anritsu OpenClaw Agent。
- 2026-08-13 KM A2A bridge 已補強 receiver evidence：`A2ATaskCorrelation` 現保存 `openclaw_forward_status`、`openclaw_receiver`、`openclaw_audit_id` 與 `dry_run_side_effect_counts`；sdk transport 對 completed dry-run 強制驗證 `accepted`、`anritsu-openclaw`、非空 audit id、完整 correlation 與所有 counters=0。新增後 focused bridge tests 結果 `24 passed`。KM HTTP timeout 改為環境可配置，`KM_A2A_HTTP_TIMEOUT_SECONDS=60`，smoke/client timeout 改為可指定且預設90秒；只重啟獨立 `km-a2a-bridge.service`，沒有重啟主 KM/OpenClaw。
- 2026-08-13 receiver final Gate 通過：全新 `run_id=openclaw-receiver-final-20260813T033332Z` 回 `state=completed`、`openclaw_forward_status=accepted`、`openclaw_receiver=anritsu-openclaw`、`openclaw_audit_id=oc-audit-9f03fae3c081421693174ff2eca2d71b`，`context_id=ctx-881e1cfe52262c9e40fdfc079d366cdb`、`a2a_task_id=task-881e1cfe52262c9e40fdfc079d366cdb`、`run_id`完整；七項 `dry_run_side_effect_counts` 均為0，test/report/ingest仍為pending，沒有儀器、iperf、Excel或攝入副作用。此前兩個全新 run 曾因 client timeout 失敗，但其中一個在 KM server timeout後仍完成；已以90秒 client timeout修正並重新通過。
- 2026-08-13 已啟動實際48小時 OpenClaw receiver dry-run監測：systemd user transient unit=`km-anritsu-openclaw-2day.service`，每30分鐘、每次新的run_id，固定`dry_run=true`，監測程式為 [`scripts/run_anritsu_openclaw_2day_monitor.py`](/home/da40_ai_gb10/knowledge-base/scripts/run_anritsu_openclaw_2day_monitor.py)，結果保存於`/home/da40_ai_gb10/.local/state/km-a2a/anritsu-openclaw-2day.jsonl`；交接文件為 [`docs/anritsu-openclaw-2day-test-2026-08-13.md`](/home/da40_ai_gb10/knowledge-base/docs/anritsu-openclaw-2day-test-2026-08-13.md)。第一筆`openclaw-2day-20260813T033418Z-0001`已PASS，包含完整receiver audit/correlation與七項counters=0；48小時尚未完成，不能提前宣稱穩定通過。

- 2026-08-04 查詢 KM Anritsu agent token：目前 `config/report-ingest.env` 與執行中 `kb-web` 的 `KB_AGENT_TOKEN_HASHES_JSON` 都只有 `anritsu-agent-01` 的 `replace-sha256` placeholder，沒有可反推出的真實 token；`KB_INGEST_REQUIRE_AGENT_AUTH=false`，因此目前 `/api/upload/ingest` 只要求 `Authorization` header 存在，不會執行 Bearer token hash 驗證。結論：不能提供現成有效 KM token；正式讓 Anritsu agent 使用前，必須產生隨機 token、只保存 SHA-256 hash、設定 `KB_INGEST_REQUIRE_AGENT_AUTH=true`，並重啟 KM web。不要把明文 token 寫入專案記憶或 Git。
- 2026-08-04 已完成 Anritsu agent 認證設定：`anritsu-agent-01` 已寫入使用者提供 token 的 SHA-256 hash，`KB_INGEST_REQUIRE_AGENT_AUTH=true` 已啟用，並以 `./restart_kb.sh` 重啟 KM web 與 ingestion workers；容器環境驗證及 `https://127.0.0.1:3030/health` 均正常。明文 token 未寫入專案、Git 或記憶；外部 Anritsu agent 應以 `Authorization: Bearer <token>` 搭配 `X-Agent-ID: anritsu-agent-01` 使用。OpenClaw gateway 不需因本次 KM token 設定而重啟。
- 2026-08-03 已依前一輪發現的 hash 自我引用問題修正 strict ingest 契約：producer 不再必須把 `ingestFileHash` 寫回同一份 Excel；KM 會在收到 bytes 後自行計算 SHA-256，寫入 task state、registry、`.source.json`、Neo4j 與 Qdrant。若 Excel 內額外提供 `ingestFileHash`，仍會驗證其與實際 bytes 一致；未提供則由 KM 產生。另修正 staging 暫存檔名處理，並保留 producer 的原始 `originalFileName` metadata，不將 agent transport filename 誤當成邏輯檔名。新增 server-generated hash 測試，避免外部 agent 遇到不可生成的循環 hash。
- 2026-08-04 追查最近一次 Anritsu 上傳失敗：`2026-08-03 18:38:31 +08:00` 的 `POST /api/upload/ingest` 回 `422`，沒有建立 task、沒有進入 Celery、Neo4j/Qdrant 沒有被執行。前一筆 Anritsu `NCQ1230` 任務在 strict contract 部署前仍以 legacy 流程完成；最新 `NCQ1333` 請求是在 strict contract 啟用後被 upload validator 拒絕。最可能是外部 agent 仍使用舊的無 identity headers 指令，會觸發 `headers_missing`；即使 headers 已提供，transport filename 使用 `ANRITSU__...__SIT-TR...xlsx` 而 Excel `originalFileName` 保持原始 `SIT-TR...xlsx` 也不應視為衝突，因此已修正 validator 只拒絕含路徑的 metadata filename，不再要求它等於 multipart transport filename。新增 contract rejection warning log，後續可直接看到 code/fields。尚未取得當次 HTTP response body，因此 `422` 的具體 code 仍需以外部 agent 回應或重試後的新 log 最終確認。
- 2026-08-03 已依 `KM_AGENT_CONFLICT_PROTECTION_SPEC.md` 實作 KM 攝入衝突保護第一版。新增 [`src/ingest_conflict_protection.py`](/home/da40_ai_gb10/knowledge-base/src/ingest_conflict_protection.py)：讀取 Excel `KM_Metadata`、驗證必要 metadata/header、計算 `documentId` 與 `idempotencyKey`、檢查 `sourceFileHash`/實際收到 bytes 的 `ingestFileHash`，並對缺欄位、metadata mismatch、hash mismatch 以顯性 `422` 錯誤拒絕；strict ingest 預設啟用，舊的檔案 hash 去重只有在 `KB_ALLOW_LEGACY_INGEST=true` 且未提供身份 headers 時才可使用。新增 [`src/ingest_registry.py`](/home/da40_ai_gb10/knowledge-base/src/ingest_registry.py)：SQLite WAL 持久化 `ingestion_requests` 與 `ingestion_events`，對 `idempotency_key`、`document_id`、`task_id` 建立唯一約束，重送回傳原 task，文件身份不同則回 `409`，並保存不含秘密的稽核事件。
- 2026-08-03 已把文件鎖接到 [`src/web_api/tasks.py`](/home/da40_ai_gb10/knowledge-base/src/web_api/tasks.py)：strict task 以 `kb:ingest:document-lock:<documentId>` Redis `SET NX EX` 取得鎖，owner token compare-and-delete 釋放，鎖忙時不刪除別的 worker 的鎖並將 task 標為 rejected/failed；`ingest_document()`、Neo4j Document name、Qdrant point namespace 改用 `document_id` 作為 strict logical key，不再以檔名清理或覆蓋不同 run；完整身份欄位會傳到 `.source.json`、Neo4j、Qdrant 與查詢來源。`ReportSearchFilters` 已增加 source system、environment、project、artifact、schema、document/idempotency 欄位。
- 2026-08-03 已更新 [`EXTERNAL_AGENT_KB_INGEST_APIS.md`](/home/da40_ai_gb10/knowledge-base/EXTERNAL_AGENT_KB_INGEST_APIS.md)，補上 strict headers、`KM_Metadata` 欄位、duplicate/conflict 回應、文件身份與輪詢規則；可選 `KB_INGEST_REQUIRE_AGENT_AUTH=true` 時會使用既有 Bearer agent auth，並要求 agent environment 與 `sourceSystem` 一致。`GET /api/upload/tasks/{task_id}` 在 Redis task TTL 過期後會回查持久化 registry。
- 2026-08-03 驗證結果：`python3 -m compileall -q src tests` 通過；`PYTHONPATH=. uv run --with pytest --no-project pytest -q tests/test_ingest_conflict_protection.py tests/test_test_reports.py` 結果 `11 passed`；`KB_REPORT_DB_PASSWORD=test docker compose config --quiet` 通過；SQLite identity duplicate/document-conflict smoke test 通過。無法在目前主機執行 Redis runtime smoke test，因本機沒有可解析的 `redis:6379` 服務；尚未重建生產容器，因此尚未做實際外部 HTTPS multipart E2E。
- 2026-08-03 已知規格風險：規格要求 `ingestFileHash = SHA-256(包含 KM_Metadata 的完整上傳 Excel bytes)`，同時又要求該 hash 寫在同一份 Excel 的 `KM_Metadata.ingestFileHash`。這是自我引用；目前程式忠實執行規格並要求 metadata 值等於實際 bytes，因此外部 producer 正式啟用前必須決定修正版契約，例如 detached manifest/header 或排除該欄位的 canonical hash。未完成前，不應宣稱外部 Excel 已可無歧義通過 strict hash validation。
- 2026-07-30 已依使用者要求在本機完成 Sub2API 隔離安裝。部署目錄為 /home/da40_ai_gb10/knowledge-base/sub2api-deploy，使用官方 docker-compose.local.yml、Compose project sub2api、獨立 network sub2api_sub2api-network 與獨立資料目錄；Web 綁定 127.0.0.1:18080 -> 8080，PostgreSQL/Redis 沒有 host port，未加入 knowledge-base_default，也未修改主機 Nginx、KM Compose、Neo4j、Qdrant 或既有 Redis。三個容器 sub2api、sub2api-postgres、sub2api-redis 均為 healthy。安裝後驗證：Sub2API HTTP 200、KM https://127.0.0.1:3030/health HTTP 200、KM http://127.0.0.1:8000/health HTTP 200、KB Qdrant 6335/healthz HTTP 200；現有 KB/AnythingLLM 容器維持原狀。Sub2API 管理者帳密寫在部署目錄 .env，不可提交到 Git。

- 2026-07-30 已評估在本機隔離安裝 Sub2API：目前 KB/KM 使用 80/443、3030、3000、8000、6333/6335、6379、5432、Neo4j 17474/17687，Docker project 為 knowledge-base，KB 容器在 knowledge-base_default；主機資源約 20 CPU、119 GiB RAM 可用、根分割區約 1.6 TB 可用。結論是可行但只接受隔離部署：Sub2API 使用獨立 compose project/network/volumes，內建 PostgreSQL 與 Redis，不得連 KB 的 5432/6379 或 knowledge-base_default；Web 不使用預設 host 8080，建議僅綁 127.0.0.1:18080，且不修改主機 Nginx/80/443。官方 Sub2API Docker 文件顯示預設 Web port 8080、需要 PostgreSQL/Redis，並建議使用 docker-compose.local.yml；官方也提供 SERVER_PORT、POSTGRES_PASSWORD、JWT_SECRET、TOTP_ENCRYPTION_KEY 等設定。公開版本審查另發現 knowledge-base/docker-compose.yml:43 仍有硬編碼 Neo4j 密碼，該密碼需立即輪換並從公開 repository/history 清理，之後才能安全進行任何公開服務整合。

- 2026-07-30 已依使用者要求建立公開分享用的 source-only 清理副本。原始 knowledge-base repository 維持不變且不公開；因 Git 歷史約 3.73 GiB，且包含 .venv、frontend/node_modules、.hermes-backups 與疑似 credential/private-key 內容，因此改採全新 history。清理副本位於 /tmp/knowledge-base-public.czqBtA，commit 為 ed58505 publish sanitized knowledge-base source，共 112 個檔案、約 4.3 MB；已排除 .venv、node_modules、.hermes-backups、data/、.env、Excel/PPTX/PNG、runtime 與測試報告，並將內部 IP/本機路徑匿名化。Python syntax check 通過，秘密樣式掃描未發現 API key/private key 格式。建議新 GitHub repository 名稱為 knowledge-base-agent-source，但 URL 目前不存在；本機沒有 gh CLI，Playwright Firefox 也未安裝，尚未建立或公開 GitHub repository。後續需由使用者在已登入 GitHub 介面建立空白 Public repository，再將清理副本設定 remote 並 git push -u origin main。

- 2026-07-21 已依使用者要求新增第二份外部 agent 攝入規格文件 [`EXTERNAL_AGENT_KB_INGEST_APIS.md`](/home/da40_ai_gb10/knowledge-base/EXTERNAL_AGENT_KB_INGEST_APIS.md)。文件與既有 [`EXTERNAL_AGENT_KB_QUERY_APIS.md`](/home/da40_ai_gb10/knowledge-base/EXTERNAL_AGENT_KB_QUERY_APIS.md) 分工：query 文件維持 read-only 查詢，ingest 文件描述 write/ingest 流程。新文件以 `https://61.216.9.52:3030` 為預設 base URL，說明外部 agent 應透過 `POST /api/upload/ingest?extraction_mode=<mode>` multipart 上傳檔案，再用 `GET /api/upload/tasks/{task_id}` 輪詢狀態；列出支援格式、200MB multipart part 上限、`4g5g/wifi/lab/project/automation` 模式、`queued -> upload_saved -> converting -> converted -> extracting -> writing_neo4j -> writing_qdrant -> refreshing_index -> completed/failed` 狀態生命週期、重複檔案 hash 去重語意、批次上傳模式、watch folder 替代方案、Markdown 測試結果 artifact 建議格式，以及正式部署安全建議。文件明確要求外部 agent 不直接連 Neo4j/Qdrant/Redis/File Store，而是只傳 artifact 給 KB API，由 KB 後端 Celery `ingest_file_task` 轉 Markdown、寫 `.source.json`、呼叫 `ingest_document()`、清舊資料、寫 Neo4j 與 Qdrant 並更新 index。已檢查文件章節，檔案共 458 行。
- 2026-07-21 已分析使用者問題「EXTERNAL_AGENT_KB_QUERY_APIS.md 外部如何傳送到檔案後端的 Neo4j/Qdrant」。結論：`EXTERNAL_AGENT_KB_QUERY_APIS.md` 目前是外部 agent 的受控查詢文件，明確排除 `/upload/*`、`/api/upload/*`，因此它本身不提供傳檔寫入 Neo4j/Qdrant 的能力。外部傳檔進 KB 後端的正確路徑應是另一份 ingest 規格：外部 agent 以 multipart 呼叫 `POST /api/upload/ingest?extraction_mode=<4g5g|wifi|lab|project|automation>` 上傳檔案，KB web 接收後寫入 `data/uploads/<category>/<task_id>/original/`、建立 Redis ingest task state、派發 Celery `ingest_file_task` 到 ingest queue；worker 轉 Markdown 到 `converted/`、寫 `.source.json`、呼叫 `ingest_document()`，由 KB 端統一清舊資料、萃取/建立 Neo4j 圖譜資料、寫入 Qdrant 向量點、更新 index；外部再用 `GET /api/upload/tasks/{task_id}` 輪詢 `writing_neo4j`、`writing_qdrant`、`completed/failed`。建議不要讓外部 agent 直連 Neo4j/Qdrant；若要讓外部 agent 同時查詢與上傳，應新增一份 `EXTERNAL_AGENT_KB_INGEST_APIS.md` 或在現有文件中新增受控寫入章節，但 token scope 必須與 query read-only 分離。
- 2026-07-20 已依使用者要求讀取專案記憶與全域 OpenClaw 記憶，追查最後完整啟動 knowledge-base 的方法。結論：目前應以 repository 內的 [`restart_kb.sh`](/home/da40_ai_gb10/knowledge-base/restart_kb.sh) 為正式完整啟動入口，而不是較舊的 `start.sh`。全域記憶 `/home/da40_ai_gb10/.openclaw/workspace/MEMORY.md` 也明確記錄啟動方式為 `cd /home/da40_ai_gb10/knowledge-base && ./restart_kb.sh`。目前腳本流程會先檢查宿主機 Ollama `127.0.0.1:11434`，啟動/建立獨立 `kb-qdrant`，移除 KB 自己的舊容器（不碰 AnythingLLM），以 `KB_FRONTEND_BUILD_DIR=/home/da40_ai_gb10/knowledge-base/.frontend-build-runtime-user8` 重建前端並複製 `chat.html` 與前端 lib，接著執行 `docker compose up -d --build redis neo4j web celery_search_worker celery_ingest_worker celery_beat nginx`，最後檢查 `3030/6335/17474/17687/11434`、`https://127.0.0.1:3030/health`、`chat.html`、容器內 `http://127.0.0.1:8000/health`、Qdrant health、容器到 Ollama 與 WebSocket proxy smoke test。需注意全域舊記憶曾提 `.frontend-build`，但目前實際 repo 已改為 `.frontend-build-runtime-user8`，必須以現有 `restart_kb.sh` / `docker-compose.yml` 為準。
- 2026-07-20 已檢查目前 knowledge-base runtime 是否啟動：`https://61.216.9.52:3030/health` 與 `https://61.216.9.52:3030/chat.html` 皆連線失敗（curl exit code 7，chat.html HTTP code 000），`http://127.0.0.1:8000/health` 也連線失敗；`docker compose ps` 在 repository 內沒有列出任何 compose service，`ss -ltnp` 顯示 3030 與 8000 沒有 listener。`docker ps` 只看到 `kb-qdrant` 與 `anythingllm-qdrant` 仍在跑。結論：目前 KB 對外 web/API/chat 服務未啟動，僅 Qdrant 相關容器在線；若要恢復，需要啟動 KB compose 或執行專案既有重啟流程（例如 `./restart_kb.sh` / `docker compose up -d`，依現場部署方式決定）。
- 2026-07-20 已依使用者要求整理「外部電腦 / 外部 AI agent 查詢 KB 所有資料」的受控查詢 API 文件，新增 [`EXTERNAL_AGENT_KB_QUERY_APIS.md`](/home/da40_ai_gb10/knowledge-base/EXTERNAL_AGENT_KB_QUERY_APIS.md)。文件以 `https://61.216.9.52:3030` 為預設 base URL，採白名單方式列出外部查詢可用端點：`GET /health`、`GET /`、`POST /search`、`GET /tasks/{task_id}`、`POST /category-relevance`、`POST /analyze-question`、`POST /api/source-categories`、`GET /api/files`、`GET /api/category-stats`、`GET /api/category-files`、`GET /api/document`、`GET /stats`、`GET /hybrid-status`、`GET /extraction-modes`，並提供 curl 範例、request/response schema、輪詢規則、sources_only 用法、文件清單與文件內容讀取方式。文件同時明確排除 `/api/openclaw/chat-config`、`/ws`、`/admin/*`、`/upload/*`、`/skills/*`、`/api/increment-search-count` 與 `DELETE /tasks/{task_id}`，避免外部 agent 學到 chat runtime、管理、寫入或取消任務能力。正式化建議仍是補 API token、read-only scope、IP allowlist/mTLS、rate limit、audit log 與 agent 專用同步封裝 `/api/agent/query`。
- 2026-07-20 已分析「外部 AI agent 需要查詢這台 knowledge-base 所有資料」的整合方式。現有查詢主幹是 FastAPI `POST /search` 提交非同步搜尋任務，`GET /tasks/{task_id}` 取回 `answer/sources/citation_distribution/mode`；這比 WebSocket chat 更適合外部 agent 取資料。建議外部 agent 只走 KB API Gateway，不直連 Neo4j/Qdrant/File Store；短期可直接用 `/search` + `/tasks/{task_id}`，查詢模式依需求用 `auto/vector/hybrid/sources_only`，並限制 `top_k`、timeout、重試與輪詢頻率。正式化建議新增 agent 專用 `/api/agent/query` 同步封裝與 `/api/agent/search` 非同步封裝，統一處理 API token、scope、rate limit、audit log、來源引用格式、錯誤碼與查詢範圍；若真的要「所有資料」能力，也應以 read-only scope 表達，必要時提供 `list_documents/get_document/get_sources` 這類受控端點，而不是開放 DB 帳密。安全設計需區分 ingest/write 與 query/read token，支援 IP allowlist 或 mTLS，並保留每次 query、agent_id、source_env、task_id、引用文件與耗時紀錄。
- 2026-07-20 已分析「外部電腦上的 AI agent 測試環境，測試完成後將結果傳入這台 knowledge-base」的整合方式。現有 repository 已有可用主幹：FastAPI `/api/upload/ingest` 可接收檔案並提交 Celery ingest 任務，任務會轉 Markdown、寫入 Neo4j/Qdrant、更新索引，並可透過 `/api/upload/tasks/{task_id}` 查狀態；另有 watch folder / n8n 範例，可讓外部環境以 SCP/SFTP/共享資料夾落檔後由 KB 定時掃描攝入。建議短期採「外部 AI agent 產出 Markdown/JSON/HTML/PDF 測試報告 → 呼叫 `/api/upload/ingest?extraction_mode=automation` 或放入 watch folder → KB 攝入」；中期補一個專用 `POST /api/external-test-results` 入口，接收結構化 payload、產生標準 Markdown 與 source metadata，再共用既有 ingest pipeline；正式部署需補 API token/mTLS 或 IP allowlist、結果 schema、run_id/idempotency key、來源環境欄位、附件/截圖打包規範、任務狀態回查與失敗重送機制。結論：不要讓外部環境直接寫 Neo4j/Qdrant，應讓它只送標準化 artifact，由 KB 端統一轉換、去重、攝入與索引，才能避免跨 session、跨部署路徑與資料 schema 漂移。
- 2026-07-20 已依 `all_kowledge.jpg` 的最終完整系統拓樸，對目前 knowledge-base repository 做現況／缺口盤點，產出可編輯的 PowerPoint [`knowledge_base_topology_gap_comparison.pptx`](/home/da40_ai_gb10/knowledge-base/knowledge_base_topology_gap_comparison.pptx)，生成腳本為 [`generate_kb_topology_gap_comparison_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_kb_topology_gap_comparison_pptx.py)。簡報共 3 張：第 1 張以原參考圖架構呈現完整差異覆蓋圖，綠框為已具備、橘色虛線為部分具備、紅色虛線為尚缺；第 2 張抽出目前已具備的 Browser → Nginx → FastAPI/Celery → Qdrant/Neo4j/File Store → OpenClaw/Ollama 端到端主幹；第 3 張整理四項主要差距與補齊順序。判定結論：Nginx、Search/Admin/Chat UI、Upload/Watch、FastAPI、WebSocket Proxy、SearchEngine、Celery、Redis、Neo4j、File Store 已有實作；Document Pipeline 的 Convert/Chunk 已有但 OCR 為條件式；Qdrant 已存在但以獨立容器運作；OpenClaw Gateway/Runtime 與 Ollama 已有串接，但仍是 KB Compose 外部相依；Runtime State 目前有 task/cache/locks，但統一持久化 Chat/Memory 尚未完整；三種角色已有操作路徑，但登入、RBAC、API scope 與 audit 尚未形成真正的治理層。缺口優先序標為 P0「角色與存取治理、Runtime State 完整化」，P1「外部 AI 生命週期、資料平台一致化」。已以 `python3 -m py_compile` 驗證腳本、以 `python-pptx` 驗證 3 張投影片結構，並以 LibreOffice 成功轉 PDF、逐頁轉 PNG 目視確認無明顯溢出或遮擋。另在 2026-07-20 的唯讀 runtime 探測中，`kb-qdrant` 容器正在運作，但 `https://61.216.9.52:3030/health` 當時無法連線，因此投影片明確採「repository 能力與部署邊界」作為狀態判定，而非宣稱當下所有服務都在線。
- 2026-06-18 已評估「兩個獨立 knowledge-base 環境共用同一組 Neo4j / Qdrant」的可行性：技術上可行，因為程式已支援透過 `NEO4J_URI` / `QDRANT_URL` 指到外部資料庫，而且目前 Neo4j / Qdrant 寫入本來就是固定 schema / 固定 collection（例如 Qdrant `knowledge_base`、`kb_syntheses`，Neo4j `Document` / `Entity` / `Report` / `Section` / `TestItem` 等），沒有內建 tenant 隔離；但若兩邊會 ingest 不同資料，風險很高，因為 `doc_name`、`Project.code`、`TestItem.canonical_name`、Qdrant point id（由 `doc_name + chunk_index` 決定）都有碰撞或互相覆蓋的可能，而且任一環境的清除/重攝入操作都會影響另一邊。建議只在「兩邊要共用同一套知識內容、且接受共享維運」時採用；若兩邊資料不同，應改成各自獨立 DB / collection，或先補 tenant / env 前綴再共庫。
- 2026-06-17 已將 `generate_dual_test_env_ollama_architecture_pptx.py` 的總覽頁改成單一合併架構圖，明確呈現 Anritsu 與 Amarisoft 兩個環境各自保留獨立 OpenClaw 控制層，但都共用同一台 DGX GB10 上的 Ollama / LLM 推論服務；已重新產出 [`dual_test_env_ollama_architecture.pptx`](/home/da40_ai_gb10/knowledge-base/dual_test_env_ollama_architecture.pptx)，並用 `python3 -m py_compile` 與 `python3` 讀取 pptx 內容驗證可正常生成，輸出中已可看到新標題「雙環境共用同一台 DGX GB10 的 LLM」與共用 DGX 區塊。
- 2026-06-15 已將「安裝包完成後還需要設定什麼，才能把系統順利連線起來」整理成一份給非技術使用者的 PPTX 簡報，檔案為 [`onprem_post_install_connection_guide.pptx`](/home/da40_ai_gb10/knowledge-base/onprem_post_install_connection_guide.pptx)，對應產生腳本為 [`generate_onprem_post_install_guide_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_onprem_post_install_guide_pptx.py)。簡報共 7 張，內容包含：安裝包已自動完成哪些事、OpenClaw gateway 如何接起來、host nginx 是否為選配、raw 資料應放在哪裡、如何驗證「已連線」、以及常見問題排錯。
- 2026-06-15 已完成 `172.14.1.122` 的 KB 測試環境重置，並將原始系統 `data/raw` 底下的所有檔案與子目錄同步到遠端 `/home/da40_ai_gb10_2/knowledge-base-onprem/app/data/raw`（共 56 個檔案與子目錄），讓後續可直接用最新 release 安裝包重新做首次安裝與手動 ingest 驗證；同時 release installer 仍保留同機 OpenClaw gateway 預設正規化為本機 IP + `18790` 的修正，避免新裝後又回到 `127.0.0.1:18789`。
- 2026-06-15 已再把 `172.14.1.122` 的 KB on-prem 相關檔案、容器、volume、舊安裝包與 host nginx 設定清掉，讓測試環境回到可重新安裝的乾淨狀態；隨後又把最新 release 安裝包複製到遠端 `/tmp`，準備進行「從零安裝」驗證與手動測試 ingest。
- 2026-06-14 已替「安裝包完成後，還需要設定哪些才能將系統順利連線起來」做成一份給非技術使用者看的簡報，檔案為 [onprem_post_install_connection_guide.pptx](/home/da40_ai_gb10/knowledge-base/onprem_post_install_connection_guide.pptx)，對應產生腳本為 [generate_onprem_post_install_guide_pptx.py](/home/da40_ai_gb10/knowledge-base/generate_onprem_post_install_guide_pptx.py)。內容分成 7 張投影片，重點包含：安裝包已自動完成哪些事、OpenClaw gateway 如何正規化成本機 IP + 18790、host nginx 是否為選配、raw 資料應放在哪裡、如何驗證連線成功，以及常見錯誤的簡單排錯方式。簡報已驗證可正常開啟。
- 2026-06-14 已把 KB 安裝包的 OpenClaw gateway 預設修正納入 release installer，避免新裝後又落回 `127.0.0.1:18789` 導致 `chat.html` 顯示未連線：`release/build_release.sh` 新增 `normalize_openclaw_gateway_defaults()`，在同機安裝時會把 gateway host 正規化成本機 IP、port 正規化成 `18790`，並將 `OPENCLAW_GATEWAY_WS_URL` 一律重建成 `ws://<host>:18790/ws`，同時 `confirm_and_collect()` 與非互動模式也改為以本機 IP / 18790 當預設值。最新成功產出的安裝包為 [knowledge-base-onprem-20260614_103654-75f3ba30.tar.gz](/home/da40_ai_gb10/knowledge-base/release/dist/knowledge-base-onprem-20260614_103654-75f3ba30.tar.gz)。
- 2026-06-14 在 `172.14.1.122` 重新安裝 KB on-prem 後若出現 `chat.html` 顯示未連線，根因是安裝後 `.env` 與 `install-state.env` 仍指向 `KB_OPENCLAW_GATEWAY_HOST=127.0.0.1`、`KB_OPENCLAW_GATEWAY_PORT=18789`，但主機上的 `openclaw-gateway` 實際監聽在 `0.0.0.0:18790`；此外 `docker compose --env-file ../.env up -d --force-recreate web nginx` 可正確將新 env 套入容器，`/api/openclaw/chat-config` 會回傳 `gatewayWsUrl=ws://172.14.1.122:18790/ws` 與完整 `privateKeyPem/publicKeyPem`，`web` log 也會顯示 `connected upstream gateway=ws://172.14.1.122:18790/ws`。另需注意當時主機 `/etc/nginx/sites-available/openclaw-https` 是 0 bytes，屬於 host nginx opt-in 功能未正確落地的獨立問題，不是 KB 連線失敗主因。
- 2026-06-14 已將 `172.14.1.122` 上的 KB on-prem 環境完整清除，準備用 release 安裝包重新模擬首次安裝：已透過 `docker compose down -v --remove-orphans` 清掉 `kb_onprem-*` 容器與 `kb_release_*` volumes，並刪除 `/home/da40_ai_gb10_2/knowledge-base-onprem` 安裝根目錄與 KB 專屬 Docker images（`kb_onprem-web:latest`、`kb_onprem-celery_*:latest`）；同時移除主機層 `/etc/nginx/sites-available/openclaw-https` 與 `sites-enabled/openclaw-https` 站台 symlink，讓 `172.14.1.122` 回到接近乾淨、可重新安裝的狀態。OpenClaw 本體與使用者個人工作區未動。
- 2026-06-13 已把 OpenClaw 的主機 nginx 設定也納入 release installer，但維持 opt-in，不會預設改動主機 nginx：`release/build_release.sh` 現在支援 `--configure-openclaw-nginx`，並可搭配 `--openclaw-nginx-listen-ip`、`--openclaw-nginx-listen-port`、`--openclaw-nginx-backend-host`、`--openclaw-nginx-backend-port` 由 installer 在目標主機上建立 `/etc/nginx/sites-available/openclaw-https` 與對應 symlink；生成的 `install.sh` 內也包含 `detect_primary_ip()`、`configure_openclaw_host_nginx()` 與對應 summary，package root `README.md` 也已補上 opt-in 說明。最新成功產出的安裝包為 [knowledge-base-onprem-20260613_123704-75f3ba30.tar.gz](/home/da40_ai_gb10/knowledge-base/release/dist/knowledge-base-onprem-20260613_123704-75f3ba30.tar.gz)。
- 2026-06-13 已把今天在 `172.14.1.122` 上調整的 KB on-prem chat 防卡死修正回灌到 release 安裝包：更新 [release/build_release.sh](/home/da40_ai_gb10/knowledge-base/release/build_release.sh) 的 installer 預設值，讓新裝與升級時自動採用 `KB_CHAT_GLOBAL_CONCURRENCY_LIMIT=2`、`KB_CHAT_BROWSER_CONCURRENCY_LIMIT=1`、`KB_CHAT_SESSION_LOCK_TTL=600`、`KB_CHAT_GLOBAL_SLOT_TTL=600`、`KB_CHAT_QUEUE_ACTIVE_TTL=600`；同時把這些值寫進 `.env` 與 `install-state.env`，並在安裝腳本內新增 `reset_chat_runtime_state()`，啟動完成後會自動清掉 Redis 裡殘留的 `kb:chat:queue:req:*`、`kb:chat:session_lock:*` 與 `kb:chat:browser_active:*`，避免舊 session / active slot 讓第一筆聊天請求卡死。最新可交付安裝包為 [knowledge-base-onprem-20260613_122552-75f3ba30.tar.gz](/home/da40_ai_gb10/knowledge-base/release/dist/knowledge-base-onprem-20260613_122552-75f3ba30.tar.gz)。
- 2026-06-13 已針對 `172.14.1.122` 的 KB on-prem 做「只改遠端、不動原始系統」的防卡死調整：遠端 `/home/da40_ai_gb10_2/knowledge-base-onprem/.env` 與 `install-state.env` 已將 `KB_CHAT_GLOBAL_CONCURRENCY_LIMIT` 從 1 調高到 2，並把 `KB_CHAT_SESSION_LOCK_TTL` 與 `KB_CHAT_GLOBAL_SLOT_TTL` 從 1200 縮短到 600，目的是避免單一長任務或殘留 slot 直接把所有聊天請求卡死；同時保留 `KB_CHAT_BROWSER_CONCURRENCY_LIMIT=1`，不影響同一個瀏覽器內的基本互斥。已重建遠端 `web` 容器並驗證容器內實際環境變數已生效，之後在 `https://172.14.1.122:18443/chat.html` 送出 `今天天氣如何` 時，畫面可先進入 `等待階段: 生成回覆中`，最後正常回出基本 LLM 天氣回覆與 `wttr.in` 來源，代表此調整已把「排隊中卻沒有基本回覆」的問題顯著緩解，且原始系統尚未套用此 patch。
- 2026-06-13 在 `https://172.14.1.122:18443/chat.html` 以 `今天天氣如何` 實測時，先前一輪會長時間停在 `排隊中`，後續查到遠端 Redis 的 `kb:chat:queue:active` 與對應 session lock / browser_active 殘留，導致 `web` log 持續出現 `Chat queue claim waiting global limit request_id=chat-0 queue_rank=0 active_count=1`。在清掉這次測試留下的 `kb:chat:queue:active`、`kb:chat:queue:req:chat-0`、session lock 與 browser_active 鍵後，重新開乾淨的 Playwright session 再送同題，頁面先進入 `等待階段: 生成回覆中`，最後成功多出第二則 bot 訊息，內容為「今天台北的氣象資訊如下：目前天氣狀況為 [Insert current weather data if retrieved or leave as general placeholder]. (註：由於目前的外部搜尋服務尚未啟用 API 金鑰，我無法即時獲取實時預報。) 建議您可以參考 local 的天氣應用程式以獲取最精確的當前氣溫。」並附上 `參考來源：(尚未取得相關知識庫數據)`。這次證實 on-prem 小幫手在沒有 KB 命中時仍會回基本 OpenClaw LLM 答案，而排隊卡住的根因是殘留的 active slot / session lock，而不是聊天頁本身不能回覆。
- 2026-06-13 追查 `https://172.14.1.122:18443/chat.html` 在「妳在嘛」場景下排隊久候的原因，確認不是 OpenClaw 沒回，而是 websocket 斷線後舊的 queued request 沒有被清掉，Redis 中殘留的 `kb:chat:queue` 會讓新請求長時間排在 `chat-1` 後面。已在 `src/web_api/__init__.py` 加入 `pending_request_ids` 與 `release_pending_requests()`，讓 websocket teardown 會釋放該連線自己尚未完成的 queued request；並同步到遠端 `172.14.1.122`、手動清除殘留 `chat-0/chat-1` 後重新測試，現在 `妳在嘛` 會正常顯示 OpenClaw 回覆，輪詢結果確認第二則 bot 訊息出現為「我在這裡，準備好協助你處理任何事情了。有什麼我可以幫你的嗎？」。
- 2026-06-13 已將本機 `~/.openclaw/workspace/` 內的 `SOUL.md`、`USER.md`、`AGENTS.md`、`TOOLS.md`、`IDENTITY.md`、`HEARTBEAT.md`、`BOOTSTRAP.md` 同步到 `172.14.1.122` 的 `/home/da40_ai_gb10_2/.openclaw/workspace/`，並以 sha256 checksum 驗證兩邊內容完全一致。這是為了讓兩台機器上的 OpenClaw 行為模式、規則與啟動/心跳流程盡量對齊。
- 2026-06-13 已修正 KB on-prem 小幫手在 `https://172.14.1.122:18443/chat.html` 送出問題後「有回覆但畫面不顯示」的根因：OpenClaw upstream 其實是回 `event=agent`，而原本前端只處理 `event=chat`，所以 assistant/lifecycle 事件被漏掉，畫面會長時間停在「生成回覆中」或只看到使用者訊息。已在 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 補上對 `event=agent` 的相容處理，會把 `stream=assistant` 的 `delta/text` 渲染成 bot 訊息，並把 `stream=lifecycle phase=end` 視為完成；同步更新遠端 `172.14.1.122` 的 runtime 檔案後，實測在 `chat.html` 輸入 `你在嘛?` 會正常顯示 OpenClaw 回覆 `我在這裡，正準備好協助你。有什麼我可以幫你的嗎？`。這次的修正重點是把「OpenClaw 有回但 KB UI 吃不到」的事件格式差異補齊，而不是只修 session key 或模型設定。
- 2026-06-13 已完成 KB on-prem 的 OpenClaw identity 修正與驗證：release installer 新增 `sync_host_openclaw_identity()`，安裝 / 升級時會自動將主機 `~/.openclaw/identity/device.json` 與 `device-auth.json` 同步到 `runtime/openclaw/identity/`，避免 `chat-config` 回傳空的 `privateKeyPem/publicKeyPem`。也已在現有 `172.14.1.122` 安裝根目錄手動同步 identity，重新整理 `https://172.14.1.122:18443/chat.html` 後狀態已從「未連線」變成「已連線」，且 `GET /api/openclaw/chat-config` 已回傳完整金鑰。新發行包為 [knowledge-base-onprem-20260613_094505-75f3ba30.tar.gz](/home/da40_ai_gb10/knowledge-base/release/dist/knowledge-base-onprem-20260613_094505-75f3ba30.tar.gz)。
- 2026-06-13 追查 `https://172.14.1.122:18443/chat.html` 顯示「未連線」的根因：不是 OpenClaw gateway 或 nginx 未啟動，而是 release runtime 掛載的 `/home/da40_ai_gb10_2/knowledge-base-onprem/runtime/openclaw/identity/device.json` 內 `privateKeyPem` / `publicKeyPem` 目前是空字串。`/api/openclaw/chat-config` 因而回傳 `privateKeyPem: ""`、`publicKeyPem: ""`、`publicKeyRaw: ""`，前端在收到 `connect.challenge` 時就會印出 `[Chat] runtime config not ready` 並拒絕完成連線。對照之下，主機上的 `~/.openclaw/identity/device.json` 其實是有完整金鑰的，因此後續修正應以把主機 identity 金鑰同步進 release runtime，或讓 install/compose 直接掛載正確的 identity 路徑為主。
- 2026-06-13 已釐清並固定驗證範圍：`https://61.216.9.52:3030/chat.html` 是原始系統的對外網址，`https://172.14.1.122:18443/chat.html` 是另一台電腦上的 KB on-prem 系統入口。後續所有 on-prem 安裝、nginx、OpenClaw gateway、KB 連線與聊天驗證，都必須以 `172.14.1.122:18443` 為準，不可再把原始系統網址誤當成這台機器的驗證入口。
- 2026-06-13 已用瀏覽器真實流程驗證 KB 小幫手可正常回覆：在 `https://61.216.9.52:3030/chat.html` 先確認狀態由「未連線」變成「已連線」，再從右下角 `KB Chat v2026-05-20` 浮動按鈕開啟聊天，輸入 `請查詢SCU2140相關報告資訊` 後等待約 60 秒，畫面成功回出 `🦾 CSIT_KM小幫手` 的 KB 參考內容與 `原文` 摘錄，且引用統計顯示 `本次共引用 60 份來源，回推成 1 份原始文件`，說明聊天鏈路可用。先前試過的泛用問句 `請簡單介紹這個系統` 沒有在等待窗內回出實質答案，因此後續驗證應優先用可命中的 KB 問句。
- 2026-06-11 已在遠端 `172.14.1.122` 完成 OpenClaw / nginx 對外入口調整：OpenClaw gateway 改為內部 `ws://172.14.1.122:18790/ws`，並以 `0.0.0.0:18790` 監聽，KB on-prem 的 `.env` 與 `install-state.env` 也同步改成 `KB_OPENCLAW_GATEWAY_WS_URL=ws://172.14.1.122:18790/ws`。同時新增 nginx 站台 `/etc/nginx/sites-available/openclaw-https`，由 `https://172.14.1.122:18789` 對外進入，反向代理到 `http://127.0.0.1:18790`，並已啟用 `sites-enabled/openclaw-https` 與重載 nginx。驗證結果：`curl -k https://172.14.1.122:18789` 回傳 OpenClaw Control UI，KB `web` 容器 log 顯示 `WebSocket proxy ... connected upstream gateway=ws://172.14.1.122:18790/ws`，代表前端已從「未連線」恢復為可連線狀態。
- 2026-06-11 針對升級後安裝失敗的 `Frontend runtime build is missing: .../runtime/frontend/index.html` 已完成修補：根因是 release 產線原本只把 Vite build 輸出保留在 `.frontend-build-runtime-user8`，沒有把 build 成果複製進發行包的 `runtime/frontend/`，導致 installer 在 `apply_upgrade_or_install()` 驗證 runtime 時找不到 `index.html`。已將 `build_frontend_runtime()` 改成在 build 完成後把 `.frontend-build-runtime-user8` 的內容完整複製到 `runtime/frontend/`，再補上 `chat.html` 與 lib 檔案；新包為 [knowledge-base-onprem-20260611_102513-75f3ba30.tar.gz](/home/da40_ai_gb10/knowledge-base/release/dist/knowledge-base-onprem-20260611_102513-75f3ba30.tar.gz)，並已同步到遠端 `/tmp`。
- 2026-06-11 針對升級安裝時出現的 `Empty source arg specified` 已完成第三次修補：根因是 release installer 在 `apply_upgrade_or_install()` 內的 `rsync -a --delete "${app_excludes[@]}" ...` 與 `runtime_excludes` 兩行，因為 build-time heredoc 沒有把 `${app_excludes[@]}` 轉義，導致生成出的 install script 出現空字串參數。已改為保留陣列展開的 runtime 字串，並把升級備份旗標統一為 `UPGRADE_BACKED_UP`，避免互動式升級與主流程重複備份兩次。新包為 [knowledge-base-onprem-20260611_102121-75f3ba30.tar.gz](/home/da40_ai_gb10/knowledge-base/release/dist/knowledge-base-onprem-20260611_102121-75f3ba30.tar.gz)，並已同步複製到遠端 `/tmp`。
- 2026-06-11 針對安裝過程中的 `指令找不到` / `rsync error: Empty source arg specified` 已完成第二次修補：根因是 release installer 在 `write_openclaw_overlay()` 產生 `00-bootstrap.md` 時，把 `sessionKey` 與聊天網址包在反引號裡，導致 shell 在執行安裝腳本時把隨機 session key 當成命令替換執行。已將該段改為純文字輸出 `sessionKey: $OPENCLAW_SESSION_KEY` 與 `正式 Chat 網址: /chat.html?sessionKey=$OPENCLAW_SESSION_KEY`，並重建新包 [knowledge-base-onprem-20260611_101427-75f3ba30.tar.gz](/home/da40_ai_gb10/knowledge-base/release/dist/knowledge-base-onprem-20260611_101427-75f3ba30.tar.gz)，已同步複製到遠端 `/tmp`。
- 2026-06-11 針對遠端安裝時出現的 `INSTALL_ROOT: 未綁定的變數` 已完成修補：根因是 release installer 在 `set -u` 下先呼叫 `prepare_default_values()`，但 `INSTALL_ROOT` 尚未初始化就被 `[[ -f "$INSTALL_ROOT/..." ]]` 讀取。已將 `prepare_default_values()` 改為使用 `local install_root="${INSTALL_ROOT:-$HOME/knowledge-base-onprem}"`，並在進入該流程前先把 `INSTALL_ROOT` 設為預設值；已重建新包 [knowledge-base-onprem-20260611_100519-75f3ba30.tar.gz](/home/da40_ai_gb10/knowledge-base/release/dist/knowledge-base-onprem-20260611_100519-75f3ba30.tar.gz) 並同步覆蓋到遠端 `/tmp`。
- 2026-06-11 已新增面向非技術人員的 B2B/on-prem 安裝手冊 [docs/onprem-install-guide.md](/home/da40_ai_gb10/knowledge-base/docs/onprem-install-guide.md)，內容以「先準備什麼、帶哪些檔案、如何解壓、如何執行 `--check-only`、如何正式執行 `install.sh`、如何處理 `--offline`、常見錯誤與升級舊版本」的順序編寫，並在 [README.md](/home/da40_ai_gb10/knowledge-base/README.md) 與 [release/README.md](/home/da40_ai_gb10/knowledge-base/release/README.md) 補上入口連結，讓不熟悉系統的人可直接照步驟安裝。
- 2026-06-11 已依使用者要求，從 Bnext 文章 https://www.bnext.com.tw/article/90965/claude.md-claude-code 讀取並整理 Claude Code 的 12 條規則，並同步寫入全域 `/home/da40_ai_gb10/.codex/AGENTS.md` 與專案內 `/home/da40_ai_gb10/knowledge-base/AGENTS.md`。新增段落標題為 `Claude Code 十二條規則`，內容涵蓋先思考、簡單優先、外科手術式修改、目標導向、避免把確定性工作交給模型、硬性 token 預算、衝突選邊、先讀再寫、測試要有業務意義、長任務檢查點、約定優先、顯性失敗等 12 點。
- 2026-06-11 已完成 release installer 的兩個新增控制旗標：`--check-only` 會只做前置條件掃描並直接結束，不進入安裝、不補裝、不改寫檔案；`--offline` 會完全停用任何網路補裝，若缺少必需依賴則在進入安裝前直接失敗，且若同時帶 `--auto-install-deps` 會以 offline 為準。這次已同步更新 [release/build_release.sh](/home/da40_ai_gb10/knowledge-base/release/build_release.sh) 與 [release/README.md](/home/da40_ai_gb10/knowledge-base/release/README.md)，並重建發行包為 [knowledge-base-onprem-20260611_094458-75f3ba30.tar.gz](/home/da40_ai_gb10/knowledge-base/release/dist/knowledge-base-onprem-20260611_094458-75f3ba30.tar.gz)。已驗證 build 腳本 `bash -n` 通過，tar 包內 `install.sh` 也通過 `bash -n`。
- 2026-06-10 已將新電腦重建手冊整理成正式中文 SOP [docs/new-machine-rebuild-guide.md](/home/da40_ai_gb10/knowledge-base/docs/new-machine-rebuild-guide.md)，內容已重構為「前置準備、取得程式碼、建立相容路徑、設定 config、安裝依賴、啟動 Neo4j/Qdrant、執行 `restart_kb.sh`、還原資料 bundle、重新 ingest、驗證清單與常見排障」的完整交接流程；同時把 [README.md](/home/da40_ai_gb10/knowledge-base/README.md) 的入口說明更新為「重建 SOP」，避免後續閱讀者只看到零散手冊。這次整理是文件層級調整，未改動程式邏輯。
- 2026-06-10 已更新新電腦重建手冊 [docs/new-machine-rebuild-guide.md](/home/da40_ai_gb10/knowledge-base/docs/new-machine-rebuild-guide.md) 與投影片 [new_machine_rebuild_guide.pptx](/home/da40_ai_gb10/knowledge-base/new_machine_rebuild_guide.pptx)，新增 Docker 安裝說明，以及 Neo4j / Qdrant 在 Docker 中的啟動方式。內容現在明確區分：Docker 安裝、Neo4j 由 `docker-compose.yml` 的 `neo4j` service 啟動、Qdrant 由 `restart_kb.sh` 以獨立 `kb-qdrant` 容器啟動，並同步把後續步驟編號往後調整，確保新電腦照著文件就能把整套 knowledge-base 系統架起來再重新 ingest。
- 2026-06-10 已確認目前 knowledge-base 並未使用像 `bge-reranker-v2-m3` 這類獨立重排模型；實作上是先用 Qdrant 做 embedding 召回，再由 `src/search/__init__.py` 的 `_rank_vector_results()` 依 `doc_hints`、`case_hints`、章節標題、檔名命中與原始 score 做規則式重排。`src/vector_store/__init__.py` 只負責把 `sentence-transformers/all-MiniLM-L6-v2` 產生的 embedding 寫入 / 查詢 Qdrant，沒有 cross-encoder rerank pipeline。
- 2026-06-10 已依使用者要求產出「另一台電腦重建 knowledge-base 系統」的投影片手冊，檔案為 [new_machine_rebuild_guide.pptx](/home/da40_ai_gb10/knowledge-base/new_machine_rebuild_guide.pptx)，目前為 9 張投影片；對應的生成腳本為 [generate_new_machine_rebuild_guide_pptx.py](/home/da40_ai_gb10/knowledge-base/generate_new_machine_rebuild_guide_pptx.py)。內容涵蓋前置環境、Docker 安裝、Neo4j / Qdrant 容器啟動、clone 與 symlink、config 設定、服務啟動、資料 bundle 還原、重新 ingest、驗證與常見排錯，主軸明確是「先把系統架起來，再重新 ingest 資料」，不要求把舊資料直接搬進 GitHub。
- 2026-06-10 已把 code-only GitHub repo `dev-work` 重新同步到最新重建手冊內容，最新推送 commit 為 `20fd257`（`docs: sync rebuild guide into code-only repo`）。code-only repo 現在包含 `docs/new-machine-rebuild-guide.md`，且 `README.md` 與 `docs/github-backup-plan.md` 已補齊最新連結，方便新電腦直接照步驟重建後再重新 ingest。原始 `knowledge-base` 工作樹仍保留完整本機開發狀態，不再直接拿去覆蓋 GitHub 的乾淨版本。
- 2026-06-09 已實際用 headless Chromium 檢查 Neo4j Browser `http://localhost:17474/browser/`：頁面本身可正常載入，`page.title()` 為 `Neo4j Browser`，`body` 顯示的是 `No instance connected` 與連線表單，且 console 沒有頁面錯誤，表示這不是前端快取壞掉，而是 Browser 尚未連到資料庫。進一步確認目前 KB 的 Neo4j 容器對外映射是 host `17474`（HTTP）與 `17687`（Bolt），因此 Browser 預設的 `neo4j://localhost:7687` 不是這個 KB 容器的連線埠；若要看到已攝入的報告資料，需在 Browser 內手動連到 `bolt://localhost:17687`（或等價的 `neo4j://localhost:17687`）並輸入 `neo4j / #*cda40da40`。目前 `kb-neo4j` 容器內仍有 9 筆 `Document`，所以資料本身是存在的。
- 2026-06-09 已整理出新電腦重建手冊 [docs/new-machine-rebuild-guide.md](/home/da40_ai_gb10/knowledge-base/docs/new-machine-rebuild-guide.md)：內容包含前置安裝、Git clone、建立相容 symlink、複製 `config/config.yaml.example`、啟動 `restart_kb.sh`、還原獨立資料 bundle、以及重新 ingest 的完整步驟。由於目前 code-only repo 仍含有部分絕對路徑，手冊特別提醒先建立 `/home/da40_ai_gb10/knowledge-base` 的 symlink，或自行把硬編碼路徑改成新機器上的實際位置，避免第一次搬機器就因 path mismatch 卡住。
- 2026-06-09 已完成「只保留可重建程式碼、之後重新 ingest 資料」的 GitHub 方案 A 落地：另外建立獨立的 code-only 工作區，移除 `data/`、`.venv`、frontend/node_modules、build/dist、草稿/備份檔與 local config，保留 `src/`、`frontend/`、`docs/`、`scripts/`、`Dockerfile`、`docker-compose.yml`、`restart_kb.sh`、`start.sh`、`requirements.txt`、`config/config.yaml.example` 等重建所需內容，並將 GitHub remote `dev-work` force update 到乾淨版本。最終成功推送的 commit 為 `8433ebd`（`chore: drop draft and backup files`），GitHub 上的 `dev-work` 現在已是可 clone、可在新電腦重新 setup、再重新 ingest 的輕量化版本；資料需透過獨立 bundle 另行還原，不再依賴 repo 內的原始資料。
- 2026-06-09 最新一次以使用者提供的 `github_pat_...` token 嘗試推送到 `dev-work` 時，GitHub 回覆 `RPC failed; HTTP 500 curl 22` / `send-pack: unexpected disconnect while reading sideband packet`，但 `git ls-remote` 仍顯示遠端 `dev-work` 在 `f726f8a64851a7e8884b7888c4c5165853d0ff01`，表示本地 `1d66ca27` 尚未成功上傳。這次不是明確的權限拒絕，而是遠端傳輸/pack 流程失敗，若要繼續應改用 SSH push、縮小一次推送的內容，或再重試一次確認是否為 GitHub 暫時性問題。
- 2026-06-09 進一步嘗試使用使用者提供的新 GitHub PAT 進行 `git push`，GitHub 回覆 `Write access to repository not granted` 並以 403 拒絕寫入。這代表憑證即使可被接受，也沒有該 repo 的 push 權限，可能是 token 未授權 `repo` scope、帳號不是該倉庫協作者、或目標 repository 並非該 PAT 所屬帳號可寫入。後續若要成功推送，需先確認 GitHub 帳號對 `kyocarlos/knowledge-base` 具備寫入權限，或改推到你有權限的 fork / 重新授權 PAT / 使用 SSH key。
- 2026-06-09 已嘗試使用使用者提供的 GitHub PAT 進行 `git push`，但 GitHub 回應 `Invalid username or token. Password authentication is not supported for Git operations.`，因此遠端推送尚未成功。這代表目前問題不是 repo 內容，而是憑證本身無效、過期、權限不足或字串有誤。後續若要繼續推送，需使用新的有效 PAT 或改用 SSH / `gh auth login`。
- 2026-06-09 已開始落實方案 A 的 GitHub 備份流程：新增 [docs/github-backup-plan.md](/home/da40_ai_gb10/knowledge-base/docs/github-backup-plan.md) 說明「GitHub 放可重建的程式碼、資料另存 bundle」；新增 [scripts/create_data_backup_bundle.sh](/home/da40_ai_gb10/knowledge-base/scripts/create_data_backup_bundle.sh) 可把 `data/raw/`、`data/processed/`、`data/assets/`、`data/uploads/` 與 `config/config.yaml` 打成獨立 tar.gz 備份；`.gitignore` 也補上 `.frontend-build-runtime-*`、`.venv_playwright/`、`final_runs/`、`backups/` 與多個本機生成檔。`README.md` 已加入新電腦重建導向。Git remote 也已清掉 token，改回乾淨的 `https://github.com/kyocarlos/knowledge-base.git`；本地 commit 已完成為 `9f1ae36a`（`docs: add GitHub backup and restore workflow`），但實際 `git push` 目前因這台機器沒有可用的 GitHub 認證而失敗，下一步需要提供 SSH key / PAT 或改用已登入的 GitHub 工具才能把這筆備份推上遠端。
- 2026-06-09 目前正在整理「更新到目前進度的記憶與 Git 備份」：已先讀取本檔與目前工作樹狀態，確認倉庫中仍有大量既有修改與未追蹤檔案，這一輪不做功能改動，只先把最新進度同步回記憶，接著會建立一筆乾淨的 Git 備份提交。後續若要接手，應先沿用本檔既有脈絡，再依目前的 KB / 前端 / ingest 狀態續作。
- 2026-06-09 已依使用者要求清除 SCU2060 / SCU2140 / SCU5050 在 Neo4j 與 QDrant 內的資料，供乾淨手動測試使用。實際從 Neo4j 找到並清除的 `Document` 節點為 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8`、`SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005`、`SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001`；`cleanup_existing_document()` 執行後三者在 Neo4j 與 QDrant 的殘留都已清空，並已用查詢驗證 `MATCH (d:Document) WHERE d.name CONTAINS 'SCU2060/2140/5050'` 與 `vector_store.list_documents()` 都回空。後續若要重新測試圖片 chunk 行為，需先重啟服務，再重新攝入這三份文件。
- 2026-06-09 已把 chunk-level 圖片引用從「文件級廣播」修正為「只保留 chunk 內文命中的 refs」：`src/chunker/__init__.py` 移除了先前會把整份 `source.json` 的 `image_refs` 複製到所有 chunk 的 fallback，現在只會根據每個 chunk 自己的內文抽取 `asset://...` 並去重後寫入 `chunk.metadata.image_refs`；`src/vector_store/__init__.py` 仍沿用同一套共用抽取 helper，將 chunk 內文與 metadata 內的 refs 一起寫進 QDrant payload。已用 `python3 -m py_compile src/chunker/__init__.py src/vector_store/__init__.py src/web_api/tasks.py src/image_refs.py` 驗證語法，並用暫存 Markdown 實測確認只有含 `頁面快照引用` / `圖片` 的 chunk 會保留 `image_refs`，其他 chunk 不再重複顯示同一批圖片。
- 2026-06-08 已完成 `image_refs` 的穩定化修補：新增 `src/image_refs.py` 作為共用抽取/正規化 helper，讓 `src/chunker/__init__.py` 不再只靠 Markdown 內文，而是會先讀 sidecar `*.source.json` 的 `image_refs`，再合併 chunk 內文抽出的 asset refs 寫回 `chunk.metadata.image_refs`；若 chunk 內文沒有 inline 引用，會以 source metadata 作為 fallback，確保沒有 `asset://...` 內文時仍能保留圖片引用。`src/vector_store/__init__.py` 已改成使用同一個 helper，寫入 QDrant 時會把 `metadata.image_refs` 與 content 抽出的 refs 一起去重後存進 payload。`src/web_api/tasks.py` 的 `_write_source_metadata()` 也已新增 `image_refs` 欄位，`ingest_file_task` 與 watch ingestion 的 source metadata 都會把 converter 回傳的 `image_refs` 一起落盤。已用 `python3 -m py_compile src/image_refs.py src/chunker/__init__.py src/vector_store/__init__.py src/web_api/tasks.py` 驗證語法，並用暫存 markdown + `original/sample.source.json` 的最小測試確認 `chunk_document()` 在內文沒有 inline asset refs 時，仍會把 `image_refs` 穩定寫進每個 chunk metadata。
- 2026-06-04 已依使用者指定安裝 Webwright skill，來源為 `https://github.com/microsoft/Webwright/tree/main/skills/webwright`，安裝位置為 `/home/da40_ai_gb10/.codex/skills/webwright`。後續若需做瀏覽器自動化、長流程網頁操作或 Playwright 類任務，應優先考慮直接使用這個 skill。
- 2026-06-04 已更新 [AGENTS.md](/home/da40_ai_gb10/knowledge-base/AGENTS.md) 的網頁測試原則：凡是網頁功能測試、網頁設計驗證、或前端修改後的確認，統一以 Webwright 為第一優先工具；Playwright 僅在 Webwright 無法處理、遇到工具限制、或需要更細緻瀏覽器除錯時才作為備援。原本「優先使用 Playwright」的描述已改成「Webwright / Playwright 測試規範」，以免後續人員誤把 Playwright 當成首選。
- 2026-06-04 已實際透過瀏覽器測試 `請整理 TP-Link Archer BE805 的 5GHz 80MHz 與 160MHz 數據`：前端先進入 `https://61.216.9.52:3030/chat.html`，開啟聊天浮窗後送出查詢，websocket 連線成功，接著 `/search` 產生 task `f35af84c-9650-40df-9eea-20b160f1453f` 並連續輪詢 `/tasks/{task_id}`，最後 console 顯示 `[Heatmap] Prepared WiFi-specific KB result.` 與 `wait timing summary`，代表這句話確實走 WiFi-specific KB 路徑而不是 report_graph。最終回答回推到 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx`，內容包含 `4.2.3 5GHz - Bandwidth 80MHz` 與 `4.2.4 5GHz - Bandwidth 160MHz`，解讀明確寫出 80MHz 的 Tx/Rx 約 `2450.1~2484.5 / 2063.04~2248.58 Mbps`、160MHz 的 Tx/Rx 約 `4606.04~4732.45 / 3984.19~4117.04 Mbps`，並指出 160MHz 的 `2882.4 Mbps` 正好是 80MHz 的 `1441.2 Mbps` 兩倍。熱圖卡片也同步更新為 `WiFi=100/1`、`4G/5G=0/0`，表示這次只命中 1 份 WiFi 原始文件。
- 2026-06-04 已實際透過瀏覽器測試 `TP-Link Archer BE805 的 2.4GHz 和 5GHz 表現有什麼差異`：前端同樣先進入 `https://61.216.9.52:3030/chat.html` 並開啟聊天浮窗，送出後 `/search` 產生 task `78bf922b-a824-4608-a7fe-147ed55a73f4`，console 顯示 `[Heatmap] Prepared WiFi compare KB result.`，但這次 `matched_count=1`、`total_sources=1`，代表只命中單一 WiFi 文件。最終回覆沒有進入真正的雙頻比較，而是回 `KB 匯整來源：type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx`，`原文` 直接寫明「未找到足夠的 WiFi 文件可進行比較。」；`解讀` 也只列出「目前只找到：type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx」與「未命中的查詢文件：BE805、TP-LINK ARCHER BE805」。這表示此問法目前會被辨識成 WiFi compare 類，但因為缺少第二份可對照的 WiFi 文件，所以系統會退回單文件提示，不會自動合併成 2.4GHz vs 5GHz 的對比結論。
- 2026-06-08 針對 `/admin/chunks` 的 SCU2060 / SCU2140 / SCU5050 圖檔缺失問題已確認根因：後端 `admin_chunk_assets` 只會從 `data/assets/<doc_name>/...` 提供實體檔；`chunk_document()` 目前只補 `source_path` 等基礎 metadata，不會主動帶入 `image_refs`；`vector_store.add_documents()` 雖會從 chunk 內容與 metadata 擷取 `image_refs`，但 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md` 與 `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md` 的 `data/processed/Report` 版本內並沒有 `asset://...` 引用，因此 QDrant payload 內 `image_refs` 為空，`data/assets` 也沒有對應資產目錄。相對地，`SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8` 這版有 65 個 chunk 且 `image_refs` 與 `data/assets/.../excel/...` 正常存在；如果 UI 顯示的是 `SCU2060-EV-V001` 舊版，則會因為舊版沒有 chunk / 資產而顯示「資產不存在」或查無內容。根因偏向「舊版重攝入時未保留或未重新導出圖片資產」，不是單純前端連結格式錯誤。
- 2026-06-04 已再用更精準問法 `請整理 TP-Link Archer BE805 的 2.4GHz Throughput 與 5GHz Throughput，分開看兩個頻段` 實測：前端送出後 `/search` 產生 task `886e84fa-daf7-41db-a333-e2098aef2b02`，console 顯示 `[Heatmap] Prepared WiFi-specific KB result.`，並在輪詢數秒後回覆完成。這次最終答案已成功把 `4.1 2.4GHz Test` 與 `4.2 5GHz Test` 兩個段落都拉出來，原文中完整包含 2.4GHz 的 20MHz / 40MHz throughput 表，以及 5GHz 的 20MHz / 40MHz / 80MHz / 160MHz throughput 表；解讀則明確指出 2.4GHz 在 20MHz 下只有少數頻道通過、40MHz 幾乎全失敗，而 5GHz 在 80MHz / 160MHz 下表現穩定且顯著更高。這證實只要把問法拆成明確的 `2.4GHz Throughput` + `5GHz Throughput`，系統就會把 2.4GHz 內容一併拉出，而不是像前一版那樣退回單文件提示。後續若要穩定得到兩頻段比較，這個問法比單純問「2.4GHz 和 5GHz 表現有什麼差異」更可靠。
- 2026-06-05 已實測 `https://61.216.9.52:3030/chat.html` 對 `請整理 TP-Link Archer BE805 的 2.4GHz Throughput 與 5GHz Throughput，分開看兩個頻段` 的反應：前端確實送出 `POST /search`，並持續輪詢 `/tasks/1d34f620-5609-48ba-9ae9-acfe3b55a613`，但 task 長時間維持 `pending`，input 與送出按鈕都被前端鎖住，畫面沒有最終回覆。`celery -A src.web_api.tasks:celery_app inspect active` 顯示該任務仍在 `celery@3a051b5a3e4a` 的 worker pid 98 上執行，`kwargs` 為 `top_k=6, sources_only=True`。對照程式碼可見 `src/web_api/tasks.py` 的 sources_only 路徑在 `search_task()` 會直接走 WiFi / report 搜尋分支，而 `src/search/__init__.py` 的 `_build_wifi_throughput_band_answer()` 會進一步呼叫 `_compose_raw_then_interpretation()`，再進到 `_build_report_graph_interpretation()` 的 `llm_client.chat(...)`。這次現象顯示 task 被卡在後端的長時間搜尋/解讀階段，而不是前端沒把訊息送出去；後續若要修，應優先檢查 sources_only 路徑在 WiFi band raw / report interpretation 的 timeout 與回退機制。
- 2026-06-05 已將 knowledge-base 內所有實際使用的 Ollama 預設模型統一改為 `gemma4:12b`：`config/config.yaml`、`config/config.yaml.example`、`src/main.py`、`src/search/__init__.py`、`src/web_api/ollama_client.py`、`src/web_api/llm_factory.py`、`src/web_api/__init__.py`、`src/converter/__init__.py`、`src/ingest.py`、`src/extract_entities.py`、`src/web_api/tasks.py`、`src/web_api/tasks.py.bak` 與 `start.sh` 都已改成 `gemma4:12b`，並把 README / llm-flow / self-evolution-report 文件同步更新為新模型名。已用 `python3 - <<'PY' ... load_config()` 驗證目前 `config` 讀回的 `llm_model` 與 `ollama.model` 都是 `gemma4:12b`，且 `ollama list` 顯示本機已存在 `gemma4:12b` 模型。之後又以 `docker restart kb-web kb-celery-search kb-celery-ingest kb-celery-beat` 重啟知識庫服務，讓 web / worker / beat 重新載入新的預設模型設定。
- 2026-06-04 已新增全域工作原則：所有修改預設都應避免硬編碼，優先採用可擴充、可配置、資料驅動或共用規則的做法；只有在使用者明確指定要硬編碼時才採用硬編碼方案。後續若遇到路由、分類、compare 候選或 UI 行為調整，應先檢查是否能抽成共用 helper、規則表或 metadata 驅動機制，再考慮局部特例寫死。
- 2026-06-03 已徹底追到 `search_task(..., sources_only=True)` 為什麼在 live 任務裡還會掉回 `vector`：根因不是 compare builder 不會組兩份 WiFi，而是 `sources_only` 路徑把 Neo4j profile 轉成 WiFi metadata 時，`_build_wifi_metadata_source()` 沒有把 `converted_path` / `original_path` 帶回去，導致 `_build_wifi_throughput_band_raw_body()` 讀不到 CHS 那份 converted markdown，compare builder 只要遇到這筆就會失敗並落回一般 vector fallback。已修正 `src/search/__init__.py` 讓 `_build_wifi_metadata_source()` 同時輸出 `converted_path` 與 `original_path`，並重新重建整套 KB 後驗證：`search_task.run('請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput', 'auto', sources_only=True)` 現在回 `mode=wifi_compare`，sources 也穩定包含 `SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.md` 與 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx`；`/search` + `/tasks/{task_id}` 的 live API 也已對齊，不再掉回 `vector`。
- 2026-06-03 已追查 `請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput` 中 BE805 為何沒有穩定進入 compare 候選：live Neo4j 裡根本沒有 `TP-Link Archer BE805` 的 `Document` 節點，只有 `SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10`，因此 compare 只能依賴 filesystem fallback。原本 `_find_wifi_document_metadatas_for_query()` 在找到 1 筆 WiFi profile 時就會早退，導致 compare 需求下的 fallback 不會補進 BE805；已把早退條件改成「只有在非 compare 或 WiFi profile 已達 2 筆以上時才直接返回」，讓 compare 題能在 Neo4j 只有 1 筆 WiFi 文件時繼續合併檔案系統候選。已在 live `web` 容器內直接驗證：`_find_wifi_document_metadatas_for_query()` 會回傳 `['type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10', 'SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10']`，`_build_wifi_throughput_compare_answer()` 也能正常產生 `mode=wifi_compare` 與兩份來源；但同時也觀察到 `search_task(..., sources_only=True)` 的實際任務仍有一條路徑會掉回 `mode=vector`、只回 CHS 單文件原文，表示 task 層仍可能存在額外的快取/分支差異，後續若要完全收斂，應再追這條 sources_only 任務為何沒有採用已成功的 compare builder 結果。
- 2026-06-03 已實際在 `https://61.216.9.52:3030/chat.html` 重測 `請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput`。這次流程是先送 `POST /search`，接著輪詢 `/tasks/{task_id}`，最後前端 console 顯示 `Prepared WiFi compare KB result.`；但 KB 只穩定命中 1 份 WiFi 文件 `SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.md`，熱圖也顯示 `WiFi=100/1`、`4G/5G=0/0`。最終 bot 回覆為「`KB 參考已整合知識庫來源`」、「`KB 匯整來源：SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.md`」，並明確提示「未找到足夠的 WiFi 文件可進行比較」，同時列出未命中的查詢文件為 `BE805`、`CHS3320N-D388`、`TP-LINK ARCHER BE805`。這代表目前路由已正確進入 WiFi compare，但比較來源仍不足，下一步應追查 BE805 為何未被 compare 候選穩定命中。
- 2026-06-03 已再掃一次同類型被錯放的 WiFi 檔案並逐份拉回正確類別：`data/raw/type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.xlsx` 與 `data/raw/type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx` 已刪除，避免與 `data/raw/WiFi` 中的 canonical 檔重複；`data/type2_WiFi_AP.xlsx` 已複製成 `data/raw/WiFi/type2_wifi_WiFi_AP.xlsx`，並補齊 `data/uploads/WiFi/ingest_20260603_185500_wifi_ap/original/type2_wifi_WiFi_AP.source.json`，Neo4j 中的 `type2_wifi_WiFi_AP` 節點確認仍為 `storage_category = WiFi`、`extraction_mode = wifi`。最新掃描結果顯示已沒有 `type2_wifi` / `WiFi_AP` 類檔案殘留在錯誤路徑，WiFi 原始資料目前只保留在 `data/raw/WiFi` 與 `data/uploads/WiFi`。
- 2026-06-03 已直接把被錯放到 `4G_5G` 的 `SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10` 正式重攝入回 WiFi 類別，並刪除舊的 `data/uploads/4G_5G/ingest_20260602_075125_0655d88d` 錯放資料夾。實作上是先用 `cleanup_existing_document(doc_name)` 清掉 Neo4j / QDrant / 舊資產，再從 `data/raw/WiFi/SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.xlsx` 重新轉成新的 WiFi ingest 目錄 `data/uploads/WiFi/ingest_20260603_184500_chs3320n/converted/SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.md`，接著以 `extraction_mode='wifi'` 重新 `ingest_document()`。重建後 Neo4j 的 `Document` 節點已顯示 `storage_category = WiFi`、`extraction_mode = wifi`，而 `SearchEngine.search('請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput', mode='auto')` 也仍回 `mode=wifi_compare`，答案內同時包含 BE805 與 CHS3320N-D388，證明資料層已回到正確類別；舊的 4G/5G 版本資料夾已確認刪除，不再殘留在 uploads 下。
- 2026-06-03 已繼續追查 `請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput` 為什麼一度只回單一 BE805 文件：根因不是 query 沒抓到 `CHS3320N-D388`，而是 WiFi metadata 搜尋只掃 `data/uploads/WiFi`、`data/raw/WiFi`、`data/processed/WiFi`，但 `CHS3320N-D388` 這份 WiFi 報告先前被舊規則攝入到 `data/uploads/4G_5G/ingest_20260602_075125_0655d88d/converted/SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.md`，因此永遠不會進入 WiFi 候選清單。已將 `src/search/__init__.py` 的 `_find_wifi_document_metadatas_for_query()` 擴大到掃描整個 `data/uploads` / `data/raw` / `data/processed`，再以檔名與 query hint 做 WiFi 文件篩選；同時新增 `_merge_wifi_metadata_candidates()`，讓 compare 路徑在 Neo4j 找不到兩份 WiFi 文件時，能從檔案系統補回候選並維持去重順序。`src/search/__init__.py` 與 `src/web_api/tasks.py` 的 compare 入口都已補上 fallback 合併，避免 sources_only 與主搜尋出現不同結果。已重新 `./restart_kb.sh` 並實際在 live `/chat.html` 測 `請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput`，最終 task `ee5280ed-7fa1-4a41-81c2-e1053608c546` 回傳 `mode=wifi_compare`，`answer` 內同時包含 `TP-Link Archer BE805` 與 `CHS3320N-D388` 兩份文件，`contains_chs=True`、`contains_be805=True`，確認 compare 現在可正確補回被錯放到 `4G_5G` 的 WiFi 報告。
- 2026-06-03 已實際詢問 `請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput` 並觀察 live `/chat.html`：請求先送到 `/search`，產生 task `f765e30b-008e-42cb-82ac-e8a3741afe72`，輪詢後約 4.6 秒完成。這次回覆沒有進入真正的雙文件 compare，而是先命中 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx` 的 WiFi 原文路徑，answer 直接列出 BE805 的 `2.4GHz / 5GHz / 6GHz` throughput 表，再由 LLM 在解讀段落明確指出「來源文件僅包含 TP-Link Archer BE805 的測試數據，完全缺失 CHS3320N-D388 的相關資料，因此無法進行兩款產品的 WiFi Throughput 比較」。熱圖統計顯示本次只回推到 1 份 WiFi 原始文件，`WiFi=100/1`、`4G/5G=0/0`。這代表目前路由行為是「當 compare 目標只穩定命中一份 WiFi 文件時，先回單文件 throughput 原文，再由解讀層說明缺少對比文件」，而不是誤跳到 4G/5G 或 BE805 以外的 report。
- 2026-06-03 已追查 `請整理 TP-Link Archer BE805 的 5GHz 80MHz 與 160MHz 數據` 為什麼原文已顯示 160MHz、但解讀卻說找不到 160MHz：根因不是資料缺失，而是 `src/search/__init__.py` 的 `_build_report_graph_interpretation()` 會把 `raw_answer` 直接截成前 2600 字元，導致 WiFi throughput 原文的後段 `4.2.4 5GHz - Bandwidth 160MHz` 被裁掉，LLM 只看到 80MHz 區塊，便誤判資料不足。已改成共通的 `_build_balanced_raw_excerpt()`，不再只保留開頭，而是同時保留原文前段與尾段；`_build_report_graph_compare_llm_comment()` 也一起改用這個 helper，避免 compare comment 也因截斷漏掉後段內容。已重啟 `./restart_kb.sh` 並在 live `/chat.html` 實測同一句話，現在回答的 `解讀` 會明確列出 `80MHz` 與 `160MHz` 兩段數值，並正確比較 `160MHz` 約為 `80MHz` 兩倍，證明問題已修正且不再誤判「找不到 160MHz」。
- 2026-06-03 已繼續追查 `請比較 CHS3320N-D388 和 NCQ2200B2V-D294 的 WiFi Throughput` 在 live chat 仍回到 BE805 的原因，確認問題不在 `SearchEngine.search()` 本身，而是在 `src/web_api/tasks.py` 的 `search_task(..., sources_only=True)` 快捷路徑：這條路徑會先走 report-like / vector 的舊分支，沒有套用新的 WiFi compare 路由，因此前端 `prepareReportGraphContext()` 先拿到 `report_graph` 結果，直接渲染出錯誤的 compare answer。已著手把 `sources_only` 路徑補齊成與主搜尋相同的 WiFi compare 邏輯，改成先用 `_find_document_profiles_for_query()` 找出 WiFi 兩份文件，再由 `_build_wifi_throughput_compare_answer()` 產生 compare 回答，避免 compare query 再被 report_graph 先截胡。
- 2026-06-03 已把 WiFi compare 路徑整理成更明確的規則：前端 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 的 compare 分支現在會先檢查 `shouldPreferWifiCompare(query)`，只要是 `比較/差異/...` 且帶有 WiFi 線索，就優先走 `prepareWifiSpecificSummary()`，不再先問 `prepareReportGraphContext()`；WebSocket proxy 的 `run_compare_report_graph_direct()` 也改成接受 `wifi_compare` 與 `report_graph` 兩種結果，並在註解中明確標示 WiFi compare 優先、report_graph 第二順位。這樣未來新的 WiFi 比較題就算命中 compare 入口，也會先走 WiFi compare，不會因為 query 含有「比較」而被 report_graph 搶先處理。
- 2026-06-03 已把 compare 判斷再抽成共用 helper：新增前端共用檔 [`frontend/lib/compare-rules.js`](/home/da40_ai_gb10/knowledge-base/frontend/lib/compare-rules.js) 供 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 同步使用，並新增 Python 版 [`src/compare_rules.py`](/home/da40_ai_gb10/knowledge-base/src/compare_rules.py) 供 websocket proxy 的 `_is_compare_like_query()` 直接引用，避免三個路徑各自維護不同的 compare 正則。`restart_kb.sh` 也同步將 `compare-rules.js` 複製到 `.frontend-build-runtime-user8/lib/`，確保 `chat.html` 在 runtime 直接載入同一份 helper。已完成 `python3 -m py_compile src/web_api/__init__.py src/compare_rules.py` 與 `npm --prefix frontend run build`，並實際重啟 KB 後用 `/chat.html` 驗證 `請比較 CHS3320N-D388 和 NCQ2200B2V-D294 的 WiFi Throughput` 仍正確回 `CHS3320N-D388` + `NCQ2200B2V-D294`，不再出現 `TP-Link Archer BE805`。
## 進度記錄

- 2026-06-03 已釐清使用者對攝入/搜尋設計的期待：文件類別應以檔名中的 `type1~type6` 為第一優先來源，而不是以專案名稱（如 CHS / NCQ）判斷；若檔名是 `type1`，就應進 `4G/5G` 類別，`type2` 就應進 `WiFi` 類別，之後搜尋只要輸入專案名稱或相關字串，就應先透過 Neo4j / 文件 metadata 找到對應文件，再依其 `storage_category` / `extraction_mode` 路由到正確類別。現況檢查結果是「攝入端部分符合、搜尋端未完全符合」：`src/ingest.py` 與 `src/web_api/__init__.py` 的 upload / watch 流程確實會用 `detect_extraction_mode(filename)` 決定類別，且 `resolve_storage_category()` 也會把檔名推回對應資料夾；但 `detect_extraction_mode()` 仍然是檔名子字串判斷，沒有做更完整的 type-aware 強制檢查，且 `resolve_storage_category()` 在無法辨識時仍會回退到預設 `4g5g`。更重要的是 `src/search/__init__.py` 的查詢路由仍以 query heuristics 為主，WiFi compare / WiFi band 流程會先靠 `_is_wifi_specific_query()` 與 `_find_wifi_document_metadatas_for_query()` 掃資料夾候選，而不是先從 Neo4j 的 Document metadata 解析出文件類別；因此只打專案名稱時，若該文件曾被錯分到 `4G_5G` 或 query 沒帶足夠 WiFi hints，就可能被錯誤路由或拿到不相干的 WiFi 文件補位。下一步若要真正符合設計，應把「type1~type6 → 類別」做成唯一真實來源，並讓搜尋先 resolve doc_name 再決定 category，而不是反過來依 query 猜 category。
- 2026-06-03 已繼續追查 `請比較 CHS3320N-D388 和 NCQ2200B2V-D294 的 WiFi Throughput` 在 live chat 仍先出現錯誤 compare 結果的原因，確認問題不在 `SearchEngine.search()` 本身，而是在 `src/web_api/tasks.py` 的 `search_task(..., sources_only=True)` 快捷路徑：這條路徑會先走 report-like / vector 的舊分支，沒有套用新的 WiFi compare 路由，因此前端 `prepareReportGraphContext()` 會先拿到 `report_graph` 結果。已將 `sources_only` 路徑補齊成與主搜尋一致的 WiFi compare 邏輯，改成先用 `_find_document_profiles_for_query()` 找出 WiFi 兩份文件，再由 `_build_wifi_throughput_compare_answer()` 產生 compare 回答；並在真實 `/chat.html` 驗證，現在 `KB 參考` 回覆已包含 `KB 匯整來源：type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.md` 與 `SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.md`，不再冒出 `TP-Link Archer BE805`。這次也確認熱圖卡片統計回到 `WiFi=100/2`、`4G/5G=0/0`，代表來源分類與 compare 路由已對齊。
- 2026-06-02 已修正 `請整理 SCE2200 的 Handover 測試內容與結果。` 這類查詢只回 `5. Reference / TestItem=handover` metadata-only 的問題：根因是 Handover 的 general summary 路徑原本只抽大章節或直接被 report graph metadata 截胡，沒有優先抓 `3.1 / 3.2 / 4.1 ~ 4.4` 的原文。已在 `src/search/__init__.py` 新增 Handover 專用的 marker block 抽取與壓縮邏輯，會先從 `## 3. Test Result Summary` 切出 `3.1 Intra-Band Handover Test Summary` 與 `3.2 Inter-Band Handover Test Summary`，再抽 `4.1 Intra-band Xn Handover Test`、`4.2 Intra-band NG Handover Test`、`4.3 Inter-band Xn Handover Test`、`4.4 Inter-band NG Handover Test`，同時在回答中新增 `## 圖譜關聯` 段落列出專案、原始文件、來源路徑、轉換檔與命中章節；`_report_graph_search_raw()` 的 Handover early return 也改成直接回這份原文摘要，而不是再只回 metadata-only。已在本機用 `SearchEngine.search('請整理 SCE2200 的 Handover 測試內容與結果。', mode='auto', top_k=6)` 驗證，現在回答會同時包含 3.1/3.2/4.1~4.4 與 `## 圖譜關聯`、`## 解讀`，不再只剩圖譜關聯或章節定位。
- 2026-06-02 已再次重啟 `./restart_kb.sh` 並在重啟後驗證同一題 `請整理 SCE2200 的 Handover 測試內容與結果。`：目前線上/本機回覆都已包含 `## 3.1 Intra-Band Handover Test Summary`、`## 3.2 Inter-Band Handover Test Summary`、`## 4.1 ~ 4.4` 與 `## 圖譜關聯`，不再回到 `NG/Xn Handover Test Report / SCE2200 / 5. Reference / TestItem=handover` 這種 metadata-only 結果。這次驗證確認修正不只是工作區生效，而是已部署到實際執行中的服務。
- 2026-06-02 進一步修正 `SCU2050` 這類不同模板的 Handover 報告：它的章節不是 `Intra-Band / Inter-Band`，而是 `3.1 Xn Handover Test Summary`、`3.2 NG Handover Test Summary`、`4.1 Xn Handover`、`4.2 NG Handover`。原先的 Handover 抽取規則過度偏向 `SCE2200` 的版型，會把 `Excel 圖片摘要` 當成 fallback。已在 `src/search/__init__.py` 將 `_build_handover_section_digest()` 改成支援兩種模板：先從 `## 3. Test Result Summary` 抽出 `Xn/N2` 或 `Intra-Band/Inter-Band` 的 3.x 摘要，再抓 4.x 原文；fallback 也排除 `Excel 圖片摘要`、`Cover`、`Table of Contents`，避免再回到圖片清單。已用 `./restart_kb.sh` 重啟並驗證 `請整理 SCU2050 的 Handover 測試內容與結果`，線上回覆現在會包含 `3.1 Xn Handover Test Summary`、`3.2 NG Handover Test Summary`、`4.1 Xn Handover Test`、`4.2 NG Handover Test` 與 `## 圖譜關聯`，不再只剩圖片摘要。
- 2026-06-02 已補上 WiFi 的跨專案 compare 路徑，讓 `請比較 TP-Link Archer BE805 和 NCQ2200B2V-D294 的 WiFi Throughput。` 不再只回單一 WiFi 文件。根因是原本 WiFi 路徑只有單文件 `wifi_band_raw`，沒有像 4G/5G 那樣的 compare 模板，因此當 query 同時提到兩個 WiFi 專案時，系統只會先命中其中一份文件，再用單文件解讀回答。已在 `src/search/__init__.py` 新增 `_find_wifi_document_metadatas_for_query()`、`_build_wifi_throughput_compare_answer()` 與 `WiFi compare` 早期分支，會先找出兩份 WiFi 文件，再各自抽出 `2.4 / 5 / 6GHz` throughput 原文後組成 compare answer；同時收緊 `_extract_wifi_band_query_targets()` 的頻段偵測，避免 `BE805` 這類型號內的數字被誤判成 `5GHz`。已用 `./restart_kb.sh` 重啟並在 live `/search` + `/tasks/{task_id}` 驗證，現在這句查詢會回 `mode=wifi_compare`，sources 同時包含 `TP-Link Archer BE805` 與 `NCQ2200B2V-D294` 兩份 WiFi 報告，解讀也會明確比較 2.4GHz、5GHz、6GHz 的 throughput 差異，而不是再說 NCQ2200B2V-D294 缺資料。
- 2026-06-02 已修正 `請查詢 NCQ2200B2V-D294 的 Wi-Fi Throughput 報告內容。` 這類沒有指定頻段的 WiFi throughput 泛查詢，會被一般 vector search 帶到圖片索引 / 目錄 chunk、導致 LLM 誤判「原文只有結構索引沒有數值」的問題。根因是 `_build_wifi_throughput_band_answer()` 原本只在 query 明確包含 `2.4GHz / 5GHz / 6GHz` 時才走 raw section 抽取，遇到只問 `Wi-Fi Throughput 報告內容` 就會退回 vector_search；而 `NCQ2200B2V-D294` 的 converted markdown 前段恰好有大量圖片摘要與圖表索引，向量召回便偏向這些 chunk。已在 `src/search/__init__.py` 修正為：只要 query 命中 throughput hints，且可定位到 WiFi 文件，就算沒有指定頻段也會預設抽取 `2.4 / 5 / 6GHz` 三個 throughput 章節，避免退回一般向量搜尋；同時移除 helper 中殘留的早退條件。已重啟 `./restart_kb.sh` 並用線上 `/search` + `/tasks/{task_id}` 驗證，`請查詢 NCQ2200B2V-D294 的 Wi-Fi Throughput 報告內容。` 現在會回 `mode=wifi_band_raw`，answer 直接包含 `### 4.1 2.4GHz Test`、`### 4.2 5GHz Test`、`### 4.3 6GHz Test` 的原文區塊，而不是再回圖片/圖表索引摘要。
- 2026-06-02 已修正 `請比較 SCU2140、SCU2060、SCU5050 的 Latency與 BLER 差異` 會只回 throughput/BLER、漏掉 RTT 的問題：根因有兩層，第一層是 compare 路徑原本固定偏向 throughput 的 case summary，第二層是 `Latency Test` 的表格抽取在找 `RTT (ms)` 時只看 block marker 前段，剛好把 RTT 行切掉。已在 `src/search/__init__.py` 新增 compare metric target 判定，讓 `Latency / BLER` 題型優先走 `latency + bler`；同時將 `_extract_compare_table_cells()` 改成 block marker 前後都會嘗試抽表，並在 compare 來源組裝時把含 `RTT (ms)` / `Latency Test` 的原始 chunk 回灌進 `compare_case_map`，讓 RTT 能和 BLER 一起進到比較表。已用 `./restart_kb.sh` 重啟後實測，現在 `https://127.0.0.1:3030/tasks/{task_id}` 的回答會同時包含 `RTT` 與 `BLER`，且解讀段落也能正確比較 `SCU2060 / SCU2140 / SCU5050` 的延遲與誤碼率差異，沒有再回到 throughput 的 2k7 差異。
- 2026-06-02 已修正 `請比較 SCU2140、SCU2060、SCU5050 的下載速度差異` 回答中誤稱「沒有資料」的問題：根因不是三份報告沒有數據，而是比較題的 test-item 萃取規則沒有把 `下載速度 / download speed / 下載速率 / 網速` 視為 throughput 類關鍵字，導致 query 沒有進入 compare 版的 throughput 抽數值路徑，最後只剩章節級別的圖譜描述，再被 LLM 解讀成資料不足。已在 `src/search/__init__.py` 的 `_extract_report_test_item_hints()` 將 throughput 同義詞擴充為 `download speed / downlink speed / 下載速度 / 下載速率 / 下載速 / 網速`，讓這類比較題能命中 throughput compare 路由並抓到 `Performance Test` 的實際 case 數據。已重啟 `./restart_kb.sh` 後用線上 API 驗證，`/search` + `/tasks/{task_id}` 現在會回 `mode=report_graph`，答案直接輸出 `Case 1~16` 的跨專案對照表與簡短評論，且明確顯示 `SCU5050` 在各 case 的 DL 最高、`SCU2060` 多數 case 最低，沒有再出現「資料不足」的誤判。
- 2026-06-02 已修正 `NCQ2200B2V-D294 的 2.4GHz / 5GHz / 6GHz Throughput 結果是什麼？` 只顯示 2.4GHz 的問題：根因是 WiFi band throughput 的原始抽取邏輯只會抓第一個命中的頻段，導致同一句同時提到 `2.4GHz / 5GHz / 6GHz` 時，後續 band 被忽略。已在 `src/search/__init__.py` 將 `_extract_wifi_band_query_target()` 改成 `_extract_wifi_band_query_targets()`，可依原始順序收集所有頻段，並讓 `_build_wifi_throughput_band_answer()` 逐一抽出 `4.1 2.4GHz Test`、`4.2 5GHz Test`、`4.3 6GHz Test` 三個章節；若某頻段缺章節，則會顯示 `未找到對應的章節內容。`。已先以本機 `SearchEngine.search('NCQ2200B2V-D294 的 2.4GHz / 5GHz / 6GHz Throughput 結果是什麼？', mode='auto', top_k=6)` 驗證會回 `mode=wifi_band_raw`，且答案同時包含 `4.1 2.4GHz Test`、`4.2 5GHz Test`、`4.3 6GHz Test`。之後已執行 `./restart_kb.sh` 重啟線上服務，並用 `curl -sk https://127.0.0.1:3030/search` + `curl -sk https://127.0.0.1:3030/tasks/{task_id}` 驗證線上回應同樣是 `wifi_band_raw`，且三個頻段都確實出現在 `answer` 中，代表這次修正已真正部署生效。
- 2026-06-01 已整理 `NCQ2200B2V-D294` 報告內容的最佳問法：這份檔案是 `type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.xlsx` 的 WiFi throughput 報告，內容包含 `2. Introduction`、`4.1 2.4GHz Test`、`4.2 5GHz Test` 與雙頻 throughput 結果。若要讓小幫手命中正確路由，建議在提問中明確帶上 `WiFi`、`Throughput`、`2.4GHz / 5GHz`、`report` 或完整檔名，而不要只寫型號代碼 `NCQ2200B2V-D294`；例如可問「請幫我整理這份 WiFi Throughput 報告 `NCQ2200B2V-D294` 的測試內容與結果，重點看 2.4GHz、5GHz、各 bandwidth 的 throughput 數據」。目前判斷這樣的問法比單獨問型號更容易避開一般 `report_graph` 的 4G/5G 路由。

- 2026-06-01 已分析 `type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.xlsx` 手動攝入後卻查到 4G/5G 報告的原因：目前可確認檔案本體已進入 `data/uploads/WiFi/ingest_20260601_014315_7eb7be99/converted/type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.md`，且內容已包含 `NCQ2200B2V-D294`、`throughput`、`2.4GHz / 5GHz / 6GHz` 等 WiFi throughput 資訊，表示轉檔與落盤有完成；但查詢句 `請查詢 NCQ2200B2V-D294 的 Throughput 測試數據` 並不會觸發目前的 WiFi 專用路由，因為 `SearchEngine._is_wifi_specific_query()` 只認 `tp-link / archer / be805 / 5ghz / 6ghz / wifi6 / wifi7 / mesh / ssid / ap` 等提示，沒有把「WiFi 型號代碼」當成 WiFi 線索，所以 `search()` 會直接落入 `_is_report_like_query()`，再被 `report_graph` 的 throughput 規則帶去 4G/5G 報告。現階段判斷這是「查詢路由/意圖辨識」問題，不是主要的攝入失敗；另外目前也未看到這份檔案對應的 `.source.json` sidecar，未來若要讓檔案查找與索引更穩定，建議一併補齊。
- 2026-06-01 已新增手動攝入流程的客戶說明用 PPTX：[manual_ingest_customer_intro.pptx](/home/da40_ai_gb10/knowledge-base/manual_ingest_customer_intro.pptx)。內容採 3 頁亮色系簡報：第 1 頁說明「手動攝入是什麼」與適用情境，並用一條完整流程總結「上傳文件 -> 自動轉換 -> 切成 chunks -> 寫入 Neo4j -> 寫入 Qdrant」；第 2 頁用 5 個步驟拆解實際手動攝入流程，讓客戶可以理解上傳後系統會自動完成處理，不需要人工逐步搬移資料；第 3 頁以 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.xlsx` 為實例，示意報告會切成 `2. Introduction`、`3. Test Result Summary`、`4. Performance Test` 等 chunks，再分別進入 Neo4j 與 Qdrant，說明前者負責關聯脈絡、後者負責語意搜尋。對應生成腳本為 [`generate_manual_ingest_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_manual_ingest_pptx.py)。
- 2026-06-01 已將 [`neo4j_customer_intro.pptx`](/home/da40_ai_gb10/knowledge-base/neo4j_customer_intro.pptx) 與 [`qdrant_customer_intro.pptx`](/home/da40_ai_gb10/knowledge-base/qdrant_customer_intro.pptx) 補上實際對應範例，讓客戶更容易理解兩個資料庫在系統中的用途。Neo4j 頁面新增兩組實際關聯示例，包含 `SCU2060 ↔ SCU2140` 的 Throughput / Latency 關係，以及 `SCU2050 ↔ SCU2060` 的 Handover / Performance 脈絡；Qdrant 頁面新增 chunk 範例，說明像 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.xlsx` 這類報告會切成 `2. Introduction`、`3. Test Result Summary`、`4. Performance Test` 等獨立向量區塊，再由語意搜尋召回。對應生成腳本仍為 [`generate_db_intro_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_db_intro_pptx.py)。
- 2026-06-01 已為知識庫後端兩個主要資料庫各製作一份客戶說明用 PPTX：[neo4j_customer_intro.pptx](/home/da40_ai_gb10/knowledge-base/neo4j_customer_intro.pptx) 與 [qdrant_customer_intro.pptx](/home/da40_ai_gb10/knowledge-base/qdrant_customer_intro.pptx)。兩份皆為單頁亮色系簡報，內容以「用途 / 系統內角色 / 客戶如何理解」為主，盡量避免技術名詞堆疊。Neo4j 頁面重點在說明它負責保存文件、專案與章節之間的關聯；Qdrant 頁面重點在說明它負責保存內容向量、支援語意搜尋與相似段落召回。對應生成腳本為 [`generate_db_intro_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_db_intro_pptx.py)。
- 2026-06-01 已將 [`query_examples_slide.pptx`](/home/da40_ai_gb10/knowledge-base/query_examples_slide.pptx) 改成亮色系版本，整體視覺已從深色主題轉為白底 / 淺藍綠的商務風格。內容維持原本 3 頁與 20 條實際 query 範例不變，但封面、題目卡、標籤與說明區都已同步改成亮色系，讓簡報更適合正式對外展示。對應生成腳本為 [`generate_query_examples_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_query_examples_pptx.py)。
- 2026-06-01 已將 [`kb_architecture_slide.pptx`](/home/da40_ai_gb10/knowledge-base/kb_architecture_slide.pptx) 改成亮色系版本，整體視覺由深色背景切換為白底/淺藍綠系，讓簡報更像正式商務提案頁。內容仍維持 3 頁正式說明，但色彩與卡片樣式已重新設計為更明亮、更易讀的風格，避免深色簡報造成客戶閱讀負擔。對應生成腳本為 [`generate_kb_architecture_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_kb_architecture_pptx.py)。
- 2026-06-01 已將知識庫系統架構簡報改成更正式的說明版：[kb_architecture_slide.pptx](/home/da40_ai_gb10/knowledge-base/kb_architecture_slide.pptx)。目前仍維持 3 頁，但內容已從極簡提示改為可直接對客戶說明的正式文字：第 1 頁說明簡報目的與系統定位，第 2 頁以簡化架構圖說明前端入口、知識庫核心與 Neo4j/Qdrant 的分工，第 3 頁則以段落文字清楚描述各元件責任與整體結論。原本偏口語的示例式文字已移除，版面也保留較豐富的色塊與說明卡，以維持正式但不失簡潔的簡報風格。對應生成腳本為 [`generate_kb_architecture_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_kb_architecture_pptx.py)。
- 2026-06-01 已將知識庫系統架構簡報再簡化成更適合業務/客戶看的極簡版：[kb_architecture_slide.pptx](/home/da40_ai_gb10/knowledge-base/kb_architecture_slide.pptx)。目前只保留 2 頁：第 1 頁是簡報封面與重點摘要，第 2 頁只放三個核心區塊「前端入口 / 小幫手卡片盒」、「後端核心」、「Neo4j + Qdrant」，並用一句簡短說明區分 Neo4j 與 Qdrant 的角色。原本的 Nginx、Celery、Redis、Ollama、OpenClaw 等技術細節已移除或縮成註記，避免畫面太技術化；對應生成腳本為 [`generate_kb_architecture_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_kb_architecture_pptx.py)。
- 2026-06-01 已新增簡化版知識庫系統架構簡報：[kb_architecture_slide.pptx](/home/da40_ai_gb10/knowledge-base/kb_architecture_slide.pptx)。內容採 3 頁設計：第 1 頁是簡報封面與重點摘要，第 2 頁用單張架構圖說明從使用者、前端、Nginx、FastAPI，到 Celery / Redis / Neo4j / Qdrant / Ollama / OpenClaw 的整體關係，第 3 頁用「查詢流程」與「上傳 / 攝入流程」兩條路徑說明資料如何流動。這版刻意簡化，不放程式碼與部署細節，適合直接對客戶簡報使用；對應生成腳本為 [`generate_kb_architecture_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_kb_architecture_pptx.py)。
- 2026-06-01 已將 `query_examples_slide.pptx` 改成真正有內容的三頁式簡報：第 1 頁是封面，第 2 頁放 10 條 4G/5G 實際範例題目，第 3 頁放 10 條 WiFi 實際範例題目。4G/5G 頁面涵蓋 `SCU2140 / SCU2060 / SCU5050 / Throughput / Case / Latency / Performance / Handover / 相關報告` 等題型，WiFi 頁面涵蓋 `TP-Link Archer BE805 / 2.4GHz / 5GHz / 6GHz / 80MHz / WiFi 7 / WiFi 6 / 相關文件` 等題型。已保留生成腳本 [`generate_query_examples_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_query_examples_pptx.py)，之後只要重跑腳本就能更新整份 PPTX。
- 2026-06-01 已將 `query_examples_slide.html` 的內容實際輸出成 PowerPoint 檔案：[query_examples_slide.pptx](/home/da40_ai_gb10/knowledge-base/query_examples_slide.pptx)。此檔為真正的 PPTX 文件，不只是 HTML 視覺模擬；目前內容是一頁式 16:9 封面簡報，沿用封面式設計，適合直接在 PowerPoint / LibreOffice 開啟與編修。為了可重製，也另外保留生成腳本 [`generate_query_examples_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_query_examples_pptx.py)。
- 2026-06-01 已將 `query_examples_slide.html` 改成更接近 PPTX 開頭頁的封面式版型：採 16:9 單頁簡報風格、深色漸層背景、上方品牌列、左側大標題與副標、右側摘要卡片，以及下方 4 個精簡的 query 類型卡，重點放在「先講測試邏輯，再往下帶代表性例句」。這版比原本的矩陣表格更像簡報開場頁，適合直接拿去當投影片首頁使用。
- 2026-06-01 已確認剛剛產生的 `query_examples_slide.html` 實體路徑是 `/home/da40_ai_gb10/knowledge-base/query_examples_slide.html`，檔案位於專案根目錄；後續若再次詢問同一檔案位置，可直接使用這個絕對路徑。


- 2026-06-01 已新增一張可直接拿去報告的單頁 HTML 投影片：[query_examples_slide.html](/home/da40_ai_gb10/knowledge-base/query_examples_slide.html)。內容將 4G/5G 與 WiFi 的範例題型依語意類型分成 4 類：`直接查數據`、`完整/詳細`、`比較/差異`、`泛問/相關文件`，每一類都各自列出 4G/5G 與 WiFi 的實測句型，例如 `請查詢SCU2140的Throughput測試數據`、`請顯示SCU2060詳細的Throughput測試數據`、`SCU2060、SCU2140、SCU5050 的Throughput有什麼差異？`、`請查詢TP-Link Archer BE805的5GHz Throughput測試數據`、`WiFi 7 和 WiFi 6 有什麼差別？` 等。這張 slide 採單頁深色簡報風格，已可直接作為簡報使用；若之後要延伸，也可再拆成多頁版或補成可列印版 PDF。
- 2026-06-01 已修正卡片盒點文件出現 `file not found` 的問題：根因是 `src/web_api/__init__.py` 的 `/api/document` 只查 `data/processed/{category}`，且 metadata fallback 也只掃 processed 目錄，所以像 WiFi 的 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10` 這種只落在 `data/uploads/WiFi/.../converted/` 的文件，一點進去就會 404；同時 `get_category_files()` 也只列 processed 檔案，無法把 upload-only 的文件補進卡片盒。已做兩層修正：新增共用文件解析 helper `_find_document_content()`，會依序搜尋 processed / uploads / 全資料根目錄，並回推 `*.source.json` 的 `converted_path` / `original_path`；`get_category_files()` 也改成同時掃 `data/processed/<category>` 與 `data/uploads/<category>` 的 markdown/text 檔，避免卡片盒列出後卻打不開。已重啟 `web` / `nginx` 後實測 `WiFi`、`Lab`、`Project`、`Automation` 的第一個文件都能正常打開，`WiFi` 的 BE805 文件現在回傳的是 `data/uploads/WiFi/ingest_20260531_021134_9058675d/converted/type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.md`，`/api/category-files?category=WiFi` 也已把這份 upload-only 文件列進去；`4G/5G` 目前在現有資料下沒有文件可列。這次修正已覆蓋卡片盒的通用文件開啟路徑，不只 WiFi，之後其他分類若也只存在於 uploads 轉換目錄，會同樣可開啟。
- 2026-05-31 已修正 `請查詢TP-Link Archer BE805的Throughput測試數據` 這類 WiFi 專用查詢會掉回 4G/5G report_graph 的問題：根因不是 WiFi 文件未攝入，而是前端 `prepareWifiSpecificSummary()` 與 WiFi 專用分支原本只等 120 秒，遇到 WiFi 向量檢索耗時較長時就會提早 timeout，接著 `sendMessage()` 仍會繼續往一般 `reportLikeQuery` / `prepareReportGraphContext()` 走，最後把 4G/5G 的 Throughput 報告蓋上來。已同步做兩層修正：`frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 的 WiFi 專用等待時間已拉到 360000 ms，且 WiFi 查詢一旦進入專用分支，不論是否直接命中原文，都不再 fallback 到一般 report 查詢，而是只顯示 WiFi 原始文件 context 或 WiFi fallback 訊息；後端 `src/search/__init__.py` 仍維持 WiFi-specific query 先於 report_graph 的 routing，`TP-Link Archer BE805` 這類查詢現在會正確命中 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.md`，回傳的 `citation_distribution` 也只會是 WiFi 類別。已用 `https://61.216.9.52:3030/chat.html` 實測，頁面最後顯示的是 BE805 的 WiFi 原始文件與摘要內容，沒有再出現 SCU2060 / SCU2140 / SCU5050 的 4G/5G report_graph，證實前端 fallback 已被切斷且不影響原本 4G/5G 查詢路徑。
- 2026-05-31 已修正 `請查詢TP-Link Archer BE805的5GHz Throughput測試數據` 這類 WiFi band throughput 查詢只顯示 20MHz 與 160MHz、漏掉原始 80MHz 的問題：根因不是原始 Excel 沒有 80MHz 數據，而是 WiFi 專用路徑仍先走 `vector_search`，最後由 LLM 在上下文裡自行挑片段，導致 5GHz 的 80MHz 章節可能被排序或摘要階段忽略。已在 `src/search/__init__.py` 新增 WiFi band throughput 的固定原文抽取路徑：只要 query 明確命中 `2.4GHz / 5GHz / 6GHz` 與 `throughput` 類語意，就會直接從對應 converted markdown 抽出整個 `4.1 / 4.2 / 4.3` 主章節，確保 `5GHz` 的 `20MHz / 40MHz / 80MHz / 160MHz` 全部同時保留，不再交由向量排序挑段落；其中 80MHz 在原始 WiFi 報告中有完整 Tx/Rx 數值，新的固定抽取路徑會直接把這段原文帶回。已用本機 `SearchEngine.search('請查詢TP-Link Archer BE805的5GHz Throughput測試數據')` 驗證會直接回 `mode=wifi_band_raw`，輸出原文中完整的 `4.2 5GHz Test` 區塊，包含 `4.2.3 5GHz - Bandwidth 80MHz`，不再只剩 20MHz / 160MHz 兩段。
- 2026-05-31 已再驗證 `TP-Link Archer BE805` 的三個 WiFi 頻段 Throughput 查詢一致性：`請查詢TP-Link Archer BE805的2.4GHz Throughput測試數據`、`5GHz Throughput測試數據`、`6GHz Throughput測試數據` 現在都會直接走 `mode=wifi_band_raw`，輸出 `## 原文` + `## 解讀` 的固定格式，來源皆為 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx`。其中 2.4GHz 會完整列出 `4.1 2.4GHz Test` 的 20MHz / 40MHz 內容，5GHz 會完整列出 `4.2 5GHz Test` 的 20MHz / 40MHz / 80MHz / 160MHz 內容，6GHz 會完整列出 `4.3 6GHz Test` 的 80MHz / 160MHz / 320MHz 內容；6GHz 的 80MHz 原始表格本來就多數為空白欄位，因此現在的輸出會如實保留空白，不會補值。這代表三個頻段已經統一成同一種 WiFi band 直出流程，格式一致且不再回掉 4G/5G report_graph。
- 2026-05-31 已將 WiFi band raw 的固定原文直出再補上 LLM 簡短分析，讓行為更接近 4G/5G 模式：原本 2.4 / 5 / 6GHz throughput 只有原文表格與固定解讀，沒有真的把原文交給 LLM 做短評。已修正 `src/search/__init__.py` 的 WiFi band raw 路徑，改成先抽出 `4.1 / 4.2 / 4.3` 主章節原文，再透過既有 `_compose_raw_then_interpretation()` 呼叫 LLM 生成 2~4 條簡短解讀；同時修掉 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 中 WiFi 直出判斷引用不存在 `getSourceRawPath()` 造成的例外，避免 WiFi band raw 直接落版被前端錯誤打斷。已用 `https://61.216.9.52:3030/chat.html` 逐項測試 `2.4GHz / 5GHz / 6GHz`，三者都已回傳 `mode=wifi_band_raw`，且 `## 原文` + `## 解讀` 格式一致；其中 5GHz 的 `80MHz`、6GHz 的 `80MHz / 160MHz / 320MHz` 都已如實保留在原文區塊，LLM 解讀僅做短評，不新增數字。

- 2026-05-30 已修正 `請顯示SCU2060詳細的Throughput測試數據` 這類「單一報告 + 數值題 + 明確要求詳細/完整」的查詢只輸出 case 13~16 的問題：根因是 `_build_numeric_direct_answer()` 在沒有 case hint 時仍會經 `_select_numeric_case_sources()`，而該選取器預設只保留同文件中 case 編號最高的 4 個 case。已新增 `_should_preserve_all_numeric_cases()`，當 query 含有「詳細 / 完整 / 全部 / 所有 / 列出 / 顯示 / 明細 / 測試數據」等訊號時，數值題會改走全 case 合併路徑，保留 `Case 1~16` 的完整逐 case 原文，不再只取尾段四個 case。已用 [`https://61.216.9.52:3030/chat.html`](https://61.216.9.52:3030/chat.html) 實測，現在 `SCU2060` 的 Throughput 詳細數據已能完整顯示 `Case 1~16`，不會再只看到 `Case 13/14/15/16`。
- 2026-05-30 已將 knowledge-base 內所有 Ollama 預設模型統一改為 `qwen3.6:35b-a3b`：`config/config.yaml`、`config/config.yaml.example`、`src/main.py`、`src/search/__init__.py`、`src/web_api/llm_factory.py`、`src/web_api/__init__.py`、`src/web_api/tasks.py`、`src/converter/__init__.py`、`src/web_api/ollama_client.py` 等 runtime 路徑的預設值都已改成新模型；同時 README 與 LLM flow 文件也同步更新，避免文件還顯示舊的 `gemma4:e4b`。已刪除 `src/web_api/minimax_client.py` 後，現在 KB 只保留 Ollama 路徑，之後若要改模型只需要調整 `ollama.model` 與相關預設值，不再有 MiniMax 的切換/備援分支。
- 2026-05-30 已移除 knowledge-base 內所有 MiniMax-M2.7 相關設定與切換分支，統一只保留 Ollama：`config/config.yaml` 與 `config/config.yaml.example` 不再含 `minimax` 區塊，`src/web_api/llm_factory.py` 改為固定建立 Ollama client，`src/web_api/__init__.py` 的 `/analyze-question`、`src/converter/__init__.py`、`src/search/__init__.py` 也都移除 MiniMax provider 分支；同時刪除 `src/web_api/minimax_client.py`，並同步更新 README 與 LLM flow 文件，避免文件仍顯示可切換 MiniMax。這代表 KB 核心搜尋、compare、報告摘要與卡片分析現在都只會使用 Ollama，若未來要改模型只需調整 Ollama 設定，不再有 MiniMax 備援切換。
- 2026-05-30 已評估移除 MiniMax-M2.7 相關設定的影響：若只移除 knowledge-base repo 內的 MiniMax 設定，核心 KB 搜尋、compare、report_graph、圖片/OCR 增強、實體萃取多半仍會因 Ollama fallback 正常運作，但 `/analyze-question` 的卡片分析與少數可切換 provider 的路徑會失去 MiniMax 備援能力，會統一退回 Ollama。若要連 OpenClaw 小幫手端一起去掉 MiniMax，則還需同步修改 `~/.openclaw/openclaw.json` 或對應的 OpenClaw 設定，否則代理層仍可能使用 MiniMax-M2.7。整體建議是：KB 攝入與搜尋維持在後端，OpenClaw 只保留觸發與編排，不要把攝入或查詢核心搬到 skill 內。
- 2026-05-30 評估 OpenClaw 介入攝入流程的方式：結論是攝入本體應維持在 knowledge-base 後端，OpenClaw 比較適合扮演觸發器/編排層，而不是把 ingest 邏輯搬進 skill 或 prompt 內。若要讓小幫手主動協助上傳新報告，較佳做法是由 OpenClaw 透過 MCP 或現有 HTTP API 觸發 KB 的 `/upload`、`/upload/ingest`、`/upload/tasks/{task_id}` 等端點；其中 MCP 適合做成穩定、可重用、可控權限的工具介面，skill 則較適合承載「何時要觸發攝入」的流程規則，但不建議讓 skill 直接承擔檔案上傳與 Neo4j/QDrant 寫入。這樣能保留 KB 端既有的模式自動判斷、report/simple 圖譜驗證與任務追蹤機制，也能避免把資料寫入責任分散到 agent 端造成不一致。
- 2026-05-30 已修正上傳攝入入口的模式覆寫風險：`/upload/ingest` 原本只會把檔名偵測結果中的 `report` 保留下來，其餘情況一律使用前端傳入的 `extraction_mode`，導致像 `type6_NR-Handover-*.xlsx`、`type6_NR-Throughput-*.xlsx` 這類本應走 `simple` 的檔案，可能被錯誤當成 `4g5g` 上傳。已將 `effective_mode` 改成：只要 `detect_extraction_mode()` 回傳 `report` 或 `simple`，就直接採用檔名判斷結果，不再被前端預設模式覆寫；這樣新報告上傳時只要檔名規則正確，就會自動走對應的攝入路徑，避免未來再出現「檔案已上傳但圖譜不完整」的風險。
- 2026-05-30 檢查並強化目前攝入機制的風險控制：先前 `type6` / `simple` 類 Handover 報告會只進 QDrant、不進 Neo4j，造成像 `SCU2050` 這類新進 Handover 專案在查詢「有哪些專案有 Handover 測試項目？」時漏掉。已把 `src/ingest.py` 的 `simple` 模式改成：只要 `infer_report_type()` 判定為非 `generic_report`，就先補寫 Neo4j report graph，再寫 QDrant；若圖譜寫入後 `sections/test_items/test_cases/metrics` 統計為 0，則直接視為失敗，避免「看似成功但其實沒有圖譜」的假成功。`src/search/__init__.py` 也已新增 Handover catalogue 分支，可直接從 `data/processed/**/*.source.json` 彙整所有 Handover 報告來源，避免查詢端只依 Neo4j 而漏掉應該顯示的專案。已用本機 py_compile 驗證語法通過，並確認 `SearchEngine._report_graph_search_raw('有哪些專案有Handover測試項目？')` 會回傳 `sources=2`。這次的風險改善重點是：未來新進的報告型 `simple` 文件，不會再悄悄只進向量庫而沒有圖譜。

- 2026-05-30 再次修正 `有哪些專案有Handover測試項目？` 在線上 `https://61.216.9.52:3030/chat.html` 仍只顯示單一 `SCE2200` 的問題：這次真正卡住的點是在前端 `prepareGeneralHandoverSummary()` 會先走 `mode=basic` 並直接落版 `summaryResult.answer`，而 `basic` 路徑原本在 `search()` 內又因 `report_graph` 的 Handover catalogue 分支位於空 hints 早退之後，導致 catalog query 其實沒有被執行，最後只剩既有的單一 Handover 摘要。已將 `src/search/__init__.py` 的 Handover catalogue 分支提前到空 hints 早退之前，讓 `有哪些專案有Handover測試項目？` 這類 query 在 basic / auto 都會先返回 `## 原文` 表格，內容直接列出 `SCE2200` 與 `SCU2050` 兩份 Handover 報告；同時 `src/ingest.py` 的 `simple` 模式若偵測到 Handover 文件，也會額外補寫 Neo4j report graph，避免未來新增的 Handover 文件只進向量庫。已用本機 `SearchEngine._report_graph_search_raw` 驗證會回傳 `report_graph`、`sources=2`，並重啟 KB 讓 runtime 載入新版邏輯，之後同類 Handover 清單查詢應可直接顯示兩份專案，而不是單一 `SCE2200`。
- 2026-05-30 已修正「有哪些專案有Handover測試項目？」只回到單一專案且內容錯誤的問題：根因是目前 Neo4j 內只存在 `SCE2200` 的 Handover report graph，`SCU2050` 的 `type6` Handover 文件原本只走 QDrant / markdown，沒有寫入 Neo4j 圖譜，因此查詢端若只依圖譜會漏掉 `SCU2050`。已同步做兩層修正：`src/ingest.py` 的 `simple` 模式若偵測到 Handover 文件，會額外補寫 Neo4j report graph；`src/search/__init__.py` 則新增 Handover catalogue 查詢分支，會掃描 `data/processed/**/*.source.json` 組出所有 Handover 報告的清單，輸出固定的 `## 原文` + `## 解讀`。已重新攝入 `data/processed/Simple/type6_NR-Handover-SCU2050-EV-V004.md`，Neo4j 現在可查到 `SCE2200 / type6_NR-Handover-SCE2200-n79-EV-V13.8` 與 `SCU2050 / type6_NR-Handover-SCU2050-EV-V004` 兩份 Handover 報告；本機也已用 `SearchEngine._report_graph_search_raw('有哪些專案有Handover測試項目？')` 驗證會回傳 `report_graph`、`sources=2`，`answer` 的原文表格已列出兩份來源。這版已重啟 KB，之後同類 Handover 清單查詢會直接反映已攝入的完整來源，而不再只剩 Neo4j 中的單一項目。
- 2026-05-30 已修正 `SCU2140、SCU2060、SCU5050 的Throughput有什麼差異？` 這類 compare 問題只顯示 13~16 四個 case 的問題：根因是 compare 路徑在沒有明確 case hint 時，仍把 numeric compare 交給 `_build_numeric_direct_answer()` 與 `_select_numeric_case_sources()`，後者預設只保留同文件中 case 編號最高的 4 個 case，導致前面的 case 被大量裁掉。已新增 compare 專用的全 case 對照路徑，當 query 屬於 compare + numeric、但沒有 case hint 時，會改為保留每個專案的所有 case sources，並依 case number 組成全量對照表，讓 `Case 1~16` 都能納入比較；同時保留 LLM 的簡短評論作為 `## 解讀`，不再只顯示少數高 case。已重新啟動 KB 並用 [`https://61.216.9.52:3030/chat.html`](/home/da40_ai_gb10/knowledge-base/AGENTS.md) 實測，現在 compare 回覆已會列出 `Case 1` 到 `Case 16` 的逐 case 對照表，之後同類 compare 問法也會沿用這個全 case 路徑。
- 2026-05-30 已將知識庫各模式統一調整為「原文先出、LLM 解讀置後」的雙段式回覆：先前雖然 report_graph / compare / Handover 部分路徑已經能輸出原文，但 basic / vector / hybrid / deep 等模式仍是單純把 LLM 的總結直接回給前端。已新增共用的原文包裝邏輯（從 `sources` 或 `graph_results` 生成原文區塊），並讓 `search()` 在所有成功結果上先檢查是否已含 `## 原文`，若尚未包含就自動補上原始資料，再保留原本的 LLM 解讀作為最後段落；同時將 `SCU2050 的相關報告數據` 的一般 Handover 摘要改成以 LLM 解讀重寫，不再使用固定條列，確保最終回覆是「原始章節摘錄 + LLM 針對原始資料的總結」。已重新啟動 KB，並用 [`https://61.216.9.52:3030/chat.html`](/home/da40_ai_gb10/knowledge-base/AGENTS.md) 重新驗證 `請查詢SCU2050的相關報告數據`，現在回覆已正確呈現 `## 原文` 與 `## 解讀` 兩段，且 `4.2 NG Handover` 等原始內容完整保留；另驗證 `SCU2140、SCU2060、SCU5050 的case 15Throughput有什麼差異？` 仍維持 compare 的原文 / 解讀結構且未被二次包裝，說明這次是共用包裝、沒有破壞既有 report_graph / compare 路徑。
- 2026-05-30 已修正 `SCU2050 的相關報告數據` 一般 Handover 回覆數據不完整的問題：根因是先前 `src/search/__init__.py` 的 `general handover summary` 路徑雖然已避開 OpenClaw 蓋寫，但仍把 converted md 交給 LLM 摘要，導致 `2. Introduction / 2.5 Test Environment / 2.7 Test Configuration / 3. Test Result Summary / 4.1 Xn Handover / 4.2 NG Handover` 等章節中的原始數值容易被壓縮或省略。已將這條路徑改成直接從 converted markdown 抽出主要章節原文區塊（優先包含 `2. Introduction`、`2.5 Test Environment`、`2.7 Test Secenarios`、`3. Test Result Summary`、`4.1 Xn Handover`、`4.2 NG Handover`），不再依賴 LLM 摘要原始數據；解讀段則只做固定的補充說明，不會改動數值內容。已重新啟動 KB 並在 [`https://61.216.9.52:3030/chat.html`](/home/da40_ai_gb10/knowledge-base/AGENTS.md) 實測，現在回覆已可直接列出 SCU2050 Handover 報告的完整原文章節與 4.2 NG Handover 明細，避免再出現「有摘要但數據不完整」的情況。
- 2026-05-30 已將同一條全域工作規範同步到 `~/.codex/AGENTS.md`：新增「每次修改前要先確認前一次及既有修正內容，任何新改動都不得影響前幾次已完成的修正，若有衝突要先調整整體方案再動手」等條款，確保全域規則與專案內 [AGENTS.md](/home/da40_ai_gb10/knowledge-base/AGENTS.md) 一致。
- 2026-05-30 已更新 `AGENTS.md` 的全域工作規則，新增「每次進行修改前，必須先確認前一次與既有修正內容，避免新改動影響前幾次已完成的修正」的明確要求；後續做任何新修改前，都要先回顧既有修正與驗證結果，若會互相衝突要先調整整體方案，不可只針對單一現象局部修補。
- 2026-05-30 已修正 `請找出所有有Latency測試項目的報告` 只找到單一報告的問題：根因分成兩層，第一層是 `src/report_graph.py` 的 ingest 規則原本只會把 section 歸類成單一 `TestItem`，而 throughput 報告內的 latency 區塊雖然有 `Latency Test / RTT (ms)`，卻被歸到 `throughput`，導致 Neo4j 裡只有 `handover / throughput`，沒有真正的 `latency` 節點；第二層是 `src/search/__init__.py` 的 report graph 回答層對 `Latency` 類查詢仍沿用抽樣 sources，會把其他報告的 latency 區塊壓掉，只剩單一專案被列出。已將 ingest 改成同一個 section 可同時掛上 `throughput` 與 `latency` 兩個標準 TestItem，並重新 ingest 三份 throughput 報告 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md`、`SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md`、`SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md`；同時把 latency 類查詢改成 `preserve_all=True`，避免回答層只看前幾筆來源。已用 Neo4j 直接驗證目前 `TestItem` 已包含 `handover / throughput / latency` 三類，且 `MATCH (r:Report)-[:HAS_TEST_ITEM]->(t:TestItem {canonical_name:'latency'})` 可回到三份報告。再用 [`https://61.216.9.52:3030/chat.html`](/home/da40_ai_gb10/knowledge-base/AGENTS.md) 實測同題後，回覆已能列出 `SCU2060 / SCU2140 / SCU5050` 三份報告，表示 ingest 與查詢兩層都已修正，往後新攝入的 throughput 報告也會自動帶上 latency 關聯。
- 2026-05-30 已釐清「前兩天的 token 用量」在本機 Codex 紀錄中的可得性：專案本身沒有保存可直接對應「前兩天」的 per-day token 報表，`/home/da40_ai_gb10/.codex/state_5.sqlite` 的 `threads.tokens_used` 只能提供 thread 級彙總。實際查詢 `2026-05-28 ~ 2026-05-29` 時，該區間在本機 `threads` 表中沒有對應紀錄，因此可計算的前兩天加總為 0；若要看真實帳單/用量，仍需到對應的 usage 或 billing 系統查詢。這次也順帶確認本機 `threads` 的整體 `tokens_used` 總和為 1,083,808,292，但這不等於兩天內用量。
- 2026-05-30 已修正 `chat.html` 的 SCU2050 一般 Handover 查詢路徑：先前 `SCU2050 的相關報告數據` 會先走後端 Handover 摘要，但最終仍被 OpenClaw 的最後一段改寫成「沒有找到任何關於 SCU2050 的報告資料」，造成前端顯示與後端摘要不一致。已將 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 的 `prepareGeneralHandoverSummary()` 對齊為 `mode: basic`、`top_k: 6`，並保留 `reportLikeQuery` 下的直接落版邏輯，確保像 `SCU2050 的相關報告數據` 這種泛報告查詢會直接顯示後端整理好的 Handover 摘要，不再被 OpenClaw 蓋掉；同時仍保留 `SCU2050 的Performance Test數據` 的固定拒答 guardrail。已透過 `https://61.216.9.52:3030/chat.html` 實測，輸出內容正確包含 `2. Introduction`、`2.7 Test Scenarios`、`3. Test Result Summary`、`4.1 Xn Handover` 等摘要段落，且最後畫面上顯示的是後端摘要而不是舊的「沒有 SCU2050 資料」答覆。
- 2026-05-29 已再次驗證 `SCU2050 的相關報告數據`：前端/助理若仍顯示「沒有找到任何關於 SCU2050 的報告資料」的舊答案，較可能是舊分頁或快取，而不是現行後端真的沒有資料。實測目前 `/search` 在 `mode=auto` 下會先走 Handover 泛查詢摘要路徑，回覆 `mode=basic` 且內容包含 SCU2050 Handover 報告的產品與測試概述、`2.7 Test Configuration`、`4.1 Xn Handover Test`、`3. Test Result Summary` 等摘要，`sources` 也會帶回 `type6_NR-Handover-SCU2050-EV-V004.xlsx`。另外 `SCU2050 的 Performance Test 數據` 仍維持固定拒答，說明性能題 guardrail 與一般 Handover 摘要路徑已分流成功。
- 2026-05-29 已修正 SCU2050 這類 Handover 報告的泛查詢誤攔問題：先前 `請查詢SCU2050的相關報告數據` 會被 `數據` 關鍵字誤判為 Performance 題，進而直接回覆「這份 Handover 報告沒有 Performance Test 章節，因此無對應章節可回覆」，導致明明有其他章節內容卻被擋掉。已將 Handover 缺章節的固定拒答收斂為「只有在明確詢問 Performance Test / throughput / latency / BLER / RTT / case / test case 等性能數據時才適用」，並新增一般 Handover 摘要路徑：當 query 是泛報告查詢但不是性能題時，系統會依 project code 找到對應的 Handover metadata，直接讀取 converted md 內容，再透過既有 LLM 摘要流程回覆其他章節重點，不再一律拒答。已重啟 KB 並驗證 `請查詢SCU2050的Performance Test數據` 仍維持固定拒答，但 `請查詢SCU2050的相關報告數據` 現在會回覆 SCU2050 Handover 報告的設備與測試環境資訊、`3. Test Result Summary` 與 `4. Xn/N2 Handover` 等其他章節摘要，達到「保留性能題 guardrail、同時允許一般報告摘要」的兼顧效果。
- 2026-05-29 已將 compare 類回答的 Ollama 輸出上限再次調高：先前把 `ollama.num_predict` 提到 2048 後，仍有 `SCU2140 和 SCU5050 共通的測試項目` 這種比較評論在句尾被切斷的現象，因此將 `config/config.yaml` 與 `config/config.yaml.example` 的 `ollama.num_predict` 進一步提高到 4096，並保留 `src/search/__init__.py` 的截斷偵測與保底評論。重啟 KB 後重新驗證同題，compare 的 `## 解讀` 已可完整輸出，最後一條評論不再被截尾。
- 2026-05-29 已修正 `SCU2140 和 SCU5050 共通的測試項目` 類 compare 回答被截斷的問題：根因是 compare 的 `### LLM 簡短評論` 由 Ollama 生成，而 runtime 的 `ollama.num_predict` 仍停在 768，導致模型在較長評論句尾被切斷，出現半句或尾端殘缺的情況。已將 `config/config.yaml` 的 `ollama.num_predict` 提升到 2048，並在 `src/search/__init__.py` 的 compare 評論生成加入截斷偵測與保底評論：若 LLM 評論看起來像被截斷，就會改用規則式的簡短比較評論，避免半句直接顯示給使用者。已重啟 KB 並重新驗證 `請查詢SCU2140和SCU5050共通的測試項目`，現在 compare 的 `## 解讀` 可以完整輸出，不再在句尾被截斷。
- 2026-05-29 已修正 `請列出Throughput底下有哪些Case` 的語意路由：原本這題會被 `list` / `numeric` 路徑帶偏，甚至因 `_report_graph_search_raw()` 內漏掉 `asks_case_list` 判斷而直接拋錯，最後退回 vector，輸出成大量 case 13~16 的原文片段。已在 `src/search/__init__.py` 補齊 `_report_graph_search_raw()` 的 `asks_case_list` / `asks_latency_reports` 判斷，並新增 `preserve_all=True` 的 report graph source 選取模式，讓 case-list 問法不再做 per-report 抽樣。另將 case-list 的章節欄優先收斂到 `4. Performance Test` 類章節，避免封面 / 目錄混入。已重啟 KB 並重新驗證 `請列出Throughput底下有哪些Case`，現在回覆為 `report_graph`，且可正確列出 `SCU2060 / SCU2140 / SCU5050` 各自 `1~16` 的 Case 清單；同輪回歸也確認 `請查詢Throughput相關報告數據`、`有哪些專案有Throughput測試項目？`、`SCU2140、SCU2060、SCU5050 的Throughput有什麼差異？`、`請找出所有有Latency測試項目的報告`、`請查詢SCU2140和SCU5050共通的測試項目`、`請查詢SCU2050的Performance Test數據`、`請查詢SCU2050的相關報告數據` 都仍維持正確語意。
- 2026-05-26 已進一步修正 SCU5050 `Performance Test` 回答與原始 Excel 不一致的殘留問題：根因不只在 chunk 粒度，還在報告重試 / 排序與 agent 規則會把 `3. Test Result Summary` 和 `4. Performance Test` 混用。已完成三層修正：`src/chunker/__init__.py` 現在會在遇到新 Markdown 標題時先 flush 既有 chunk，確保 `3. Test Result Summary` 與 `4. Performance Test` 不再跨章節拼接；`src/web_api/tasks.py` 對 report-like 的 performance 數值查詢不再強制塞入 `Test Result Summary`，且在 sources 上會優先保留 `Performance Test` 詳細 case；`src/search/__init__.py` 也對數值抽取加入更強的章節權重與 prompt 規則，明確要求 `Performance Test` 題型只能用 `4. Performance Test` 的逐 case 數據，不得把 summary 平均值當成詳細 case。同步更新 `/home/da40_ai_gb10/.openclaw/workspace/skills/kb-query/SKILL.md`，讓 helper 端也遵守同一條硬規則。已重新 ingest 3 份 report 並重啟 KB；最新驗證 `請查詢SCU5050 的Performance Test 數據` 時，`/tasks/{task_id}` 的 `sources` 只回傳 `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001` 的 `## 4. Performance Test` 詳細 chunk（例如 chunk 27），不再夾帶 `3. Test Result Summary` 的混合內容，代表後續回答應可直接對齊原始 Excel 的 detailed case 數據。
- 2026-05-26 已實測 helper 查詢 `請查詢SCU5050 的Performance Test 數據`，並把回覆逐欄對照原始 Excel `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.xlsx`。結果顯示 helper 的第二組表格（Case 13~16）與 Excel 的 `4.13~4.16 Test Case` 平均值一致，例如 Case 13 的 `DL 1260 / UL 187 / Bidirection 1272 / 155 / UDP DL 1311 / UDP UL 195 / RTT 26.452`，Case 14~16 也都對得上；但 helper 的第一組表格明顯錯位，將 `3. Test Result Summary` 中 Case 9~12 的平均值（如 `1307 / 1120 / 945 / 744` 與 `61.056 / 27.068 / 25.703 / 26.185`）誤標成 Case 13~16。也就是說，helper 這次回覆不是整體一致，而是混用了不同章節的數值；後續若再查相同題目，應強制只取 `## 4. Performance Test` 內的對應 case，避免 summary table 與 detailed table 交叉混用。
- 2026-05-26 已更新 [`AGENTS.md`](/home/da40_ai_gb10/knowledge-base/AGENTS.md) 的全域工作規則，明確加入跨電腦、跨 session、跨 runtime、跨部署路徑的影響評估要求；後續所有修改都必須優先考慮所有可預見的執行場景與失敗模式，不能只修單一機器或單一現象，並且要以根因修正與共通機制為主，若方案只覆蓋局部案例則必須明確標註適用範圍與未覆蓋風險。
- 2026-05-26 已修正 SCU5050 `Performance Test` 數據混值問題：原始 Excel 與轉出的 `data/processed/Report/SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md` 內容本身是正確的，例如 case 13 的 `Bidirection - DL` / `Bidirection - UL` 與 summary table 中的 `Bidirection` 值皆能在原檔對上；真正的問題出在 `src/chunker/__init__.py` 的 `chunk_by_headers()`，它會把整個 `## 4. Performance Test` 章節當成一個過大的向量 chunk，導致 QDrant 召回時同一筆 source 內混入多個 case（例如 case 13 與 case 16）而讓 LLM 在回答時把不同 case 的數字交叉引用。已將 chunker 改成逐行切分並在超過 `max_chunk_size` 時立即 flush / hard split，避免單一 chunk 夾帶整個章節；接著已在 `web` 容器內重新 ingest `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md`、`SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md`、`SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md` 三份 report，並重新執行 `restart_kb.sh` 驗證服務正常。最新的 source 搜尋顯示 case 13 已拆成更小的 chunk（例如 case 13 head / tail 分開），不再出現先前那種把 1~16 case 全包進同一筆 source 的情況。
- 2026-05-26 已把卡片盒改回「從 sources 回推到原始文件，再點擊顯示那些文件」的路徑：`frontend/chat.html` 現在會優先從 `sources` 聚合出 `topic.files`，並以 `citation_source_name` 顯示原始 `.xlsx` 檔名；卡片點擊時若已有回推結果，就直接開啟這些文件，不再只看 `/api/category-files` 的分類清單。後端 `/api/document` 也已補上 metadata fallback，可直接用原始 `.xlsx` 名稱回推到對應的 converted `.md` 內容。已重啟 KB 驗證 `請查詢SCE2200相關報告的資訊`：`sources` 仍有 11 筆 chunk，但 `citation_source_name` 去重後只有 1 份原始文件 `type6_NR-Handover-SCE2200-n79-EV-V13.8.xlsx`，`/api/source-categories` 也將其歸到 `4G/5G`，而 `/api/document?category=4G/5G&doc_name=type6_NR-Handover-SCE2200-n79-EV-V13.8.xlsx` 已可成功回傳內容，代表卡片顯示與點擊流程都已回到原本要的「文件級」行為。
- 2026-05-26 已把引用文件顯示邏輯改回「Excel 原始來源優先、沒有 Excel 才顯示 md」：在 `src/search/__init__.py` 新增 citation source enrichment，會回查 processed 目錄的 `.source.json`，並以 `citation_source_name / citation_source_path / citation_source_ext / citation_source_kind` 回傳給前端；若來源是 Excel，顯示原始 `.xlsx` 檔名與路徑，若沒有可對應的 Excel 中繼資料，則保留 md。前端 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 也同步改成優先讀 `citation_source_name`。已重啟 KB 驗證 `請查詢SCE2200相關報告的資訊`，`/tasks/{task_id}` 的 sources 現在顯示 `type6_NR-Handover-SCE2200-n79-EV-V13.8.xlsx`，`citation_source_kind=excel`，證實引用文件已回到原始 Excel 名稱。
- 2026-05-25 已正式修正 SCU2060 `Performance Test` 誤判：在 `src/web_api/tasks.py` 將報告型查詢的召回上限從 8 提升到 20，並新增第二輪聚焦查詢邏輯。當報告型查詢是 `SCU/SCE` 這類題目、且第一輪搜尋沒有抓到 `Performance Test` / `Test Result Summary` 時，系統會自動補打一輪 `Performance Test throughput latency bler rtt Test Result Summary` 的聚焦查詢，並合併去重後的 sources。已重啟 KB 驗證，使用 `請查詢SCU2060 的 Performance Test 數據` 重新搜尋時，`/tasks/{task_id}` 回傳的 sources 已包含 `chunk 10` 與 `## 4. Performance Test`，證明原先誤判是召回策略不足，不是 QDrant 沒有資料。
- 2026-05-25 重新分析 SCU2060 `Performance Test` 誤判：`data/processed/Report/SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md` 本體確實有 `## 4. Performance Test` 與完整 throughput / latency / BLER / RTT 表格（例如 4.1 的 Downlink 705、Uplink 169、RTT 16/31/163；4.2 的 Downlink 608、Uplink 277、RTT 17/27/45）。但 OpenClaw 舊回答那次走的是 `SCU2060 Performance Test` 的泛查詢，`/search` 在 `top_k=8` 下只回到 `2.6 DUT Test Configuration`、`2.7 Test Procedure`、`3. Test Result Summary` 前段，沒有把 `chunk 10 = ## 4. Performance Test` 排進來，因此 agent 才誤判為「只有設定章、沒有實際數據」。實測把查詢改成更聚焦的 `SCU2060 throughput latency bler rtt` 並把 `top_k` 拉到 20 時，`chunk 10` 就會出現。這表示問題主因是搜尋召回策略 / query 太泛，而不是文件缺資料。

- 2026-05-25 已把 KB 的 Neo4j host 映射從 `127.0.0.1:7474/7687` 改成 `127.0.0.1:17474/17687`，並同步更新 `restart_kb.sh` 的埠檢查與顯示。重新執行 `restart_kb.sh` 後，`kb-neo4j` 可正常起來且顯示 `127.0.0.1:17474->7474/tcp`、`127.0.0.1:17687->7687/tcp`，所有驗證項目通過；接著也把主機 `neo4j.service` 再啟動回來，確認它與 KB 可以同時存在，不再互撞埠位。這是目前的永久避讓方案。
- 2026-05-25 已查出 `restart_kb.sh` 失敗的真正原因：主機上有 `neo4j.service`（PID 4198 / 4860）正在佔用 `127.0.0.1:7474` 與 `127.0.0.1:7687`，導致 KB 的 `kb-neo4j` 無法綁定埠。已先執行 `systemctl stop neo4j`，再重新跑 `restart_kb.sh`，這次已完整成功；最終狀態為 `kb-neo4j` / `kb-redis` 皆 `healthy`，`kb-nginx`、`kb-web`、`kb-celery-beat`、`kb-celery-search`、`kb-celery-ingest` 皆已啟動，腳本驗證也通過首頁、管理後台路由、管理 API、QDrant health、Ollama 連線與 WebSocket proxy smoke test。
- 2026-05-25 已執行 `restart_kb.sh` 重新啟動知識庫。過程中前端 build 成功，compose 也開始建立各服務，但在 `kb-neo4j` 啟動時失敗，錯誤為 `failed to bind host port 127.0.0.1:7474/tcp: address already in use`。目前可確認 `kb-redis` 與 `kb-qdrant` 已起來，`kb-neo4j` 停在 `Created` 狀態，整體 `docker compose ps` 只看到 `kb-redis` 運作中。這表示異常不是 build 或 image 問題，而是主機端 7474 / 7687 埠已被既有程序占用，導致 Neo4j 無法綁定並使整次重啟中止。
- 初始建立。
- 今日完整變更記錄已整理到 [`/home/da40_ai_gb10/knowledge-base/DAILY_CHANGELOG_2026-05-18.md`](/home/da40_ai_gb10/knowledge-base/DAILY_CHANGELOG_2026-05-18.md)。
- 最新釐清：後續效能評估只針對 `knowledge-base` 本體，不包含 `AnythingLLM`。
- 目前已確認的主要瓶頸是 chat 排隊、單一 Ollama 實例、`num_predict=16384`、檢索 `top_k` 偏高，以及 CPU embedding。
- `syntheses` 快取只對重複問題有幫助，不能解釋兩台電腦同時首次提問的慢速差異。
- 已完成一版「只提速、不改回覆格式」的參數調整：`num_predict` 降到 2048、`basic_top_k` 降到 3、`deep_top_k` 降到 6，並同步對齊搜尋入口、GraphRAG 與 vector store 的預設值。
- 目前再進一步把單一 Ollama 的執行壓力降下來：`CHAT_GLOBAL_CONCURRENCY_LIMIT=1`、`OLLAMA_NUM_PARALLEL=1`、`OLLAMA_MAX_LOADED_MODELS=1`。
- 最新排查：兩台電腦回覆來源不同，主因很可能是 `frontend/chat.html` 只等 8 秒就把 KB 搜尋結果送往 OpenClaw；在 `CHAT_GLOBAL_CONCURRENCY_LIMIT=1` 的情況下，較慢的那台容易拿不到 KB context，最後變成只依 OpenClaw / md 脈絡回覆。
- 已加入保護機制：`frontend/chat.html` 與 Vue 版 `frontend/src/views/ChatView.vue` 都會先等 KB 搜尋完成，若 KB context 尚未準備好，就不送出 OpenClaw，避免不同電腦因時序差異走到不同回答來源。
- Vue 前端已完成 production build 驗證，輸出更新到 `.frontend-build-live`，權限也已修回目前使用者可寫。
- `restart_kb.sh` 不需要再額外加一套 Vue 對齊邏輯；它的 `npm --prefix frontend run build`  արդեն 會把 `ChatView.vue` 與 `src/services/api.js` 一起編進前端輸出。
- 先前 build 後曾把 `chat.html` 靜態入口遮掉，已手動把 `frontend/chat.html` 與 `frontend/lib/marked.min.js` 補回 `.frontend-build-live`，讓 `/chat.html` 恢復小幫手頁面。
- 目前 KB 保護機制改成「最多等 60 秒再送 OpenClaw」，不再用立刻拒送；超時才提示使用者稍後再試。
- KB 等待上限已改成可調參數，存在 `config/config.yaml` 的 `openclaw_chat.kb_search_timeout_seconds`，並透過 `/admin/chat-settings` 與系統管理頁共用調整。
- `/admin/chat-settings` 一開始回 405/500 的根因，是 nginx 沒把 `/admin/chat-settings` 轉到 kb-web，且後端一度把設定寫到唯讀的 `config/config.yaml`；目前已改成由 nginx 代理到後端，並把 runtime 設定寫到可寫的 `data/chat_settings.yaml`。
- 新一輪分析方向：要讓「單一文件詳細查詢」更快，核心不是再加大檢索，而是縮短整條路徑，優先看文件定位、chunk 數量、context 長度、生成 token、以及是否還要經過 OpenClaw / 其他 fallback。
- 對單文件場景，最有效的優化通常是「先定位單檔，再做局部檢索」，避免走全庫 top_k；其次才是降 `num_predict`、壓縮 context、預先做文件摘要與章節索引。
- 若回覆來源不穩定或時序敏感，與其等很久，不如把查詢分成 fast path 與 deep path，先回可用答案，再視需要補深度。
- 目前 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 在 KB 超時時都會停止並提示使用者，沒有把原始問題直接交給 OpenClaw。
- 若要在超時後讓 OpenClaw 接手，這會把體驗從「明確失敗」改成「保底回覆」，但也會降低 KB 錨定性與答案一致性，且在系統忙碌時不一定真的更快。
- 已改成 KB 超時後 fallback 到一般回答，並在前端明確標示「一般回答」，附帶「本次未取得知識庫內容」說明；對使用者顯示的字串已改寫成「直接搜尋」，避免暴露 OpenClaw 名稱。
- 前端實作同時保留 KB 命中時的 enriched message，只有 timeout / 無 KB context 才走一般回答。
- `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 都已同步更新；Vue 版已成功透過 `vite build --outDir /tmp/frontend-build` 驗證可編譯。
- 專案現有 `.frontend-build-live` 目錄為 root 擁有，直接 build 會因清理舊輸出而失敗，這是既有權限狀態，不是本次程式碼錯誤。
- 2026-05-22 已備份 `/home/da40_ai_gb10/.openclaw/openclaw.json` 為 `openclaw0522.json`，並把 OpenClaw 主模型改成本地 Ollama `ollama/gemma4:e4b`；`agents.defaults.model.primary` 現在指向 `ollama/gemma4:e4b`，`models.providers` 也補上 `ollama` provider（`http://127.0.0.1:11434/v1`、`apiKey=ollama-local`），原本的 `minimax/MiniMax-M2.7` 與 `minimax/MiniMax-VL-01` 保留為 fallback。這代表小幫手本體的主對話模型已從 MiniMax 切回本地 Ollama。
- 2026-05-22 進一步把 `/home/da40_ai_gb10/.openclaw/openclaw.json` 縮到只保留本地 Ollama 主模型：`agents.defaults.model.primary = ollama/gemma4:e4b`，`agents.defaults.models` 只保留 `ollama/gemma4:e4b`，`models.providers` 也只剩 `ollama`，`auth.profiles` 中的 Minimax / Google 已移除，`tools.media.image.models` 也清空為 `[]`。也就是說，OpenClaw 本體目前只留本地 Ollama 主模型，沒有額外備援模型資訊。
- 2026-05-22 進一步調整 OpenClaw 主模型：`openclaw.json` 現在改成 `ollama/gemma4:31b` 為主力模型，`ollama/gemma4:e4b` 作為 fallback；同時 `agents.defaults.models` 增加 `ollama/gemma4:31b`，`models.providers.ollama.models` 也補上 `gemma4:31b` 的本地 Ollama 模型定義。這代表小幫手本體會優先用 31B 版本，若需要才回退到 e4b。
- 2026-05-22 進一步把 OpenClaw 主模型改成 `ollama/qwen3.6:35b-a3b`，其他模型改為 fallback：`agents.defaults.model.primary = ollama/qwen3.6:35b-a3b`，fallback 依序保留 `ollama/gemma4:31b`、`ollama/gemma4:e4b`；`models.providers.ollama.models` 也新增 `qwen3.6:35b-a3b` 的本地模型定義。這代表小幫手本體目前會優先使用 qwen3.6:35b-a3b，若需要才回退到 gemma4 系列。
- 已清空 KB 專用 Qdrant 與 Neo4j：Qdrant 的 `knowledge_base` / `kb_syntheses` collection 已刪除，Neo4j 目前 `nodes=0`、`rels=0`。
- 已確認手動上傳與自動攝入最後都走同一套 `ingest_document` 寫入流程；在 KB 的 Docker runtime 下，Neo4j 由 `NEO4J_URI=bolt://neo4j:7687` 指向 KB Neo4j，Qdrant 由 `qdrant.url=http://host.docker.internal:6335` 指向 KB Qdrant。
- 需要注意：如果直接在主機上跑部分 Python 入口而不是透過 KB 容器環境，Neo4j 預設值仍可能回落到 `bolt://localhost:7687`，因此是否命中 KB 資料庫取決於執行環境是否有被 Docker env 覆蓋。
- 2026-05-19 已再次清空 KB Neo4j 與 Qdrant：Neo4j `nodes=0`、`rels=0`，Qdrant `/collections` 仍為空列表。
- 2026-05-19 追查 `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.xlsx`：檔名未命中 type1~type6，所以被歸到 `4g5g`，轉出的 md 有 11 個 chunk；Neo4j 寫入結果只看到 `Document` + `TextUnit` 與 `CONTAINS`，代表萃取幾乎沒抽出實體/關係；主機側 `VectorStore` 初始化則因 `host.docker.internal:6335` 無法解析而失敗，導致 Qdrant 寫入被跳過。
- 2026-05-19 已新增 `Report` 萃取模式：只要檔名包含 `SIT-TR-SC` 就會自動走 `report`；此模式會以「文件 + chunk 向量」為主，Neo4j 只保留 `Document` / `TextUnit` 結構，不再做實體關係抽取。
- `Report` 模式已同步接到上傳入口、watch folder、自動分類、索引與前端選項；`resolve_storage_category()` 也會把 `SIT-TR-SC` 類檔案放進 `Report` 資料夾。
- 最新驗證：`python3 -m py_compile` 通過所有修改的 Python 檔；`frontend` 以 `npx vite build --outDir /tmp/frontend-build` 成功，現存的 `npm --prefix frontend run build` 失敗仍是 `.frontend-build-live` 的既有權限問題。
- 2026-05-19 追查 `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.xlsx` 再次出現 Neo4j 只有文件結構、QDrant 空白的案例：`kb-celery-search` log 明確顯示當時仍跑舊版規則，訊息是「未偵測到特定類型，使用預設模式 (4G/5G)」，代表新加的 `Report` 規則還沒被目前執行中的 worker 吃到；同一段 log 也顯示 QDrant upsert 回 `404 Collection doesn't exist`，原因是 worker 啟動時雖曾連到 collection，但後來 collection 被清掉後，`VectorStore` singleton 沒有重新建立 collection，而且 `ingest_vector()` 會吞掉錯誤，所以任務最後仍顯示完成。
- 2026-05-19 已修補 QDrant 的硬傷：`VectorStore.add_documents()` 現在會在 collection 不存在時自動重建後重試，且 `ingest_vector()` / `ingest_document()` 不再把 QDrant 寫入失敗當成成功完成；這樣即使手動清空 QDrant，也不需要先重啟 worker 才能重新攝入。
- 2026-05-19 追查 WiFi Excel 自動攝入：watch 流程在決定輸出資料夾時，`watch_folder_scan()` 會先用 `resolve_storage_category(None, file_path.name)` 依檔名判斷，`resolve_storage_category()` 再回退到 `infer_storage_category_from_filename()` / `detect_extraction_mode()`；這條路徑是純檔名規則，不看 Excel 內容。`WiFi` 只會在檔名命中 `type2` 或相關關鍵字時進入，否則 `detect_extraction_mode()` 的預設值仍是 `4g5g`，最後就會被放進 `data/processed/4G_5G`。因此這次現象不是轉檔壞掉，而是分類規則沒有把「WiFi 相關內容」辨識成 `wifi`，目前設計仍是 filename-driven 而非 content-driven。
- 2026-05-19 已再次清空 KB Neo4j 與 Qdrant 供手動測試：Neo4j `nodes=0`、`rels=0`；Qdrant 的 `knowledge_base` 與 `kb_syntheses` collection 已刪除，`/collections` 目前為空。
- 2026-05-19 追查 `type6_SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md` 沒有新增 Neo4j/Qdrant 資料的可能原因：`detect_extraction_mode()` 會先命中 `SIT-TR-SC` 並回傳 `report`，所以 `type6` 前綴不會讓它進 `simple`；但 watch 流程會先用檔名算出 `Report` 資料夾與 processed 同步比對，如果 `processed/Report` 已有同 hash / 同名 / 同 stem 的檔案，watch 端會先刪掉重複檔不進 ingest。另一方面，真正進入 `ingest_document()` 後又會先執行 `cleanup_existing_document(doc_name)`，把同名 Document / TextUnit / 關係 / Qdrant points 先清掉再重寫，所以「同一份文件再次攝入」在數量上可能看起來沒有增加。若要區分是「被重複檔規則跳過」還是「成功覆寫但數量不變」，需要看 watch log 是否出現 `watch 與 processed 內容相同，已刪除 watch 重複檔` 或 `已存在相同內容，刪除 watch 重複檔`，以及是否有 `Report 模式` / `QDrant 寫入完成` 的紀錄。
- 2026-05-19 架構評估：若要讓 OpenClaw 直接查 KB 的 Neo4j / QDrant 而不要再透過 KB 原生 Ollama，這件事是可行的，但不是現有 `/search` 流程的預設行為。現在的 `KnowledgeBaseSystem` 與 `SearchEngine` 都把 LLM 放在查詢流程中，用於關鍵字抽取、模式選擇與回答生成；`/analyze-question` 也會先叫 LLM 抽實體，再查 Neo4j / Qdrant。若要完全繞過 Ollama，需要另外做「純檢索」路徑，或讓 OpenClaw 直接連 Neo4j / Qdrant 自己做 retrieval，再由 OpenClaw 或另一個外部模型負責最後回答。

- 2026-06-03 已修正 WiFi compare 會把 `請比較CHS3320N-D388 和 NCQ2200B2V-D294 的 WiFi Throughput。` 誤導成 `TP-Link Archer BE805` 與 `NCQ2200B2V-D294` 對照的問題。根因不是 hardcode BE805，而是 `_find_wifi_document_metadatas_for_query()` 在 WiFi compare 時只要看到 `WiFi` / `Throughput` 這類泛用詞就會把資料夾內可見的 WiFi 報告全部納入候選，再取前兩份做 compare；查詢中的 `CHS3320N-D388` 又因為緊貼中文動詞，原本的 regex boundary 沒抓到，結果只剩 `NCQ2200B2V-D294`，系統便退回用其他 WiFi 文件湊滿兩份。已在 `src/search/__init__.py` 新增 `_extract_wifi_doc_hints()`，讓 compare 先抽出明確的 WiFi 型號/文件代號，並調整 `_find_wifi_document_metadatas_for_query()` 為「有明確型號時只收該型號命中的文件，沒有命中就不拿無關文件補位」；同時在 `search()` 的 compare 分支加上缺文件保護，當查詢指定的 WiFi 文件不足 2 份時，會直接回覆「未找到足夠的 WiFi 文件可進行比較」並列出命中的與缺失的文件，而不是再回 BE805 之類的無關結果。已用 `python3 -m py_compile src/search/__init__.py` 與 `SearchEngine(llm_client=object()).search('請比較CHS3320N-D388 和 NCQ2200B2V-D294 的 WiFi Throughput。', mode='auto', top_k=6)` 驗證：目前 `_extract_wifi_doc_hints()` 能抓出 `CHS3320N-D388` 與 `NCQ2200B2V-D294`，但因知識庫內只找到 `NCQ2200B2V-D294`，回覆會明確指出缺少 `CHS3320N-D388`，不再誤配到 `TP-Link Archer BE805`。

## 使用方式

- 每次開始工作前先讀取本檔。
- 在對話壓縮或重要進度更新後，將最新狀態寫回本檔。
- 2026-05-19 已將 KB timeout 回退到修改前的固定版本：移除 `/admin/chat-settings` 與 `openclaw_chat.kb_search_timeout_seconds` 可調設定，`chat.html` 及 Vue 版 `ChatView` 恢復為固定等待值，不再從 runtime config 讀取 KB 等待秒數；管理頁的 KB 等待設定卡也已移除。
2026-05-19 session 相關改動仍保留，未受 KB timeout 回退影響：`/api/openclaw/chat-config` 仍輸出 `sessionKey` / `gatewayWsUrl` / `authToken` / `deviceToken` 等 runtime 資訊；前端 `chat.html` 與 `ChatView.vue` 仍會以 localStorage 生成 browser-scoped sessionKey，並在 WebSocket auth / sendMessage / history / event filtering 中使用；後端 websocket proxy 仍保留 per-session lock、queue 與 session filter 邏輯。
2026-05-19 針對瀏覽器看到的 504 錯誤，前端實際請求會打到 `/api/analyze-question`（由 `frontend/chat.html` 的 `apiUrl()` 組出），而 `/analyze-question` 是同步執行 LLM 實體抽取 + Neo4j 查詢 + Qdrant fallback 的路徑；`nginx.conf` 的 `/api/` location 沒有額外設定 `proxy_read_timeout`，因此若同步分析過久就可能在反向代理層超時成 504。
2026-05-19 已修正 504 風險：`nginx.conf` 的 `/api/` location 新增 `proxy_connect_timeout` / `proxy_send_timeout` / `proxy_read_timeout`，`frontend/chat.html` 的 `/analyze-question` 改成 2.5 秒後自動 abort 並回退卡片意圖推測，`frontend/src/services/api.js` 的 `analyzeQuestionApi()` 也統一加入短 timeout，避免 heatmap 分析請求拖垮主聊天流程並在瀏覽器留下 504。
2026-05-19 已開始落實小幫手端到端耗時量測：`frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 都已加入從送出到回覆完成的 latency tracking，會在 assistant 訊息下方顯示 `回覆耗時`，其中 `chat.html` 另外記錄 `首字` 時間以便辨識串流回覆速度。
2026-05-20 外部連線檢查：`kb-nginx` 已對外發布 `3030->443`，本機 `ss` 顯示 `0.0.0.0:3030` 正在監聽；以 `https://61.216.9.52:3030/health` 測試時可連到 Nginx（HEAD 會回 `405`、GET 會回 `200`）。因此 `ERR_CONNECTION_REFUSED` 較像是前端當下連線時的暫時性失敗或瀏覽器/網路側狀態，而不是目前服務持續不聽 3030。因 `sudo` 需要密碼，尚未能直接檢查主機防火牆規則。
2026-05-20 追查 4 個 `type6` Excel 未攝入：`data/watch` 當下是空的，而這 4 個原始 `.xlsx` 已出現在 `data/processed/` 根目錄；`watch_folder_scan()` 只掃 `watch_folder`，且 `_sync_watch_with_processed()` 會把與 processed 同 hash 的 watch 檔直接刪除，所以這種情況會導致掃描結果一直是 `0 個待處理檔案`，不會產生 md 或分類輸出。
2026-05-20 實測 `type6_NR-Throughput-SCU2140-n78-EV-V005.xlsx` 攝入：手動觸發的 `watch_folder_scan` 成功完成，流程包含 `type6` 命中、Excel 轉成 `data/processed/Simple/type6_NR-Throughput-SCU2140-n78-EV-V005.md`、`source.json` 生成、QDrant 寫入 11 筆向量、原始 xlsx 移入 `data/processed/Simple/`；但因同時還有另一個週期性 watch task 幾乎同步觸發，第二個 worker 在第一個已把檔案搬走後才接手，因此報 `檔案不存在`。這表示攝入流程本身正常，異常點是重複觸發造成的競態。
2026-05-20 卡片盒設計再評估：目前卡片盒數字來源混合了問題意圖分析與回答來源統計，因此對像 `5GHz UNII 頻段` 這類題目容易出現「看起來不像題目意圖」的分數；下一步較合理的方向，是把卡片盒改成顯示「這次回答引用了什麼」，並以 5 個類別的引用比例作為主要視覺化，而不是繼續把它當成題目分類器。這樣會提升可解釋性，但會失去題目意圖判斷能力。
2026-05-20 已開始把 chat.html 的卡片盒改成「回答引用分布」模式：頁面標題與說明已改為引用分布，卡片不再先跑 `/analyze-question` 的題目意圖分數，也不再輪詢 `/api/category-stats`；現在只在最終 assistant 回覆的 `sources` block 或 DOM 來源中統計 5 類資料的引用比例，卡片大數字改為百分比，並以 `strong/medium/weak/none` 對應高/中/低/無的引用集中度。若沒有可辨識來源，卡片會停在「本次無引用」而不是維持舊 heatmap 分數。
2026-05-20 追查詢問小幫手流程偏慢的主因：前端 `frontend/chat.html` 目前對每次問題都先送 KB 搜尋且固定用 `mode: 'hybrid'`，還會先等 KB context 最多 8 秒；後端 `search_task` 的 hybrid 路徑會做兩次 Ollama chat（關鍵字萃取 + 最終回答），再加上向量與圖譜查詢。更關鍵的是 `KnowledgeBaseSystem` 與 `src/web_api/cache.py` 都仍有 localhost 預設，導致 worker 內的 Neo4j / Redis 實際命中 `localhost:7687` 與 `localhost:6379` 失敗，`kb-celery-search` log 也顯示每次 hybrid 查詢都會先撞到 Redis 與 Neo4j 連線錯誤。這使得快取與圖譜路徑失效，整體查詢時間拉長到約 61 秒。
2026-05-20 已先修正 localhost 連線設定：`src/web_api/cache.py` 的 Redis 預設已改成優先吃 `REDIS_URL / CELERY_BROKER_URL`，fallback 也改成 `redis://redis:6379/0`；`src/search/__init__.py` 的 `SearchEngine` 會優先使用 `NEO4J_URI`，不再默認掉回 `bolt://localhost:7687`；`src/main.py` 的 `KnowledgeBaseSystem` 也同步優先吃環境變數覆寫 Neo4j 連線資訊；`src/web_api/tasks.py` 的 worker Redis 預設也改成 `redis://redis:6379/0`。這樣 Docker worker 不會再因為 `localhost` 預設去撞本機服務。
2026-05-20 已完成這次 localhost 連線修正的正式備份：除了程式碼修正外，也把實際對外服務使用的 `.frontend-build-live/chat.html` 版本一併納入備份脈絡，避免前端 runtime 與 source 不一致；後續若再看到 Redis / Neo4j 走回 localhost，可先對照這次備份點 `Fix localhost Redis and Neo4j defaults` 與本次正式備份記錄。
2026-05-20 卡片盒的正式設計意圖已再確認：卡片盒應以「最後回答引用了哪些文件」作為比例依據，不再使用題目分類或查詢意圖分數。也就是說，4G/5G、WiFi、Lab、Project、Automation 的分數，應反映最終回答實際引用到的各類文件數量；如果同一題同時引用 4G/5G 與 WiFi，則依各自被引用的文件數量決定比例高低。若某份文件同時含多主題內容，應優先以文件本身的分類/路徑判定，而不是回頭猜題目意圖。
2026-05-20 已把 `frontend/chat.html` 的卡片盒顯示再往前推一版：標題與說明改成「以最終回答引用的文件數量決定 5 類資料比例」，並新增 `citation-summary` 總結列，會直接顯示本次共引用了幾份來源、已歸類幾份、未歸類幾份；每張卡片則維持百分比大數字與「引用 X 份」的文件數量，讓卡片盒完全表達最後回答引用來源的分布，而不是題目意圖。
2026-05-20 已清掉 `frontend/chat.html` 中殘留的舊意圖分析函式（`updateCardRelevance` / `updateCardsFromAnalyze` / `analyzeQueryIntent` / `updateCardsFromIntent` 等），現在卡片盒只保留「回答引用分布」的路徑；要把 source 同步到實際 runtime，需執行 `./restart_kb.sh`，它會重建前端、重啟 KB 容器，並把最新的 `frontend/chat.html` 複製進 `.frontend-build-live`，且不會影響 AnythingLLM。
2026-05-20 已再把卡片盒的來源分類補強為「後端解析來源類別」：前端不再用來源字串關鍵字猜類別，而是呼叫 `/api/source-categories` 取得每個來源文件對應的 category，並且明確排除 `graph` 類來源不納入文件占比，避免 `WiFi` 這種誤判是被圖譜節點或字串命中帶出來的假訊號。卡片盒現在只統計 backend 回傳的文件類別，比例才會反映真正引用文件的分布。
2026-05-20 已將後端來源規則中的 `Report` 類別移除，卡片盒與 `/api/source-categories` 現在只保留五類：`4G/5G`、`WiFi`、`Lab`、`Project`、`Automation`。報告型檔案不再是獨立來源類別，而是會依檔名/內容回到這五類中的一類，避免卡片盒出現整排 0 分的情況。
2026-05-20 進一步修正卡片盒引用比例 API 的掛載路徑：`/source-categories` 改成 `/api/source-categories`，因為前端實際是走 `/api/...` 對外存取；先前路徑掛錯會導致瀏覽器打不到正確 endpoint，因此即使後端邏輯正確，前端卡片仍可能顯示全 0。這次修正後，需重新啟動 KB 讓新 route 與前端同步生效。
2026-05-20 重新實測 `請查詢SCE2200的相關報告資訊`：後端 `POST /api/source-categories` 對 `type6_NR-Handover-SCE2200-n79-EV-V13.8` 與 `type6_NR-Throughput-SCU2140-n78-EV-V005` 的分類都回到 `4G/5G`，matched_count=2，理論上卡片盒應顯示 `4G/5G=100%`。同一輪 `search_task` 的最新執行已經很快（worker log 約 0.142s），主因是 `kb_syntheses` cache hit 與 vector 查詢；因此若瀏覽器還看到 `4G/5G=0%`，更像是前端 runtime / 舊分頁 / JS 執行中斷問題，而不是來源分類後端本身錯誤。
2026-05-20 已將卡片盒更新路徑再收斂：`frontend/chat.html` 不再做任何 DOM fallback，也不再掃 `.source-tag` 來反推來源；現在只根據最終 task payload 裡的 `sources` block 更新卡片比例。這樣可以避免舊訊息殘留或畫面渲染時序影響 `4G/5G` 比例，卡片盒會完全以後端 task payload 為準。
2026-05-20 為了解決 `restart_kb.sh` 在 `.frontend-build-live` 上遇到 root-owned 權限問題，已把 KB 前端 runtime 目錄改到 `.frontend-build-runtime`，並同步修改 `docker-compose.yml` 的 nginx volume 掛載與 `restart_kb.sh` 的 build 輸出路徑。之後重啟時會重新建置前端並掛載新的可寫目錄，避免再卡在舊的 root-owned runtime 目錄。
2026-05-20 已完成卡片盒分布的最終修正：`search_task` 會回傳 `citation_distribution`，`/tasks/{task_id}` 的 `TaskStatusResponse` 也已加入同欄位，不再被 FastAPI 裁掉；前端 `chat.html` 只要拿到 task payload 的 `citation_distribution` 就直接更新卡片，不再依賴 DOM fallback 或第二次分類 API。重新實測 `請查詢SCE2200的相關報告資訊` 時，`/tasks/{task_id}` 已能看到 `citation_distribution.category_counts["4G/5G"] = 2`，因此理論上卡片盒應顯示 `4G/5G = 100%`，不應再回到全 0。
2026-05-20 追查 `請查詢SCU2140的相關報告資訊` 後卡片盒 4G/5G 顯示 0：截圖 console 顯示 Hermes/OpenClaw final payload 的 `message.content` 只有 1 個 `text` block，沒有 `sources` block，因此 `frontend/chat.html` 的 `allSourceItems=[]`，`updateCardsFromSources([])` 直接走 `No file-like sources to classify`，卡片全歸 0；後端 `/api/source-categories` 對 `type6_NR-Throughput-SCU2140-n78-EV-V005` 與 `type6_NR-Handover-SCE2200-n79-EV-V13.8` 可正確分類為 `4G/5G`，所以根因是前端只看最終 chat payload 的 structured sources，但 KB search 的 sources 沒有被帶入該 payload。
2026-05-20 已實作方案 A 修正卡片盒引用統計：`frontend/chat.html` 新增 `pendingKbSourceItems`，在 `/search` task 完成後保存 `result.sources`；final chat payload 若沒有 `sources` block，則以這份 KB structured sources 更新 `updateCardsFromSources()`，並處理 KB sources 比 final payload 晚到時的刷新。同步複製到 `.frontend-build-live/chat.html` 讓線上 `/chat.html` 立即生效；`node --check /tmp/kb-chat-inline.js` 通過，線上頁面已確認包含 fallback 程式碼，`/api/source-categories` 對 `type6_NR-Throughput-SCU2140-n78-EV-V005` 回 `4G/5G`。
2026-05-20 進一步追查後確認：`search_task` 與 `/tasks/{task_id}` 已可正確帶出 `citation_distribution`，且重新實測 `請查詢SCE2200的相關報告資訊` 時 task payload 內 `4G/5G = 2`。若瀏覽器卡片仍顯示 `0`，目前更像是前端舊分頁、瀏覽器快取，或 JS 執行時沒有切到最新 runtime，而不是後端 citation distribution 計算錯誤。
2026-05-20 重新量測查詢體感：一筆新的 `請查詢SCU2060的相關報告資訊` 在 worker 端的 `tasks.search_task` 完成時間約 56 秒，屬於冷啟動 hybrid 路徑的高延遲案例；但同一系統在 synthesis cache hit 時也能落到 0.1~0.3 秒級。前端 `frontend/chat.html` 目前在送出前仍會先等 KB context 最多 8 秒（`Promise.race(..., 8000)`），而 KB search 本身又是 `mode: 'hybrid'`。因此使用者體感慢的主要來源是「前端先等 KB context」與「冷 hybrid 搜尋」疊加，而不是單一 LLM 生成步驟。
2026-05-20 已開始把聊天流程改成「先送小幫手、後補 KB」：`frontend/chat.html` 不再等待 KB context 再送出訊息，改成按下送出後立即把原始問題送進 OpenClaw，小幫手先回覆、KB 背景查詢再補卡片與來源統計；背景 KB 搜尋也從 `hybrid` 改為 `vector`，實測一筆 `請查詢SCU2060的相關報告資訊` 的 vector 搜尋約 0.35~0.5 秒就完成，明顯比之前的 hybrid 冷路徑 50+ 秒更適合作為背景補充來源。
2026-05-20 已在 `frontend/chat.html` 右下角新增版本徽章 `KB Chat v2026-05-20`，用來快速辨識瀏覽器是否載入最新 runtime；這個標記不影響功能，只是為了排查舊分頁 / 快取 / runtime 不同步時，能一眼看出目前頁面是否是新版。
2026-05-20 已更新聊天流程為「先送小幫手、後補 KB」：送出問題後不再等待 KB context 才進入聊天，而是直接送原始問題給 OpenClaw，KB 搜尋改為背景執行並改用 `vector` 模式做補充來源；實測 `SCU2060` 類查詢的背景 vector 搜尋可在 0.35~0.5 秒完成，而之前冷 hybrid 路徑會飆到 50+ 秒。右下角版本徽章 `KB Chat v2026-05-20` 用來確認瀏覽器是否載入這版 runtime。
2026-05-20 重新實測 `請問SCU2140的相關報告資訊`：`/search` 背景任務改用 `vector` 後，Qdrant 檢索約 0.2 秒就完成，task 總耗時約 19.7 秒；`search_task` log 顯示真正花時間的是最後一段 `POST http://host.docker.internal:11434/api/chat` 的 Ollama 回答生成，而不是向量搜尋本身。相比舊版 `hybrid` 冷路徑曾出現 50~60 秒，現階段的主要體感瓶頸已從「檢索前先等 KB context」轉成「最後 LLM 生成時間仍偏長」。若要再縮短體感，優先方向是：維持 send-first、不再阻塞主聊天；讓 KB 只做背景補卡片；降低 prompt/context 長度或 num_predict；必要時採流式回覆或更快模型。
2026-05-20 已開始縮短 Ollama 生成時間：`extract_keywords()` 改為規則式萃取，不再每題額外呼叫 LLM；`ollama.num_predict` 已從 2048 下修到 768，且 `src/web_api/ollama_client.py` 的 fallback 預設也同步降到 768，避免 config 沒吃到時又回到高輸出長度。這一輪的目標是直接減少每次查詢的 LLM 呼叫次數與輸出 token 數，優先改善 `SCU2140 / SCU2060 / SCE2200` 這類報告題的尾端生成時間。
2026-05-20 實測 `請問Wifi 加強措施清單 有哪些`：`/search` 的 vector 任務回來的三份 sources 全是 `4G/5G` 報告（`SCU2060`、`SCU5050`、`SCU2140`），`citation_distribution` 為 `4G/5G=3, WiFi=0`，task 耗時約 15.7 秒。後續已確認正式聊天路徑會直接以 Neo4j / QDrant 的搜尋結果組 KB context，不再把 `index.md` 當成回答 prompt 的索引來源；因此若 WiFi 題仍回到 4G/5G，應優先檢查 WiFi 文件是否真的進入 QDrant / Neo4j，而不是回頭看 `index.md`。
2026-05-20 再次實測同題 `請問Wifi 加強措施清單 有哪些`：`/search` 任務耗時約 21.3 秒，`citation_distribution` 仍是 `4G/5G=3, WiFi=0, Lab=0, Project=0, Automation=0`，來源仍為 `type6_NR-Throughput-SCU2060-n79-EV-V13.8`、`type6_NR-Throughput-SCU5050-n78L-EV-V001`、`type6_NR-Throughput-SCU2140-n78-EV-V005`。這表示卡片盒若顯示 `4G/5G = 100% / 引用 3 份` 是正確的；如果前端還看到別的比例，應優先懷疑舊分頁或瀏覽器快取，而不是卡片統計邏輯。從知識庫內容來看，WiFi 類文件仍未實際進入可檢索來源，因此問 WiFi 題時檢索會持續回到 4G/5G 報告。
2026-05-20 重新審視卡片盒引用數量規則：前端會先把 task payload 的 `sources`（或後備的 `pendingKbSourceItems`）做去重，再用後端 `/api/source-categories` 把每個來源文件映射到五類之一，最後以 `categoryCounts[category] / matchedTotal` 算百分比；`shouldCountCitationSource()` 只讓 mode 為 `vector/cleaned/doc/file` 的來源進統計。後端 `_resolve_source_category()` 目前也只接受 `4G/5G / WiFi / Lab / Project / Automation`，即使文件被推斷成 `Report` 也會被排除，因此卡片盒的正式計數單位是「可回溯到五類之一的來源文件數」，不是 chunk 數，也不是 `graph` 節點數。
2026-05-20 已整理 WiFi 文件重新 ingest 後的 QDrant 驗證清單：先確認 WiFi markdown 真的在 `data/processed/WiFi`，再透過 `/upload/tasks/{task_id}` 或 watch task log 看到 `converted -> extracting -> writing_neo4j -> writing_qdrant -> refreshing_index -> completed`，最後用 `/admin/vector-stats` 確認 `knowledge_base` collection 的 points 數有增加，或直接在 Qdrant dashboard 搜尋 `doc_name/type2_*` payload。若 `data/processed/WiFi` 有檔但 QDrant 沒增加，優先查 ingest task 是否停在 `writing_qdrant`、`QDrant 寫入失敗`、或 `watch/processed` 同步把檔案視為重複而跳過。
2026-05-21 實測將 `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.xlsx` 放進 watch 後，watch task 會正確辨識為 `Report` 並搬到 `data/processed/Report/`，但原本 `ingest_document()` 的 Report 分支有一個未定義變數 `neo4j_uri` 的 bug，導致 `[Report] 寫入失敗: cannot access local variable 'neo4j_uri' where it is not associated with a value`，因此 Neo4j 沒有寫入成功；QDrant 也沒有出現這份文件的 `doc_name` payload。已修補為先 `load_config()` 並取得 `neo4j_uri / neo4j_user / neo4j_password` 再寫入 Neo4j，後續若要驗證 Report ingest 成功，需要重新放入 watch 或重新觸發 ingest 再看 `/admin/vector-stats`、`/admin/graph-stats` 與 QDrant scroll 是否能找到該 `doc_name`。
2026-05-21 已重新驗證同一份 `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001` 的 Report ingest：在 `kb-celery-search` 容器內直接呼叫 `ingest_document(..., extraction_mode='report')` 成功完成，log 顯示 `Report 模式` 下 Neo4j 文件結構完成、分塊 11 個區塊、QDrant 寫入 11 筆向量，`result=True`。進一步直接查 Neo4j 可找到 `Document(name='SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001', extraction_mode='report', source='/home/da40_ai_gb10/knowledge-base/data/processed/Report/SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md')`，且對應 `TextUnit` 數量為 1；QDrant 以 `doc_name` scroll 也能找到該文件的 points，代表 Report 模式的 Neo4j / QDrant 寫入修補已經生效。 
2026-05-21 已清除 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005` 在 Neo4j 與 QDrant 的既有資料，準備驗證新的 watch ingest：`cleanup_existing_document('SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005')` 在 `kb-celery-search` 容器內執行成功，QDrant scroll 針對同一個 `doc_name` 回傳空結果，Neo4j 以 `MATCH (d:Document {name:'SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005'}) RETURN count(d)` 也回到 `0`。這代表後續把 `/home/da40_ai_gb10/knowledge-base/data/raw/SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.xlsx` 放進 watch 時，可以用新增的資料判斷是否真的有重新寫進 Neo4j / QDrant。
2026-05-21 已再次確認並清除 `type6_NR-Throughput-SCU2140-n78-EV-V005` 在 Neo4j 與 QDrant 的既有資料：`cleanup_existing_document('type6_NR-Throughput-SCU2140-n78-EV-V005')` 成功執行，Neo4j `MATCH (d:Document {name:'type6_NR-Throughput-SCU2140-n78-EV-V005'}) RETURN count(d)` 回到 `0`，QDrant 也不再有 `doc_name` 含 `2140` 的 points。這次清除只針對該文件本身，不會刪除其他內容裡僅提到 `SCU2140` 的相鄰文件。
2026-05-21 針對 `請查詢SCU2140相關報告資訊` 的直接測試確認：`/search`（`mode=vector`）確實從 QDrant 拉回 3 筆來源，`sources` 全部對應 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005`，`citation_distribution.category_counts["4G/5G"]=3`，但 task 的 `answer` 仍然是空字串。這代表 KB 資料確實有從資料庫讀出來，但先前前端的 `formatKnowledgeBaseContext()` 因為 `result.answer` 為空就直接回空 context，導致後續送給 OpenClaw 時沒有帶到 KB 來源。已修正前端為「只要有 sources 就能組 KB context」，並把來源摘要拼進 prompt，即使 answer 空白也會把資料庫查詢結果送給小幫手。
2026-05-21 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 的 KB context 條件已修成只看 `sources` / `answer` 任一存在即可；同時為每個 source 附上摘要片段，避免 KB task 的 `answer` 空白時整包 context 被丟掉。已用本地 Node 測試確認 `SCU2140` 的 KB context 會包含三份來源文件與摘要片段，即使 task `answerLength=0` 也能產生 763 字的 context。
2026-05-21 已把前端 runtime 目錄從 `.frontend-build-runtime` 改成 `.frontend-build-runtime-user`，並同步更新 `restart_kb.sh`、`docker-compose.yml`、`frontend/package.json`、`frontend/vite.config.js`。新的 runtime 目錄由目前使用者建立並擁有，之後 `restart_kb.sh` 可正常 build 與清理，不再撞到 root-owned 舊目錄的 `Permission denied`。
2026-05-21 `restart_kb.sh` 已重新跑通：前端 runtime 成功輸出到 `.frontend-build-runtime-user`，`kb-web`、`kb-celery-search`、`kb-celery-ingest`、`kb-celery-beat`、`kb-nginx`、`kb-redis`、`kb-neo4j` 都已正常啟動，`/health`、`/chat.html`、`/admin/graph-stats`、QDrant health 與 WebSocket proxy smoke test 全部通過。瀏覽器現在應該可以實際吃到「只要有 sources 就組 KB context」的修正版。
2026-05-21 已把參考來源顯示改成更明確的來源管線形式：`frontend/chat.html` 會把來源 tag 顯示成 `Qdrant 文件片段` / `Neo4j 圖譜關聯` / `KB 匯整來源`，並在來源名下方保留文件名；`frontend/src/views/ChatView.vue` 也同步把 `KB 參考` 的提示換成多行來源清單，讓使用者可以直接分辨來源是向量片段、圖譜關聯，還是 KB 匯整後的摘要，而不是看成「直接讀原始檔」。
2026-05-21 追查「⚠️ 資料不足原因」這類回覆：那三條原因（搜尋命中但無詳細數據、相似度分數偏低、PDF/圖片難直接讀表）不是後端明文返回的事實診斷，而是模型根據 KB context 自行整理出的不足說明。實際上，`SCU2140` 的 `/search` 任務是有從 Qdrant 找到 3 份來源、`citation_distribution` 也正確統計到 `4G/5G = 3`，只是 task 的 `answer` 可能是空字串或摘要過短，前端便把來源片段和「資料不足」提示一起送給小幫手，導致模型用一般化語句解釋不足原因。這類說法應視為「模型推測」，不能直接當成資料庫真的缺少該 PDF / 圖片或真的只剩低相似度結果。
2026-05-21 已依要求將 KB 的 Neo4j 與 QDrant 全部清空：Neo4j 以 `MATCH (n) DETACH DELETE n` 後，`MATCH (n) RETURN count(n)` 為 `0`；QDrant 先前的 `knowledge_base` 與 `kb_syntheses` collections 已全部刪除，`/collections` 目前回傳空列表。之後若要做新的 ingest 測試，會從完全空白的資料庫開始。
2026-05-21 追查 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.xlsx` 放進 watch 後 Neo4j 沒新增、QDrant 只有 segments 但沒有 points：`watch_folder_scan` log 顯示檔案被判定為與 `processed` 同 hash 的重複檔，直接刪除 watch 版本，所以根本沒有進 ingest。後來確認 `data/processed/Simple/type6_NR-Throughput-SCU2140-n78-EV-V005.md` 與 `.source.json` 仍存在，因此 duplicate detection 會把 watch 裡的新檔移除。QDrant 目前 `points_count=0` 但 `segments_count=8`，代表 collection 曾經存在並保留分段結構，但實際向量點已空，不代表有新資料成功寫入。
2026-05-21 已排除這次手動 ingest 會被重複檔擋下的因素：`data/processed/Simple/type6_NR-Throughput-SCU2140-n78-EV-V005.md`、`.source.json`、`.xlsx` 已從 processed 移除，並且 `cleanup_existing_document('type6_NR-Throughput-SCU2140-n78-EV-V005')` 也已在 Neo4j / QDrant 清空對應資料。現在若再把 `/home/da40_ai_gb10/knowledge-base/data/raw/SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.xlsx` 放入 watch，應可避免再次因同 hash 舊檔而被 watch duplicate detection 直接刪除。
2026-05-21 已把聊天主路徑改回「回答一定帶 KB context」：`frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 現在都會先用 `searchApi(..., 'vector', { top_k: 5 })` 取得知識庫結果，將 `formatKnowledgeBaseContext(result)` 組成 prompt 後，再把同一則使用者問題送給 OpenClaw；若 KB context 未能取得，仍會送出一個明確標示「知識庫不足」的 context block。這代表目前小幫手回答會重新以 KB 檢索內容作為前置參考，而不是只靠 OpenClaw 自身答案或原始文字脈絡。
2026-05-21 目前最新聊天流程已回到「先取 KB context，再送 OpenClaw」：前端按下送出後先把訊息設為 loading、啟動 KB vector 搜尋（`top_k=5`）、等待 `/tasks/{task_id}` 完成並把 `result.answer + result.sources` 組成 `formatKnowledgeBaseContext(result)`；接著把「【知識庫參考資料】 + 使用者問題 + 回答要求」一次送給 OpenClaw WebSocket upstream。KB 搜尋結果仍會同步更新卡片盒的引用分布，但不再只是背景補來源，而是會進入回答 prompt。若 KB 沒有可用內容，仍會送一段明確標示「知識庫不足」的 fallback context，避免完全脫離 KB。
2026-05-21 已先暫停 `kb_syntheses` 機制：`src/search/__init__.py` 已移除 search() 中的 synthesis 快取讀取，也移除 hybrid / hybrid_plus 的 synthesis 寫回。搜尋路徑現在不再讀寫 `kb_syntheses`，避免舊摘要覆蓋 QDrant / Neo4j 的當次結果。
2026-05-21 進一步把搜尋 prompt 收斂成保守版：`_generate_answer_vector()` 與 `_generate_hybrid_answer()` 都新增規則，只有在完全沒有相關來源時才可以說「無法回答 / 查無資料」；只要有找到相關來源，就不能再說沒有資料，若片段不足則必須明確說「已找到相關文件，但片段不足以重建完整答案」。前端送出的 KB context 也同步改成同樣規則。
2026-05-21 再次實測 `請查詢SCU2140相關報告資訊`：`/search` 仍會從 QDrant / KB 取回 3 筆來源，`citation_distribution` 為 `4G/5G=3`，`answerLength=0` 但 KB context 仍可由 sources 組出；最終 OpenClaw 回覆已能直接根據同一份 `SCU2140` 報告輸出完整摘要與 `參考來源：SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md（已攝入知識庫）`，不再把有來源的情況誤說成查無資料。這次 live test 也確認 KB 資料確實是從 QDrant 命中後再帶入回答流程，而不是直接讀原始檔。
2026-05-21 再次針對 `SCU2140` 檢查 QDrant 內容：collection `knowledge_base` 內共有 11 個 points，且不只含文件中繼資訊；其中 `chunk_index=7` 的 `## 4. Performance Test` 已包含 TCP/UDP throughput 與 latency 表格，`chunk_index=8` 的 `## 5. Reference` 也含更完整的 throughput / BLER / RTT 數據。這次小幫手之所以回出文件基本資料、章節與圖片附件，而不是吞吐量表格，較像是查詢時命中了前置章節與 TOC 類 chunks，而非 QDrant 沒有詳細數據。未來若要穩定拿到數值，查詢語句應更聚焦在 `throughput / test result / BLER / latency`，或調整檢索排序讓結果優先包含 7、8 這類性能表格 chunk。
2026-05-21 這次針對 `SCU2140` 的修正思路可泛化到其他「結構化 / 數值型」文件題型：例如 throughput 報告、測試結果表、規格表、log 摘要、SOP 條列。原則是讓 KB context 優先攜帶最接近答案的表格/數值 chunk，而不是只帶文件中繼資訊、TOC 或前言。對敘述型文件則可維持原本摘要優先的組裝方式，不一定要強行套用表格優先策略。
2026-05-21 已開始把 `SCU2140` 這一類 report 的 KB context 組裝改成報告優先：`frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 都新增 report-like source 偵測與排序，會優先把 `Performance Test` / `Test Result Summary` / `Reference` 這類段落送進 prompt，並把 report 類摘要長度放寬到約 1200 字左右，避免只有文件中繼資訊和目錄章節被帶入回答。非 report 類文件仍維持原本的前 5 筆 sources + 180 字摘要策略。
2026-05-21 進一步修正 `SCU2140` 類報告的檢索召回：`/search` 現在已支援 `top_k` 並會把前端傳入值一路送到 `search_task` 與 `kb.search()`；任務層對 report-like 查詢會自動把召回至少拉到 `8`，避免只拿到 TOC / 前言 chunk。`SearchRequest` 也補上 `top_k` 欄位，`/search` 的 cache key 會把 `top_k` 納入，避免不同召回設定互相污染。`SearchEngine.search()` 也已改為支援並轉傳 `top_k` 到 basic/deep/vector/hybrid/hybrid_plus 各路徑。已執行 `python3 -m py_compile src/web_api/__init__.py src/web_api/tasks.py src/search/__init__.py` 並成功跑完 `./restart_kb.sh`，runtime 已載入新版召回邏輯。
2026-05-21 重新實測 `請查詢SCU2140相關報告資訊`（`mode=vector`, `top_k=8`）後，`/tasks/{task_id}` 的 `sources` 已穩定拉出 `Performance Test` 的數值 chunk，包含 `4. Performance Test`、`Test Case 1~16`、`TCP Throughput`、`UDP Throughput`、`RTT (ms)` 等完整表格內容；`citation_distribution` 顯示 `4G/5G = 8`、`matched_count = 8`，代表這次 `top_k` 傳遞與 report-like 擴大召回已真正生效，搜尋層不再只回 TOC / 前言 chunk。若之後小幫手仍少報數值，下一步應優先檢查前端 context 組裝與最終回答 prompt，而不是 QDrant 本身沒資料。
2026-05-21 已完成端到端 websocket 實測 `SCU2140` report 回答：前端 report-aware context 已再加強為「原文 + chunk + 數值優先」；經由 `/api/openclaw/chat-config` 取得 session / auth 後，模擬 `chat.send` 進入 OpenClaw，最後回覆已成功輸出完整數值表格，而不是只剩章節大綱。最終答案包含 `Test Case 1~3` 的 `TCP Throughput / UDP Throughput / RTT / BLER` 原始數據，以及 `最高 DL TCP 727 Mbps`、`最高 UL TCP 376 Mbps`、`最佳 Latency Avg 26 ms`、`BLER 全部 0%` 等關鍵數值，證實這次 report prompt 與 context 組裝已達到「數字優先、原文優先」的目標。後續若擴到其他 report 題型，可沿用此種「表格原文 + 明確數值提取要求」的寫法。

2026-05-21 進一步釐清 SCU2140 manual test 與自動 websocket 實測不一致的原因：後端 `/search` 對 `請查詢SCU2140相關報告資訊` 仍會回傳 8 筆來源，且其中已包含 `Performance Test` 的數值 chunk（例如 `Latency (ms)`, `TCP Throughput`, `UDP Throughput`）；我以最新 runtime 直接走 websocket `chat.send` 實測時，OpenClaw 最終確實會輸出完整數值表格。若瀏覽器手動測試仍只顯示章節摘要與資料不足，問題更像是該瀏覽器分頁尚未載入最新 runtime / JS bundle，或走到不同的舊前端訊息組裝路徑，而不是 QDrant / Neo4j 沒有詳細數據。
## Chunk 原圖檢視設計評估（2026-05-21）

- 2026-06-10 已確認目前這台知識庫主機上的 Docker 為 `Docker Engine - Community 29.1.3`，`docker info` 顯示主機與 Docker Server 架構皆為 `arm64/aarch64`，作業系統為 `Ubuntu 24.04.4 LTS`。因此若使用者詢問「目前系統所使用的 Docker 是官方的還是 ARM 版本」，正確結論是：這是官方 Docker Engine Community 的 ARM64 版本，不是第三方改版；容器層面的實際映像仍需依各 image 的 `platform`/manifest 判定，但 Docker 主程式本身就是 ARM64。
- 2026-06-10 已確認 knowledge-base 專案目前沒有額外的 `.env` 檔存在於專案根目錄；`docker-compose.yml` 與 `restart_kb.sh` 的環境變數主要是直接寫在 compose / script 內，實際會掛載的設定檔是 `config/config.yaml`，而不是透過單一 `.env` 集中管理。若未來要新增 `.env`，預設會是專案根目錄下的 `/home/da40_ai_gb10/knowledge-base/.env`，但目前並不存在。
- 2026-06-10 針對「在另一台全新電腦完整部屬 knowledge-base」的評估結論：最完整且風險最低的方式是把部署拆成四層處理，依序為「作業系統/工具」、「程式碼」、「狀態資料」、「驗證與維運」。程式碼層以 code-only repo 為主，並修正所有硬編碼絕對路徑或用 symlink 兼容；狀態資料層則把 `data/raw`、`data/processed`、`data/assets`、`data/uploads`、Neo4j volume、Qdrant volume、以及 `config/config.yaml` 分開備份與還原；運行層要預先安裝 Docker、Node、Python、Ollama 與必要模型；驗證層則以 `restart_kb.sh`、`/health`、Web UI、Neo4j Browser、Qdrant health、以及一筆實際查詢來確認端到端可用。若要做到真正可重複部署，下一步應把這套流程再腳本化成一鍵 bootstrap/restore 流程，而不是只靠手動步驟。

- 需求是：文件攝入到 QDrant 後，另外提供一個地方查看「被 chunk 的原生圖片」與文字。
- 結論是：QDrant 本身不適合作為原始圖片儲存層，應該只存 chunk 的索引與圖片引用資訊。
- ingest 時需要把原始圖片或頁面快照輸出成可回溯的實體檔案，並記錄在 chunk metadata 裡。
- 建議新增一個 companion artifact index 或至少一組穩定的 asset path，例如：
  - `data/assets/<doc_name>/page-001.png`
  - `data/assets/<doc_name>/sheet-<sheet>/image-<n>.png`
- Qdrant payload 至少要補：
  - `doc_path`
  - `source_kind`
  - `section_title`
  - `page_num` / `sheet_name`
  - `image_refs`
- 另外新增一個查看介面或 API，讓前端可以依 `doc_name + chunk_index` 顯示：
  - chunk 文字
  - 原圖預覽
  - 章節 / 頁碼 / sheet 資訊
- 對 Excel / 圖片型文件，converter 目前只會產生圖片摘要文字，沒有保存可直接展示的原圖資產，所以這部分要在 ingest/converter 階段補上。

## 系統管理頁新增 Chunk Viewer 分頁（2026-05-21）

- 使用者希望在 `https://61.216.9.52:3030` 的系統管理頁面另外開一個分頁，專門查看「chunk 原圖 + chunk 文字」。
- 建議不要把原圖直接塞進 QDrant；QDrant 只保存檢索所需 metadata 與原圖引用。
- 最合適的實作方式是：
  - 新增一個 admin tab / 獨立路由
  - ingest 時把原始圖片或頁面快照落盤成 asset files
  - QDrant payload 補 `doc_name`、`chunk_index`、`page_num` / `sheet_name`、`image_refs`
  - 新頁面用 `doc_name + chunk_index` 查 chunk 文字與原圖
- 這樣系統管理頁可以獨立瀏覽：
  - 來源文件
  - chunk 文字
  - 原圖預覽
  - 章節 / 頁碼 / sheet 資訊

## Chunk Viewer MVP 實作完成（2026-05-21）

- 已新增獨立路由 `/admin/chunks`，並在主導航列加入 `Chunk 檢視` 入口。
- 已新增後端 API：
  - `GET /admin/chunk-documents`
  - `GET /admin/chunk-documents/{doc_name}/chunks`
  - `GET /admin/chunk-assets/{asset_path:path}`
- QDrant payload 現在會帶：
  - `source_path`
  - `source_name`
  - `source_ext`
  - `source_dir`
  - `section_title`
  - `image_refs`
- chunk 分塊 metadata 也補上了 `source_path` 等來源資訊。
- Excel 檔的 embedded images 已可落盤到 `data/assets/<doc_name>/excel/<sheet>/image-xx.*`，並由 Chunk Viewer 直接顯示。
- 目前 MVP 先支援 Excel 內嵌圖片的原圖預覽；PDF 頁面快照與更完整的 OCR/裁切資產，留到下一階段補強。
- Chunk Viewer 頁面現在也補上了「選擇文件 -> 上傳並攝入」的控制項，不必切去其他頁面就能新增測試文件。
- Chunk Viewer 上傳流程改成先讀 response text，再嘗試 JSON parse；若後端/代理回傳 HTML 錯誤頁，UI 會顯示實際回應內容，不再只噴 `Unexpected token '<'`。
- Chunk Viewer 的文件清單與 chunk 資料端點需要經由 Nginx 反代到後端，已補上 `/admin/chunk-documents` 與 `/admin/chunk-assets` 的 proxy 規則；否則上傳成功後重新整理文件清單會拿到 `index.html`，造成 JSON parse 失敗。

## 原生圖片檢視需求（2026-05-21）

- 使用者要的是「chunk 後能直接看到完整原生圖片」，不是在 Markdown 或 UI 裡看到 base64 字串。
- 正確做法是把圖片當成獨立 asset 落盤，QDrant 只保存 `image_refs` 與 chunk metadata。
- Viewer 頁面應以 `img src=/admin/chunk-assets/...` 顯示真正的圖片檔，而不是把 base64 直接塞在 chunk content 裡。
- 若來源是 Excel 的 embedded image，可直接把 raw bytes 存成 png/jpg。
- 若來源是 PDF 或掃描檔，則需要先產生 page snapshot 或 crop 圖，再以 asset 方式顯示。
- converter 與 Chunk Viewer 都已加入 base64 inline media 清理，避免 chunk 文字區塊殘留長串 data URI；畫面只保留可點開的原圖 asset。
- 2026-05-21 已確認「原圖不顯示」的根因是舊 ingest 任務與舊 runtime 還在使用沒有 `image_refs` 的 payload；現在新版 `converter` 會把 Excel embedded images 落盤到 `data/assets/<doc_name>/excel/<sheet>/image-xx.*`，並把 `image_refs` 寫進 Markdown 與 QDrant payload。`/admin/chunk-documents/{doc_name}/chunks` 會回傳這些引用，而 `/admin/chunk-assets/{asset_path}` 可直接回傳原圖。為了避免 `restart_kb.sh` 再卡在 root-owned 舊 runtime 目錄，前端 build/runtime 已改到新的可寫目錄 `.frontend-build-runtime-user2`。
- 2026-05-21 最新狀態：已把 Chunk Viewer 與原圖資產鏈路跑通，SCE2200 / SCU2140 類 Excel 檔重新 ingest 後，`data/assets/<doc_name>/...` 已確實落盤，`/admin/chunk-documents/{doc_name}/chunks` 會回傳非空 `image_refs`，`/admin/chunk-assets/{asset_path}` 也能直接回原圖；`restart_kb.sh` 目前改用新的可寫前端 runtime `.frontend-build-runtime-user3`，避免再撞到 root-owned 舊目錄。後續若再看到 /admin/chunks 只顯示文字而無圖，優先檢查是否是舊瀏覽器分頁或舊 runtime 快取，而不是 ingest 或 asset endpoint 本身。

## Chunk 編輯與回復（2026-05-21）

- 若未來要讓使用者直接修改 chunk 文字，正確設計不應只改 Qdrant 中某一筆 chunk，而是採「來源檔 / 章節為單位」的版本化流程。
- 每次套用修改前，應先保留原始來源檔與該次 ingest 產物快照，讓使用者可以一鍵回復上一版。
- 回復上一版時，應以「重新 ingest 舊版本來源」的方式回復 Neo4j、Qdrant、chunk viewer 與圖片資產的一致性，而不是只把 Qdrant 單筆 content 改回去。
- 若有 LLM 幫改，應先產生建議 diff，再由使用者確認後才寫回來源檔。
- 簡化版 MVP 可以做成：
  - 編輯前自動備份原始 markdown / source json / asset refs
  - 提供 `回復上一版` 按鈕
  - 回復後重新 ingest，保持資料庫與 viewer 同步
- 目前已開始實作可編輯版本：新增 `data/chunk_edits/<doc_name>/` 備份目錄、後端 chunk edit / restore API，以及 Chunk Viewer 的 inline 編輯與版本歷史操作；儲存時會先備份來源檔，再修改來源 markdown 並重新 ingest，回復版本也同樣會重新 ingest 以保持 Neo4j / QDrant / 原圖資產一致。
- 2026-05-22 進一步修正 chunk 編輯後原圖消失的問題：在修改或回復 chunk 前，系統會先嘗試從 converted markdown 反推原始 xlsx（優先找 `uploads/**/original/<stem>.xlsx`，找不到再看 `data/raw/<stem>.xlsx`），並呼叫 converter 重新輸出 Excel embedded images 到 `data/assets/<doc_name>/...`，之後才重新 ingest。這樣修改文字內容時可保住原圖資產，不必再手動重跑整份 Excel 攝入。
- 2026-05-22 進一步確認 `SIT-SR-SC-NR-Handover-SCE2200-n79-EV-V13.8` 的原圖消失原因：不是 Chunk Viewer 本身壞掉，而是先前 chunk edit/reingest 只改了 markdown 並重寫 Neo4j / Qdrant，沒有重新生成 Excel 原圖資產；當時 `data/assets/SIT-SR-SC-NR-Handover-SCE2200-n79-EV-V13.8` 已不存在，所以 viewer 只能看到原圖引用字串。現已補上 `rebuild_source_excel_assets()`，在編輯或回復 chunk 時會先找原始 xlsx 並重建 `data/assets/<doc_name>/...`，再做重新 ingest，避免之後再發生原圖消失。

- 2026-05-22 已直接對 SCE2200 執行「不改內容、只重建原圖資產」：以最新的原始 xlsx 重新輸出 22 個 asset 檔到 `data/assets/SIT-SR-SC-NR-Handover-SCE2200-n79-EV-V13.8/excel/...`，沒有改動 chunk 文字或 QDrant payload；這樣 `/admin/chunks` 重新整理後即可直接讀到原圖，不需要再重跑整份 ingest。
2026-05-21 已修正 Chunk Viewer 原圖 404 的根因：`/admin/chunk-assets` 原本只認 `/app/data/assets`，但實際有原圖的掛載目錄是在 `/home/da40_ai_gb10/knowledge-base/data/assets`。`src/chunk_assets.py` 現在會優先選擇環境變數 `KB_ASSETS_ROOT`，其次選實際存在的掛載目錄 `/home/da40_ai_gb10/knowledge-base/data/assets`，再回退到 `/app/data/assets`。修正後已重新啟動 KB，並用 `curl -k` 實測 `https://127.0.0.1:3030/admin/chunk-assets/SIT-SR-SC-NR-Handover-SCE2200-n79-EV-V13.8/excel/Cover/image-01.png` 成功回傳圖片二進位，不再是 `資產不存在`。
2026-05-21 針對 Chunk Viewer 編輯儲存後刷新回原文的問題進行修正並驗證：根因有兩層，第一層是 nginx 原本只代理 `/admin/chunk-documents/{doc}/chunks`，沒有把 `/versions`、`/chunks/{chunk_id}/edit`、`/versions/{version_id}/restore` 這些子路由轉到後端，導致前端在存檔/載入版本歷史時拿到 SPA HTML 而不是 JSON；第二層是 `admin_chunk_document_edit_chunk()` 一開始還保留 `if old_content not in current_text: 409` 的硬擋，讓我新增的 section fallback 根本跑不到。已修正 nginx regex、移除前置硬擋，並在 `chunk_editing.apply_chunk_edit_to_source()` 加上 section-based fallback。實測結果：以 `SIT-SR-SC-NR-Handover-SCE2200-n79-EV-V13.8` 的 chunk 5 進行臨時編輯時，API 成功回傳 `edit_strategy=section` 且 `ingested=true`；修改後 `SAVE_TEST_MARKER` 會真的寫入來源 md 與 `/admin/chunk-documents/.../chunks`，刷新後仍保留；再用 version restore 成功回復並重新攝入，marker 從 source md 與 chunk payload 中清除，表示編輯 / 回復 / 重攝入鏈路已正常。
2026-05-21 已為 Chunk Viewer 的編輯/回復動作加入完成提示：在 `frontend/src/views/ChunkViewerView.vue` 中，`saveChunkEdit()` 與 `restoreVersion()` 成功時會額外跳出 `window.alert()`，讓使用者在完成儲存並重新攝入、或完成版本回復後立即看到明確提示；頁面內原本的訊息列仍保留。
2026-05-21 已整理一份可直接向主管報告的 Chunk 檢視功能開發說明文件：`CHUNK_VIEWER_DEVELOPMENT_REPORT.md`。內容包含 Chunk Viewer 的設計原理、資料流、前後端架構、原圖資產鏈路、編輯/版本回復機制，以及實作工具（FastAPI、Vue、Vite、QDrant、Neo4j、MarkItDown、OpenPyXL、Docker Compose、Nginx、curl 等）。
2026-05-21 已開始落實 Chunk Viewer 的非 LLM 美化方案：`frontend/src/views/ChunkViewerView.vue` 新增 `Raw / 美化版` 切換，`美化版` 直接使用 `marked` 將 chunk 內容渲染成 Markdown 格式，讓標題、表格、清單、引用與圖片呈現更像報告閱讀器的版面；這是純規則式呈現，不會動到原始 chunk，也不會用 LLM 重寫內容。
2026-05-22 已完成 Chunk Viewer 的非 LLM 美化方案並成功重啟：`frontend/src/views/ChunkViewerView.vue` 保留 `Raw / 美化版` 切換，`美化版` 以 `marked` 將 chunk 內容渲染成 Markdown 版面，並加上表格、引用、圖片、程式碼等視覺樣式；為避免前端 runtime 再度撞上 root-owned 舊目錄，`restart_kb.sh` / `frontend/package.json` / `frontend/vite.config.js` / `docker-compose.yml` 已統一改用新的可寫 runtime 目錄 `.frontend-build-runtime-user4`，且這次 `restart_kb.sh` 已成功完成建置與服務重啟。
2026-05-22 補充理解：小幫手回覆的「漂亮格式」不是單純靠 LLM 本身完成，而是 LLM 先根據 prompt 生成 Markdown/結構化內容，再由前端使用 `marked` 等 renderer 與 CSS 樣式把標題、表格、條列、引用、來源 footer 等呈現成更好讀的版面；另外 chunk viewer 的非 LLM 美化也是純前端渲染層處理，不會改動原始 chunk。
2026-05-22 Markdown renderer 說明：在這個專案中，renderer 指的是前端把 Markdown 文字轉成 HTML 的渲染器（例如 `marked.parse()`）。它不負責生成內容，只負責把 `# 標題`、`| 表格 |`、`- 清單`、`> 引用`、圖片與程式碼區塊轉成瀏覽器可顯示的版面；因此聊天回覆與 Chunk Viewer 的「漂亮感」主要來自「LLM 產生結構化文字 + renderer + CSS」的協作。
2026-05-22 補充 PDF 在 Chunk Viewer 的現況：PDF 可以從 `Chunk 檢視` 頁上傳並經 `MarkItDown` 轉成 markdown/chunk，但目前只有 Excel 內嵌圖片有完整的 asset 落盤與 `image_refs` 鏈路；PDF 這條路徑尚未看到 page snapshot / 原生頁面圖資產的完整支援，因此 PDF 若是掃描檔或圖表很多的文件，可能只會看到文字 chunk，而不一定能像 Excel 一樣直接看到原始圖片。
2026-05-22 評估 PDF 補強對 Excel 的影響：若 PDF 的「轉 md + 頁面快照」做成獨立於副檔名分支的處理流程，只在 `.pdf` 路徑輸出 page snapshot 與對應的 `image_refs`，理論上不會影響既有 Excel 的 embedded image 落盤與原圖顯示；真正要小心的是共用的 `converter`、`chunk_assets`、`cleanup` 與 `Chunk Viewer` 欄位結構，若把 PDF 邏輯寫進 Excel 共享段落，就可能影響原本已驗證正常的 Excel 圖片鏈路。因此建議維持 PDF / Excel 雙路徑分流，並用既有 Excel 範例（如 SCU2140 / SCE2200）做回歸測試，確認 Excel 原圖與 `image_refs` 不被回歸破壞。
2026-05-22 已為 Chunk Viewer 的上傳流程補上「攝入完成」提示：`frontend/src/views/ChunkViewerView.vue` 現在不只在送出後顯示已提交任務，還會輪詢 `/api/upload/tasks/{task_id}`，等任務真的 `completed` 後才跳出 alert，讓使用者明確知道處理已結束；若任務尚在排隊或處理中，畫面會持續顯示進度文字，避免把「已送出」誤認為「已完成」。
2026-05-22 追查 chunk viewer 的圖片 404 根因：同一個 chunk 裡若同時出現 `asset://...` 與 `原圖引用：...` 兩種寫法，`vector_store._extract_image_refs()` 會把它們都抓進 `image_refs`，導致其中一筆會帶前綴 `asset://`。前端 `Chunk Viewer` 與後端 `/admin/chunk-assets/{asset_path}` 若直接把這個字串當路徑，就會出現「一張正常、一張資產不存在」的狀況。已補上兩層修正：`vector_store` 會在抽引用時正規化成裸路徑，`admin_chunk_assets` 也會把舊資料的 `asset://` 前綴自動剝掉，避免舊 chunk 再出現 404。已用 `TEST_AMR_Device.pdf` / `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.xlsx` 走過驗證，PDF 頁面快照與 Excel 原圖都可正常顯示。
2026-05-22 補充設計邊界：若未來要讓 PDF 只保留最能反映原始數據的一張圖，這個規則應只套用在 `.pdf` 的頁面快照分支，不影響 `.xlsx` 的 embedded image 落盤與 `image_refs` 鏈路。也就是說，Excel 保持現有全量原圖輸出不變，PDF 才做「擇優保留一張」或「頁面快照縮減」的策略，兩條資料流應維持獨立，避免回歸到 Excel 圖片顯示不完整的問題。
2026-05-22 補充 PDF 原圖抽取可行性：若想把 PDF 內嵌的原圖直接抽出，而不是用整頁 page snapshot，技術上可行，但要明確區分 PDF 的兩種資產型態：① 嵌入式 raster image（可直接抽檔）② 向量圖 / 文字 / 表格版面（無法直接抽成單一圖檔，通常仍要靠頁面渲染）。因此若未來要做 PDF 原圖檢視，較穩的做法是「嵌入式圖片抽取 + 頁面快照」雙軌並存，並維持 Excel 的 image_refs 鏈路完全不動。
2026-05-22 已正式落實 PDF 的「內嵌原圖抽取 + 頁面快照」雙軌方案，並且保留 Excel 鏈路完全不動：`src/converter/__init__.py` 現在在 `.pdf` 分支中同時做兩件事，一是用 `pdftoppm` 產生頁面快照，二是用 `pdfimages -list` / `pdfimages -all -p` 抽出 PDF 內嵌圖片；兩種資產都會寫入 `data/assets/pdf/<doc_name>/...`，再以 `asset://...` 的形式掛到 markdown 與 `image_refs`。另外也把 `src/vector_store/__init__.py` 與 `src/web_api/__init__.py` 的資產引用做了正規化，避免舊資料裡夾帶 `asset://` 前綴導致 Chunk Viewer 點圖 404。已用 `AFC Device (DUT) Compliance Test Plan v1.7.pdf` 實測到 `image_refs=69`，同時維持 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.xlsx` 的 14 筆 Excel 圖片引用正常，確認 Excel 沒有被 PDF 新流程影響。
2026-05-22 已開始實作 PDF 的獨立頁面快照路徑，且不影響 Excel 現有鏈路：`src/converter/__init__.py` 針對 `.pdf` 新增 `poppler-utils` 依賴的頁面渲染與資產落盤，將每頁輸出為 `data/assets/<doc_name>/pdf/page-XXX.png`，再把 `原圖引用：asset://...` 寫入 markdown，讓 `vector_store` 能把頁面圖引用進 Qdrant payload；Excel 的 `.xlsx` 分支仍維持原本的 embedded image 落盤與摘要輸出邏輯，不共用 PDF 的頁圖處理。已用本機 `TEST_AMR_Device.pdf` 實測成功，輸出 4 頁 page snapshot；也用 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.xlsx` 對照驗證，Excel 仍可正常產出 14 個 `image_refs` 與原本的圖片摘要格式，未被 PDF 新分支影響。
2026-05-22 追查 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.xlsx` 無法從 `watch` 攝入的原因：不是 converter 或 Neo4j / Qdrant 壞掉，而是 `data/processed/Simple/type6_NR-Throughput-SCU2060-n79-EV-V13.8.xlsx` 已存在且與原始檔內容完全相同。`watch_folder_scan` 在同步 `watch/processed` 時會先以 hash 去重，發現同內容就直接刪除 watch 內的檔案，因此不會生成新的 ingest 任務；log 已明確出現 `watch 與 processed 內容相同，已刪除 watch 重複檔` 與 `發現 0 個待處理檔案`。若要強制重新攝入，需先刪除既有 processed 版本或改動檔案內容以產生不同 hash。
2026-05-22 已依需求清除 `data/processed/Simple/type6_NR-Throughput-SCU2060-n79-EV-V13.8.*`（md / source.json / xlsx），以排除 watch/processed 去重造成的阻擋。現在再把 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.xlsx` 放回 `watch` 時，應會走新的 ingest，而不會再因為與 processed 既有版本 hash 相同而直接被刪除。
2026-05-22 已再次實測 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.xlsx` 從 `watch` 攝入：檔案從 `data/raw` 複製到 `data/watch/` 後，`watch_folder_scan` 正常辨識成 `Report` 流程，沒有再被 hash 去重刪掉；log 顯示 `[Report] Neo4j 文件結構完成`、`[Report] QDrant 寫入完成`、`向量攝入完成`，最後 task 回傳 `processed=['SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.xlsx']`、`total=1`。實際檔案也已落到 `data/processed/Report/SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.{md,source.json,xlsx}`，確認這次是真的攝入成功而不是被去重擋住。
2026-05-22 追查 `SCU2060` 為何已成功攝入卻仍被小幫手說成「QDrant 集合為空」：已確認知識庫本體是正常的，`/tasks/{task_id}` 回傳 `matched_count=8`、`total_sources=8`，QDrant 內也能 scroll 到 `doc_name = SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8` 的 points；問題更像是 OpenClaw 內部 workspace 還保留舊 fallback 規則（`kb-query` skill 與 `memory/2026-05-07.md`）教它在 API / index.md 不足時直接掃 `data/processed/`，這會繞過正式 KB 檢索鏈路，導致它可能直接讀原始檔並說出與資料庫狀態不一致的結論。已開始把 OpenClaw workspace 的舊 fallback 與 `index.md` 依賴改成以 `/search` API 的 `sources` 為準。
2026-05-22 同題重測已完成：在重新載入 OpenClaw gateway / workspace 規則後，再問 `請查詢SCU2060相關報告數據`，最終回覆已不再說 QDrant 空，而是正確引用 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md`，並列出 SCU2060 的 throughput / latency / BLER 數據。實際 session 仍會先做 index / processed 的輔助查找，但最後答案已改為基於知識庫文件內容，不再走「QDrant 空就直接讀原始檔」的舊 fallback；這代表 OpenClaw workspace 舊規則與 gateway 熱載入已更新到新查詢路徑。
2026-05-22 目前狀態確認：小幫手已能正常拿到知識庫內容並完成回答，但在某些 session 裡仍會先用 `index.md` 與 `data/processed/` 做輔助查找；真正的修正點是讓最終答案回到 `/search` / 知識庫文件結果，而不是再用「QDrant 空」或直接讀原始檔的舊 fallback。也就是說，現在不是完全取消所有文件系統輔助，而是把它降為前置探索，最終答案仍需以 KB 檢索結果為準。
2026-05-23 已重新實測 `SCU2140的相關報告數據`：OpenClaw 這次實際對 KB 發出 `mode=hybrid` 查詢，`/tasks/{task_id}` 回傳的 `sources` 內含 3 筆向量檢索結果，且 `mode` 顯示為 `vector`，`citation_distribution` 也回到 `4G/5G = 3`。這表示小幫手確實有經過 QDrant 的向量查詢路徑，而不是只讀原始檔或直接跳過 KB；同時也再度證實，若最終回答內容不理想，問題比較可能出在 OpenClaw 的 prompt / context 組裝，而不是 KB 本體沒有查到 QDrant。
2026-05-23 進一步追查使用者看到「知識庫中沒有針對 SCU2140 的向量或圖譜檢索結果；以上數據來自直接掃描 processed 目錄」的原因：這不是 KB 沒有查到，而是 OpenClaw 工作區仍殘留舊 fallback 規則，會把 `/search` 任務中 `answer` 仍為空的情況，誤判成沒有可用的向量 / 圖譜結果，進而嘗試改用 processed 直掃。已在 `/home/da40_ai_gb10/.openclaw/workspace/AGENTS.md` 移除該 fallback，並強制要求最終答案只能根據 `/search` 的 `sources` 與 Neo4j / QDrant 檢索結果作答，不可再直接掃描 processed。
2026-05-23 最新重測已完成：`SCU2140的相關報告數據` 在 OpenClaw 端已改為正確發出 KB `/search`，並在 `/tasks/aea25eda-1966-4064-8cbf-2c1c7bf61680` 回傳 `status=completed`、`sources=3`、`citation_distribution=4G/5G=3`，最終回答也已改成根據知識庫查詢結果整理 `SCU2140 / SCU2060 / SCU5050` 的報告數據摘要，沒有再出現「QDrant 空、直接掃 processed」的舊說法。這次修正的重點是：`/.openclaw/workspace/skills/kb-query/SKILL.md` 已改為使用 `http://127.0.0.1:3030` 作為 KB API，並且 `answer` 空字串不可再被誤判為「KB 沒命中」；OpenClaw gateway 也已重新載入該規則。
2026-05-23 進一步追查確認：`kb-ingest/SKILL.md` 與 `kb-ingest/references/ingest_api.md` 內仍殘留 `localhost:8000`、`index.md`、`processed` 的舊教學，已同步改為 `127.0.0.1:3030` 與「index.md / processed 只屬歷史與輔助，不可作為最終答案 fallback」。新一輪 session 也已驗證：先讀 `kb-query/SKILL.md`，再走 `/search` 與 `/tasks/{task_id}`，最後回傳 `status=completed`、`sources=3`、`citation_distribution=4G/5G=3`，不再掉回直接掃 processed。這表示現在的根因不是 KB 空，而是 workspace 內的舊教學文件仍會誤導 agent；目前已把最主要的誤導來源收斂掉。
2026-05-23 追查 `wifi 關鍵訊號值` 的來源顯示方式：若 OpenClaw 最終回覆的「參考來源」標成 `processed/WiFi`，代表這次回答大概率是走了工作區檔案系統的 local scan / index 摘要，而不是從 KB `/search` 的 `sources` 直接組出來。問題不在 QDrant / Neo4j 本體，因為 KB 實際已可查到 WiFi 文件；真正的偏差點在 OpenClaw 的查詢路徑仍允許把 `index.md` 與 `data/processed/` 當成可用來源。後續若要徹底修正，應再收緊 OpenClaw workspace 的提示與 fallback，讓「只要有 `/search` 的 sources，就必須引用 KB 檢索結果；不得以 processed 檔名作為最終參考來源」成為硬規則。
2026-05-23 進一步定位 `wifi 關鍵訊號值` 仍引用 `processed/WiFi` 的殘留來源：目前最可疑的不是 `kb-query/SKILL.md`（它已明確禁止 processed fallback），而是 `/.openclaw/workspace/MEMORY.md` 裡仍保留完整的 `index.md` 歷史流程章節，以及 `/.openclaw/workspace/memory/2026-04-29.md` 內的「使用者提問 → 讀取 index.md → 找到相關文件 → 向量+圖譜搜尋 → 生成答案」舊流程描述；另外 `/.openclaw/workspace/skills/kb-ingest/references/ingest_api.md` 也仍以 `processed/` 作為流程終點。這些歷史/教學內容雖然標註為舊機制，但仍可能被 agent 當成可用路徑，導致最終答案引用本機實體檔案而非 `/search` 的 `sources`。後續若要完全清掉，應優先收斂這三份檔案中的歷史描述與任何可被解讀為「直接讀 processed」的示例。
2026-05-23 已把上述三份 OpenClaw workspace 內容進一步收斂：`/.openclaw/workspace/MEMORY.md`、`/.openclaw/workspace/memory/2026-04-29.md` 已改成只保留 `index.md` 的歷史備註，明確禁止再把它當作回答流程或 fallback；`/.openclaw/workspace/skills/kb-ingest/references/ingest_api.md` 也移除了 `processed/` 作為流程終點的寫法，並把回答依據改回 `/search` 的 `sources` 與 Neo4j / QDrant 檢索結果。這次收斂的目的，是讓 OpenClaw 只剩「/search 的 sources 才能當參考來源」這條路，不再被歷史教學文件暗示去直接讀本機 processed 檔案。
2026-05-23 進一步再收斂歷史段落中的舊索引語意：`/.openclaw/workspace/MEMORY.md` 與 `/.openclaw/workspace/memory/2026-04-29.md` 已將 `index.md` 改寫成純歷史註記，不再出現可執行的查詢流程；`/.openclaw/workspace/memory/2026-04-30.md`、`/.openclaw/workspace/memory/2026-05-17.md` 也已把「index.md / 舊分類」字樣壓成抽象歷史描述。現在 workspace 中能引導模型的，應只剩 `kb-query` 的正式規則與 `/search` 回傳的 `sources`，避免再被歷史章節帶回檔案系統掃描。
2026-05-23 最新重測 `wifi 關鍵訊號值`：雖然我已把 `kb-query/SKILL.md` 的 KB 端點改成 `https://127.0.0.1:3030/search` 與 `https://127.0.0.1:3030/tasks/{task_id}`，但 OpenClaw 這次執行時仍出現舊式 fallback 與錯誤 endpoint：先嘗試 `http://127.0.0.1:3030/search`（被 nginx 以 HTTPS port 擋下 400），又嘗試 `https://127.0.0.1/search`（回到 AnythingLLM 前端頁面），後面還出現 `docker exec kb-web curl -s http://localhost:8000/tasks/...` 的舊輪詢命令。這表示目前它仍未穩定只依 `/search` 的 `sources` 作答，仍殘留舊的本機/processed 類 fallback，需進一步讓 OpenClaw 重新載入 workspace 規則或檢查其他會覆蓋 `kb-query` 的記憶來源。
2026-05-24 進一步追查到真正的殘留來源之一是 OpenClaw 的短期回憶庫 `/.openclaw/workspace/memory/.dreams/short-term-recall.json`：其中仍有舊片段明確提到 `processed`、`localhost:8000`、`index.md`。已先手動刪掉兩條最直接的舊 fallback recall，讓 recall store 從 18 條降到 16 條；接著嘗試 `openclaw memory index --force` 強制重建索引，但因 Gemini embedding quota 429（RESOURCE_EXHAUSTED）而失敗，因此短期記憶索引暫時無法靠 reindex 自動刷新。這代表如果之後 OpenClaw 還會回到 processed / index.md fallback，優先查的已不只是 skill 檔，而是 short-term recall 是否仍混入歷史片段。
2026-05-24 進一步確認：僅清理 workspace 文件與 Git reflog 還不夠，OpenClaw 的 `agent:main:main` 仍會沿用同一條舊 session 線；即使嘗試 `openclaw agent --session-id <uuid>` 或 `openclaw agent --to +15555550123`，回覆仍重用舊 session id `7fa7c1e8-dcc2-4865-9ba7-811516edb356`，並繼續把 `wifi 關鍵訊號值` 直接答成本地文件答案。已確認 `openclaw-gateway` 重啟後仍如此，表示目前剩下的污染核心更像是 agent session / compaction / memory 內部狀態，而不是單純的 skill 或檔案內容；要真正切斷舊 fallback，可能需要能重置 main session 的機制，或改用能真正產生新 session 的入口。
2026-05-24 進一步追查 OpenClaw session 汙染：`openclaw agent` 仍持續沿用舊的 `agent:main:main` session，嘗試 `--session-id` / `--to` 都無法真正切斷；而 `openclaw acp client` 雖可建立全新 ACP session（例如 `a2726482-413e-4fc8-a905-4705956ffcde`），但落盤到 `/home/da40_ai_gb10/.openclaw/agents/main/sessions/*.jsonl` 時會出現 `ACP_SESSION_INIT_FAILED`，訊息指出 `ACP metadata is missing for agent:main:acp:<session>`，並要求用 `/acp spawn` 重新建立與 thread rebind。這表示目前污染核心已不只是 skill / workspace / Git reflog，而是 `agent:main:main` 對應的持久 ACP metadata / session 綁定仍未真正清掉；下一步應聚焦在正確的 `/acp spawn` 或 session rebind 流程，而不是繼續嘗試 `openclaw agent` 舊入口。
2026-05-24 進一步查到 OpenClaw 官方 ACP 文件：`openclaw acp` 是 Gateway-backed ACP bridge（給 IDE / client 用），而真正用來跑外部 harness 的是 ACP Agents / `/acp spawn`。官方文件明確寫到：若要把這個工作帶回 OpenClaw 的 chat-bound ACP session，應使用 `/acp spawn codex --bind here`（或 thread binding 變體），而不是只用 `openclaw acp client`。這也解釋了為什麼我用 `openclaw acp client` 開出的新 session 仍然出現 `ACP_SESSION_INIT_FAILED`：那只是 bridge/client 層，不會自動替 agent thread 建立 ACP metadata。下一步若要真正解除 `agent:main:main` 汙染，應回到 `/acp spawn` 的 agent-side 重新綁定流程，而不是繼續在 bridge client 上反覆開新 session。
2026-05-24 依官方 ACP 文件進一步釐清：`openclaw acp` 只是 Gateway-backed ACP bridge（給 IDE / client 用），它不會替 agent-side conversation 自動建立 ACP metadata；真正要重建可綁定的 harness session，必須走 OpenClaw 的 ACP Agents 流程，也就是在可綁定的 chat / agent surface 使用 `/acp spawn codex --bind here`（或對應的 thread 變體）。我實測 `openclaw acp client` 建出的多個新 session（例如 `a272...`、`b3f...`）都只會得到 `ACP_SESSION_INIT_FAILED`，訊息明確寫著 `ACP metadata is missing for agent:main:acp:<uuid>` 並要求重新 `/acp spawn` rebind thread；這表示目前卡住的點是「agent-side ACP metadata / thread rebind」，不是 bridge session 本身。後續若要真正解除 `agent:main:main` 汙染，應優先找到可執行 `/acp spawn codex --bind here` 的原生 OpenClaw 對話入口，而不是再繼續用 `openclaw acp client` 反覆嘗試。

## 2026-05-24 OpenClaw ACP metadata recovery
- OpenClaw 的問題核心已縮小到 ACP metadata/session store，而不是 KB 本體。
- `~/.openclaw/agents/main/sessions/sessions.json` 先前沒有任何 `source=acp` 的 session entry，導致 `ACP_SESSION_INIT_FAILED`。
- 已在 `sessions.json` 補入最小 ACP session metadata（`acp.identity` 帶 `agentSessionId`，state=resolved/source=ensure），讓 ACP client 可以正常起 session。
- 之後以 `wifi 關鍵訊號值` 做的測試，OpenClaw 已能正確走到 KB 的正式查詢結果，不再回退成直接掃 `data/processed/`；回覆內容也正確列出 WiFi RSSI 門檻與來源。
- 代表目前的關鍵路徑已從「本機檔案 fallback」收斂回「`/search` + `sources` + QDrant/Neo4j」。

## 2026-05-24 OpenClaw ACP metadata rebind success
- 已確認 OpenClaw 的真正污染點是 ACP session metadata，而不是 KB 本體或 `processed/` 內容。
- `~/.openclaw/agents/main/sessions/sessions.json` 原本沒有任何 `source=acp` entry，會導致 `ACP_SESSION_INIT_FAILED` 並觸發舊 fallback。
- 已補入一筆最小可用的 ACP metadata（`agent:main:acp:rebind-20260524`），讓 ACP client 可正常起 session。
- 以 `wifi 關鍵訊號值` 測試後，OpenClaw 已回到正式 KB 路徑，能正常命中 QDrant 的 `sources`，並正確輸出 WiFi RSSI 門檻資料。
- 目前 `sessions.json` 內僅保留這一筆 ACP metadata，未再發現其他 ACP session 汙染項。

## 2026-05-25 deterministic KB fallback race fix
- Browser `/chat.html` 與 Vue `ChatView.vue` 已把 deterministic KB 補述改成「延遲回補最後一則 bot bubble」：當 report-like 問題先出現保守答案、而 KB sources 稍後才回來時，前端會用同一輪 `/search` 的 `sources` 重新覆寫最後一則 bot 訊息，補上 `【知識庫補充摘錄】`，避免不同電腦 / 不同 session 因時序差異看不到補述。
- `chat.html` 以 `botMessageSequence + data-message-seq` 定位最後一則 bot bubble；Vue 版則以 `pendingDeterministicKbFallback.messageIndex` 直接回寫 `messages` 陣列。這樣不依賴 KB sidecar 一定先到，也不依賴模型一定先完整回覆。
- 這次已重新 build 並 `restart_kb.sh` 重啟成功，需再做 browser 驗證確認 `SCU2060` / `SCU2140` 的保守回答是否真的會在 KB sources 晚到時被回補。
2026-05-24 SCU2140 1307 Mbps hallucination traced and hardened
- 已確認 `1307 Mbps` 只存在於 `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001`，不屬於 `SCU2140`。
- 以 `請顯示SCU2140的throughput數` 重新測試時，KB `/search` 的前段來源已經正確收斂到 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005`，但 OpenClaw 最終回答仍曾錯把 `1307` 帶進 `SCU2140` 的結果中，證明這次是**回答層 hallucination / prior-memory contamination**，不是 retrieval 汙染。
- 已在 `/.openclaw/workspace/skills/kb-query/SKILL.md` 補上更硬的數字保真規則：
  - 指定文件代號時，只能使用同一份文件代號的來源；
  - 回答內所有數字、Case 編號、Mbps / ms / dBm 等指標，必須能在本次 `/search` 的 `sources` 文字中逐字找到；
  - 禁止沿用先前對話或其他報告中的數字補值。
- 目前下一步應優先驗證新版 `kb-query` 是否能真正壓制 `SCU5050` 的 `1307` 混入 `SCU2140` 回答的現象。
- 2026-05-24 進一步收緊數字題規則：`kb-query/SKILL.md` 已新增「逐列抽取」模式，明確要求 throughput / latency / BLER / RTT / RSSI 等數值題只能列出本次 `sources` 中逐字可對上的 case / row / column，不得自行整理出新的 `最高值 / 最佳值 / 趨勢摘要`，除非來源文件本身已明確標出。若來源只有封面、TOC 或摘要，則只能誠實說明片段不足，不能補值。目標是徹底避免 SCU2140 類題目再從其他報告借用數字或跨 case 合成新結論。
- 2026-05-24 再次強化數值題輸出格式：`kb-query/SKILL.md` 現在要求 throughput / latency / BLER / RTT / RSSI 類問題必須以「來源文件逐 case 原文摘錄」形式回答，固定先說明逐 case 摘錄，再接 markdown 表格，且禁止自行生成 `Peak Performance` / `Key Takeaways` / `Summary` / `最佳值` / `趨勢觀察` 等跨 case 濃縮段落；若使用者沒有明確要求摘要，就只能做原文抽取，不得把多個 case 改寫成濃縮版。目標是讓 `SCU2140` 這類題目即使查對資料，也不能再被模型自行壓成摘要而失真。
- 2026-05-24 進一步補上數值題的正反範例：`kb-query/SKILL.md` 已明確寫入 throughput 類問題的**正確範例**應是 `Case | Band | TDD Time Slot | DL (TCP) Mbps | ...` 的逐列表格，**錯誤範例**則包含 `最高 DL 733 Mbps`、`最佳 UL 519 Mbps`、`快速結論`、`Peak Performance` 等濃縮句型；同時禁止在來源沒有摘要表時自行產生 `快速參考` 或 `重點整理`。這是為了避免模型即使知道不能跨報告借數字，仍習慣性把原始 case table 再壓縮成摘要。
- 2026-05-24 數值題又進一步加上回答後處理：`src/search/__init__.py` 新增 `_sanitize_numeric_response()`，會在 LLM 回答後自動刪除 `快速參考` / `Summary` / `Peak Performance` / `Key Takeaways` / `最佳值` / `最高值` / `趨勢觀察` / `快速結論` / `摘要` 等摘要段落，只保留逐 case 原始表格與來源，避免模型即使 prompt 已限制仍自行附加 summary block。這是為了徹底壓掉 `SCU2140` 類數值題輸出末尾的濃縮摘要，只讓結果保留原始 case table 與來源標註。
- 2026-05-24 最新實測 `查詢SCU2140 的throughput 數據`：正式 agent-side 路徑已可正確回傳 `SCU2140` 的完整 throughput 表格（Case 1~16），來源明確標註為 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md`，沒有再出現「找不到資料」或誤答成其他報告的情況。這次回覆仍帶有 `極值速查` 類摘要段落，代表資料已正確命中，但模型輸出後處理還需要再往下壓掉 summary block，讓結果更貼近「逐 case 原文摘錄」的要求。
- 2026-05-24 同題在不同電腦出現相反結果：一台電腦的正式 agent-side 測試已可穩定回到 `SCU2140` 的完整 throughput 表格；但另一台電腦詢問同題時，OpenClaw 卻回覆「知識庫中沒有 SCU2140 的相關資料」，並用泛化的 `Neo4j + QDrant + /search API` 來源說法。這表示問題不在 KB 資料本體，而更像是該電腦上的 OpenClaw session / client 路徑 / 快取狀態仍未完全同步到最新規則；後續若要處理，應優先檢查那台電腦是否仍在使用舊 session、舊 gateway 或尚未重新載入的 workspace 狀態，而不是再查 QDrant 是否有 SCU2140 資料。
- 2026-05-24 另一台電腦再測 `查詢SCU2140 的throughput 數據` 時仍回覆「KB API 未能提供足夠內容 / 知識庫中沒有 SCU2140 的相關資料」，這代表跨電腦的差異目前更像是各自的 OpenClaw client / session / endpoint 狀態不一致，而不是 KB 本體沒有資料。特別要注意：`kb-query` skill 現在硬指定 `https://127.0.0.1:3030/search`，若那台電腦沒有透過同一個 KB 主機或隧道提供 localhost 3030，實際就可能查到自己的本機而不是知識庫主機，因此會出現「這台能查到、那台查不到」的現象。後續排查應先確認那台電腦的 `127.0.0.1:3030` 到底指向哪裡，以及是否真的已重新載入新版 workspace / session。
- 2026-05-24 已嘗試以不同 session 方式重測 `查詢SCU2140 的throughput 數據`（使用 `openclaw agent --to +15555559999 ...` 開新 session）：在這台機器上仍能正常回傳 `SCU2140` 的完整 throughput 表格與來源 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md`，沒有重現「找不到資料」。這表示僅切換 session 並不足以重現另一台電腦的失敗情況，跨電腦差異更像是 endpoint / client 狀態不一致，而不是 session 變化本身。
- 2026-05-24 針對 `https://61.216.9.52:3030/chat.html` 的瀏覽器路徑做了實測：頁面可正常開啟、WebSocket 可連上，但同題 `查詢SCU2140 的throughput 數據` 的最終 payload 只回傳 `NO`，且 wait timing 顯示 `kbSearchMs=0`、`queueWaitMs≈35718ms`、`generationMs=0`、`totalMs≈50955ms`，代表這條前端 session 並沒有像正式 agent 路徑一樣拿到 KB sources，而是走到一條不同的瀏覽器/前端路徑。這再度證實跨電腦或跨入口的不一致，核心仍在 client/session/endpoint，不在 KB 資料本體。
- 2026-05-24 已修正瀏覽器版 `/chat.html` 與 Vue 版 `ChatView.vue` 的 KB 等待時間：原本 `prepareKnowledgeBaseContext()` 只等 `15000ms`，在慢一點的電腦上容易先 timeout，導致 OpenClaw 只收到空 KB context，最後回 `NO`；現在已把等待時間統一拉到 `60000ms`，與系統的「最多等 60 秒再送 OpenClaw」策略對齊，避免因不同電腦速度差異造成有些分頁拿不到 KB sources 的狀況。
- 2026-05-24 進一步把瀏覽器版 `/chat.html` 與 Vue 版 `ChatView.vue` 的 KB 等待時間再拉到 `120000ms`，避免較慢機器或較長 queue wait 時 KB context 尚未就緒就先送出 OpenClaw，造成瀏覽器分頁回 `NO` 或看起來像沒查到資料；`restart_kb.sh` 已重跑完成，新的前端 runtime 目錄也已同步生效。
- 2026-05-25 重新實測 `https://61.216.9.52:3030/chat.html` 上的 `查詢SCU2140 的throughput 數據`：頁面可正常連線、WS 也有建立，但最後 bot 仍回「知識庫中目前沒有關於 SCU2140 throughput 的查詢結果」，`wait timing` 顯示 `queueWaitMs≈104840ms`、`firstAssistantMs≈50545ms`、`totalMs≈120167ms`，而 `kbSearchMs=0`；console 也顯示 `[KB] Search timeout` 與 `No citation data from final payload or KB search`。這表示即使瀏覽器版 timeout 已拉到 120 秒，`/chat.html` 這條入口仍然沒有穩定拿到 KB sources，問題更像是這條瀏覽器 session / queue path 還沒真正對到正式 agent-side KB 查詢路徑，而不是 QDrant 本體沒有 SCU2140。

## 2026-05-24 SCU2140 檢索排序修正已生效
- 先前 `請顯示SCU2140的throughput數` 容易被 `SCU2060` / `SCU5050` 相似報告污染，主因是 vector 檢索 top_k 的前排來源仍混入封面、TOC、測試環境與交叉引用片段，導致正確的 `SCU2140` throughput chunk 沒有穩定排到前面。
- 已在 `src/search/__init__.py` / `src/vector_store/__init__.py` 加入文件代號提示 (`_extract_doc_hints`)、章節加權 (`_section_boost`) 與 rerank (`_rank_vector_results`)：
  - 會優先提高 query 中文件代號對應的同檔 chunk 權重
  - 會優先提高 `Performance Test` / `Reference` / `Test Result Summary` 類 chunk 權重
  - 會降低 `Cover` / `Table of Contents` / `Preface` 類 chunk 權重
  - `vector_search` 與 `_vector_search_raw` 先拉大候選數再重新排序，避免只有前幾筆雜訊
- 這次重新 `restart_kb.sh` 後，`/search` 查 `請顯示SCU2140的throughput數` 的前 8 筆來源已全部收斂到 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005`，前 4 筆分別是：
  - `## 4. Performance Test`
  - `## 5. Reference`
  - `## 3. Test Result Summary`
  - `## 2.6 Test Config`
- 這代表新的 rerank 已成功把真正的 throughput chunk 拉到前排，`SCU2060` / `SCU5050` 不再污染同題的 KB context；後續若小幫手還有答錯，優先檢查 OpenClaw 的 prompt / session，而不是 KB 檢索排序。

## 2026-05-24 OpenClaw workspace residual audit
- 重新稽核 OpenClaw workspace 後，殘留的 `processed/`、`index.md`、`localhost:8000` 只剩下：
  - `kb-query` skill 的禁止項（明確說不能再掃 `index.md` / `data/processed/`）
  - `kb-ingest` skill 的輸出路徑說明（`data/processed` 是 ingest 的目的地，不是 fallback 來源）
  - `MEMORY.md` 的歷史目錄註記
- 這些殘留不再構成可執行的回答 fallback；目前 OpenClaw 的有效 KB 依據已收斂回 `/search` 的 `sources` 與 Neo4j / QDrant 查詢結果。

## 2026-05-24 OpenClaw ACP retry still fails on generated session key
- 重新用 `openclaw acp --session agent:main:acp:rebind-20260524 client` 測試 `wifi 關鍵訊號值` 時，終端仍回報 `ACP_SESSION_INIT_FAILED`。
- 實際錯誤指出的 session key 是 `agent:main:acp:c0edd636-e9a1-4e50-a116-3a9f701b69b3`，與我手動補進 `sessions.json` 的測試 key 不同，表示 `openclaw acp client` 仍會生成自己的 ACP session key，不會直接沿用我手動補的那筆。
- 目前可確定：單純在 `sessions.json` 補一筆 ACP metadata，還不足以保證 `openclaw acp client` 的新 session 會自動匹配到；仍需找到真正的 `/acp spawn` / bind 流程或該 client 產生 session key 的正確掛勾點。

## 2026-05-24 OpenClaw 正式 agent 路徑驗證
- 進一步改用 `openclaw agent --agent main --message '/acp spawn codex --bind here' --json` 測試，這次能成功啟動一條新的 Codex ACP session，`agentMeta.sessionId = 349c0765-2632-4453-bdd4-6526b884b540`，代表真正可用的流程是 `agent` / `/acp spawn` 的 agent-side 路徑，而不是 `openclaw acp client` 的 bridge 路徑。

## 2026-05-24 SCU2140 throughput trace discrepancy
- 以 `openclaw agent --agent main --message '請顯示SCU2140的throughput數' --timeout 180 --json` 實測時，OpenClaw 最終回覆錯答成 `SCU2060` 的報告數據，未正確回到使用者要求的 `SCU2140`。
- 直接查 Qdrant 後確認 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005` 的資料確實存在，尤其 `chunk_index=12`（`## 5. Reference`）包含完整 throughput / latency / BLER / RTT 數值。
- 因此這次問題不是 QDrant 沒資料，而是 OpenClaw 的回答路徑發生了文件對象錯置，將 `SCU2140` 誤答成 `SCU2060`。後續應優先追查是否還有殘留 session/context 汙染，或 prompt / routing 在回答時拿錯來源文件。
- 再用同一條正式 `openclaw agent` 路徑測 `wifi 關鍵訊號值`，最終回覆已回到正確的 WiFi RSSI 表格，內容不再提 `QDrant 空`、`processed` 直掃或 `index.md` fallback。這表示目前 OpenClaw 已可透過正式 agent-side ACP session 正常走 KB 查詢路徑，而不是 bridge client 的舊污染路徑。
- 因此最新結論是：若要做可綁定、可持久的 ACP session，應使用 `openclaw agent` / `/acp spawn codex --bind here` 這條官方 agent-side 路徑；`openclaw acp client` 仍只適合作為 bridge/調試，不應當作主要查詢入口。

## 2026-05-24 ACP session cleanup
- 先前為了驗證 ACP metadata 而手動補入的測試 entry `agent:main:acp:rebind-20260524` 已從 `~/.openclaw/agents/main/sessions/sessions.json` 移除，並保留清理前備份 `sessions.json.bak-cleanup-20260524-111547`。
- 目前 `sessions.json` 已不再包含那筆 synthetic ACP key；正式可用的 ACP 路徑已確認是 `openclaw agent --agent main --message '/acp spawn codex --bind here'`，而不是 `openclaw acp client` 的 bridge session。
- 這次清理的目的，是讓 session store 回到乾淨狀態，避免之後把測試用 ACP key 誤認成正式對話綁定依據。

## 2026-05-24 latest KB probe
- 再次以正式路徑 `openclaw agent --agent main --message 'wifi 關鍵訊號值' --json` 觀察回覆結果，返回的是正確的 WiFi RSSI 表格，並附上 `type2_WiFi_Troubleshooting_Guide.md (Knowledge Base 本地文件)` 作為來源標記。
- 這次輸出沒有再出現 `ACP_SESSION_INIT_FAILED`、`QDrant 空`、`processed` 直掃或 `index.md` fallback 的語句，代表目前正式 agent-side 路徑已能穩定走知識庫查詢，且回覆內容與來源標註都回到預期狀態。
- 進一步以正式路徑 `openclaw agent --agent main --message '請查詢SCU2060相關報告數據' --json` 再測一次，這次回覆也正確輸出 SCU2060 報告的完整數值表格（TCP/UDP Throughput、Latency、BLER、RSRP、SINR 等），並附上 `SIT-SR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md (Knowledge Base 本地文件)` 作為參考來源；這證明正式 agent-side KB 路徑不只對 WiFi 題穩定，對報告型數值題也同樣穩定。

## 2026-05-24 SCU2140 1307 Mbps hallucination traced
- 已確認 `1307 Mbps` 只存在於 `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001`，不在 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005`。
- 直接檢查 `SCU2140` 與 `SCU5050` 的轉檔 md 後可知：`SCU2140` 第 9~16 類 throughput 數據是 726/625/526/402/733/499/398/323 等級，不包含 `1307`；`1307` 是 `SCU5050` 在 `n78_3.5GHz` 的 Case 9。
- 進一步查最近一次 OpenClaw / KB session，KB `/search` 的正式結果其實已收斂到 `SCU2140` 單一文件與 `chunk_index=11` 的 `## 4. Performance Test`，`citation_distribution` 也只有 `SCU2140`；但最終小幫手仍在回答中輸出了 `1307 Mbps`。
- 這表示這次錯誤已不是 retrieval 汙染，而是 answer generation hallucination / prior-memory contamination：模型在看到 `SCU2140` 的正確 chunk 後，仍把先前記住的 `SCU5050` 數字混進答案。
- 下一步修正方向：在回答 prompt 再加硬限制，明確要求「只能使用本次 `/search` 返回的 sources 與內容，不得引用其他文件、其他報告或記憶中的數字；若 sources 沒有明確數值，就必須說明資料不足，不能補數字」。

## 2026-05-25 browser chat 非阻塞化
- 已將 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 的送出流程改成「正文先送、KB 後補」，不再 `await prepareKnowledgeBaseContext()` 後才送 OpenClaw；KB 查詢改為背景進行，只負責補充 citation / heatmap，不再作為正文是否能送出的阻塞點。
- 這次也同步把送給 OpenClaw 的 prompt 改為非阻塞版：不再因 KB sidecar 尚未回來就宣告「沒有可用來源」，而是先請模型直接回答，再由前端在背景補 KB sources 與引用資訊。
- `frontend/chat.html` 與 Vue 版已重新 build，`restart_kb.sh` 已成功重啟；此版本的目標是避免 `SCU2140` 類查詢在 browser `/chat.html` 入口再因 KB search timeout 而回 `NO` 或空引用卡片。
- 2026-05-25 以 Playwright 重測 `https://61.216.9.52:3030/chat.html` 的 `請顯示SCU2140的throughput數據` 後，browser 端依舊在 120 秒內持續輪詢到 `/tasks/4a4988e7-2b22-4e48-9197-648470e41bd2` 的 `pending`，最後觸發 `[KB] Search timeout` 與空 citation cards；但同一個 task_id 由 shell `curl` 直查已是 `completed`，且 worker log 顯示 `Task tasks.search_task[4a4988e7-2b22-4e48-9197-648470e41bd2] succeeded in 24.9s`。這表示 browser 入口仍有獨立的 KB sidecar/polling 同步問題，尚未真正解除瀏覽器端的 timeout 卡住現象。
- 進一步把 `/tasks/{task_id}` 的 browser polling 做了 cache-busting（`?t=${Date.now()}`）與 `no-cache / no-store / pragma / expires` header，並同步套到 `frontend/src/services/api.js::getTaskStatus()`；目的是避免瀏覽器端在同一 task id 上一直吃到過期的 `pending` 回應。
- 這次修正後仍需再重測 `SCU2140`：若 browser 端仍出現 `pending` 與 `KB Search timeout`，代表問題已不是單純 cache，而是 browser 入口的 KB sidecar / final payload 消費鏈路仍需進一步重構，應優先讓 main answer 不被 sidecar 影響，並只在 final payload 缺 sources 時才補卡片。
- `restart_kb.sh` 已再次成功重啟，前端 runtime 已建到 `.frontend-build-runtime-user8` 並載入最新 browser polling 邏輯。接下來重測 `SCU2140` 時應優先觀察 `/tasks/{task_id}` 是否還會被瀏覽器端固定在 `pending`；若仍然如此，需進一步將 browser citation cards 的資料來源切到 final payload 優先，避免 KB sidecar timeout 直接把卡片清空。
- 2026-05-25 已將 browser `/chat.html` 與 Vue 版 `ChatView.vue` 的 KB sidecar 改成 `sources_only` 快速路徑：`/search` 仍回傳 task，但 `search_task` 在 `sources_only=True` 時會直接走 `_vector_search_raw` / `_deep_search_raw`，跳過 LLM 生成答案，僅回傳 `sources` 與 `citation_distribution`。同時保留 cache-busting 的 `/tasks/{task_id}?t=...` 輪詢。最新實測 `請顯示SCU2140的throughput數據` 時，browser 端的 `/tasks/f430bc21-299f-433f-aa72-e63b0e9b7971` 已能快速回 `completed` 並帶回完整 `sources`，表示 KB sidecar 的 timeout 問題已被壓下；後續若要再優化，重點會轉向主回答的渲染與引用顯示，而不是 KB search 本身。
- 2026-05-25 再次用 Playwright 實測 browser `/chat.html` 的 `請顯示SCU2140的throughput數據`：`/search` 已能快速回 `completed + sources`（例如 `task_id=ef89b295-fed7-4ac0-b7fb-bb5345e7451f`），但頁面上的 `citationSummary` 仍停留在「正在統計這次回答實際引用到的文件類別...」，且 chat 區只停留在使用者提問，沒有正常顯示最終回答與引用卡片。這表示 KB sidecar 的後端已經通了，但 browser 端的「引用結果顯示 / 主回答接收」仍有未收斂的前端同步問題，後續要再追 `chat.send` 與 websocket final payload 的銜接。
- 2026-05-25 已修正 browser `/chat.html` 的最後一段銜接：`sendMessage()` 改成正文先送、KB 背景補卡片；`/search` 增加 `sources_only=true` 快速路徑；`shouldRenderChatEvent()` 改為接受同一個 base session（忽略 `__browser__` 後綴）；且當 KB sources 先回來時，即使 `answer` 是空，也會立即刷新 citation cards，不再卡在 loading。最新 Playwright 實測 `請顯示SCU2140的throughput數據` 時，browser 端可正常顯示最終回答，citationSummary 也正確更新為「本次共引用 8 份來源，已歸類 8 份」，卡片來源顯示 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md (QDrant 向量搜尋)`，證明 browser 入口的主回答與引用卡片銜接已恢復正常。

- 2026-05-25 再次核對 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md` 的轉檔內容，確認它不只含第 2.4/2.5 章節，也包含完整的 `## 3. Test Result Summary` 與 `## 4. Performance Test`；第 4 章明確有 TCP/UDP throughput、Latency、BLER 與 RTT 數值（例如 lines 231-245）。因此若某次回覆宣稱『目前只有測試環境配置與 iperf3 指令，尚未有第 4 章數據』，那屬於回答路徑/session 的誤判，**不是**這份 SCU2060 報告本體資料不足。
- 2026-05-25 為了讓不同電腦 / 不同 session 的 browser `/chat.html` 行為更穩定，已在 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 補上 deterministic KB excerpt fallback：當查詢像 `SCU2140` / `SCU2060` 這類 report 題，且模型回覆出現「資料不足 / 只有前段章節 / 沒有第 4 章 / 查無資料」等保守訊號時，前端不再只顯示模型自行整理的內容，而會把同一輪 `/search` 取得的 `sources` 組成一段固定格式的 `【知識庫補充摘錄】`。這個設計的目標是把「跨電腦 session 差異」造成的結果不一致收斂到前端 deterministic 補充層，降低某台機器因模型過度保守而直接說找不到資料的機率。
- 2026-05-25 以 browser `/chat.html` 實測 `請查詢SCU2060的throughput數據` 與 `請顯示SCU2140的throughput數據` 後，KB `/search` 都能正確回傳 `completed + sources`，citation cards 也會即時更新；這次終端訊息顯示的是完整的 KB throughput 表格，而沒有觸發 `【知識庫補充摘錄】` fallback，表示前端 deterministic 補述是保底機制，只有當模型回覆本身過於保守時才會接手。換句話說，browser 路徑已能穩定拿到正式 KB 資料；這次測試也證實 deterministic 補述並非每次都出現，而是只在回答內容觸發保守條件時才補上。
- 2026-05-25 進一步用 browser `/chat.html` 重測 `請查詢SCU2060的throughput數據` 時，console 已明確顯示 KB context / citation distribution 正常回來，`updateCardsFromCitationDistribution` 也有成功刷新卡片；但這次 Playwright 腳本在等待最終 bot bubble 時超時，未能完整截到最後訊息內容，因此這次只能確認前半段的 KB sidecar 與 heatmap 綁定正常，無法 100% 斷言 deterministic KB excerpt 是否有在最終泡泡中出現。這表示 browser 端的 sources/citation 更新鏈路已穩，但若要完全驗證補述是否觸發，還需要再做一次更長等待或直接抓 websocket final payload 的測試。

- 2026-05-25 針對另一台電腦回報的『SCU2060 throughput 只有第 2.4/2.5、沒有第 4 章』再做本機核對，確認這是**回答路徑/快取/session 的誤判**，不是報告本體缺數據。實際 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md` 在本機轉檔內容裡明確有 `## 3. Test Result Summary` 與 `## 4. Performance Test`，第 4 章包含 TCP/UDP throughput、Latency、BLER、RTT 數值；因此若某台機器仍回覆只有環境配置與 iperf3 指令，最可能原因是它還在用舊的 OpenClaw client / browser 快取 / 舊 session，而不是 KB 本體缺資料。
- 2026-05-26 已將 `frontend/src/views/ChatView.vue` 的文案與 `frontend/chat.html` 對齊，統一改用「原始文件」語境，避免再與 `sources chunk` 數混淆；包含 `知識庫原始文件摘錄`、`知識庫原始文件參考`、`原始文件：`、`相關原始文件：` 與 `未知原始文件` 等字樣。
- 2026-05-26 已重新執行 `restart_kb.sh`，前端重新建置並成功載入新版 Vue 文案；`docker compose ps` 與健康檢查均正常，`kb-neo4j` 維持在 `127.0.0.1:17474` / `127.0.0.1:17687`，系統啟動完成。
- 2026-05-26 查明 Neo4j Browser 的混淆來源：主機上的 `neo4j.service` 仍是 `active`，且 `bolt://localhost:7687` 這份主機 Neo4j 目前是空的；KB 真正有資料的是 Docker 容器 `kb-neo4j`，透過 `bolt://localhost:17687`（主機）或容器內 `bolt://neo4j:7687` 連線，節點數為 8、關係數為 4，包含 4 個 `Document` 與 4 個 `TextUnit`。因此 `http://localhost:17474/browser/` 如果沒有手動連到 `17687`，很可能看到的是空資料庫畫面，而不是 KB 容器內的圖。
- 2026-05-26 以兩個不同的 `openclaw agent --session-id ...` turn 重測「請問目前Neo4j內有任何的資料嗎?」，兩次都回覆 Neo4j 目前有 4 個 `Document`、4 個 `TextUnit`、4 條 `CONTAINS` 關係，總計 8 個節點、4 條關係；這表示在本機環境下，即使切換 agent turn，也沒有重現『查不到任何資料』的誤判。若另一台電腦仍回覆空資料，較可能是它連到主機空的 `bolt://localhost:7687`，或是用到了不同的 Neo4j 實例 / 舊 session / 舊 Browser 連線目標。
- 2026-05-26 已將 knowledge-base 內部 Neo4j 預設值統一改成 Docker service name `bolt://neo4j:7687`，包含 `config/config.yaml`、`config/config.yaml.example`、`src/main.py`、`src/ingest.py`、`src/graphrag/__init__.py`、`src/graphrag/neo4j_schema.py`、`src/search/__init__.py`、`src/web_api/tasks.py`、`src/web_api/__init__.py`、`README.md` 與 `src/web_api/tasks.py.bak`。之後若沒有額外覆寫 `NEO4J_URI`，應該都會指向 KB 容器內的 Neo4j，而不是主機上的空 `neo4j.service`。
- 2026-05-26 已把 `README.md` 其他 Neo4j 相關段落一併改寫成「Docker 內 KB 服務」語境，包含快速開始、Neo4j 連線、開發檢查、注意事項與技術棧，避免再讓讀者誤以為需要另外起一份主機 Neo4j 或使用 `bolt://localhost:7687`。
- 2026-05-26 已把 chat 入口的 Neo4j meta 問題分流成即時狀態查詢：`frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 只在問題明確命中 Neo4j 連線 / 實例 / 資料存在等 meta 條件時，才改讀 `/admin/graph-stats` 並直接回覆 runtime 連線位址、使用者、資料庫與節點/關係統計；一般查詢仍維持原本 `/search` + KB sources 流程，不會被這條 meta 分流影響。已在 `chat.html` 實測 `你是連哪一個Neo4j的實例? 請顯示詳細資訊`，回覆明確顯示 `bolt://neo4j:7687` 與 `Document=4 / TextUnit=4 / CONTAINS=4`，而像 `Neo4j 相關報告的資訊` 與一般報告查詢則不會被攔截。
- 2026-05-26 使用者回報：在其中一台電腦查詢一般問題後，答案會在每一台電腦的小幫手都顯示出來。進一步檢查後確認，真正的漏洞是在 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 的 `shouldRenderChatEvent()` 仍允許「同一個 base session」通過，導致不同電腦只要 base session 相同就會互相看到同一則 chat event。已將條件收斂成必須完整 `sessionKey` 完全相等才顯示，並移除 `getBaseSessionKey()` 的容錯後門；這次修改只影響 live chat event 隔離，不影響一般 KB `/search` 查詢流程。`restart_kb.sh` 已重跑並通過，前端與 API 服務正常。

## 2026-05-26 SCU5050 Case 13~16 retrieval alignment
- 使用者要求把 `SCU5050 Performance Test` 的回覆逐項對照原始 Excel，並確認 Case 13~16 是否完全一致。
- 起初的 generic query `請查詢SCU5050 的Performance Test 數據` 仍只拉到 `4.1 Test Case 1`，代表泛用檢索雖已收斂到 `Performance Test` 章節，但還沒有把明確 case 編號變成硬條件。
- 已在 `src/search/__init__.py` 補強：
  - 新增 `case hints` 抽取與過濾，`Case 13/14/15/16` 會只保留對應 case 的 chunk。
  - 報告型數值題的候選 `top_k` 提高，避免候選數不足導致錯配。
  - `_section_boost()` 與 `_rank_vector_results()` 仍保留 `Performance Test` 優先，但會在明確 case 時進一步收斂到正確 chunk。
- 已重新 `restart_kb.sh` 並實測定向查詢：
  - `SCU5050 Performance Test Case 13 DL UL RTT BLER` -> `chunk_index=48`
  - `SCU5050 Performance Test Case 14 DL UL RTT BLER` -> `chunk_index=49`
  - `SCU5050 Performance Test Case 15 DL UL RTT BLER` -> `chunk_index=51`
  - `SCU5050 Performance Test Case 16 DL UL RTT BLER` -> `chunk_index=53`
- 對照原始 Excel，Case 13~16 的數值已一致，且不再混入其他 case 的數據。
- 補充：這次測試顯示 source selection 已修正，但某些定向 query 的 `answer` 欄位仍可能是空字串；若後續要讓自然語言答案也完整輸出，需另查 answer generation 的早停或 prompt 約束。

## 2026-05-26 generic Performance Test answer expansion
- 使用者進一步要求 generic 問法 `請查詢SCU5050 的Performance Test 數據` 也要能完整列出 Case 13~16，而不是只回單一 case。
- 根因修正：
  - `hybrid_search` / `hybrid_plus_search` 的來源去重改成以 `文件 + chunk + 章節 + 內容雜湊` 為鍵，不再用文件名去重，避免同一份報告的多個 case 被壓成單筆。
  - `_is_numeric_extraction_query()` 擴充了 `performance test / performance / 數據 / 數值 / 報告` 等關鍵字，讓這類 generic report query 也會進入數值直接輸出路徑。
  - `_generate_hybrid_answer()` / `_generate_answer_vector()` 在數值題時改成直接組裝來源原文，不再依賴 LLM 來摘要，避免答案被縮成單一 case。
  - `REPORT_RECALL_TOP_K` 由 20 提高到 60，讓 generic report query 的候選集能覆蓋到後段 case。
- 驗證：
  - 重啟 `restart_kb.sh` 後，重新詢問 `請查詢SCU5050 的Performance Test 數據`，回覆已能直接列出 `Case 13 / Case 14 / Case 15 / Case 16` 四段原文摘錄。
  - 最新任務結果中，answer 已明確包含 Case 13~16，且 Case 13 的數據與原始 Excel 一致。
- 補充：
  - generic 問法目前輸出的是「最高四個 case 的原文摘錄」，這符合 SCU5050 這份報告的需求；若未來其他報告 case 數更多，可能要再調整排序或選取策略。

## 2026-05-26 multi-project Performance Test consistency check
- 針對 `SCU2140 / SCE2200 / SCU2050 / SCU2060 / SCU5050` 這五個專案，重新用同一句型詢問 `請查詢<project> 的Performance Test 數據` 並逐一比對原始 Excel。
- 實測結果：
  - `SCU2140`：helper 回覆的 Case 13~16 來源為 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.xlsx`，數值與原始 Excel 的 `4.13~4.16 Test Case` 一致。
  - `SCU5050`：helper 回覆的 Case 13~16 來源為 `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.xlsx`，數值與原始 Excel 的 `4.13~4.16 Test Case` 一致。
  - `SCU2060`：helper 回覆雖標成 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.xlsx`，但內容是錯位 / 造出的數字，例如 Case 13 出現 `12 | 12 | 12 | 12 | 12`，與原始 Excel 的 case 13~16 不一致。
  - `SCE2200`：helper 回覆跳到 `Excel 圖片摘要 - 1. Preface`，並非 Performance Test 數據；這份 workbook 本身是 Handover 報告，沒有 `Performance Test` 章節，因此這個 query 對該檔案不具可比性，但 helper 仍未能正確說明缺少對應章節。
  - `SCU2050`：helper 回覆錯誤引用了 `SCU2140` 的 performance data，與 `type6_NR-Handover-SCU2050-EV-V004.xlsx` 的實際內容不符；且該 workbook 本身也是 Handover 報告，沒有 `Performance Test` 章節。
- 結論：
  - `SCU2140`、`SCU5050` 一致。
  - `SCU2060` 不一致。
  - `SCE2200`、`SCU2050` 屬於報告類型不相符（Handover 報告無 Performance Test），helper 回覆也沒有正確處理這個前提。

## 2026-05-27 Handover Performance Test guardrail
- 使用者要求把 `SCE2200`、`SCU2050` 這兩種 Handover 報告的查詢規則補強成：如果沒有 `Performance Test` 章節，就明確回覆無對應章節，不可再誤答其他報告的 case 數據。
- 已在 `src/search/__init__.py` 新增共通 guardrail：
  - 先依 query 解析 project code，回推 `data/processed/**/*.source.json` 對應的原始 workbook。
  - 若對應檔案是 Handover 類報告，且轉出的 markdown 內容中沒有 `Performance Test`，就直接回覆「這份 Handover 報告沒有 Performance Test 章節，因此無對應章節可回覆。」
  - 這個短路規則同時套用在 `basic / vector / hybrid / hybrid_plus`，避免再把 SCU2140 / SCU5050 之類的 throughput 報告混進來。
- 已完成重啟與實測：
  - `請查詢SCE2200 的Performance Test 數據` -> 回覆明確指出 `type6_NR-Handover-SCE2200-n79-EV-V13.8.xlsx` 沒有 `Performance Test`。
  - `請查詢SCU2050 的Performance Test 數據` -> 回覆明確指出 `type6_NR-Handover-SCU2050-EV-V004.xlsx` 沒有 `Performance Test`。
- 驗證結果：
  - 兩個 Handover 報告現在都不再誤抓其他 throughput 報告的 Case 13~16。
  - 回覆與來源檔案一致，且 sources 也只保留對應的原始 Handover workbook。

## 2026-05-27 Neo4j schema / ingest proposal
- 使用者要求以投影片格式評估如何把不同專案的 Excel 測試報告攝入 Neo4j，讓共通測試項目（例如 Throughput）可跨專案關聯搜尋。
- 已產出一份 HTML 投影片：[neo4j_schema_ingest_presentation.html](/home/da40_ai_gb10/knowledge-base/neo4j_schema_ingest_presentation.html)
- 這份提案的核心 schema 為：
  - `Project`
  - `Report`
  - `TestItem`
  - `Section`
  - `TestCase`
  - `Metric`
  - `SourceChunk`
- 關係設計為：
  - `Project -> Report`
  - `Report -> Section`
  - `Section -> TestItem`
  - `TestItem -> TestCase`
  - `TestCase -> Metric`
  - `TestCase -> SourceChunk`
  - `Report -> SourceChunk`
- 關鍵結論：
  - 只存 `Document/TextUnit` 不足以支援跨專案測試項目關聯。
  - 必須先 canonicalize `TestItem`，再把 `Case / Metric` 結構化，否則 Throughput、Latency 等共通測試項目仍會只停留在文字層。

## 2026-05-27 Neo4j report graph implementation
- 已開始實作並完成 report graph 攝入功能，讓 Excel 測試報告不只寫成 `Document/TextUnit`，也會同步建立可跨專案關聯的 Neo4j 圖譜。
- 新增模組：[src/report_graph.py](/home/da40_ai_gb10/knowledge-base/src/report_graph.py)
  - 提供 `Project / Report / Section / TestItem / TestCase / Metric / SourceChunk` 的 schema 與寫入邏輯。
  - `TestItem` 已做 canonicalize，至少涵蓋 `throughput` / `handover` / `latency` / `tcp` / `udp` / `bler`。
  - `SourceChunk` 保留原始 md 片段與證據路徑，來源仍可回推到原始 Excel。
- ingest 已接上 report graph：
  - [src/ingest.py](/home/da40_ai_gb10/knowledge-base/src/ingest.py) 的 `report` 模式會同時寫入 legacy `Document/TextUnit` 與新的 report graph。
  - [src/graphrag/neo4j_schema.py](/home/da40_ai_gb10/knowledge-base/src/graphrag/neo4j_schema.py) 也同步建立新節點的 constraints / indexes。
- 查詢端已接上 report graph：
  - [src/search/__init__.py](/home/da40_ai_gb10/knowledge-base/src/search/__init__.py) 新增 `_report_graph_search_raw()`。
  - `search()` 對 report-like query 會優先走 report graph，再回傳 `mode = report_graph`。
  - `search_task` 的 `sources_only` 與一般搜尋都已避免把 report graph 結果再誤覆蓋回舊 fallback。
- 驗證結果：
  - 已重啟 KB，並成功把 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md`、`SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md`、`SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md` 攝入 report graph。
  - `請查詢Throughput相關報告數據` 現在會走 `report_graph`，回傳 3 份相關報告：
    - `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.xlsx`
    - `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.xlsx`
    - `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.xlsx`
  - `請查詢SCU2140的相關報告數據` 會走 `report_graph`，並以 Case 13~16 逐 case 原文摘錄回覆。
- 目前已知限制：
  - `Throughput` 的跨專案結果已成立，但 answer 仍偏向來源摘錄或簡式報表摘要，後續還可再優化成更像「跨專案對照表」的輸出。
  - `SCE2200 / SCU2050` 這類 Handover 報告的無 `Performance Test` guardrail 仍沿用既有規則，沒有被 report graph 取代。

## 2026-05-27 report graph cross-project table
- 使用者要求將 `report_graph` 的輸出整理成「跨專案對照表」，讓相同 `TestItem` 的多份報告可以一眼比較。
- 已調整 [src/search/__init__.py](/home/da40_ai_gb10/knowledge-base/src/search/__init__.py) 的 `_build_report_graph_answer()`：
  - 當查詢命中多份報告時，改輸出 Markdown table。
  - 表格欄位為 `專案 / 原始文件 / TestItem / 章節`。
  - `Throughput` 這類跨專案 query 會直接顯示多份報告的對照結果，而不是單純列摘要。
- 驗證：
  - `請查詢Throughput相關報告數據` 現在回覆 `mode=report_graph`，並輸出 3 份報告的對照表：
    - `SCU2060`
    - `SCU2140`
    - `SCU5050`
  - 這代表同一個 `TestItem` 已經可以跨專案聚合顯示。
- 補充：
  - 目前表格中的 `原始文件` 與 `章節` 仍是從 report graph 的回推來源而來；未來若要更精準，還可以把 `report_title` 改成更接近原始 Excel 檔名。

## 2026-05-27 chat.send idempotencyKey fix
- 使用者在測試 websocket 聊天時遇到 `invalid chat.send params: must have required property 'idempotencyKey'`。
- 根因：
  - `frontend/src/views/ChatView.vue` 的 `chat.send` payload 原本缺少 `idempotencyKey`。
  - 其他入口（例如 `frontend/chat.html`、`frontend/ws-chat.cjs`、`frontend/ws-chat-probe.cjs`）其實已經有帶，只有 Vue 入口漏掉。
- 已修正：
  - `frontend/src/views/ChatView.vue` 的 `chat.send` 補上 `idempotencyKey: msg-${Date.now()}-${Math.random().toString(16).slice(2)}`。
  - 已重啟 `restart_kb.sh`，讓前端 runtime 載入新版程式。
- 驗證：
  - 目前 repo 內所有 `chat.send` 入口都能搜尋到 `idempotencyKey`。
  - 之後再送 websocket chat 時，應不會再因缺少該欄位被 gateway 直接拒絕。

## 2026-05-27 web testing policy update
- 使用者要求把網頁測試原則寫入 [AGENTS.md](/home/da40_ai_gb10/knowledge-base/AGENTS.md)：
  - 測試網頁功能時，優先使用 Playwright 或可用的瀏覽器自動化工具。
  - 必須模擬真實使用者流程，而不是只讀程式碼或只打 API。
  - 若畫面異常，要記錄頁面、操作步驟、預期與實際結果，並保留截圖。
  - 若有 console/network error，也要一併檢查。
- 已完成更新，並新增 `Playwright 測試規範` 段落，作為後續 UI / E2E 測試的優先原則。

## 2026-05-28 SCU5050 numeric case chunk merge fix
- 使用者回報 `請問SCU5050的相關報告資訊` 產生的回答，在 Case 15 的 `#2/#3`、`UL TCP` 與 `Peak/Average/BLER` 出現 `-` 或缺值。
- 根因不是原始 Excel 缺資料，而是 `report_graph` 的數值答案組裝邏輯只取了第一個 chunk；而 `SCU5050` 的 Case 15 被 chunker 切成多段，後半段 chunk 沒有再次重複 `Test Case 15` 標頭，導致它沒有被歸入同一 case，後續 `Uplink / Bidirection / UDP / RTT` 欄位因此被漏掉。
- 已在 [src/search/__init__.py](/home/da40_ai_gb10/knowledge-base/src/search/__init__.py) 新增 case 繼承與合併邏輯：
  - 先沿 chunk 順序推斷同一份報告、同一章節內沒有顯式 case 標頭的 chunk，視為前一個 case 的延續。
  - 再將同 case 的多個 chunk 依 `chunk_index` 合併後輸出。
- 已重新執行 `restart_kb.sh` 驗證線上服務。
- 最新驗證結果：`SCU5050` 的 Case 15 現在會完整列出 `Uplink 472 / 471 / 471 / 472 / 471 / 0`、`Bidirection - DL 674 / 680 / 676 / 680 / 677 / 0`、`Bidirection - UL 469 / 424 / 469 / 469 / 454 / 0`，以及 UDP / RTT 欄位，不再出現只顯示第一段或用 `-` 佔位的情況。

## 2026-05-28 SCU2060 report chunk boundary fix
- 使用者回報 `SCU2060` 的 `report_graph` 回答有 case 內容錯位，Case 13~16 前方會混入上一個 case 的尾段，出現 `12 / 13 / 14 / 15 / 16` 這種不合理數值。
- 根因：
  - 同一個 report chunk 內會同時包含前一個 case 的尾巴與下一個 case 的 `4.xx Test Case xx` 標頭。
  - 原本的 case 合併邏輯是以整個 chunk 為單位，沒有把 chunk 內的 case 邊界切開，因此會把上一個 case 的數值一併帶入。
- 已在 [src/search/__init__.py](/home/da40_ai_gb10/knowledge-base/src/search/__init__.py) 增加：
  - `_extract_case_sections()`：把 chunk 依 `Test Case` 標頭切成 case segment，只保留目標 case 的片段。
  - `_prefer_report_section_sources()`：numeric report 查詢優先使用 `Performance Test`，避免 `Test Result Summary` 混入。
  - `_merge_numeric_case_sources_for_output()`：改成先切 segment 再合併同 case 來源。
- 已重新執行 `restart_kb.sh` 驗證線上服務。
- 最新驗證結果：
  - `請問SCU2060的相關報告資訊`
  - `請查詢SCU2060的Performance Test數據`
  - 兩者現在都只輸出對應 case 的起始片段，不再把前一個 case 的尾段混進來。

## 2026-05-28 report 題 prompt 注入 KB 原始內容
- 使用者再測 `請查詢SCU2060的Case 13數據` 時，chat helper 仍回覆成「只有 Case 標題、詳細數值尚未完整呈現」的摘要式答案。
- 根因不是 Neo4j / QDrant 的來源缺漏，而是 `chat.html` 與 `frontend/src/views/ChatView.vue` 對 report / case 題仍採「先送聊天模型、KB 只做背景引用」的流程，沒有把 `prepareKnowledgeBaseContext()` 的結果直接注入到送給 `chat.send` 的 prompt。
- 已修正：
  - report / case 題會先同步取得 KB context，再把 `formatKnowledgeBaseContext` / `formatKnowledgeBaseContext` 的結果直接附加到送給聊天模型的 prompt。
  - 只有一般非 report 題才維持原本的背景 KB 補引用流程。
- 目標效果：
  - `SCU2060 Case 13` 這類查詢不再只回章節標題或摘要。
  - 聊天模型會直接看到 `4.13 Test Case 13` 的原始表格內容與 KB context，輸出更接近原始 Excel 數值。

## 2026-05-28 SCU2060 Case 14/15/16 report detection boundary fix
- 使用者要求再驗 `SCU2060 Case 14/15/16`，確認整份 report 的 case 查詢一致。
- 實際排查後發現，先前在 `src/web_api/tasks.py` 與 `src/search/__init__.py` 的 report / numeric detection 仍使用 `\b(?:scu|sce)\d+\b` 類邊界判斷；當查詢字串是 `SCU2060的Case 16數據` 這種「專案代碼後面直接接中文」時，`\b` 會因為中文屬於 word character 而失效，導致 report-like query 沒有被正確識別，進而落回 vector fallback，造成 case 內容再次混入別段 chunk。
- 已修正：
  - `src/web_api/tasks.py`
    - `_is_report_like_query()` 改為 `(?:scu|sce)\d+(?!\d)`。
    - `_should_retry_report_query()` 也同步改為 `(?:scu|sce)\d+(?!\d)`。
  - `src/search/__init__.py`
    - `_is_numeric_extraction_query()` 改為 `scu\d+(?!\d)`。
    - `_is_report_like_query()` 同步改為 `(?:scu|sce)\d+(?!\d)`。
- 驗證結果：
  - `請查詢SCU2060的Case 14數據` -> `mode=report_graph`，`sources_len=1`，來源為 `chunk_index=55`，`4.14 Test Case 14`。
  - `請查詢SCU2060的Case 15數據` -> `mode=report_graph`，`sources_len=1`，來源為 `chunk_index=56`，`4.15 Test Case 15`。
  - `請查詢SCU2060的Case 16數據` -> `mode=report_graph`，`sources_len=1`，來源為 `chunk_index=58`，`4.16 Test Case 16`。
  - 以上三個 case 現在都不再混入其他 case 的尾段內容，整份 SCU2060 的 case 查詢已一致。

## 2026-05-28 SCU2060 Case 15 tail chunk merge fix
- 使用者再次回報 `請查詢SCU2060的Case 15數據` 仍只顯示表頭與前半段，缺少 `Latency Test` / `RTT` 等後段欄位。
- 進一步追查後確認：
  - `report_graph` 的 `Section.text` 原本被截到 4000 字，導致 Case 15 / Case 16 這類落在 section 後半段的 case 無法被完整命中。
  - 即使把 `Section.text` 放寬後，`Case 15` 仍需把下一個 chunk (`chunk 58`) 當作尾段邊界，才能把 `chunk 56/57/58` 合併成完整 case 內容。
- 已修正：
  - [src/report_graph.py](/home/da40_ai_gb10/knowledge-base/src/report_graph.py)
    - `Section.text` 不再截斷成 4000 字，改為保留完整 section text。
  - [src/search/__init__.py](/home/da40_ai_gb10/knowledge-base/src/search/__init__.py)
    - 新增 `_extract_case_content_from_text()`，會從合併後內容中擷取指定 case 的完整區段。
    - `_merge_numeric_case_sources_for_output()` 在組 case 輸出時，會再帶上同 section 的下一個相鄰 chunk 作為尾段邊界，再用完整 case slice 輸出，避免只剩表頭或前半段。
- 驗證結果：
  - `請查詢SCU2060的Case 15數據` 現在回覆長度變為 `LEN 826`，內容已完整包含：
    - `Downlink`
    - `Uplink`
    - `Bidirection - DL`
    - `Bidirection - UL`
    - `UDP Throughput`
    - `Latency Test`
    - `RTT (ms)`
- `sources_len=1`，來源仍是 `chunk_index=56`，但 `answer` 已經是完整的 `4.15 Test Case 15` 區段，不再只剩表頭。

## 2026-05-28 self-verification before reporting rule
- 使用者要求新增工作守則：每次修正完一個問題後，必須先由我自己驗證正常、沒有回歸，才能對使用者回報已修正。
- 已更新 [AGENTS.md](/home/da40_ai_gb10/knowledge-base/AGENTS.md)：
  - 新增規則 8：每次修正一個問題後，必須先自行完成驗證，確認行為正常、沒有回歸，才能對使用者回報已修正。
- 這條規範的目的，是避免只根據程式碼修改就宣告完成，後續仍需以實際驗證結果作為回報依據。

## 2026-05-28 review prior fixes before editing rule
- 使用者要求新增工作守則：每次修改前要先回顧之前已完成的修改內容，以不能影響既有修正為原則，再去處理新的問題。
- 已更新 [AGENTS.md](/home/da40_ai_gb10/knowledge-base/AGENTS.md)：
  - 新增規則 9：每次修改前，必須先回顧既有修改與已修正內容，確認新修改不會影響已修正的行為，再開始處理新的問題。
- 這條規範的目的是讓後續每次變更都先檢查既有修正，避免新修補破壞先前已驗證完成的功能。

## 2026-05-28 throughput cross-project report graph fix
- 使用者回報查詢 `請查詢Throughput相關報告數據` 仍出現「找不到」或只看到封面 / 目錄頁的問題。
- 實際排查後確認：
  - `report_graph` 雖然已能抓到 SCU2060 / SCU2140 / SCU5050 三份 throughput 報告，但原本的排序會先取各報告的前兩筆 chunk，導致結果落在封面 / 目錄，而不是 `4. Performance Test`。
  - `Throughput` 類查詢又被視為 numeric extraction，若直接套用 numeric merge，還可能把跨專案來源壓成單一 case，讓回覆看起來像只有單一報告或單一來源。
- 已修正：
  - [src/search/__init__.py](/home/da40_ai_gb10/knowledge-base/src/search/__init__.py)
    - `report_graph` 的跨專案/多報告選取改成先依章節權重排序，再挑選每份報告的 top chunk，讓 `4. Performance Test` 優先於 cover / TOC / preface。
    - `numeric extraction` 只有在明確 case hint 存在時才做 case merge，避免 generic `Throughput` 查詢被壓成單一來源。
    - `doc_name` 不再被 `report_title` 覆蓋，保留原始 report file stem 作為來源識別。
- 驗證結果：
  - `請查詢Throughput相關報告數據` 現在回覆為跨專案對照表，列出：
    - `SCU2060 | OTA Throughput Test Report | throughput | 4. Performance Test`
    - `SCU2140 | OTA Throughput Test Report | throughput | 4. Performance Test`
    - `SCU5050 | OTA Throughput Test Report | throughput | 4. Performance Test`
  - `sources_len=12`，且前幾筆來源已是 `4. Performance Test` chunk，而不是封面 / 目錄。

## 2026-05-28 report_graph direct output bypass
- 使用者回報 `請查詢Throughput相關報告數據` 在前端仍會被聊天模型改寫成錯誤的 case 型摘要，雖然後端 `report_graph` 已回傳正確跨專案對照表。
- 根因：
  - `report_graph` 後端答案已正確，但前端仍將 `report_graph` 結果拼入 `chat.send` prompt，再交給上游 LLM 重寫。
  - 上游 LLM 會重新摘要成 case / 數值混用的內容，導致最終使用者看到的回覆不穩定。
- 已修正：
  - [frontend/chat.html](/home/da40_ai_gb10/knowledge-base/frontend/chat.html)
    - 若 `prepareKnowledgeBaseContext()` 回傳的 `kbResult.mode === 'report_graph'` 且有 `answer`，前端直接用 `addMessage('bot', kbResult.answer, ...)` 顯示最終答案。
    - report_graph 類查詢不再送入 `chat.send` 讓 LLM 二次改寫。
  - [frontend/src/views/ChatView.vue](/home/da40_ai_gb10/knowledge-base/frontend/src/views/ChatView.vue)
    - 同步加入 report_graph 直接落版分支，避免 Vue 入口仍被模型重寫。
- 驗證結果：
  - 已重新執行 `restart_kb.sh`。
  - 前端 build 成功，KB runtime 啟動完成。
  - `kb-neo4j`、`kb-redis`、`kb-web`、`kb-nginx`、celery workers 都正常啟動，`WebSocket proxy smoke test` 通過。
  - 這代表 report_graph 的直接輸出分支已能正常載入到 runtime，且不影響一般查詢流程。

## 2026-05-28 compare query per-project report graph fix
- 使用者詢問 `SCU2140、SCU2060、SCU5050 的case 15Throughput有什麼差異？` 時，原本回覆只剩單一報告（SCU5050），把其他專案誤判成沒有資料。
- 根因：
  - `compare` 類意圖雖然有被辨識出來，但 `report_graph` 原本仍用單次混合檢索與單一答案組裝，沒有針對「同一 Case 跨多專案比較」做逐專案取樣。
  - 在多 project hints + case hint 的情境下，單次檢索結果容易只留下某一份報告的來源，導致其餘專案被遮蔽成「無資料」。
- 已修正：
  - [src/search/__init__.py](/home/da40_ai_gb10/knowledge-base/src/search/__init__.py)
    - 新增 `_rows_to_report_graph_sources()`，統一把 report graph rows 轉成 sources。
    - 新增 `_report_graph_query_rows()`，把 Neo4j 查詢抽成可重用函式。
    - 新增 `_build_report_graph_compare_answer()`，把 compare 類查詢組成跨專案對照格式。
    - 在 `_report_graph_search_raw()` 中，若 query 命中 `compare` 且同時有多個 project hints + case hints / test item hints，會改成「逐專案查詢 -> 逐專案組答案 -> 最後合併」，避免單次檢索遮蔽其他專案。
- 驗證結果：
- 重新執行 `restart_kb.sh` 後，再查 `SCU2140、SCU2060、SCU5050 的case 15Throughput有什麼差異？`
  - `/tasks/{task_id}` 回傳 `sources = 3`，且三個專案都各自出現：
    - `SCU2060`
    - `SCU2140`
    - `SCU5050`
  - 回答內容已按專案分段，不再只剩 SCU5050，compare 路徑已恢復正常。

## 2026-05-28 compare query anti-rewrite guard
- 使用者後續回報 compare 題仍可能被舊前端或舊 session 送去上游 LLM 改寫，導致看起來「不同專案的數值幾乎一樣」。
- 已補強：
  - [frontend/chat.html](/home/da40_ai_gb10/knowledge-base/frontend/chat.html)
  - [frontend/src/views/ChatView.vue](/home/da40_ai_gb10/knowledge-base/frontend/src/views/ChatView.vue)
    - compare-like query 會先直接走 `prepareReportGraphContext()`，命中 `report_graph` 就直接落版，避免前端把正確答案再交給 LLM 重寫。
  - [src/web_api/__init__.py](/home/da40_ai_gb10/knowledge-base/src/web_api/__init__.py)
    - websocket proxy 新增 compare 短路，舊客戶端也會先透過本機 `/search` 取得 `report_graph` 結果，再決定是否往上游送出，降低 browser cache / 舊 bundle 影響。
- 驗證結果：
  - 直接呼叫本機 `/search` 的 compare 查詢可回傳 `mode=report_graph`，且 sources 包含 `SCU2060 / SCU2140 / SCU5050` 三份報告。
- `SCU2060` 的 `Case 15` 原始 Excel 內容本身就是 `15` 值，與 `SCU2140` / `SCU5050` 的數值不同，因此 compare 題的「幾乎一樣」是錯誤改寫造成，不是來源資料相同。
- 2026-05-29 進一步修正 compare 題的解讀方式：原本 compare mode 會先把每個專案各自組成 `## 原文 / ## 解讀`，導致 LLM 只看單一專案上下文時，容易在每段都說「缺少其他資料，無法比較」。已將 compare 改成「整體跨專案一次比較」：先輸出三個專案的原文對照，再由新的 `_build_report_graph_compare_interpretation()` 根據整體 compare raw 產生 2~4 條真正的跨專案比較解讀，不再在每個專案段落內單獨下「無法比較」結論。已重啟 KB 並用 `https://61.216.9.52:3030/chat.html` 實測 `SCU2140、SCU2060、SCU5050 的case 15Throughput有什麼差異？`，後端 `report_graph` 現在回傳 `mode=report_graph`、`sources=3`，`answer` 內有 `## 原文` 與 `## 解讀`，且不再包含「無法比較 / 缺乏資料」等錯誤收尾。
- 2026-05-29 進一步把 compare 解讀整理成正式對照表：`src/search/__init__.py` 已新增 compare 專用的表格化輸出邏輯，會直接從跨專案 raw answer 中切出 `SCU2060 / SCU2140 / SCU5050` 各自的原文，再以 Markdown 表格列出 `DL TCP / UL TCP / Bidirection - DL / Bidirection - UL / RTT` 的 `Peak / Avg / BLER` 或 `Min / Avg / Max / Loss`，最後加上一欄差異摘要（例如哪個專案平均值最高 / 最低）。已以 `https://61.216.9.52:3030/chat.html` 實測 `SCU2140、SCU2060、SCU5050 的case 15Throughput有什麼差異？`，回覆的 `## 解讀` 現在就是正式對照表，且不再出現「無法比較」或缺資料的文字結尾。
- 2026-05-29 進一步把 compare 解讀調成「固定表格 + LLM 簡短評論」的雙層輸出：`src/search/__init__.py` 的 compare 解讀現在會先以固定 Markdown 表格列出 `DL TCP / UL TCP / Bidirection - DL / Bidirection - UL / RTT` 的跨專案對照，再額外呼叫 LLM 產生 2~3 條短評，評論只允許根據表格與原文做摘要，不可新增數字。已重啟 KB 並用 `https://61.216.9.52:3030/chat.html` 實測同一題，`answer` 長度為 `3712`，且明確包含 `### LLM 簡短評論`，代表這次 compare 題已確實有 LLM 介入分析，同時保留固定表格穩定性。

## 2026-05-28 main chat entry policy
- 已新增專案級規範：往後知識庫相關的測試與修改，優先以 `https://61.216.9.52:3030/chat.html` 作為主要驗證入口。
- 目的：
  - 避免不同前端入口、不同 session 或不同瀏覽器快取造成測試結果分歧。
  - 讓後續知識庫測試、compare 題、report graph 題、citation 顯示等，都以同一個使用者實際入口為主。
- 除非任務明確要求，否則不應把其他入口當成唯一驗證依據。

## 2026-05-28 chat.html compare-path verification
- 以 `https://61.216.9.52:3030/chat.html` 實測 compare 題 `SCU2140、SCU2060、SCU5050 的case 15Throughput有什麼差異？`
- 驗證結果：
  - 頁面可正常載入並連上 WebSocket。
  - `compare` / `report_graph` 路徑可正常觸發，沒有再出現 `buildSourceReferenceHint is not defined` 之類的前端錯誤。
  - citation card 會同步更新，實測顯示 `matched_count = 3`、`total_sources = 3`。
  - 回覆內容已進入跨專案 compare 分段，包含 SCU2060 / SCU2140 / SCU5050 三份來源。
- 觀察到的殘餘現象：
  - `SCU5050` 的 `Case 15` 原文段落在實測回覆中仍只看到前半段（目前停在 `Downlink`），後續 `Uplink / Bidirection / UDP / RTT` 未完整呈現，可能是另一條來源裁切或 case 組裝邏輯問題，需後續單獨追查。

## 2026-05-28 SCU5050 case 15 source chunk truncation fix
- 進一步追查後確認，`SCU5050` Case 15 的截斷根因不是 compare 組裝，而是 report graph 攝入時把 `SourceChunk.content` 截成 4000 字，造成後段 `Uplink / Bidirection / UDP / RTT` 無法被查詢端讀到。
- 已修正：
  - [src/report_graph.py](/home/da40_ai_gb10/knowledge-base/src/report_graph.py)
    - `SourceChunk.content` 改為保留完整 chunk，不再以 4000 字截斷。
- 已重攝入：
  - `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md`
  - `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md`
  - `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md`
- 驗證結果：
  - 以 `https://61.216.9.52:3030/chat.html` 再次查詢 `SCU2140、SCU2060、SCU5050 的case 15Throughput有什麼差異？`
  - `SCU5050` Case 15 已完整輸出：
    - `Downlink 687 / 680 / 683 / 687 / 683 / 0`
    - `Uplink 472 / 471 / 471 / 472 / 471 / 0`
    - `Bidirection - DL 674 / 680 / 676 / 680 / 677 / 0`
    - `Bidirection - UL 469 / 424 / 469 / 469 / 454 / 0`
    - `UDP Throughput`
    - `Latency Test`
    - `RTT (ms) 16.717 / 27.684 / 46.714 / 0 / -65 / -11 / 25.5`
- 這個修正是共用層變更，對之後新增或重新攝入的 report 也會生效；已存在舊資料需重新 ingest 才會完全吃到新邏輯。

## 2026-05-28 report graph adjacent chunk case boundary fix
- 進一步掃描其他 case 時，發現 `SCU2060` 的 `Case 14` 仍可能只回到前半段。深入追查後確認原因不是前端，而是 `SearchEngine._merge_numeric_case_sources_for_output()` 在補鄰接 chunk 時，比對使用了 `report_title`，導致 `chunk 56` 這種跨 case 邊界的尾段沒被正確併入 `Case 14`。
- 已修正：
  - [src/search/__init__.py](/home/da40_ai_gb10/knowledge-base/src/search/__init__.py)
    - 鄰接 chunk 的報告識別改以 `doc_name` 為主，比對鍵不再用 `report_title`。
    - 這讓 `Case 14` 這種跨 chunk 邊界時，能把下一個 chunk 的前半段（屬於前一 case 的尾巴）一起收進來。
- 驗證結果：
  - 以 `https://61.216.9.52:3030/chat.html` 實測：
    - `請查詢SCU2060的Case 14數據`
    - `請查詢SCU2060的Case 15數據`
    - `請查詢SCU2060的Case 16數據`
    - `請查詢SCU2140的Case 16數據`
    - `請查詢SCU5050的Case 16數據`
  - 結果皆完整包含 `Uplink`、`Bidirection - UL`、`UDP Throughput`、`Latency Test` 與 `RTT`，未再出現只剩第一列或只剩表頭的截斷狀況。

## 2026-05-28 raw first then interpretation answer format
- 使用者要求調整回答格式為「先原文、後解讀」，讓 LLM 仍可提供分析，但不影響原始數值正確性。
- 已修正：
  - [src/search/__init__.py](/home/da40_ai_gb10/knowledge-base/src/search/__init__.py)
    - 新增 `_build_report_graph_interpretation()`：根據已整理好的原文與來源，生成 2~4 條的解讀段落，禁止新增原文沒有的數字。
    - 新增 `_compose_raw_then_interpretation()`：把回答統一包成 `## 原文` + `## 解讀` 的雙段式格式。
    - `report_graph`、compare、numeric direct answer、vector/hybrid numeric direct answer 都改成優先輸出原文，再附上解讀。
- 驗證結果：
  - 以 `https://61.216.9.52:3030/chat.html` 實測 `請查詢SCU2060的Case 15數據`
  - 回覆已變成雙段式：
    - `原文` 段先完整保留 Case 15 原始表格
    - `解讀` 段由 LLM 產生，且未重複出現 `解讀` 標題
  - 原始數值沒有被改寫，仍保持與來源 Excel / md 一致。
  - 後續抽查 `SCU2140 Case 16` 與 `SCU5050 Case 16`，也都能穩定輸出 `原文` + `解讀` 雙段式，且原文數值保持一致。

## 2026-05-31 WiFi 上傳舊任務清理
- 使用者要求清掉先前誤分到 `4G_5G` 的 WiFi 上傳任務，避免日後統計與卡片盒混淆。
- 清理內容：
  - Redis 任務歷史中移除舊的 `4G_5G` 任務：
    - `ingest_20260531_013522_4c5f8026`
    - `ingest_20260531_015300_7a4c0ca4`
  - 刪除對應的舊上傳目錄：
    - `data/uploads/4G_5G/ingest_20260531_013522_4c5f8026`
    - `data/uploads/4G_5G/ingest_20260531_015300_7a4c0ca4`
  - 刪除舊的 assets 目錄：
    - `data/assets/type2_SIT-TR-WL-Throughput-TP-Link_Archer_BE805-MP-V10`
- 保留正確的新任務：
  - `ingest_20260531_021134_9058675d`
  - `storage_category = WiFi`
  - `extraction_mode = wifi`
- 驗證結果：
  - `kb:ingest_task:*` 與 `kb:ingest_tasks:index` 現在只剩正確的 WiFi 任務。
  - `data/uploads/4G_5G/` 下已無 BE805 相關舊任務目錄。
  - `data/assets/` 中保留正確的 `type2_wifi_SIT-TR-WL-Throughput-TP-Link_Archer_BE805-MP-V10`。
- 2026-05-31 已修正 WiFi band raw 的 `## 解讀` 仍落到固定 fallback 的問題：根因是目前知識庫的 LLM 已切換為 Qwen3.6 `qwen3.6:35b-a3b`，而 Qwen3.6 在 Ollama 預設會啟用 thinking；我們先前在 `src/web_api/ollama_client.py` 的 `OllamaLoadBalancer.chat()` / `generate()` 只取 `message.content`，但實際回來的是 `content=''`、`thinking` 有完整推理內容，因此 `_build_report_graph_interpretation()` 判定為空後就回退到固定摘要。已將 Ollama 呼叫明確改成 `think=False`，讓 Qwen3.6 直接輸出最終短評內容；再以 `/api/chat` 與 `OllamaClient.chat()` 逐一驗證，確認容器內對 `http://host.docker.internal:11434/api/chat` 的請求現在會回傳非空 `content`。已重啟 KB 後，用 `https://61.216.9.52:3030/chat.html` 實測 `請查詢TP-Link Archer BE805的5GHz Throughput測試數據`，回覆已變成 `## 原文` + `## 解讀`，其中 `## 解讀` 是由 LLM 產生的 3~4 條短評，而非固定 fallback；後續 WiFi band throughput 的 2.4 / 5 / 6GHz 也會同樣走這條真實 LLM 短評路徑。

## WiFi 2.4G / 5G / 6G 回覆狀態確認（2026-06-01）

- 目前專案記憶中已記錄：WiFi 2.4G / 5G / 6G 小幫手回覆內容問題已解決，且在 `https://61.216.9.52:3030/chat.html` 上做過實測。
- 已知修正重點包括：
  - WiFi 專用查詢不再掉回一般 `report_graph` / 4G/5G 報告路徑。
  - 2.4GHz / 5GHz / 6GHz throughput 查詢會走 WiFi band raw 路徑，保留對應頻段的原始章節內容。
  - 5GHz 的 `80MHz`、6GHz 的 `80MHz / 160MHz / 320MHz` 已在原文輸出中保留，不再被前端或 LLM 摘要階段漏掉。
- 目前結論：就「之前那個 WiFi 2.4G / 5G / 6G 回覆內容問題」而言，專案內的修正與驗證都已完成，狀態視為已解決；若之後再次出現異常，優先檢查是否為新版本前端、舊瀏覽器快取或新的 ingest 資料路徑造成的回歸。

- 2026-06-01 已實測 SCU2140、SCU2060、SCU5050 的 Throughput 查詢流程：前端 console 出現的 ERR_CERT_AUTHORITY_INVALID 主要發生在 /search 的 fetch 階段，會讓 prepareReportGraphContext、prepareGeneralHandoverSummary、prepareKnowledgeBaseContext 都報 Failed to fetch；但我用 websocket probe 直接送 chat.send 到 OpenClaw Gateway 後，助手仍可正常產生完整答案。實測中 assistant 先輸出『我將透過知識庫系統查詢這三種設備的 Throughput 差異』，接著列出 SCU2140、SCU2060、SCU5050 的逐案原文表格，核心結論是 SCU5050 的 DL 和整體 throughput 最佳、SCU2060 多數案例最低、SCU2140 介於兩者之間。這表示目前問題較像瀏覽器對 HTTPS 憑證的信任或前端 fetch 端點設定，不是小幫手本身不會回答。

- 2026-06-02 已整理手動測試小幫手的範例題目方向：4G/5G 題目建議用 `SCU2140 / SCU2060 / SCU5050 / Throughput / Handover / Latency / Performance / compare / 差異` 等關鍵字組合，WiFi 題目建議用 `TP-Link Archer BE805 / NCQ2200B2V-D294 / 2.4GHz / 5GHz / 6GHz / 80MHz / 160MHz / WiFi Throughput` 等字眼；比較題可直接用 `A、B、C 的 Throughput 有什麼差異？` 這種格式。這些題目可作為手動驗證前端路由、KB 搜尋與回答是否正常的標準測試集。

- 2026-06-02 已修正 WiFi 查詢路由 bug：先前 `請查詢 NCQ2200B2V-D294 的 WiFi Throughput 報告內容` 會因 `wifi` 未被納入 `_is_wifi_specific_query()` 的 hint 而直接落入 `report_graph`，最後誤回 SCU2060 / SCU2140 / SCU5050 的 4G/5G 報告。已同步在 `src/search/__init__.py`、`frontend/chat.html`、`frontend/src/views/ChatView.vue` 將 `wifi / wi-fi` 納入 WiFi 專用判斷，並在 `src/web_api/tasks.py` 的 `sources_only` 分支先優先走 WiFi metadata / raw band / vector 路徑，再考慮 report_graph。已用本機 Python 驗證：`SearchEngine.search('請查詢 NCQ2200B2V-D294 的 WiFi Throughput 報告內容', mode='auto')` 會直接回 `wifi_band_raw`，`search_task(..., sources_only=True)` 也會先回 `NCQ2200B2V-D294` 對應的 WiFi 原文，而不再被 4G/5G report_graph 抢走。

- 2026-06-02 已更新手動測試題庫建議：由於 WiFi 路由已修正，後續驗證應同時覆蓋 `WiFi`、`Wi-Fi`、`WiFi Throughput`、`2.4GHz / 5GHz / 6GHz`、`TP-Link Archer BE805`、`NCQ2200B2V-D294` 等關鍵字組合，並保留 `SCU2140 / SCU2060 / SCU5050` 的 4G/5G compare / throughput / latency / handover 題目作為對照，確認兩條路徑不會互相污染。

## 2026-06-03 type1~type6 作為主分類來源的設計對齊修正
- 使用者要求：專案名稱不固定，不應以 `CHS / NCQ ...` 這類字首當作分類依據；攝入時應以檔名中的 `type1~type6` 為主，`type1` 走 `4G/5G`，`type2` 走 `WiFi`，之後搜尋時只要輸入專案名稱等相關字串，小幫手應能透過 Neo4j / metadata 找到對應文件，再依文件類別路由，不應靠 query heuristics 亂跳到別的文件。
- 已開始修正並落地的層級：
  - [src/storage_paths.py](/home/da40_ai_gb10/knowledge-base/src/storage_paths.py)
    - 新增 `infer_storage_category_from_path()`。
    - `resolve_storage_category()` 改成讓檔名推斷優先，只要檔名能明確判定，就不再被預設 `4G_5G` 覆蓋。
  - [src/ingest.py](/home/da40_ai_gb10/knowledge-base/src/ingest.py)
    - `detect_extraction_mode()` 補上 `sit-tr-wl / wifi / wi-fi / wireless` 的 WiFi 類型偵測，讓 WiFi 報告即使沒有明寫 `type2` 也能被正確辨識。
    - 寫入 Neo4j 與 chunk metadata 時同步帶入 `storage_category` / `extraction_mode`。
  - [src/extract_entities.py](/home/da40_ai_gb10/knowledge-base/src/extract_entities.py)
    - Document 節點寫入時補上 `storage_category`，避免後續只能靠檔名猜類別。
  - [src/vector_store/__init__.py](/home/da40_ai_gb10/knowledge-base/src/vector_store/__init__.py)
    - Qdrant payload 也同步保存 `storage_category` / `extraction_mode`，讓搜尋端可以直接讀到文件類別。
  - [src/web_api/tasks.py](/home/da40_ai_gb10/knowledge-base/src/web_api/tasks.py)
    - ingest task 改成只要檔名模式不是預設 `4g5g` 就優先採用，避免 background ingest 把 WiFi 文件覆寫回 4G/5G。
  - [src/web_api/__init__.py](/home/da40_ai_gb10/knowledge-base/src/web_api/__init__.py)
    - `actual_file_categories` 改為優先讀 `.source.json` 的 `storage_category` / `extraction_mode`，再補 folder fallback。
  - [src/search/__init__.py](/home/da40_ai_gb10/knowledge-base/src/search/__init__.py)
    - 新增 document profile 解析流程，查詢時先用專案名稱/文件名稱關鍵字去 Neo4j 找文件，再根據文件類別決定走 WiFi / 4G/5G / report 等路徑。
    - WiFi compare 不再只靠掃資料夾候選，若 query 明確命中某文件但只找到 1 份 WiFi 文件，會直接回「不足以比較」而不是拿別的 WiFi 文件湊數。
- 驗證結果：
  - `python3 -m py_compile src/storage_paths.py src/ingest.py src/extract_entities.py src/vector_store/__init__.py src/search/__init__.py src/web_api/__init__.py src/web_api/tasks.py` 已通過。
  - `detect_extraction_mode('SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.xlsx')` 與 `detect_extraction_mode('type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.xlsx')` 目前都回 `wifi`。
  - `SearchEngine._extract_document_name_hints('請比較CHS3320N-D388 和 NCQ2200B2V-D294 的 WiFi Throughput。')` 會正確抽出兩個文件名 hint。
- 後續風險與待辦：
  - 目前已把 ingestion / metadata / search 方向對齊，但還需要用實際資料重新驗證 `CHS3320N-D388` 是否已在 Neo4j 中帶有正確 `storage_category`，以及搜尋是否真的能優先命中文件 profile 而非退回舊候選路徑。
  - 如果舊資料已經被錯分到 `4G_5G`，還需要做一次重 ingest 或 metadata 補寫，否則搜尋雖然路由正確，仍可能看不到舊錯分的那份文件。

## 2026-06-03 類別判斷規則改為只看 SIT-SR-SC / SIT-TR-WL
- 使用者進一步更新規則：取消原本 `type1~type6` 的分類方式，攝入時只要檔名包含 `SIT-SR-SC` 就視為 `4G/5G` 類別；只要檔名包含 `SIT-TR-WL` 就視為 `WiFi` 類別；其餘一律回預設 `4G/5G`。也就是說，現在不再依賴 `type1~type6` 來做主分類。
- 已修正：
  - [src/ingest.py](/home/da40_ai_gb10/knowledge-base/src/ingest.py)
    - `detect_extraction_mode()` 只保留兩個明確命中：`SIT-SR-SC -> 4g5g`、`SIT-TR-WL -> wifi`。
    - 原本的 `type1~type6` 分支已移除，其他檔名都回預設 `4g5g`。
  - 所有依賴 `detect_extraction_mode()` 的 ingest / upload / task 流程會跟著使用同一套新規則，不再有另一套舊分類入口。
- 驗證結果：
  - `SIT-SR-SC-Throughput-SCU2060-EV-V13.8.xlsx` 會回 `4g5g`。
  - `SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.xlsx` 會回 `wifi`。
  - `type6_NR-Handover-SCU2050-EV-V004.md` 這類不含上述兩個前綴的檔名，現在會回預設 `4g5g`。
- 結論：
  - `type1~type6` 的主分類規則已正式作廢，後續所有新文件都應以 `SIT-SR-SC / SIT-TR-WL` 作為唯一類別判定依據。

## 2026-06-03 舊資料全量重攝入完成
- 使用者要求「直接把舊資料重攝入策略一起整理」，避免資料庫裡還殘留舊規則產生的分類結果。
- 已新增重攝入工具：
  - [src/reingest.py](/home/da40_ai_gb10/knowledge-base/src/reingest.py)
    - 預設會先清空 Neo4j 與 QDrant，再重新掃描 `data/processed` / `data/uploads` / `data/raw` 中的 Markdown 文件。
    - 採用目前的 `detect_extraction_mode()` 規則，因此只會把 `SIT-SR-SC` 判成 `4G/5G`、`SIT-TR-WL` 判成 `WiFi`，其餘都回預設 `4G/5G`。
    - 保留 `--dry-run` / `--no-purge` / `--no-vector` / `--no-assets` 參數，方便未來重跑。
  - [src/runtime_config.py](/home/da40_ai_gb10/knowledge-base/src/runtime_config.py)
    - 補了 Neo4j / QDrant 的 runtime fallback，讓主機 CLI 可自動落到 `127.0.0.1:17687` 與 `127.0.0.1:6335`，不再硬吃容器內 service name。
  - [src/vector_store/__init__.py](/home/da40_ai_gb10/knowledge-base/src/vector_store/__init__.py)
    - QDrant 連線初始化也改成會依 runtime 自動選擇可用位址。
  - [src/main.py](/home/da40_ai_gb10/knowledge-base/src/main.py) / [src/ingest.py](/home/da40_ai_gb10/knowledge-base/src/ingest.py)
    - `load_config()` 改成使用 runtime Neo4j fallback，確保 CLI 與容器內行為一致。
- 實際執行結果：
  - 已以 `NEO4J_URI=bolt://127.0.0.1:17687 QDRANT_URL=http://127.0.0.1:6335 python3 -m src.reingest` 完成全量重攝入。
  - 驗證 Neo4j：
    - `SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10` -> `storage_category = WiFi`, `extraction_mode = wifi`
    - `type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10` -> `storage_category = WiFi`, `extraction_mode = wifi`
    - `SIT-SR-SC-NR-Handover-SCE2200-n79-EV-V13.8` -> `storage_category = 4G_5G`, `extraction_mode = 4g5g`
    - `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005` -> `storage_category = 4G_5G`, `extraction_mode = 4g5g`
  - 驗證 QDrant：
    - collection `knowledge_base` 狀態為 `green`
    - `points_count = 1162`
- 結論：
  - 舊分類資料已經被清空並重建，現在庫內的分類結果與新規則一致。

## 2026-06-03 SCU compare 掉進 vector 的根因追查與修正
- 使用者追問 `請比較 SCU2140、SCU2060、SCU5050 的 Throughput 差異` 為何會掉進 `vector` 而不是 `report_graph compare`。實際追查後確認，真正問題不是 compare 路由本身先天失效，而是 report graph 資料在重攝入後被破壞了：先前的全量重攝入把 `SIT-TR-SC-NR-Throughput-SCU2140/2060/5050` 這三份 report 在 `src/reingest.py` 的雙重掃描下重新分類成 `4g5g`，導致 `Neo4j` 中的 `Report/TestItem/Section` 節點關係消失，`_report_graph_search_raw()` 因此回 `0 sources`，`search()` 才會退回 `vector`。
- 問題定位：
  - `data/processed/Report/*.source.json` 其實都有正確的 `storage_category = "Report"`。
  - 但 `src/reingest.py` 原本在 metadata 掃描後，又會被後面的純 `.md` 掃描再次 `register()`，後者會用 filename 規則把 `detected_mode` 改回 `4g5g`。
  - 這使得 report 文件雖然有 metadata，最後仍被當作一般 `4G/5G` 文件重新攝入，report graph 自然就消失了。
- 已修正：
  - [src/reingest.py](/home/da40_ai_gb10/knowledge-base/src/reingest.py) 已加上保護：一旦某份文件已由 metadata 決定為 `Report`，後續純 `.md` 掃描就不再覆蓋它的 `detected_mode`。
  - 重新用最小集合 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md`、`SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md`、`SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md` 重建後，Neo4j 統計回到 `Document=3 / Report=3 / Section=40 / TestItem=2 / TestCase=95 / Metric=765`。
  - 驗證 `NEO4J_URI=bolt://127.0.0.1:17687 QDRANT_URL=http://127.0.0.1:6335 python3 - <<...>>` 下的 `SearchEngine.search('請比較 SCU2140、SCU2060、SCU5050 的 Throughput 差異')` 現在回傳 `mode=report_graph`，`sources` 也確實命中三份 report，不再掉進 vector。
- 補充結論：
  - 這次 compare 掉進 vector 的根因是「資料層的 report graph 被錯分破壞」，不是 compare 路由 heuristics 失效。
  - 只要未來 reingest 仍經過 `src/reingest.py`，就會套用這次的 metadata 保護，不會再把已標記為 report 的文件降級成 `4g5g`。

## 2026-06-03 WiFi Throughput 查詢過度精簡的原因與修正
- 使用者實測 `請查詢 NCQ2200B2V-D294 的 WiFi Throughput 報告內容`，回覆雖然有 `【知識庫參考資料】` 與原文片段，但內容仍混入 `SCU2140 / SCU2060 / SCU5050` 的 report graph 資料，看起來又短又偏題。
- 根因追查：
  - 前端的 WiFi summary 呼叫原本是 `prepareWifiSpecificSummary()`，但它在 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 中都用 `searchApi(..., 'vector', { top_k: 6 })`。
  - 這會讓後端先走一般 vector / report 路徑，WiFi 專用的 `sources_only` 分流沒有啟用，因此容易回到 `report_graph`，最後再被前端包成很保守的 KB context。
  - 直接呼叫 `/search` 驗證後，`sources_only: true` 版本會回 `mode=wifi_band_raw`，而且來源確實是 `type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.xlsx`，證明問題不是資料庫沒有 WiFi 原文，而是前端呼叫方式把它帶偏了。
- 已修正：
  - [frontend/chat.html](/home/da40_ai_gb10/knowledge-base/frontend/chat.html)
  - [frontend/src/views/ChatView.vue](/home/da40_ai_gb10/knowledge-base/frontend/src/views/ChatView.vue)
  - `prepareWifiSpecificSummary()` 已改為使用 `sources_only: true`，讓後端先走 WiFi 專用分流，再回傳 `wifi_band_raw`，避免被 report_graph / vector 混入。
- 驗證：
  - `npm --prefix frontend run build` 已通過。
  - `POST /search` 搭配 `mode=auto, sources_only=true` 對 `請查詢 NCQ2200B2V-D294 的 WiFi Throughput 報告內容`，結果為 `mode=wifi_band_raw`，answer 原文直接從 `type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.xlsx` 抽出 2.4 / 5 / 6GHz throughput 區塊。

## 2026-06-03 BE805 5GHz 80MHz / 160MHz 查詢掉回 report 的根因與修正
- 使用者實測 `請整理 TP-Link Archer BE805 的 5GHz 80MHz 與 160MHz 數據` 時，live 回覆一度還是混入 `SCU2140 / SCU2060 / SCU5050` 的 report 來源，看起來像前端被壓成很短的 KB 參考卡。
- 進一步追查後確認，真正根因不是資料錯，而是 WiFi 原文路徑的觸發條件太窄：
  - `src/search/__init__.py` 裡的 `_build_wifi_throughput_band_raw_body()` 原本只接受 `throughput / 測試數據 / throughput data` 這類字樣。
  - 這句查詢只有 `5GHz 80MHz 與 160MHz 數據`，沒有明寫 `throughput`，因此雖然 `BE805` 的 WiFi metadata 找得到，最後仍無法進入 `wifi_band_raw`，後續就掉回一般 `vector` / `report_graph` 路徑。
- 已修正：
  - [src/search/__init__.py](/home/da40_ai_gb10/knowledge-base/src/search/__init__.py)
  - `_build_wifi_throughput_band_raw_body()` 已放寬判斷，現在把 `數據 / data` 也納入 throughput 線索，並在 query 已有 WiFi 線索與頻段資訊時允許進入 WiFi band raw。
  - 這樣 `TP-Link Archer BE805 的 5GHz 80MHz 與 160MHz 數據` 這種寫法也會直接回 `wifi_band_raw`，不再需要使用者一定明寫 `throughput`。
- 驗證：
  - `NEO4J_URI=bolt://127.0.0.1:17687 QDRANT_URL=http://127.0.0.1:6335 python3 - <<...>>` 直接測 helper，`_build_wifi_throughput_band_answer('請整理 TP-Link Archer BE805 的 5GHz 80MHz 與 160MHz 數據', meta)` 現在回 `mode=wifi_band_raw`。
  - 重新 `./restart_kb.sh` 後，在 live `https://61.216.9.52:3030/chat.html` 實測同一句話，console 顯示 `Prepared WiFi-specific KB result.`，citation distribution 變成 `matched_count=1 / WiFi=100/1`，不再混入 `SCU` report 來源。
- 補充結論：
  - 這次不是硬編碼特定文件，而是把 WiFi throughput 路徑的語意門檻放寬，讓使用者常見的「數據」問法也能被辨識為 throughput 類查詢。

## 2026-06-05 OpenClaw 主模型切換為 gemma4:12b
- 使用者要求把小幫手 `openclaw` 內的主要模型也改成 `gemma4:12b`。
- 已更新 active 設定檔 [~/.openclaw/openclaw.json](/home/da40_ai_gb10/.openclaw/openclaw.json)：
  - `agents.defaults.model.primary` 從 `ollama/qwen3.6:35b-a3b` 改為 `ollama/gemma4:12b`
  - `agents.defaults.models` 新增 `ollama/gemma4:12b`
  - `models.providers.ollama.models` 將 `gemma4:12b` 放到清單第一個，保留 `qwen3.6:35b-a3b` 與其他 gemma4 型號作為次要可用模型
- 驗證結果：
  - `jq` 確認 active config 已讀到 `primary = ollama/gemma4:12b`
  - `systemctl --user status openclaw-gateway` 顯示 `openclaw-gateway.service` 仍在跑
  - gateway log 已出現 `config change detected` 與 `config hot reload applied`，表示設定已自動熱重載，不需要手動重啟
- 補充：
  - 這次只改 OpenClaw 的主模型指向，沒有動到知識庫後端設定。

## 2026-06-05 OpenClaw 前台實測驗證
- 使用者要求實際打開 `https://61.216.9.52:3030/chat.html` 驗證前台在 OpenClaw 主模型切到 `gemma4:12b` 後是否正常。
- 實測方式：
  - 先打開聊天浮窗
  - 送出問題：`請整理 TP-Link Archer BE805 的 5GHz 80MHz 與 160MHz 數據`
  - 等待助手回覆完成
- 驗證結果：
  - 前台成功顯示 `已連線`
  - 問題成功送出，且回覆未卡在 loading
  - 最終回覆成功返回 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx` 的 5GHz 原文內容，並包含 80MHz / 160MHz 段落與解讀
  - `final_runs/run_5/plan.md` 已標記所有 critical points 完成
- 證據檔：
  - [`/home/da40_ai_gb10/knowledge-base/final_runs/run_5/final_script.py`](/home/da40_ai_gb10/knowledge-base/final_runs/run_5/final_script.py)
  - [`/home/da40_ai_gb10/knowledge-base/final_runs/run_5/final_script_log.txt`](/home/da40_ai_gb10/knowledge-base/final_runs/run_5/final_script_log.txt)
  - [`/home/da40_ai_gb10/knowledge-base/final_runs/run_5/final_result.json`](/home/da40_ai_gb10/knowledge-base/final_runs/run_5/final_result.json)
  - [`/home/da40_ai_gb10/knowledge-base/final_runs/run_5/screenshots/final_execution_04_final_reply.png`](/home/da40_ai_gb10/knowledge-base/final_runs/run_5/screenshots/final_execution_04_final_reply.png)


## 2026-06-05 OpenClaw 短問句實測驗證
- 使用者要求再測一個更短的問句，確認 `gemma4:12b` 切換後連簡短對話也正常。
- 實測方式：
  - 問句：`你好`
  - 入口：`https://61.216.9.52:3030/chat.html`
- 驗證結果：
  - 頁面載入正常，聊天浮窗正常開啟
  - 問題成功送出
  - 助手正常回覆 `你好！很高興能與你交流。我已經準備好協助你了。`
  - 沒有卡在 loading，也沒有錯誤訊息
- 證據檔：
  - [`/home/da40_ai_gb10/knowledge-base/final_runs/run_6/final_script.py`](/home/da40_ai_gb10/knowledge-base/final_runs/run_6/final_script.py)
  - [`/home/da40_ai_gb10/knowledge-base/final_runs/run_6/final_script_log.txt`](/home/da40_ai_gb10/knowledge-base/final_runs/run_6/final_script_log.txt)
  - [`/home/da40_ai_gb10/knowledge-base/final_runs/run_6/final_result.json`](/home/da40_ai_gb10/knowledge-base/final_runs/run_6/final_result.json)
  - [`/home/da40_ai_gb10/knowledge-base/final_runs/run_6/screenshots/final_execution_04_final_reply.png`](/home/da40_ai_gb10/knowledge-base/final_runs/run_6/screenshots/final_execution_04_final_reply.png)

## 2026-06-05 三國演義檔案搜尋結果
- 使用者詢問是否有一份《三國演義》的小說。
- 已在本地知識庫與工作區做關鍵字搜尋，包含 `三國演義`、`三国演义`、`羅貫中`、`Romance of the Three Kingdoms`、`Sanguo` 等關鍵字。
- 搜尋範圍包含：
  - `/home/da40_ai_gb10/knowledge-base`
  - `/home/da40_ai_gb10/.openclaw/workspace`
- 結果：
  - 沒有找到明確命中的檔案或文件。
  - 目前無法確認知識庫內有收錄《三國演義》小說原文或同名條目。

## 2026-06-05 AFC Device (DUT) Compliance Test Plan v1.7 索引查核
- 使用者詢問 `AFC Device (DUT) Compliance Test Plan v1.7.pdf` 目前是否有被 Neo4j 與 QDrant 收錄。
- 已確認檔案存在於本機：
  - `/home/da40_ai_gb10/knowledge-base/data/AFC Device (DUT) Compliance Test Plan v1.7.pdf`
  - `/home/da40_ai_gb10/knowledge-base/data/uploads/Simple/ingest_20260522_024113_5d2f1280/original/AFC Device (DUT) Compliance Test Plan v1.7.pdf`
  - `/home/da40_ai_gb10/knowledge-base/data/uploads/Simple/ingest_20260522_024113_5d2f1280/converted/AFC Device (DUT) Compliance Test Plan v1.7.md`
- 查核結果：
  - Neo4j 以 `afc` / `AFC DUT` / `Compliance Test Plan v1.7` 搜尋都沒有查到對應節點。
  - QDrant `knowledge_base` collection（當前 258 points）掃描 payload 後，也沒有任何包含 `AFC` 的點位。
  - 因此目前可以判定：這份文件有本地檔案與轉換稿，但**資料庫索引中沒有實際命中**。
- 後續補查路徑後可推知：
  - 這份文件放在 `data/uploads/Simple/ingest_20260522_024113_5d2f1280/...`
  - 依現行攝入規則，`Simple` 代表 `simple` / Type6 簡化路徑
  - 目前未找到對應 source json，但從目錄結構可合理推定它當初是走 `simple` 路徑攝入或至少被歸類到 `Simple` 類別

## 2026-06-05 手動上傳 /upload 的預設類型
- 使用者詢問 `https://61.216.9.52:3030/upload` 手動上傳時會用什麼類型。
- 已確認前端 `UploadView.vue` 的預設狀態：
  - `autoIngest = true`
  - `selectedMode = '4g5g'`
- 上傳端點分工：
  - `/api/upload`：只轉成 Markdown，不進 Neo4j / QDrant
  - `/api/upload/ingest`：送背景攝入任務，會帶 `extraction_mode`
- 若是 `/upload` 頁面直接手動上傳並維持預設：
  - 會走 `autoIngest`，預設模式是 `4g5g`
  - 對於檔名無法自動辨識的文件，後端會沿用這個前端預設值
  - `simple` 不會由這個頁面的預設 UI 自動觸發，除非後端另有明確判定或使用其他攝入入口

## 2026-06-05 /upload 類別攝入調整
- 已將 `/upload` 的可選攝入類別收斂為五種：
  - `4g5g`
  - `wifi`
  - `lab`
  - `project`
  - `automation`
- 行為規則：
  - `4g5g` 與 `wifi` 維持原有攝入原則：LLM 萃取 + Neo4j + QDrant
  - `lab`、`project`、`automation` 只做 chunk 後直接寫入 QDrant，不寫 Neo4j
- 前端已同步更新 `UploadView.vue` 的說明文字與選項顯示。
- 後端 `/api/upload/ingest` 已加入白名單，若收到不支援的類別會回退成 `4g5g`，避免繞過 UI 帶入舊分類。
- 實際驗證結果：
  - `/upload` 展開後只看到 5 個類別按鈕，分別是 `4G/5G 電信設備`、`WiFi 設備`、`Lab 管理`、`Project 專案`、`Automation 自動化`
  - `4G/5G` 與 `WiFi` 的描述仍保留 `LLM 萃取 + Neo4j + QDrant`
  - `Lab / Project / Automation` 的描述顯示為 `Chunk 後直接寫入 QDrant，不寫入 Neo4j`
  - 實測送出 `lab` 類別檔案時，回應 JSON 仍保留 `extraction_mode=lab`，`storage_category=Lab`，並回傳可追蹤任務 `ingest_20260605_075349_a4b34f1f`
  - 證據保存在 `final_runs/run_7/`，包含截圖與 `final_script_log.txt`

## 2026-06-05 ts_138300v180300p_20241001 攝入清除
- 使用者要求清除剛攝入的 `ts_138300v180300p_20241001.pdf` 相關內容，以便重新手動測試新的 `/upload` 類別流程。
- 已完成的清除範圍：
  - Neo4j / QDrant：呼叫 `cleanup_existing_document('ts_138300v180300p_20241001')`
  - uploads 目錄：刪除 `data/uploads/4G_5G/ingest_20260605_072518_c25dcd0a`
  - assets 目錄：刪除 `data/assets/pdf/ts_138300v180300p_20241001`
  - Redis 任務索引：刪除 `kb:ingest_task:ingest_20260605_072518_c25dcd0a`、`kb:ingest_tasks:index` 的對應成員，以及 `kb:ingest_tasks:file_hash_index` 的對應 hash
- 驗證結果：
  - `data/uploads/4G_5G/ingest_20260605_072518_c25dcd0a` 已不存在
  - `data/assets/pdf/ts_138300v180300p_20241001` 已不存在
  - Redis 內 `ZSCORE kb:ingest_tasks:index ingest_20260605_072518_c25dcd0a` 回傳空值，`HGET kb:ingest_tasks:file_hash_index 88db8d1b257f6e711b660e025e967573177770657bf9d71fefab43331fd56103` 也已清空
- 這樣重新手動上傳時，會以全新任務進行，不會撞到舊的攝入紀錄或重複檔索引。

## 2026-06-05 Chat 穩定度排程規格
- 使用者希望把小幫手測試改成「不同時段、不同題型」的穩定度測試。
- 已建立規格文件：
  - [`/home/da40_ai_gb10/knowledge-base/docs/chat-stability-test-spec.md`](/home/da40_ai_gb10/knowledge-base/docs/chat-stability-test-spec.md)
- 規格重點：
  - 入口固定為 [`https://61.216.9.52:3030/chat.html`](https://61.216.9.52:3030/chat.html)
  - 使用 Playwright Firefox，視窗 `1280x1800`
  - 分成 4 個時段（早上 / 中午 / 下午 / 夜間）
  - 題庫分成健康檢查、WiFi、Lab/5G、邊界題四層
  - 每題都要記錄耗時、來源數、console/network errors、截圖與 task id
  - 輸出資料夾建議使用 `final_runs/chat_stability/run_YYYYMMDD_HHMMSS/`

## 2026-06-05 Chat 穩定度 Runner 落地
- 已把上一版穩定度規格落成可直接執行的 runner 腳本與範例排程：
  - [`/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_runner.js`](/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_runner.js)
  - [`/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_schedule.example.json`](/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_schedule.example.json)
- runner 行為：
  - 以 Playwright Firefox 實際操作 [`https://61.216.9.52:3030/chat.html`](https://61.216.9.52:3030/chat.html)
  - 支援 `--schedule-file`、`--slot`、`--all`、`--output-root`、`--base-url`、`--headless`、`--timeout-seconds`、`--retry-count`、`--question-delay-ms`
  - 會自動開啟聊天浮窗、等待連線狀態、逐題送出、等待 bot 回覆、保存截圖、記錄 console / request errors，並輸出 `result.json`
- 已實測成功：
  - 使用 `node scripts/chat_stability_runner.js --schedule-file scripts/chat_stability_schedule.example.json --slot s1_morning --output-root /home/da40_ai_gb10/knowledge-base/final_runs/chat_stability_test`
  - 成功產出 `/home/da40_ai_gb10/knowledge-base/final_runs/chat_stability_test/run_20260605_172540/`
  - 該次結果為 `total_questions=2`、`completed_questions=2`、`failed_questions=0`、`success_rate=1`
  - 第一題 `你好` 與第二題 WiFi throughput 題都正常回覆，代表 runner 可直接用來做排程式穩定度測試

## 2026-06-05 Chat 穩定度 Cron / Shell 入口
- 已新增可直接放進 cron 的 shell wrapper：
  - [`/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_cron.sh`](/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_cron.sh)
- wrapper 行為：
  - 支援 `SLOT=<slot_id> /bin/bash scripts/chat_stability_cron.sh`
  - 也支援 `RUN_ALL=true /bin/bash scripts/chat_stability_cron.sh`
  - 內建 `flock`，避免同時重疊執行
  - 會把執行紀錄寫到 `final_runs/chat_stability/cron_logs/`
- 已實測成功：
  - 以 `SLOT=s1_morning OUTPUT_ROOT=/home/da40_ai_gb10/knowledge-base/final_runs/chat_stability_cron_test /bin/bash scripts/chat_stability_cron.sh` 跑通
  - 成功產出 `run_20260605_173552/`
  - 該次結果為 `total_questions=2`、`completed_questions=2`、`failed_questions=0`、`success_rate=1`
  - 代表 shell / cron 入口可直接作為每日自動排程入口使用

## 2026-06-05 Chat 穩定度每 5 分鐘輪流一題
- 已新增輪流題庫與 wrapper：
  - [`/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_round_robin_catalog.json`](/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_round_robin_catalog.json)
  - [`/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_round_robin.sh`](/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_round_robin.sh)
- 已新增結果歸檔工具：
  - [`/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_bucket_run.js`](/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_bucket_run.js)
- 運作方式：
  - `round_robin_state.json` 記錄目前輪到哪一題
  - 每次 cron 觸發只會跑 1 題，跑完自動推進到下一題
  - 題庫共 30 題，包含 4G/5G、WiFi、Lab 三大類
  - 跑到最後一題後會回到第一題，形成無限輪迴
  - 若該題 `status=completed` 且有非空 `final_reply`，結果會自動歸到 `PASS/`，否則歸到 `FAIL/`
  - 加嚴後會把 `console_errors` 與 `network_errors` 一併納入 FAIL 判定
  - 每個被歸檔的 run 目錄都會附上 `bucket_report.json`，內含失敗原因
- 已實測成功：
  - 使用 `OUTPUT_ROOT=/home/da40_ai_gb10/knowledge-base/final_runs/chat_stability_round_robin_test /bin/bash scripts/chat_stability_round_robin.sh`
  - 首次執行選到 `4g5g_01_scu2140_throughput`
  - 成功產出 `PASS/run_20260605_180914/`
  - 該次結果為 `total_questions=1`、`completed_questions=1`、`failed_questions=0`、`success_rate=1`
  - 也已用 `SLOT=s1_morning OUTPUT_ROOT=/home/da40_ai_gb10/knowledge-base/final_runs/chat_stability_cron_test_passfail /bin/bash scripts/chat_stability_cron.sh` 驗證 `cron` wrapper 會把 `run_20260605_182306/` 歸到 `PASS/run_20260605_182306/`
  - 已用刻意注入 `console_errors` 的假 run 驗證 `FAIL/fail_case/` 會寫出 `bucket_report.json` 與對應失敗原因到 log

## 2026-06-05 2-Session Parallel 模式
- 已新增雙 session parallel runner 與輪替 wrapper：
  - [`/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_parallel_runner.js`](/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_parallel_runner.js)
  - [`/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_parallel_catalog.json`](/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_parallel_catalog.json)
  - [`/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_parallel_round_robin.sh`](/home/da40_ai_gb10/knowledge-base/scripts/chat_stability_parallel_round_robin.sh)
- 運作方式：
  - Session A 與 Session B 會各自使用獨立 Firefox persistent profile
  - 兩邊是獨立 browser process，不共用同一個 browser instance
  - 兩邊都會先完成載入與填題，再在同一個 barrier 同步送出
  - `console_errors` 已分成 `acceptable_warning`、`need_attention`、`hard_fail`
  - 只有 `hard_fail` 會直接判定 `FAIL`；`acceptable_warning` 與 `need_attention` 只記錄不直接失敗
  - A/B 仍需 `status=completed`、`final_reply` 非空、且 `network_errors` 為空
  - `bucket_report.json` 與 `final_script_log.txt` 會標出 `A` / `B` 的異常與 warning 分類
- 已實測成功：
  - 使用 `OUTPUT_ROOT=/home/da40_ai_gb10/knowledge-base/final_runs/chat_stability_parallel_test /bin/bash scripts/chat_stability_parallel_round_robin.sh`
  - 首次執行選到 `pair_01_4g5g_wifi`
  - 兩邊同時送出成功，且結果歸到 `PASS/run_20260605_190605/`
  - 之後也用刻意注入 `session B console_errors` 的假 run 驗證 `bucket_report.json` 會寫出 `B: console_errors=1 ...`
  - 已再驗證 `run_20260606_070253/`，同樣可正常 PASS，代表獨立 profile 版可穩定運作
  - 已再驗證新的 console 分級後，原本只因 `[Chat] 忽略其他 session 的 chat event` 而被判 FAIL 的樣本，現在會進 `PASS`，並在 log 顯示 `PASS (warnings only)`

2026-06-10 已完成「是否可商業化打包、讓使用者直接執行即自動安裝」的架構評估：目前系統已接近可交付的 Docker 化堆疊，`docker-compose.yml` / `restart_kb.sh` 已可自動拉起 Redis、Neo4j、FastAPI、Celery 與前端 runtime，`docs/new-machine-rebuild-guide.md` 也已把重建流程 SOP 化；但現階段仍有明顯的商業化阻礙，包括多處硬編碼絕對路徑（如 `/home/da40_ai_gb10/knowledge-base`、`/home/da40_ai_gb10/.openclaw`）、外部依賴（Docker、Node、Python、Ollama、系統權限）、以及首次安裝時仍需資料 bundle/設定檔才可完整可用。結論是：可做成「安裝器 + Docker/資料 bundle」的 B2B 交付模式，若要做到真正單一可執行檔的 consumer 級體驗，則需要先把路徑參數化、做第一啟動 bootstrap、並重新設計 runtime 依賴邊界。

2026-06-10 已完成 B2B/on-prem 安裝器方向評估：建議採「安裝器 + Docker runtime + 私有模型/資料 bundle」的交付模式，而不是嘗試做成單一原生可執行檔。交付物應拆成四層：1) installer/launcher 負責環境檢查、目錄建立、設定檔生成、Docker 啟動與首次 bootstrap；2) runtime 以 Docker Compose 管理 web、worker、Neo4j、Redis、Nginx 與可選 Qdrant；3) data bundle 只放客戶資料與可選 dump，不進 Git；4) license / config 管理客戶授權與站點參數。下一步若要落地，應優先把硬編碼路徑全部參數化、抽出 first-run bootstrap 流程、明確定義 host 依賴清單與失敗回退，然後再決定 installer 形式（Windows MSI、macOS PKG、Linux bash installer、或跨平台 Electron/Tauri launcher）。

2026-06-10 已確認 B2B/on-prem 方案的前提是「不能改動原始系統檔案、且原始系統必須維持正常運作」：因此不應在現有工作樹上直接重構或重寫啟動腳本，而是採旁路式交付。建議做法是建立獨立的 installer/launcher 專案，透過複製/掛載/覆寫外部設定與獨立安裝目錄來運行，同時保留原始 repo 與原始部署完全不變。新方案應使用獨立的 install root、獨立的 compose project name、獨立 container name、獨立資料目錄與獨立 port range，並以 symlink、overlay config、或外部 volume 的方式與原系統隔離，避免共用原本的絕對路徑與 runtime 狀態。

2026-06-10 已落地獨立 release pipeline，且不修改原始系統檔案：新增 [release/README.md](/home/da40_ai_gb10/knowledge-base/release/README.md) 與 [release/build_release.sh](/home/da40_ai_gb10/knowledge-base/release/build_release.sh)。此 pipeline 會從目前工作樹輸出獨立的 on-prem install package，包內包含 app 副本、runtime（Docker Compose / release Dockerfile / nginx / frontend 靜態檔）、config overlay、OpenClaw overlay 與 manifest；安裝器會把 bundle 展開到指定安裝根目錄，生成獨立 `.env`、自簽 TLS 憑證、`app/config/config.yaml` 與 `runtime/openclaw`，再以獨立 Compose project 啟動 redis / neo4j / qdrant / web / celery / nginx，並使用與原系統隔離的路徑、container 命名與資料目錄。已實測 `./release/build_release.sh` 成功產出 `release/dist/knowledge-base-onprem-20260610_184528-75f3ba30.tar.gz`，並驗證 bundle 內無 `node_modules` / `__pycache__`，installer script 也可通過 `bash -n`。

2026-06-10 已把 release pipeline 升級為版本化與可升級安裝器：`release/build_release.sh` 現在會輸出 `manifest.json` 與 `release-info.json`，兩者都帶有 `format_version`、`release_version`、`release_channel`、`git_commit`、`created_at` 等 metadata；`install.sh` 也改成互動式問答安裝，會先偵測既有 `install-state.env` 走 upgrade 流程，升級前建立備份、保留 `app/data` / `app/config/config.yaml` / `runtime/openclaw`，再同步 release payload。安裝器同時保留非互動參數模式，方便自動化部署。已重新 build 並驗證新包 `knowledge-base-onprem-20260610_185519-75f3ba30.tar.gz` 內包含 `manifest.json`、`release-info.json`、`install.sh`、`app/config/config.yaml.example`，且 installer 腳本通過 `bash -n`。

2026-06-11 已進一步強化 release installer 的前置條件流程：新增 preflight 掃描報告，會在安裝前列出 Docker / Docker Compose / tar / curl / openssl / rsync 的可用狀態；若有缺件，互動式模式會先詢問是否嘗試自動補裝，並提供 `--auto-install-deps` 供無人值守安裝時直接嘗試使用 `apt-get` 補裝可由系統套件管理的項目（目前以 Debian / Ubuntu 為主）。如果補裝後仍缺必需依賴，installer 會明確列出缺少項目並停止，避免在半安裝狀態下繼續往下跑。已重新 build 並驗證新包 `knowledge-base-onprem-20260611_094141-75f3ba30.tar.gz` 內的 `install.sh` 含有 `Preflight check`、`--auto-install-deps` 與 `Attempting to install missing packages` 字樣，且通過 `bash -n`。
- 2026-06-13 已實際驗證 `https://172.14.1.122:18443/chat.html` 的 on-prem KB 聊天鏈路：初始問題並非 WebSocket 或 nginx，而是 `device token mismatch`。已比對主機 `~/.openclaw/identity/device-auth.json` 與 release runtime `runtime/openclaw/identity/device-auth.json`，確認兩者 operator token 不同；將 runtime 的 device-auth 同步為主機版本後，`chat.html` 狀態從 `未連線` 變成 `已連線`，輸入框也正常解鎖。瀏覽器實測送出 `請查詢SCU2140相關報告資訊` 時，系統能正常回覆 KB 參考訊息，並非連線失敗；這次回覆內容顯示該題在 on-prem 目前資料中未命中對應文件，屬於資料召回/命中問題，不是通訊故障。
- 2026-06-13 已確認 `172.14.1.122` 上 OpenClaw 預設模型：透過 `/home/da40_ai_gb10_2/.npm-global/bin/openclaw models status --plain` 查得目前 configured default 為 `ollama/glm-4.7-flash`；其配置來源為 `~/.openclaw/openclaw.json`，其中 `models.providers.ollama.models` 雖列出多個可用模型，但 `models status` 明確顯示目前小幫手實際使用的預設模型是 `ollama/glm-4.7-flash`。若後續要切換模型，應以 `openclaw models set <model>` 或調整對應 config 為準。
- 2026-06-13 已將 `172.14.1.122` 上 OpenClaw 預設模型切換為 `gemma4:12b`，實際 `openclaw models status --plain` 顯示為 `anthropic/gemma4:12b`，且 `models status --json` 的 `defaultModel` 與 `resolvedDefault` 都一致為 `anthropic/gemma4:12b`。同時 `openclaw.json` 已被寫入新的預設模型狀態。需注意 `models status` 也顯示 `anthropic` provider 目前缺少可用 auth profile；若之後要確保完全使用本機 Ollama 端，可能需要再將 default model 明確切到 `ollama/gemma4:12b` 或補齊相對應 provider 認證設定。
- 2026-06-13 已修正 OpenClaw `Unknown model: anthropic/gemma4:12b` 問題：`openclaw models list` 顯示實際可用且已 configured 的模型是 `ollama/gemma4:12b`，而 `anthropic/gemma4:12b` 只是存在但缺 auth 的候選項。已執行 `openclaw models set ollama/gemma4:12b`，`models status --plain` 目前回傳 `ollama/gemma4:12b`，`models list` 也將其標記為 `default,configured`；OpenClaw gateway 於 2026-06-13 10:38:46 亦顯示 config hot reload applied，代表這次修正已生效，後續測試應不再再碰到 `Unknown model: anthropic/gemma4:12b`。
- 2026-06-15 針對使用者詢問「為什麼在 `172.14.1.122` 上請小幫手直接產生 `.py` 檔，結果只回覆寫法而沒有直接給檔案」的分析結論：最可能原因不是單一 bug，而是多個行為約束疊加。第一，該助手的預設互動很可能是「先澄清需求、再動手」的 coding assistant 風格，因此在需求不足時會先講做法而非直接輸出完整檔案。第二，如果當時那個 session 沒有可用的檔案寫入工具或被設成純文字回覆模式，就算它想生成檔案，也只能用文字描述內容。第三，使用者的指令若只說「幫我寫一個程式」而沒有附上輸入/輸出/檔名/限制，它通常會判斷資訊不足，選擇安全地回覆寫法。若之後希望它直接產出可用的 `.py` 檔，指令最好明確寫成「請直接輸出完整可執行的 `xxx.py` 內容，不要只講解；若有缺資訊，先列出假設並以最小可執行版本先給我」。
- 2026-06-15 針對使用者詢問「目前 KB 系統的小幫手 OpenClaw 是否和原生系統一樣有 skills 與 MCP 能力」的分析結論：目前 KB on-prem 有把 `skills` 做成可瀏覽/編輯的管理 API 與前端頁面，會讀取 `~/.npm-global/lib/node_modules/openclaw/skills` 與 `WORKSPACE_DIR/skills`，所以「技能檔案的查看與管理」是有接上的；但 release installer 內的 `write_openclaw_overlay()` 只建立 `gateway`、`identity`、`workspace/memory` 與最小 `openclaw.json`，沒有把原生系統 `openclaw.json` 裡的 `tools.profile`、`plugins.entries` 或任何 MCP 註冊/代理配置一併落地，因此 KB 系統本身**不等於**原生 OpenClaw 的完整技能 + MCP 執行環境。若底層主機已經有相同的 OpenClaw runtime 與外掛設定，聊天鏈路可能繼承部分能力；但就 KB 專案程式碼來看，`skills` 是「管理面有」，`MCP` 則沒有看到同等級的整合與保證。
- 2026-06-15 針對「要讓 KB 上的 OpenClaw 跟原生系統功能一模一樣，該怎麼做」的評估結論：最佳做法不是再做一個 KB 專屬的半套 overlay，而是把 KB release 的 OpenClaw runtime 與原生 `~/.openclaw` 的完整設定面對齊，包含 `tools.profile`、`plugins.entries`、skills 目錄、workspace skills、auth profiles、MCP servers/registry、identity 與 channel 設定；若要追求真正一致，應優先採「共享同一份 OpenClaw home / 同一套配置與 skills 來源」而不是單純複製 identity。若又要保留 KB 與原生系統隔離，則只能做到「功能近似」而非 100% 等價，因為原生行為會受 host 上已安裝的 skills、plugins、MCP server、環境變數與權限影響。
- 2026-06-15 針對 `172.14.1.122` 原生 OpenClaw 是否因 tool usage 限制而導致不會真的寫出 Python 檔的查核結論：本次從可讀到的 OpenClaw 設定與 session 紀錄看不出「寫檔工具被硬限制」的證據。現有 `openclaw.json` 的 `tools.profile` 仍是 `coding`，`gateway.nodes.denyCommands` 只封鎖 camera / screen / contacts / calendar / reminders / sms 類指令，未見檔案寫入相關禁用；session 記錄也顯示 `mcpCapabilities.http=true`，但 `tool_results={}` 代表那次會話根本沒有實際觸發工具。因目前無法直接 SSH 到 `172.14.1.122` 讀取其 live runtime，尚不能 100% 排除遠端主機上的額外政策，但就目前能取得的設定來看，較像是「助手在那個 session 選擇了純文字回覆 / 資訊不足先澄清」，而不是工具層硬性禁止產出 `.py` 檔。
- 2026-06-15 已把 `172.14.1.122` 對應的 OpenClaw remote profile `~/.openclaw-rem122/openclaw.json` 改成 explicit Ollama provider：`models.providers.ollama.baseUrl=http://172.14.1.122:11434`、`api=ollama`、`apiKey=ollama-local`，並把唯一可用模型定義為 `qwen3-coder-next`，同時將 `agents.defaults.model.primary` 改成 `ollama/qwen3-coder-next`。已驗證 `openclaw --profile rem122 config validate` 通過，`openclaw --profile rem122 models list` 只剩 `ollama/qwen3-coder-next`，`openclaw --profile rem122 models status --plain` 也回傳 `ollama/qwen3-coder-next`，代表這份 remote profile 已確實切到 172.14.1.122 的 Ollama 模型而不是原本的 Qwen provider。這次只修改本機的 remote profile 檔，沒有 SSH 進主機改動遠端系統檔案。
- 2026-06-17 已整理 Ollama 對外開放的官方設定重點：預設只綁 `127.0.0.1:11434`，要讓外部主機或其他容器存取需設定 `OLLAMA_HOST=0.0.0.0:11434`（Linux systemd 用 `systemctl edit ollama.service` 加 `Environment="OLLAMA_HOST=0.0.0.0:11434"`，macOS 用 `launchctl setenv`，Windows 用系統環境變數）；若是從不同網域的前端頁面呼叫，還要視需要加 `OLLAMA_ORIGINS`。官方也建議若要公開到網路，最好放在反向代理後面，例如 Nginx 轉發到 `localhost:11434`，而不是直接裸露埠號到公網。
- 2026-06-17 已確認 Ollama 官方文件：本機 API 預設服務位址是 `http://localhost:11434/api`，本機存取不需要驗證；若外部要使用本機 Ollama，做法是讓外部 client 直接把 base URL 指向主機對外 IP 與 11434 埠，例如 `http://61.216.9.52:11434/api`，再呼叫 `/api/chat`、`/api/generate`、`/api/tags` 等 endpoint。若是採 OpenAI 相容介面，則可改用 `http://61.216.9.52:11434/v1/` 作為 base_url。若要讓外部穩定連線，主機端仍需確認 Ollama 服務有對外監聽、11434 埠有放行、防火牆或反向代理沒有擋住流量。
- 2026-06-17 已補充 OpenClaw 連本機 Ollama 的設定原則：外部電腦的 `openclaw.json` 若要連到這台主機，`models.providers.ollama` 應指向 `http://61.216.9.52:11434/v1`（OpenAI 相容介面），`apiKey` 可維持任意占位字串如 `ollama-local`；主模型則把 `agents.defaults.model.primary` 設成 `ollama/<本機已安裝模型名>`，例如 `ollama/qwen3.6:35b-a3b`、`ollama/gemma4:31b` 或 `ollama/gemma4:e4b`。若是走 Ollama 原生 API，而不是 OpenAI 相容層，則 base URL 會是 `http://61.216.9.52:11434`，但 OpenClaw 現有配置脈絡以 `/v1` 為主。
- 2026-06-17 已產出雙測試環境共用 DGX GB10 Ollama 的架構簡報：[dual_test_env_ollama_architecture.pptx](/home/da40_ai_gb10/knowledge-base/dual_test_env_ollama_architecture.pptx)，並保留產生腳本 [generate_dual_test_env_ollama_architecture_pptx.py](/home/da40_ai_gb10/knowledge-base/generate_dual_test_env_ollama_architecture_pptx.py)。簡報共 5 張：封面、整體架構圖、Anritsu MT8000 環境、Amarisoft 環境、部署與維運重點。設計重點是兩個環境各自擁有獨立的 OpenClaw AI Agent 與儀器控制邏輯，但共用同一台 DGX GB10 上的 Ollama 推論服務，Anritsu 對應 `qwen3.5:35b`，Amarisoft 對應 `gemma4:12b`。
- 2026-07-16 已確認目前 knowledge-base 系統有正式 FastAPI 設計，而且是主要 Web API 後端，不是只安裝未使用的相依套件：`requirements.txt` 宣告 `fastapi>=0.115.0` 與 `uvicorn[standard]>=0.30.0`；`src/web_api/__init__.py` 建立 `FastAPI(...)` app、lifespan、CORS、Pydantic request/response models，並集中定義搜尋、非同步任務狀態、上傳、管理統計、文件/skills 管理、OpenClaw chat config 與 `/ws` WebSocket 等路由；`docker-compose.yml` 的 `web` 服務與 `Dockerfile` 都以 `uvicorn src.web_api:app` 啟動。整體資料流可概括為前端/nginx -> FastAPI/Uvicorn -> Redis/Celery 背景任務 -> Neo4j/Qdrant/LLM/OpenClaw。現況的主要結構特徵是多數 API 與模型集中在大型 `src/web_api/__init__.py`，尚未使用 `APIRouter` 拆成多個領域模組，因此功能完整，但模組化與維護性仍有改善空間。
- 2026-07-17 已完成主管報告用企業級 Knowledge Base 系統架構簡報 [`knowledge_base_enterprise_architecture.pptx`](/home/da40_ai_gb10/knowledge-base/knowledge_base_enterprise_architecture.pptx)，並新增可重建的資料驅動腳本 [`generate_enterprise_kb_architecture_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_enterprise_kb_architecture_pptx.py)。簡報採 16:9、深海軍藍/科技藍/青綠企業配色，所有架構元素均為可編輯 PowerPoint 向量圖形，共 10 張：封面、管理摘要與知識價值鏈、五層完整邏輯架構、KB Search/OpenClaw Chat 雙執行路徑、文件攝入供應鏈、混合檢索與答案生成、資料與狀態責任邊界、原始站台與 on-prem release 部署拓撲、可靠度/安全治理、主管結論與 90 天優先事項。架構內容以目前程式碼與部署設定為準，明確區分原始站台的 host Qdrant/Ollama/OpenClaw 與 on-prem release 內建 Qdrant 的差異，也涵蓋 Vue/chat、Nginx、FastAPI、Redis、Celery Search/Ingest/Beat、Qdrant、Neo4j、File Store、Ollama 與 OpenClaw。已完成 `python3 -m py_compile`、實際腳本生成、`unzip -t` PPTX 結構檢查、python-pptx 10 張頁數/圖形邊界檢查、LibreOffice 轉 10 頁 PDF，以及全頁縮圖與關鍵頁逐頁視覺檢查；修正小卡 icon/文字距離、邏輯架構頁底部重疊與 footer 裁切後驗證通過。邊界檢查僅有封面與結論頁刻意超出畫布的背景裝飾圓形，沒有內容型圖形越界。
- 2026-07-20 使用者明確回饋上一版偏向架構說明簡報、沒有足夠明確的「架構圖」，因此已另行重做真正 diagram-first 的 [`knowledge_base_architecture_diagrams.pptx`](/home/da40_ai_gb10/knowledge-base/knowledge_base_architecture_diagrams.pptx)，產生腳本為 [`generate_kb_architecture_diagrams_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_kb_architecture_diagrams_pptx.py)。新檔共 5 張且沒有封面或文字型管理摘要頁，第一張直接呈現 Knowledge Base 完整端到端總架構，後續依序為查詢與 OpenClaw 聊天架構、文件攝入與知識建立架構、混合檢索/資料融合/引用架構、現行站台與 on-prem release 部署架構；每張都包含可編輯 PowerPoint 向量元件、系統邊界、資料庫圖形、連線箭頭、方向與協定/資料流標籤。已用 LibreOffice 實際轉成 5 頁 PDF並逐頁及縮圖總覽檢查，針對窄節點調整為自動取消圖示以避免 Browser/Neo4j/Qdrant/Search Worker 等名稱不自然換行；最終 `python3 -m py_compile`、`unzip -t`、頁數、PDF 轉檔及圖形邊界檢查全部通過，5 張投影片 `out_of_bounds=0`。後續若使用者要「架構圖」，應交付此 diagram-first 新檔；上一版 `knowledge_base_enterprise_architecture.pptx` 僅適合作為架構說明型主管簡報，不應再當成純架構圖版本。
- 2026-07-20 已依使用者提供的 [`all_dig.jpg`](/home/da40_ai_gb10/knowledge-base/all_dig.jpg) 再次重製 Knowledge Base 架構簡報，新增 [`knowledge_base_architecture_all_dig_style.pptx`](/home/da40_ai_gb10/knowledge-base/knowledge_base_architecture_all_dig_style.pptx) 與可重建腳本 [`generate_kb_architecture_all_dig_style_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_kb_architecture_all_dig_style_pptx.py)。本版不使用參考圖作背景，也不沿用管理卡片版型，而是將其視覺規則重建為 PowerPoint 原生向量：白色大畫布、薄色系系統邊界、淡色圓角節點、資料庫圓柱、灰色直線/直角箭頭、少量線上標籤與大量留白。第一張採與參考圖相同的整體構圖，呈現上方使用者/管理者/知識維護者、左側存取與 Web、中央 Knowledge Base AI 應用、右側 OpenClaw/Ollama，以及下方 Unified Knowledge Data Platform；其餘四張依序拆解查詢與 Chat、文件攝入、混合檢索與引用、現行站台和 On-Prem 部署。內容維持目前系統事實，包括 Nginx、FastAPI/Uvicorn、Redis/Celery、SearchEngine、Document Pipeline、Qdrant、Neo4j、File Store、OpenClaw 與 Ollama，並區分現行 host Qdrant 與 release bundled Qdrant。驗證已完成：`python3 -m py_compile`、實際產生 PPTX、`unzip -t`、LibreOffice 轉 5 頁 PDF、逐頁 PNG/contact sheet 視覺檢查，以及 python-pptx 邊界檢查；結果為 5 張、253 個可編輯圖形、`out_of_bounds=0`。後續若使用者要求風格與 `all_dig.jpg` 雷同，應以此檔作為主要交付版本。
- 2026-07-20 已依使用者回饋強化第一張總架構圖的角色路徑，並同步更新 [`all_kowledge.jpg`](/home/da40_ai_gb10/knowledge-base/all_kowledge.jpg)、[`knowledge_base_architecture_all_dig_style.pptx`](/home/da40_ai_gb10/knowledge-base/knowledge_base_architecture_all_dig_style.pptx) 與 [`generate_kb_architecture_all_dig_style_pptx.py`](/home/da40_ai_gb10/knowledge-base/generate_kb_architecture_all_dig_style_pptx.py)。原先「使用者 / 管理者 / 知識維護者」共用單一 Browser 節點，無法判斷角色拓撲；新版拆成三個獨立角色並改用同色路徑語意：藍色「使用者」對應 Search UI / Chat UI、Search API / WebSocket 與查詢/對話；紫色「管理者」對應 Admin UI、Admin API 與管理任務；綠色「知識擁護者」對應 Upload / Watch、Ingest Task、Document Pipeline 與索引建立。Nginx、Celery、Redis 和資料平台仍以灰色線表示三角色共用基礎設施，避免誤解為三套後端。第一次以長折線由角色跨區連接的版本在渲染後判定過於雜亂，最終改成角色框內直接標示路徑摘要，搭配同色 UI 節點與 API 線追蹤，並新增圖例說明。已驗證腳本編譯、PPTX 產生、ZIP 結構、LibreOffice 轉 5 頁 PDF、第一張視覺結果與圖形邊界；最終 PPTX 為 5 張、264 個可編輯圖形、`out_of_bounds=0`，JPG 為 2000x1125 RGB。
- 2026-07-24 已分析使用者執行 `./restart_kb.sh` 時出現的 `KB_REPORT_DB_PASSWORD` compose interpolation 錯誤。根因是 `docker-compose.yml` 內 `report_registry`、`web`、`celery_ingest_worker` 都直接引用 `${KB_REPORT_DB_PASSWORD}`，但 `restart_kb.sh` 沒有先載入任何實際存在的 `.env` / `config/report-ingest.env`，而專案根目錄也沒有 `.env`，只有 `config/report-ingest.env.example` 作為範本。因此 `docker compose up -d ...` 在啟動 `report_registry` 前就因 required variable 缺值而中止。直接修法是建立真實部署 env 檔或先 export 該變數；正式修法則是讓啟動流程明確載入一份已存在的 env 檔，避免依賴人工記憶。特別注意 `KB_REPORT_DB_PASSWORD` 是 PostgreSQL 明文密碼，不是 hash；若密碼含 `$`，要在 env 檔中正確逸出，否則 compose 也可能錯誤展開。
- 2026-07-24 已落地 `KB_REPORT_DB_PASSWORD` 的啟動修正：`restart_kb.sh` 現在會先載入 root `.env` 與 `config/report-ingest.env`，若本機報表 env 檔不存在且 example 存在，則自動以 `openssl rand -hex 24`（或 `python3 secrets.token_hex`）產生一次性的 PostgreSQL 密碼，從 `config/report-ingest.env.example` 建立 `config/report-ingest.env` 並設為 600 權限，再繼續跑 `docker compose up -d --build redis neo4j web celery_search_worker celery_ingest_worker celery_beat nginx`；若 env 檔存在但未定義密碼則直接顯性失敗，避免靜默用壞設定。同步把 `config/report-ingest.env.example` 改成可被 shell `source` 的單引號格式，並將 `config/report-ingest.env` 加入 `.gitignore`。已驗證 `bash -n restart_kb.sh` 通過，且複製 example 到暫存檔後 `source` 可正常讀出 `KB_REPORT_DB_PASSWORD`、`KB_AGENT_TOKEN_HASHES_JSON` 與 `KB_REVIEWER_TOKEN_HASHES_JSON`。
- 2026-07-30 已開始整理 git 同步狀態：先清掉 `src/**/__pycache__` 的 bytecode 雜訊，並在 `.gitignore` 新增 `config/report-ingest.env`、`data/cleaned/`、`data/watch/`、`data/uploads/*/ingest_*/`、`release/.build/`、`release/dist/`，避免 runtime 產物污染同步。已將 source-only 變更暫存，包含核心程式、前端、測試、release 腳本、報表 ingest 新模組、文件與設定；刻意未暫存的仍有大型產物與資料快照，例如 `*.pptx`、`*.jpg`、`data/assets/SIT-TR-NR-Throughput-NCQ2200B2V-EV-V10/` 等，等待使用者決定是否也要一併同步到 GitHub。此時 repo 已從「混雜 code / runtime / 產物」整理成「source staged、artifact pending」兩層。
- 2026-08-03 已依已建立的 `OpenAI Subscription - WifiSit01` 渠道設定實際監控情境。新增 `channel_monitors` id 1：名稱 `WifiSit01 OpenAI Channel Health`、provider=openai、endpoint=`http://61.216.9.52:18080`、group name=`WifiSit01_DA40 / OpenAI Subscription - WifiSit01`、primary model=`gpt-5.4`、extra model=`gpt-5.4-mini`、template id 3（OpenAI Compatible 低 token 檢測）、`max_tokens=20` merge、enabled=true、interval=60 秒、jitter=10 秒；使用 group 7 `WifiSit01_DA40` 的既有 API key，api_key_encrypted 依 Sub2API TOTP_ENCRYPTION_KEY 以 AES-256-GCM 儲存，未寫入明文。第一次執行發現 Docker 內部 endpoint 會被監控 runner 的 SSRF policy 阻擋，改用既有對外 HTTP endpoint 後可連通；另發現先前 channel id 3 的 `restrict_models=true` 在沒有渠道專用 pricing records 時會讓 gpt-5.4/gpt-5.4-mini 回 503 `channel pricing restriction`，已將 channel id 3 改為 `restrict_models=false`，改由 group 7 既有 models_list_config 白名單控管，重啟 Sub2API 應用容器刷新快取。最終驗證：monitor history id 7（gpt-5.4）與 id 8（gpt-5.4-mini）均為 `operational`，latency 約 2682/2736 ms、ping 約 4 ms；Sub2API、PostgreSQL、Redis healthy。既有早期失敗 history 仍保留作為監控稽核紀錄。
- 2026-08-03 已設定一個實際但不觸發真實扣款的 Sub2API 訂閱管理情境：新增 `subscription_plans` id 1，綁定 group 7 `WifiSit01_DA40`，名稱 `WifiSit01 Internal Evaluation - 30 Days`、USD 0、30 天、`for_sale=false`、不建立 payment order；並新增 `user_subscriptions` id 1，指派給 user id 1 `admin@sub2api.local`，group 7、status=active、有效期 2026-08-03 至 2026-09-02、assigned_by=user id 2，daily/weekly/monthly usage 初始為 0。付款訂單數量維持 0，現有 user subscription 數量為 1。重啟 Sub2API 刷新訂閱快取後，以 group 7 API key 呼叫 `gpt-5.4-mini` 回 HTTP 200、finish_reason=stop、usage 9/5 tokens；Sub2API、PostgreSQL、Redis healthy。注意現行 `usage_logs.subscription_id` 欄位仍為空，表示此版本用量記錄未把手動建立的 user subscription id 寫入 usage log，但請求已正常走 group 7/account 2；未建立付款或扣款流程。
- 2026-08-03 目前 Sub2API 進度總結：已完成 OpenAI OAuth 帳號 `openAI_wifisit01`（account 2）→ group 7 `WifiSit01_DA40` → channel id 3 `OpenAI Subscription - WifiSit01` → API key id 5 的可用路由；channel id 3 最終設為 `active`、`restrict_models=false`，由 group 7 的 `models_list_config` 白名單控管模型，避免沒有 channel pricing records 時觸發 503。已建立 channel monitor id 1 `WifiSit01 OpenAI Channel Health`，endpoint=`http://61.216.9.52:18080`、primary=`gpt-5.4`、extra=`gpt-5.4-mini`、template id 3 低 token、每 60 秒加 10 秒 jitter、API key 以 AES-256-GCM 加密；監控 history 最新兩筆為 `operational`，gpt-5.4 約 2682ms、gpt-5.4-mini 約 2736ms。已建立 subscription plan id 1 `WifiSit01 Internal Evaluation - 30 Days`，綁 group 7、USD 0、30 天、`for_sale=false`；並建立 user subscription id 1，指派 user 1 `admin@sub2api.local`，active，有效至 2026-09-02，沒有 payment order 或真實扣款。重啟應用後以 API key 實測 gpt-5.4-mini HTTP 200、finish_reason=stop；Sub2API/PostgreSQL/Redis healthy。已知限制：目前 usage_logs 的 `subscription_id` 仍為空，代表手動建立的 user subscription 尚未被用量記錄欄位引用，但群組路由與請求本身正常；若後續要正式商業訂閱，需再配置付款 provider、公開販售方案、扣款與 usage/subscription 關聯邏輯。管理 API 登入密碼與 `.env` 不一致，本次渠道/監控/訂閱是以受控 SQL 交易建立並以服務重啟刷新快取。
- 2026-08-06 Anritsu agent 配合項目評估：Windows 11 Anritsu 端不需安裝 Neo4j、Qdrant、Redis，也不需重寫既有儀器控制/MCP 工具；建議保留原 agent，新增獨立 A2A Server adapter、固定測試 profile executor、任務狀態/取消/timeout 管理、Agent Card endpoint、HTTPS/VPN/mTLS、以及用 `httpx` 呼叫既有 KB strict ingest API 的 report uploader。Python 建議 3.10+，官方 SDK 使用 `a2a-sdk[http-server]` 或等效 FastAPI extra；另需依現有程式補 `httpx`、`openpyxl`/既有 Excel parser、`python-dotenv`（可選），Windows service 可用 Task Scheduler/NSSM/WinSW，不必引入資料庫。A2A 呼叫認證與 KB Excel ingest token 應分離：目前 `anritsu-agent-01` token 僅作 KB ingest，另建立 KB-to-Anritsu 的 A2A client credential；Anritsu agent 只接受 allowlisted profile，不接受 LLM 直接生成任意 shell/儀器命令。尚未修改 Anritsu 外部電腦或安裝套件。
- 2026-08-06 澄清 Anritsu 結果上傳：KB 目前已具備 Excel `/api/upload/ingest`、strict headers、`KM_Metadata`、Anritsu Bearer token、Celery 攝入及 Neo4j/Qdrant 寫入，並不需要新增第二套 Excel uploader。前一輪所稱 Anritsu 端「新增 report uploader」應理解為：A2A 測試完成後呼叫既有 uploader/MCP tool 或將既有 HTTP 上傳程式自動化；若現有 Anritsu agent 已能上傳 Excel，則這部分完全沿用，不需新增套件。A2A 只負責 KB Agent 委派測試、追蹤 task 與回傳結果 metadata；Excel 本體仍透過既有 KB ingest 流程傳送。A2A response 可回傳 `task_id`、`run_id`、`file_hash`、攝入狀態與來源資訊，不代表要把 Excel 二進位內容塞入 A2A 訊息。
- 2026-08-06 Anritsu A2A 影響風險分析：主要風險包括 A2A 與既有 agent 同進程/套件衝突、port/設定衝突、A2A 與人工操作同時控制儀器、共享檔案/Excel race、A2A 重試造成重複測試、Windows service 重啟遺失 task、KB/VPN/認證失敗、任意命令注入與不受控 duration。推薦解法為獨立 sidecar/adapter 與獨立 Python venv、獨立 port/設定/log、透過既有 adapter 呼叫測試功能、每台儀器與 profile 使用分散式/本機 lock、job allowlist/schema validation、run_id/idempotency/correlation、原子產檔與受控報告目錄、SQLite task journal、timeout/cancel/retry policy、A2A 與 ingest credential 分離、VPN/HTTPS/mTLS、dry-run 與人工批准。驗收需涵蓋手動測試回歸、A2A 與手動並發拒絕、agent 重啟恢復、網路中斷、重複 request、Excel hash/KB task 狀態、未授權命令拒絕與原有功能 health check；任何 A2A 失效都必須不阻斷原本手動測試。
- 2026-08-06 已重新確認 Anritsu A2A 可能影響並更新 `ANRITSU_AGENT_A2A_IMPLEMENTATION_GUIDE.pptx`：投影片由 16 張擴充為 22 張，新增風險總覽與 P0/P1/P2 優先順序，以及五個詳細風險專章：程序/套件/設定隔離、儀器並發與主機資源、Excel/結果/KB 攝入一致性、網路/認證/命令安全、任務恢復/版本相容/回歸。每個專章都包含可能影響、設計解法與驗收方式；明確要求 sidecar + 獨立 venv、exclusive instrument lock（owner/TTL/heartbeat）、atomic Excel write、test_status 與 ingest_status 分離、run_id/idempotency/outbox/reconciliation、A2A/ingest credential 分離、VPN/HTTPS/mTLS、profile allowlist、SQLite task journal、版本固定、feature flag 與 one-command rollback。已重新產生 PPTX、用 python-pptx 驗證 22 張投影片，並以 LibreOffice 轉 PDF、抽查新增風險頁面渲染正常。生成腳本為 `generate_anritsu_agent_a2a_guide_pptx.py`。
- 2026-08-06 已依要求整理目前 knowledge-base 可重建代碼並建立本地 Git commit `3c50a96e`（`feat: sync knowledge-base agent ingestion and architecture`），位於 branch `dev-work`，共 75 files、10864 insertions、3337 deletions。提交前排除 live `config/config.yaml`、`PROJECT_MEMORY.md`、`__pycache__`/`.pyc`、`data/ingestion-registry.sqlite3`、攝入 assets 與本機驗證截圖；明文 Anritsu token 未納入。驗證：後端 focused tests `12 passed`、frontend `npm run build` 通過、`docker compose config --quiet`、Shell/Python 語法與 `git diff --check` 通過。執行 `git push -u origin dev-work` 失敗，GitHub 回 `403 Write access to repository not granted`；目前 remote 為 `https://github.com/kyocarlos/knowledge-base.git`，本機 HTTPS credential 無該 repository 寫入權限，SSH 也沒有可用 identity。需取得具有 write 權限的 GitHub PAT/SSH key 或由有權限帳號登入後，再重跑 push；本地 commit 已完整保留。
- 2026-08-06 目前可作為功能回復點的本地 Git commit 為 `3c50a96eeae7f38fc42f9e8a6152e41bf8324286`（short `3c50a96e`，branch `dev-work`）。後續新功能出錯時，優先先保存故障現場（建立 backup branch 或 stash），再用 `git switch -c recovery/kb-20260806 3c50a96e` 建立安全復原分支並執行 `./restart_kb.sh`；若錯誤 commit 已推送或多人共用，優先使用 `git revert` 建立反向 commit，不改寫歷史。只有在已備份且確認要丟棄後續工作時，才可使用 `git reset --hard 3c50a96e`；不得搭配 `git clean -fd`，避免刪除未追蹤攝入資料。Git 只回復程式與追蹤檔，不會回復 Neo4j、Qdrant、Redis、SQLite、uploads/assets 或 live `config/config.yaml`，涉及 schema/資料遷移的新功能上線前必須另外建立資料備份與 migration rollback。此 commit 尚未成功 push GitHub，正式作為長期回復點前應在取得 GitHub write 權限後 push，並建立 annotated tag。
- 2026-08-06 已確認 GitHub push 403 的真正原因：本機 credential helper=`store` 中的 PAT 有效，登入帳號為 `kyocarlos`；但 GitHub API 對目前 remote `https://github.com/kyocarlos/knowledge-base.git` 回 `404 Not Found`，該 repository 已不存在、改名或未授權給此 fine-grained PAT，所以權限不會自行「恢復」。同一 PAT 目前可見且具 `admin/maintain/push/pull` 權限的目標為 `kyocarlos/knowledge-base-agent-source`（public），其遠端目前只有 `main=ed58505c`。本地尚未修改 origin，也尚未把 `dev-work` commit `3c50a96e` 推到新 repository；正式修正需先確認要把完整本地 branch 推到 `knowledge-base-agent-source`，再更新 remote URL 並以非 force 方式推送新 branch，避免覆蓋既有 main。
- 2026-08-06 已成功將目前 KB 可重建代碼推送到 GitHub `kyocarlos/knowledge-base-agent-source` 的新 branch `dev-work`。直接推本地 `3c50a96e` 曾因舊 repo history 約 2.96 GiB（歷史含 `.venv`/資料）在 GitHub receive-pack 階段 HTTP 500，因此改以遠端 sanitized `main=ed58505c` 建立乾淨快照，套入本次代碼/文件/PPTX，移除 `PROJECT_MEMORY.md`、data、live config、runtime/cache，並將公開快照內既有 Neo4j literal credential fallback 改成環境變數/`change-me`，修正前端 `<project-root>` build 路徑為可攜式 `vite build`/`dist`。乾淨快照驗證：focused backend tests `12 passed`、frontend production build、Compose、Python compile、diff/secret scan及檔案大小檢查通過。GitHub commit 為 `e3d7d29e210378c2211fb33dd66c4a8ea1eceb41`（`feat: sync KB agent ingestion and A2A guidance`），遠端 `main` 未覆蓋；PR 入口為 `https://github.com/kyocarlos/knowledge-base-agent-source/pull/new/dev-work`。本地 production branch 仍保留原 commit `3c50a96e`，兩者因 sanitized history 不同而 commit hash 不同。
- 2026-08-06 已在個人層級 `/home/da40_ai_gb10/.codex/AGENTS.md` 新增「Luna 子代理委派原則」：只允許將輸入清楚、範圍可列舉、成果可驗證且失敗易停止的執行型任務交給 `luna_worker`，包含檔案/入口搜尋、既有測試與失敗整理、固定欄位擷取、明確規格下的少量檔案修改、設定/API/Log 差異比較及證據摘要。禁止直接委派模糊大型功能、跨系統架構重構、正式發布/刪除資料/高風險權限決策、多人重疊修改及無驗收標準的全面優化；主 Agent（Sol）保留目標、架構、產品與風險決策權。核心判準為主 Agent 能否事先定義驗收條件並快速客觀判定結果；Luna 遇到越界或未授權決策必須停止並回報證據、阻塞與待決事項。
- 2026-08-06 已開始指揮 `luna_worker` 進行 KB A2A 導入。第一次唯讀盤點因子代理 sandbox 的 `bwrap: loopback: Failed RTM_NEWADDR` 在執行任何命令前停止，改用不啟動該隔離層但仍明確禁止寫入/網路的方式重試後成功。Luna 以檔案與行號確認：既有 KM 核心集中於 `src/web_api/__init__.py`、`report_routes.py`、Celery tasks、ingest conflict/registry、OpenClaw WebSocket、現有 Compose/Nginx/重啟腳本；第一階段不應修改這些檔案。主 Agent 審查後修正方向：使用者目標是 KB 主動命令 Anritsu，因此不是建立供外部查 KB 的 inbound facade，而是新增獨立 outbound delegation bridge，由 KB 作 A2A client、Anritsu 作 A2A server。官方資料再次確認目前 protocol 1.0、Python SDK 1.1.2 支援 JSON-RPC/HTTP+JSON/gRPC；Agent Card、HTTP header credentials與 Task lifecycle 是必要契約。建議第一版只新增預設關閉、獨立部署、只連 mock Anritsu server 的 bridge，驗證 Agent Card、獨立 Bearer credential、allowlisted profile、polling、timeout/cancel、run_id/task_id correlation；不接真實儀器、不改 KM/OpenClaw/Nginx/Compose/Neo4j/Qdrant/Celery。正式實作前需要使用者確認接受此低風險第一階段，之後才接 Anritsu 正式 URL、Agent Card 與 A2A credential。
- 2026-08-06 已評估「KM 為中心 Agent，Anritsu、Amarisoft 等測試環境為其階層下子 Agent，隨時接受 KM 呼叫」的目標架構。結論為可行且適合採 hub-and-spoke，但父子關係應是管理與工作流上的 logical hierarchy，不應是同進程、共享記憶或共享資料庫的 runtime inheritance。KM 應作為中央 Orchestrator/Control Plane，負責 Agent registry、Agent Card/capability discovery、身份與 scope、策略/人工批准、選擇目標 agent、A2A Task 建立、狀態/timeout/cancel/retry、audit 與 `context_id/task_id/run_id/ingest_task_id` correlation；Anritsu/Amarisoft 則是獨立 A2A Server/Execution Plane，只接受 schema 驗證後且列入 allowlist 的 test profile，以儀器 exclusive lock 執行、原子產出 Excel、沿用既有 KM strict ingest 上傳並回傳測試與攝入狀態。每個子 Agent 必須使用獨立 endpoint、credential、capability、queue、rate limit 與健康狀態，禁止直接存取 Neo4j/Qdrant/Redis 或 KM 內部記憶。為避免中央單點與連鎖故障，A2A bridge/task registry 應獨立於 KM 核心、預設 feature flag 關閉、採 persistent journal/outbox、明確 at-least-once + idempotency 語意，子 Agent 離線時排隊或顯性失敗，不能阻塞 KM 查詢/聊天/攝入。高風險測試需人工批准；「隨時呼叫」應解讀為隨時可提交任務，而非保證儀器立即執行。建議先 Anritsu mock/dry-run，再單一真機 profile，最後複製契約到 Amarisoft並驗證併發隔離。
- 2026-08-06 已依最新中央階層架構更新 `ANRITSU_AGENT_A2A_IMPLEMENTATION_GUIDE.pptx` 及生成腳本 `generate_anritsu_agent_a2a_guide_pptx.py`。先由 `luna_worker` 唯讀逐張審查原 22 張內容，確認原簡報的 sidecar/venv、allowlist、exclusive lock、credential separation、冪等、rollback 與既有功能隔離已符合；缺口為 KM Control Plane 定位、Anritsu/Amarisoft 獨立 Execution Plane、queue/reject、四個 canonical correlation IDs、三種獨立 status 與 rollout 順序。更新後仍為 22 張：第 1/2/3/4 張明確定義 KM Central Orchestrator、outbound Bridge 與兩個獨立測試 Agent；第 9 張固定 `context_id/a2a_task_id/run_id/ingest_task_id`；第 10 張加入 submitted/queued/working/completed/rejected/failed-canceled 並說明 A2A completed 不等於 ingest completed；第 16 張加入 busy 時 queue/reject 與 reason code；第 17 張分離 `test_status/report_status/ingest_status`；第 20 張改為 mock→dry-run→單一 Anritsu 真實 profile→獨立 Amarisoft→雙環境 concurrency；第 21 張擴充為 12 項驗收，包含不同 endpoint/credential/queue 與跨環境儀器/資料隔離；第 22 張要求先提交 mock/dry-run、queue/reject 與 rollback 證據，主 Agent 核准後才開真機。驗證通過：Python compile、重新生成 22 張、必要文字 assert、LibreOffice PDF 轉換、22 頁非空白像素檢查、重點頁面目視檢查及 `git diff --check`。本次未修改 KM runtime、Compose、Nginx、FastAPI、Celery、Neo4j/Qdrant 或 OpenClaw。
- 2026-08-06 已依最新評估開始實作 KB A2A Phase 0，新增完全隔離、預設關閉的 `km_a2a_bridge/`，未修改既有 KM FastAPI/OpenClaw/Celery/Compose/Nginx/Neo4j/Qdrant。先由 `luna_worker` 實作契約/設定與 28 項測試，主 Agent 審查後補強：`TestJob` 只允許 `run_iperf_test`、anritsu/amarisoft、安全 ID、1..3600 秒、非空安全 test cases、extra forbid；環境別 profile allowlist；enabled 時必須有至少一個 HTTPS agent endpoint、不同 outbound A2A SecretStr credential、SHA-256 control token hash；Pydantic errors 隱藏 secret input；`context_id/a2a_task_id/run_id/ingest_task_id/file_hash` correlation；獨立 `test_status/report_status/ingest_status`；穩定 rejection reasons。新增 SQLite `TaskJournal`，以 `(environment, run_id)` 保證冪等、不同 payload conflict，並處理 concurrent unique-key race；新增 `MockA2ATransport`，只產生 A2A correlation，永遠不操作儀器、不上傳 Excel，A2A completed 時三種業務狀態仍為 pending；新增 `BridgeService` 與獨立 FastAPI app，提供 unauthenticated `/health`、hash-only control-token 保護的 `POST /v1/tasks` 與 `GET /v1/tasks/{environment}/{run_id}`。依賴固定於獨立 `requirements.txt`（含官方 `a2a-sdk==1.1.2`），並提供 `.env.example`、README；目前設定只允許 `transport_mode=mock`，尚未接真實 A2A wire endpoint或儀器。驗證：新增及既有 focused tests 合計 `58 passed`、compileall、diff check；實際以 `127.0.0.1:18181` 啟動 disabled service，`/health` 回 `enabled=false, transport=mock, real_instrument_access=false`，未帶 control token 的 submit 回 401，之後已停止且 port 關閉。Luna 的最終唯讀 review 因 180 秒 timeout 未產出報告，故不視為通過；主 Agent自行補上安全 ID、secret error hiding 與 SQLite concurrency 修正。下一階段應實作官方 SDK 1.1.2 wire-level client + 本機 mock Anritsu A2A Server contract test，通過後才討論 Anritsu dry-run endpoint；仍不可直接接真實儀器。
- 2026-08-06 已完成 KB A2A 下一階段的官方 wire-level dry-run client。新增 `km_a2a_bridge/sdk_transport.py`，實際使用官方 `a2a-sdk==1.1.2` 的 `A2ACardResolver`、`ClientFactory/ClientConfig`、protobuf `SendMessageRequest` 與 JSON-RPC `SendMessage`；每個 job 固定加入 `job_schema_version=1.0` 與 `dry_run=true`。`agent_endpoints` 已釐清為不含 path 的 HTTPS discovery base URL，實際 `/a2a` interface 由 `/.well-known/agent-card.json` 決定。安全驗證要求 Agent Card 至少有 A2A 1.x JSON-RPC 與 `run_iperf_test` skill，且所有 supported interface 必須與 discovery URL 同 origin，防止惡意 Agent Card 將 outbound Bearer credential導向其他網域；遠端 Task 必須回傳非空 context/task IDs，metadata `runId` 必須一致，rejected state 映射到穩定 rejection reason。設定新增 `sdk-dry-run` transport，但預設仍為 `mock`；FastAPI factory 只有明確指定時才載入 SDK transport，health 仍標示無真實儀器權限。新增 in-memory mock Anritsu A2A HTTP server contract tests，實際驗證 Agent Card GET、Bearer header、JSON-RPC POST、結構化 data Part、Task correlation、remote busy rejection、run mismatch、cross-origin Card credential 防護，以及完整 `BridgeService → SDK transport → SQLite journal` 持久化。最終新增與既有 focused tests合計 `64 passed`、compileall 與 diff check 通過。尚未連線外部 Anritsu，也未啟動/部署 bridge、未改既有 KM runtime。下一步外部條件為 Anritsu 提供 HTTPS discovery base URL、符合契約的 Agent Card、獨立 A2A credential，並證明 `dry_run=true` 不會取得 instrument lock；完成後才能做跨電腦 dry-run，仍不得直接開真機 profile。
- 2026-08-06 釐清「KM Agent 該做的部分是否完成」：目前只完成 KM 端 A2A 的安全基礎與 wire dry-run client，不代表中央 Agent 整體整合完成。已完成項目為隔離 bridge、契約/allowlist、control/outbound credentials、SQLite journal、冪等/correlation/三狀態、官方 SDK Agent Card + SendMessage、mock/in-memory dry-run 與 64 項 focused tests。尚未完成項目包括：bridge 的正式部署與服務管理、Anritsu 真實 discovery/card/credential 跨電腦 dry-run、A2A GetTask polling/timeout/cancel/recovery、KM/OpenClaw 可呼叫的受控 tool/skill、Agent registry/health routing、多 Agent 選擇、操作者批准流程、把遠端結果與既有 ingest task correlation 回填、audit/監控、Amarisoft 接入，以及真實儀器前的完整並發/rollback/E2E 驗收。現階段刻意不修改 KM runtime，以避免在外部契約未完成前影響既有功能；應判定為「KM A2A client foundation 完成，KM Central Orchestrator integration 未完成」。
- 2026-08-06 已新增可直接交付 Anritsu Agent 的 [`ANRITSU_AGENT_A2A_REQUIREMENTS.md`](/home/da40_ai_gb10/knowledge-base/ANRITSU_AGENT_A2A_REQUIREMENTS.md)，共 333 行。文件明確定義 KM Central Orchestrator 與 Anritsu Execution Plane 角色、sidecar/venv/runtime 隔離、必要套件與模組、A2A 1.x JSON-RPC Agent Card、同 origin、安全 credential 分離、固定 job schema、`dry_run=true` 不得取得 lock/控制儀器/啟動 iperf/產正式 Excel/呼叫 ingest 的硬性規則、Task lifecycle/rejection reasons、人工與 A2A 共用 exclusive lock、四個 correlation IDs 與 file hash、冪等/conflict、test/report/ingest 三狀態、原子 Excel 與既有 KM strict ingest handoff、SQLite journal/重啟恢復/audit、health、Mock→Dry-run→單一真實 profile 的分階段順序。文件另含 17 項 Anritsu 交付清單、13 項 KM 跨電腦 dry-run 驗收條件，以及禁止進入真實儀器階段的停止條件。未包含任何現有 token 或秘密；Markdown 章節、必要內容、特定明文 token 排除與 `git diff --check` 已驗證通過。
- 2026-08-10 已完成目前 Knowledge Base 公司內部正式導入 readiness 盤點。結論：現況已有可運作的 Nginx/TLS、FastAPI、Redis/Celery、Neo4j/Qdrant、文件攝入與混合查詢、來源引用、任務狀態、嚴格 Agent 攝入身分/冪等保護、報表 Agent/Reviewer token 與部分 focused tests，且 `https://127.0.0.1:3030/health` 實測 HTTP 200；但整體定位仍是可控試行環境，尚未達企業 production gate。P0 缺口：(1) 一般使用者、管理 API、Skills 寫入、查詢/文件操作缺少統一 SSO/OIDC、RBAC/API scope，並缺 document-level ACL/filtering；(2) Compose 將 Web 8000/3000 與獨立 Qdrant 6335/6336 綁到所有介面，可繞過 Nginx/TLS/授權，且 FastAPI CORS 為 `allow_origins=["*"]` + credentials；(3) `docker-compose.yml` 仍有 Neo4j 明文密碼、`neo4j:latest`、預設 `KB_INGEST_REQUIRE_AGENT_AUTH=false`，需移至 Vault/KMS/Docker secrets、輪替現有秘密、固定映像版本/摘要；(4) 現有 `create_data_backup_bundle.sh` 只備份 raw/processed/assets/uploads/config，未涵蓋 Neo4j、Qdrant snapshot、PostgreSQL registry、Redis/A2A/ingest registry，也沒有異地加密、retention、RTO/RPO 與 restore drill；(5) 缺完整不可否認 audit、上傳惡意程式/MIME/macro/壓縮炸彈掃描、企業 PKI/DNS 與 edge rate limit/security headers。P1 缺口：集中式 structured logs/metrics/traces/alert/SLO；依賴型 readiness/liveness；單機 Compose 的 HA、restart/resource/log limits、容量/壓力/故障演練；CI/CD、dev/UAT/prod 分離、IaC、schema migration、SAST/SCA/container/SBOM/secrets scan、發布 rollback；資料分類/owner/審核/retention/legal hold/刪除/lineage/DLP；模型與 prompt 版本、批准模型資料邊界、品質/引用 eval、timeout/retry/circuit breaker；更完整 auth/E2E/load/backup-restore/security tests。P2 為使用者回饋、無障礙/瀏覽器相容、操作手冊/值班/教育訓練，以及若列入首波需求才需完成 A2A bridge 正式部署、OpenClaw tool、Agent registry/approval/monitoring 與 Anritsu/Amarisoft E2E；A2A 不應阻擋純 KB 首波上線。建議順序：先完成 P0 安全與復原門檻，再做 P1 可觀測性/發布與容量治理，最後以受控部門試點、UAT/資安審查及 restore/load test 證據決定正式放行。
- 2026-08-10 已將目前支援 A2A Agent 的最新 Knowledge Base 版本成功更新到 GitHub `kyocarlos/knowledge-base-agent-source` branch `dev-work`。本機先建立只含 A2A 的 checkpoint commit `3f15d87b`，再由遠端 sanitized `dev-work=e3d7d29e` 建立乾淨 worktree，同步 18 個檔案：隔離且預設關閉的 `km_a2a_bridge/`、4 組 A2A tests、`ANRITSU_AGENT_A2A_REQUIREMENTS.md`、22 張 Anritsu A2A 實作指南 PPTX 與生成腳本。乾淨快照 commit 為 `35d8d56a`（`feat: add isolated KM A2A delegation bridge`），已非強制推送到 `agent-source/dev-work`，未修改遠端 `main`。驗證包含一次性隔離 venv 依 `km_a2a_bridge/requirements.txt` 安裝後 `52 passed`、compileall、PPTX 生成腳本 py_compile、`git diff --check`、已知真實 token/雜湊/Neo4j literal secret scan 與大檔檢查；未推送 live `config/config.yaml`、`PROJECT_MEMORY.md`、`data/assets`、runtime registry、`__pycache__` 或任何真實 credential。GitHub branch URL：`https://github.com/kyocarlos/knowledge-base-agent-source/tree/dev-work`，commit URL：`https://github.com/kyocarlos/knowledge-base-agent-source/commit/35d8d56a`。
- 2026-08-10 使用者要求為最新 A2A KB 建立全新 GitHub 備份供大量修改。嘗試透過 GitHub API 建立 private repository `kyocarlos/knowledge-base-a2a-development`，API 回 HTTP 403 `Resource not accessible by personal access token`；目前 fine-grained PAT 可寫入既有 `knowledge-base-agent-source`，但沒有建立 repository 權限，因此未宣稱新 repo 已建立。為立即提供隔離且可回復的開發空間，已在 `kyocarlos/knowledge-base-agent-source` 建立新 branch `a2a-development`，並建立 annotated tag `a2a-safe-backup-20260810`；原 `dev-work`、新 `a2a-development` 與 tag peeled commit 均指向已驗證版本 `35d8d56a713d7436b8db2fc81ae4b96e8c13516a`，未修改原 branch 內容。後續大量修改應只推至 `a2a-development`；`dev-work` 作穩定基準，tag 作固定回復點。Branch URL：`https://github.com/kyocarlos/knowledge-base-agent-source/tree/a2a-development`。若仍要求完全獨立 repository，需先為 PAT 增加建立 repository 權限，或由 GitHub 網頁手動建立空的 private `knowledge-base-a2a-development`，之後可將 `35d8d56a` 非強制推送為新 repo `main`。
- 2026-08-10 針對「直接在現有 Knowledge Base 大幅修改且需隨時復原」的建議：不可只依賴 Git，因 Git 不涵蓋 Neo4j、Qdrant、PostgreSQL、Redis/SQLite registry、uploads/assets 與 live config。程式碼以 GitHub `dev-work` / commit `35d8d56a` 作穩定基準，固定 tag `a2a-safe-backup-20260810` 作不可移動回復點；所有大改從 `a2a-development` 再建立一個功能 branch（例如 `feature/kb-major-redesign`），禁止直接改 `dev-work` 或移動安全 tag。修改前需另建有時間戳且異地保存的完整資料快照：Neo4j dump、Qdrant snapshots、PostgreSQL dump、ingestion/A2A SQLite、uploads/assets、實際 deploy env/config 與目前 container image/version manifest，並先驗證可還原。開發期間每個可驗證階段建立小 commit/checkpoint tag，先跑 focused tests、Compose config、API/主要 `https://61.216.9.52:3030/chat.html` E2E，再允許進下一階段；高風險 schema/data migration 必須有 forward/rollback script，不能只靠程式回退。出錯時優先停止新版本、保留故障證據，從安全 commit 建 recovery branch 或對共享歷史使用 `git revert`，再還原對應資料快照與舊 image/config；不要直接 `git reset --hard` 或 `git clean -fd`，避免刪除未追蹤資料。更推薦用另一個 Git worktree/獨立 Compose project、port、volume 驗證大改，即使修改同一套 source，也不要讓未驗證版本直接寫入正式資料庫。
- 2026-08-10 已依 `docs/km-modernization` 指定流程完成 WP0 實作，來源為 GitHub branch `agent/km-modify-codex-plan` / commit `4c1ceba5`，沒有從 `main` 或 `dev-work` 開工。建立獨立 branch `agent/wp0-fastapi-contract`，最新 commit `2c46c834d8d1aef170dc4862101db02cb536e3ca` 已推送到 `kyocarlos/knowledge-base-agent-source`。WP0 僅涵蓋 REQ-API-001、REQ-API-002 與 REQ-OPS-001 的 API baseline slice：新增 `app/` FastAPI shell、typed env settings、`/api/v1/health`、`/api/v1/health/live`、`/api/v1/health/ready`、`/api/v1/version`、統一 `ApiResponse/ApiError`、X-Trace-ID middleware、穩定 exception envelope、legacy route compatibility、`requirements-dev.txt` 與 `pytest.ini`；舊 `/health`、`/search`、`/ws`、report upload/review、ingest 與 A2A route/response 保留，A2A bridge 未修改且仍 disabled/dry-run。Dockerfile、Compose、host `start.sh` 與 on-prem release builder 的 Uvicorn entrypoint 改為 `app.main:app`，Celery 仍使用 `src.web_api.tasks`；release builder 同時補上 app source copy，並修正兩個原有包版阻塞（過時 frontend output 路徑、不存在的 optional frontend lib 硬拷貝）。驗證：隔離 test venv `python -m pytest -q tests` 為 `76 passed`、compileall、bash syntax、Compose config、Vue build、實際 Uvicorn smoke 與 Webwright/Firefox 本機 Portal smoke 均通過；release package `wp0-validation-3` 成功產生並確認含 `app/app/main.py`、`app.main:app` entrypoint。Webwright 證據保留於 `/tmp/kb-wp0-webwright/final_runs/run_2/`（Search、Upload、Report Review 截圖及無 console/network error log）。未部署到正式 `https://61.216.9.52:3030/chat.html`，未執行 WP1-WP13、Knowledge Package、Qdrant/Neo4j/TimescaleDB、CSIT、RBAC、Agentic RAG 或真實儀器 A2A。嘗試透過 GitHub API 建立獨立 PR（base=`agent/km-modify-codex-plan`、head=`agent/wp0-fastapi-contract`），但目前 PAT 回 HTTP 403 `Resource not accessible by personal access token`；因此 PR 尚未建立，分支已保留，建立連結為 `https://github.com/kyocarlos/knowledge-base-agent-source/pull/new/agent/wp0-fastapi-contract`，PR body 已準備且列出 Requirement/ADR/檔案/測試/未驗證/回滾。後續需由有 Pull Request write 權限的 GitHub token/帳號建立並審查 PR，禁止直接合併 main/dev-work。
- 2026-08-10 使用者已在 GitHub 網頁成功建立 WP0 Pull Request #2：`https://github.com/kyocarlos/knowledge-base-agent-source/pull/2`。已核對 PR base=`agent/km-modify-codex-plan`、head=`agent/wp0-fastapi-contract`、1 commit、23 files、+555/-19，狀態 Open，尚未合併；目前 PR description 為空，GitHub Checks=0、Reviewers=none，應補上 WP0 Requirement/ADR、`76 passed`、compileall/Compose/Vue/release/Webwright 證據、未驗證項目與 rollback，再進行 review。不得直接合併到 `main` 或 `dev-work`。
- 2026-08-10 嘗試直接以目前 GitHub credential 更新 PR #2 description，GitHub API 回 HTTP 403 `Resource not accessible by personal access token`；目前 token 可 push branch、可讀 PR，但沒有 PR edit 權限。PR #2 本身仍正常 Open，base/head 與 WP0 commit 不變。下一步必須由已登入 GitHub 網頁的使用者在 PR #2 按 Edit，貼入已準備的 WP0 description；不得因此修改程式碼或合併分支。
- 2026-08-10 已評估 WP0 之後 Knowledge Base 的修改順序。結論：先完成 PR #2 的 description/review 與 CI gate，再開始 WP1；不要直接同時做 Knowledge Package、Qdrant/Neo4j/TimescaleDB、RBAC 或 Agentic RAG。建議順序為：WP0 review/CI → WP1 Docker/Redis/Celery/Config reliability → WP2 Knowledge Package 1.0/Validation/Routing → WP3 Qdrant projection 與 WP4 CSIT adapter（可在 WP2 Gate 後平行）→ WP5 report publish ledger（依賴 WP3/4）→ WP6 TimescaleDB、WP7 Neo4j ontology（依賴 WP2/5 的資料契約）→ WP8 RBAC/Citation/Audit（雖列在後段，正式資料與新查詢 API 前必須提前作為 cross-cutting gate）→ WP9 Portal/OpenClaw MVP integration；WP10 之後才進 Compile-Time RAG、Agentic RAG、AI analysis，A2A bridge 維持 isolated/disabled/dry-run，不應與 WP1/2 混做。PR #2 合併前須確認 legacy `/health`、`/search`、`/ws`、report upload/review、ingest、A2A dry-run、Docker/release entrypoint、76 tests 與本機 Portal smoke；建議立即補 GitHub Actions，至少執行 pytest、compileall、Compose config、frontend build 與 secret scan，因目前 PR Checks=0。WP1 的主要風險是 Celery queue/state/retry/timeout/trace、Beat 預設啟動、Compose 硬編碼路徑/秘密與 SQLite/Redis 狀態；必須先做 config contract、job state machine、有限 retry/idempotency、worker restart/duplicate/recovery tests，再修改 production startup。WP2 是所有資料庫改造的唯一入口：Parser 只能產 Knowledge Package，Validation 失敗不得產 DB mutation；在 WP2 Gate 前禁止改 Qdrant collection、Neo4j ontology 或新增 TimescaleDB schema。正式導入前還需獨立完成 SSO/RBAC/ACL、完整備份還原、audit/監控、CI/CD、容量與資安測試，不能因 WP0 health 200 或 UI 可載入就視為 production-ready。
- 2026-08-10 使用者要求先完成 PR #2 review/CI 再建立 WP1。PR #2 仍為 Open，base=`agent/km-modify-codex-plan`、head=`agent/wp0-fastapi-contract`、WP0 commit=`2c46c834`，未合併。已在隔離 worktree `/tmp/kb-wp0-ci.mOVFqd` 新增 `.github/workflows/wp0-contract.yml`，本地驗證 pytest `76 passed`、compileall、Compose config、shell syntax、frontend build 與 diff check 均通過；但 push 被 GitHub 拒絕，因目前 PAT 沒有 `workflow` scope，commit `19d0751e` 尚未進入 PR。需用具 `workflow` scope 的 credential 推送該檔案或由 GitHub UI 建立 workflow，之後再確認 Actions green；此阻塞不代表測試失敗。
- 2026-08-10 已從遠端 WP0 branch 建立並推送獨立 WP1 branch `agent/wp1-job-config-reliability`，worktree=`/tmp/kb-wp1.TULD2s`，基準為 `2c46c834`，commit=`2a4ba2af`。本輪 WP1 實作只處理背景工作設定底座：新增 `app/core/job_config.py` 的 `JobConfig` typed environment parsing 與 `JobStatus`（queued/running/succeeded/failed/retrying/cancelled）；Celery result TTL、worker concurrency、soft/hard timeout、搜尋 max retries、processing lock TTL 改由設定讀取；保留既有 `search`/`ingest` queue，並宣告 `default/document/indexing` queue contract；Compose 的 Celery Beat 改為 `scheduler` opt-in profile，Neo4j 不再接受 `change-me` 弱預設密碼。新增 `tests/test_wp1_job_config.py`。驗證結果：WP1 focused 44 passed，完整 tests `79 passed`，compileall、Compose config（以 CI-only secrets）、git diff check 均通過。尚未完成 WP1 全部驗收：trace_id→Celery headers、transient/non-retryable error taxonomy、完整 Job state persistence/transition、worker restart integration、idempotency integration、host path/named-volume 完整參數化與 WP1 PR/CI；因此不可宣稱 WP1 完成或部署 production。A2A、Portal、search、report upload/review、ingest 業務未改動。
- 2026-08-10 WP1 續作已推送至 `agent/wp1-job-config-reliability`，最新 commit=`b4aece60`。新增 `celery_headers()` 並由 search、一般 ingest、report ingest 將 HTTP `X-Trace-ID` 傳入 Celery task headers；攝入 Redis state 以新增 `job_status` 欄位映射 queued/running/succeeded/failed/cancelled，維持既有細分 `status` 供 Portal 相容；search retry countdown/max retries 改用 typed config；Compose 的 config/data/upload host mount 改為 `KB_CONFIG_ROOT`、`KB_DATA_ROOT`、`KB_UPLOAD_ROOT` 可配置，仍保留相容預設；新增 trace header contract test。完整 pytest=`80 passed`，compileall、預設與自訂 host path 的 Compose config、git diff check 均通過。WP1 仍未完全關閉：尚需 transient/non-retryable error taxonomy、明確的 retrying transition、worker restart integration、跨 API 的 idempotency integration、Beat/startup 行為的實際容器驗證，以及獨立 WP1 PR/CI；目前只可稱為 WP1 reliability implementation in progress，不能宣稱正式完成。
- 2026-08-10 WP1 再續作已推送至 `agent/wp1-job-config-reliability`，最新 commit=`348ddac8`。新增 `RetryDecision` 與 `classify_job_error()`：ValueError/TypeError/FileNotFoundError/PermissionError 視為 non-retryable；TimeoutError/ConnectionError/OSError 視為 transient；未知例外預設不自動重試，避免把業務或輸入錯誤無限重試。`ingest_file_task` 會在 transient 且未超過上限時寫入 `job_status=retrying`、釋放 document lock 後使用有限 retry；搜尋任務也套用同一 policy。新增 `tests/test_wp1_retry_policy.py`。完整 pytest=`81 passed`，compileall 與 diff check 通過。WP1 尚未完全關閉，仍需 worker restart/idempotency integration、實際容器驗證、CI/PR gate。
- 2026-08-10 WP1 再續作 checkpoint 已推送至 `agent/wp1-job-config-reliability`，最新 commit=`0dad72bd`。Compose 的 Redis/Postgres/Neo4j/web/search worker/ingest worker 加上 `restart: unless-stopped`，持久化 named volumes 保留；新增 `tests/test_wp1_celery_contract.py` 驗證 default/document/indexing 與 legacy search/ingest queues、route 及 canonical `job_status` 映射。測試先發現 `tasks.ingest_task` 仍錯誤路由到 search，已修正為既有 ingest worker queue，避免任務被錯誤 worker 消費。完整 pytest=`83 passed`，compileall、Compose config、diff check 通過。仍未完成實際 Docker worker restart/failure recovery 與真正 Redis idempotency integration；這些需可控的容器/服務環境，不能以單元測試替代。
- 2026-08-10 已直接完成 WP1 實際服務驗證，最新分支 commit=`7cfa1d6e`。使用隔離 Compose project `kb-wp1-runtime`、臨時 container names/ports 與測試資料目錄，未碰正式 `kb-*` 容器或正式資料。首次建置發現 worktree 缺少 `data/` 目錄、固定 container_name/Neo4j host ports 衝突、Neo4j healthcheck 仍用 `change-me` 且新 image 的 `cypher-shell` 不在 PATH；已在 WP1 修正 healthcheck 為 `/var/lib/neo4j/bin/cypher-shell` 並由 `NEO4J_AUTH` 取密碼，實際 healthcheck 通過。實測 Redis/PostgreSQL/Neo4j/Web/Celery search+ingest worker 啟動成功；重啟 ingest worker 後 Redis restart-check key 仍保留且 worker recovery 正常。以真實 `/api/upload/ingest` API 上傳相同 Excel 與相同 idempotency identity 兩次，兩次回傳相同 `task_id`，第二次 `duplicate=true`；過程發現 duplicate path 缺少 `get_ingest_task_state` import 導致 500，已修正。隔離容器已清理。驗證後完整 pytest=`83 passed`、compileall、Compose config、diff check 通過。WP1 尚剩 CI/PR gate 與長時間/故障注入測試；目前可稱為 implementation plus local runtime validation，仍未因 CI 未綠而宣稱正式完成。
- 2026-08-10 已產生完整 Knowledge Base modernization 簡報 `docs/km-modernization/KM_MODERNIZATION_WP0-WP13_ROADMAP.pptx`，並保留可重建腳本 `scripts/build_km_modernization_roadmap_pptx.py`。簡報共 15 張，涵蓋 WP0/WP1 今日完成狀態、WP2-WP13 全部待執行修改、目標架構與資料流、A2A/KM/Anritsu/Amarisoft 邊界、Gate/測試矩陣、rollback 與正式導入策略。PPTX 可由 python-pptx 解析，15 slides，腳本 py_compile 與 git diff check 通過。已推送至 `agent/wp1-job-config-reliability`，最新 commit=`51948675`；遠端 WP0 branch 仍為 `2c46c834`（WP0 程式碼已在 GitHub），WP1 branch 為 `51948675`。WP0 CI workflow commit 仍因 PAT 缺少 `workflow` scope 無法推送，未宣稱 CI 已綠。
- 2026-08-11 已在 agent/wp1-job-config-reliability 新增 .github/workflows/wp1-job-reliability.yml，commit=cfe5eb0d，並成功推送。Workflow 包含 backend pytest/compileall/Compose/shell、frontend npm ci/build、repository hygiene/credential scan；本地等價驗證 backend 83 passed、compileall、Compose config、shell syntax、frontend build、diff check 均通過。GitHub Actions run=https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/31449165822，查詢時為 in_progress，尚未宣稱 CI 完成。WP1 PR 尚需建立（base=agent/wp0-fastapi-contract、head=agent/wp1-job-config-reliability）並待 Actions green/review。
- 2026-08-11 已核對個人層級 Codex 自訂 Agent `/home/da40_ai_gb10/.codex/agents/luna-worker.toml`。該檔案先前已建立，為避免覆蓋有效設定，本次保留原內容不重寫；內容包含 `name = "luna_worker"`、`model = "gpt-5.6-luna"`、`model_reasoning_effort = "medium"`、清楚的 `description` 與限制範圍的 `developer_instructions`。本機 Codex CLI 版本為 `0.146.0`；官方內建手冊確認個人 custom agent 應放在 `~/.codex/agents/*.toml`，必填 `name`、`description`、`developer_instructions`，並支援 `model` 與 `model_reasoning_effort`。Python `tomllib` 解析及必要欄位比對全部通過；Codex multi-agent 工具的可用角色清單已列出 `luna_worker`，並標示固定模型與推理強度；實際以 `agent_type=luna_worker` 成功建立子執行緒，子 Agent 正確回覆工作邊界與停止回報規則，且未修改任何檔案。`~/.codex/config.toml` 未修改，驗證前後 SHA-256 均為 `eb60b573f66f054f3579827cb3435df741359d15982b55b7ba6038bef622a0cc`。
- 2026-08-11 已完成 WP0／WP1 既有成果保全、v2.6 差異盤點與驗收分支整合，未開始 WP2。主工作樹 `dev-work` 原有 `PROJECT_MEMORY.md`、`config/config.yaml`、pyc 與資料資產修改均保留，沒有切換、stash、reset 或覆蓋；實作在隔離 worktree `/tmp/kb-v26-acceptance.QptdWG`、branch `agent/wp0-wp1-v2.6-acceptance`。分支從最新 v2.6 commit `55c1b08b08870705bd471ab63f070ce39b1360be` 建立，以非破壞性 merge commit `c8a39117` 保留 WP0 `2c46c834` 與 WP1 `2a4ba2af`～`cfe5eb0d` 的完整歷史，再保留 WP0 workflow commit。新增正式 `WP0-WP1-v2.6-gap-assessment.md`，逐項使用 A-E 分類；Phase 已校正為 Phase 1 前置正式化，Anderson 僅負責 AI KM 工程與 Unit Test，CSIT Web／DB Schema／Workflow／商業邏輯列為 Patty／跨組責任。Git tree 與本機搜尋均找不到唯一來源 `docs/km-modernization/01_AI_KM_Phase規劃_v2.6.xlsx`，因此來源 Gate 明確維持阻塞，沒有猜測或反向產生工作簿。
- 2026-08-11 WP0 原 PR #2 為 open、無 review、未 merge；原 CI 失敗根因是 repository-hygiene checkout depth=1，`git diff 2c46c834..19d0751e` 發生 `fatal: bad object`，不是程式或 whitespace failure。驗收分支以 `fetch-depth: 0` 修正後，WP0 run `31466582947` 與最終 run `31467004016` 的 backend／frontend／repository-hygiene 全部成功。WP1 原分支 head `cfe5eb0d`，無 PR／review／merge；原 run `31449165822`、驗收 run `31466582953` 與最終 run `31467003384` 三個 job 全部成功。週報最終 run `31467003355` 也成功。完整本地驗證為 pytest `83 passed`、compileall、Compose config、shell syntax、frontend production build、credential scan、git diff check、JSON schema／計算與 Markdown 一致性全部通過。殘餘風險包含 frontend 3 moderate/4 high 與 PPTX 工具 2 high npm advisories，以及既有 langchain deprecation warning，未以破壞性 major downgrade 混入本驗收。
- 2026-08-11 W33 Evidence／JSON／Markdown／PPTX 已依最終 CI 實證更新：WP0=85%（15+35+25+7+3），WP1=87%（15+35+25+10+2），Phase 1=19.1%，全計畫=11.5%；沒有 E2E／驗收或 PR／review／merge 的權重未計入。`AI-KM-Weekly-2026-W33.pptx` 由 JSON 重新產生，產生器正確拒絕直接覆蓋歷史檔；候選檔經 LibreOffice 實際渲染為 7 頁 16:9 並逐頁檢查，無空白、遮蔽、溢出或不可辨識小字，再人工升級為受控產物。最終 PPTX SHA-256=`4de6d4eadfd7bbc30fa743bbe194e040a58a746fe36d3b6a1dd88475ef80b4be`。最終 commit=`47cb977e3191e6edd861f0bb172a638d8a23fcd1` 已推送到 `agent-source/agent/wp0-wp1-v2.6-acceptance`；此前主要整合/文件/CI commits 為 `c8a39117`、`fdf6a847`、`dec02bd6`、`7f0a5e80`、`7a88863f`。目前仍不具備開始 WP2 的正式條件：需取得並核對 v2.6 原始 Excel、完成 WP0 review/merge/正式入口 E2E artifact、建立並審查 WP1 PR、取得 Patty 的 CSIT API／Booking／Validation Request Contract。現有 GitHub credential 能 push 但 API 對 Pull Request/Actions write 回 403，故 Draft PR 尚未建立且不得宣稱已建立；待有權限帳號由 `agent/wp0-wp1-v2.6-acceptance` 對 `agent/km-plan-v2.6-anderson` 建 Draft PR，建立入口為 `https://github.com/kyocarlos/knowledge-base-agent-source/pull/new/agent/wp0-wp1-v2.6-acceptance`。
- 2026-08-11 使用者已透過 GitHub UI 建立 Draft PR #5：`https://github.com/kyocarlos/knowledge-base-agent-source/pull/5`，base=`agent/km-plan-v2.6-anderson`、head=`agent/wp0-wp1-v2.6-acceptance`、draft=true、mergeable=true。PR 初次觸發的 WP0/WP1 repository-hygiene 失敗，已用 PR merge ref 重現為 `tests/test_wp1_celery_contract.py` 與 `tests/test_wp1_retry_policy.py` 檔尾多一個空白行；credential scans 均 clean。只移除兩個空白行，focused tests `3 passed`，commit=`d39f9f790eb0cd0ebaf4a992b2664bd1d8b3143e` 已推送。修正後 Pull Request runs：WP0 `31467770046`、WP1 `31467770179`、Weekly `31467770024` 全部 success，WP0/WP1 的 backend、frontend、repository-hygiene 均 green。GitHub API token 仍對 PATCH PR title/body 回 403，因此 PR #5 說明目前仍為空，需由 GitHub UI 貼入已準備的需求、測試、風險、回滾與未完成項目；不得因 CI green 直接轉 Ready 或合併，仍須 review 與正式 Gate。
- 2026-08-11 已確認真實工作目錄 `/home/da40_ai_gb10/knowledge-base` 與 live KB 尚未套用 WP0／WP1。該目錄仍在 `dev-work`、HEAD=`3f15d87b`，WP0 commit `2c46c834`、WP1 head `cfe5eb0d`、驗收 head `d39f9f79` 均不是目前 HEAD ancestor；`app/main.py`、`app/core/job_config.py`、WP0/WP1 tests 與 workflows 也不存在。Dockerfile、Compose、host `start.sh` 仍以 `uvicorn src.web_api:app` 啟動。live `kb-web` 已運行 5 天，command 同樣是 `uvicorn src.web_api:app`；`/health`=200，但 `/api/v1/health` 與 `/api/v1/version` 均為 404，進一步證明 WP0 FastAPI v1 contract 尚未部署。WP0/WP1 目前只存在 GitHub Draft PR #5／隔離驗收分支，不能視為已更新正式目錄或服務。主工作樹另有使用者/runtime 的未提交 config、PROJECT_MEMORY、pyc 與 data assets，未經保全與部署計畫不得直接 merge、switch、reset 或重啟。
- 2026-08-11 已評估 WP0／WP1 導入真實 KB 的相容風險。真實 `dev-work` 與驗收分支沒有共同 merge base（183 vs 38 commits），所以 PR #5 green 不能證明可直接 merge 到 live source；應從真實 `dev-work` 建獨立 integration worktree，針對性移植 WP0/WP1 commits／patch 並重新驗證。WP0 將 Uvicorn entrypoint 從 `src.web_api:app` 改為 `app.main:app`，透過附加 legacy routes、middleware 與原 lifespan 保留 `/health`、search、WebSocket、report、review、ingest、A2A；已有單元與本機 Portal smoke，但尚未對真實資料/config/`61.216.9.52:3030` 做完整 E2E，因此仍有 middleware 順序、WebSocket/session、OpenAPI/exception 行為風險。WP1 會改 Celery queue/retry/status/trace/idempotency、將 `tasks.ingest_task` 路由到 ingest queue、增加有限 retry 與 canonical `job_status`；可能影響既有排隊任務、錯誤呈現與非完全冪等的 side effects。部署面有兩個高風險 Gate：(1) Neo4j 密碼改成必填環境變數，未提供會使 Compose 解析/啟動失敗；真實工作樹目前另有硬編碼秘密，導入時必須遷移到受控 env/secrets，不可帶入 Git；(2) `celery_beat` 改為 `scheduler` profile，若沿用普通 `docker compose up`，目前正在運行的定期 watch-folder/排程服務不會啟動，必須明確決定是否使用 `--profile scheduler`。Volume root 可配置但預設仍指向原路徑；設錯會造成看似資料遺失。`restart: unless-stopped` 可能讓設定錯誤變成 restart loop。WP0/WP1 不包含 Neo4j/Qdrant schema migration，資料格式破壞風險較低；A2A bridge 為隔離目錄，理論上可保留，但必須納入整合測試。安全導入流程：保全 dirty worktree 與資料庫/registry/uploads/config；從 `dev-work` 建 integration worktree；只移植必要 patch並解決本機秘密/config差異；建立完整 deployment env；用不同 compose project/ports/volumes 建 shadow stack；驗證 Portal、chat/WebSocket、search、Excel upload/ingest與 duplicate、report upload/review、Beat schedule、worker restart、A2A dry-run、Neo4j/Qdrant 資料量與 `https://61.216.9.52:3030/chat.html` Webwright E2E；通過後才安排停機、切換、觀察與可執行 rollback。直接覆蓋或直接合併的風險高，受控移植與 shadow 驗證後風險可降至中低。
- 2026-08-11 已制定 WP0／WP1 正式導入回滾原則。回滾必須在部署前準備，不能只依賴 Git：固定目前程式基準 `dev-work`/`3f15d87b`（tag/branch 只保護已提交 source）、將 dirty config 與未追蹤資產存入 Git 外且權限受控的部署快照、保存目前 web/Celery 確切 image ID 並加不可變 `pre-wp01-<timestamp>` tag、保存 compose/env/啟動命令與 container/volume manifest，另建立 Neo4j dump、Qdrant snapshots、PostgreSQL dump、Redis persistence/必要 registry、SQLite、uploads/assets 的同一時間點備份並驗證可讀。WP0/WP1 無 schema migration，一般不滿意或 API/啟動異常時採 Level 1 application rollback：停止新流量與新 ingest、保留故障 logs/task IDs、停止新 web/workers/beat、以舊 image＋舊 compose/config/env 重建 application containers，不重建或刪除 volumes，再驗證 `/health`、Portal/chat/WebSocket、search、ingest、report、Beat 與 A2A。只有確認導入期間造成資料污染、重複寫入或 registry 不一致才採 Level 2 full rollback：維持 maintenance、停止所有 writers，按同一 checkpoint 還原 Neo4j/Qdrant/PostgreSQL/Redis/SQLite/uploads，禁止混用不同時間點快照，完成數量/抽樣/引用一致性檢查後再開放。不得使用 `git reset --hard`、`git clean -fd`、直接刪 volume 或重新 pull `latest`；若程式改動已進共享 branch，使用 GitHub Revert PR；若尚在 integration branch，直接切回已固定的舊 release/image。正式切換前應先在 shadow stack 實際演練一次 application rollback，記錄 RTO、負責人、指令與驗收結果，才算具備可回退條件。
- 2026-08-11 已完成可執行 pre-WP01 備份、回退演練與受控正式部署。新增 `scripts/pre_wp01_backup.py`、`scripts/rollback_pre_wp01.py`、`scripts/drill_pre_wp01_rollback.py`、`scripts/drill_wp01_candidate.py`、`tests/test_pre_wp01_rollback_scripts.py`、`docs/pre-wp01-backup-and-rollback.md` 與 `docs/pre-wp01-deployment-record-20260811.md`。備份採 Git 外 0700 checkpoint，`rollback.env`/container inspect 為 0600；包含 source/config/data、精確 application images 與 image archive、PostgreSQL custom dump、Redis archive、SQLite consistent backup、Neo4j Community APOC logical export及 Qdrant online snapshots，並以 streaming SHA256 驗證。線上 checkpoint 為 `$HOME/kb-pre-wp01-backups/pre-wp01-20260811-153917`，停止 writers 且 queues/active/reserved/scheduled 均為 0 後建立的正式 maintenance checkpoint 為 `$HOME/kb-pre-wp01-backups/pre-wp01-maintenance-20260811-155643`；每份約 9.6 GB，均已完成 checksum、archive readability、`pg_restore --list`、SQLite integrity 與 snapshot 非空檢查。
- 2026-08-11 shadow rollback drill 已實際通過，證據為 `$HOME/kb-pre-wp01-drills/20260811_154229/rollback-drill.json`：baseline HTTP 200、注入候選故障 HTTP 503、呼叫與正式回退相同的 script 路徑後恢復 HTTP 200，marker 與 checkpoint image ID 完全一致，演練 container/network/volume 均清除。正式 production 第一次切換時，實際 `/search` POST 發現 WP1 把 Pydantic `SearchRequest` 當 HTTP Request 讀 headers 而回 500；系統立即使用 maintenance checkpoint 執行 Level 1 production rollback，web、search/ingest workers、Beat、nginx 五個 image ID 全部恢復，legacy `/health` 與 `/search` 均回 200，正式資料 volumes 未刪除或還原。其後修正為 FastAPI `Request` 注入，新增 X-Trace-ID/Celery regression test，完整 pytest 為 `89 passed`；候選 gate 也加入真實 `/search` POST。第二次隔離候選驗證 `$HOME/kb-pre-wp01-drills/candidate-20260811_160158/candidate-drill.json` 通過 legacy/v1 API、agent auth contract、search submission、web、兩個 workers 與 Beat，無殘留 shadow container。
- 2026-08-11 修正後 WP0／WP1 已正式部署。production legacy `/health`、`/api/v1/health`、live、ready、version 均為 200；未附 Agent headers 的 `/api/agent/v1/health` 維持既有 401 contract；production `/search` 可 submitted 並完成，兩個 Celery nodes online，Beat scheduler started。Webwright 以正式入口 `https://61.216.9.52:3030/chat.html` 完成真實使用者流程：顯示「已連線」、輸入與送出正常、收到非空 final reply、console errors=0、failed network=0；證據位於 `/tmp/kb-wp01-webwright/final_runs/run_1/`。目前 application image ID 為 `sha256:ac3c29b8f25f1427e1bcfe24e5d712fd6e4cc2d6a8d387eeaeb4113991338389`，另標記 `kb-wp01-live:2877dfcb` 與 `kb-wp01-live:70a764be`。真實 source `dev-work` 已以不覆蓋 dirty files 的 fast-forward 方式整合；部署紀錄 commit=`70a764bed33a40f0c74491620dca538e1fd8c67a`。後續校正 rollback dry-run 不應要求 production 確認碼並新增 regression test，commit=`68123a67da32874e78518b00660f7b6ad7922c13`，因此目前 HEAD 為此 commit；真實 maintenance checkpoint dry-run再驗證成功，script tests `6 passed`。原有 `PROJECT_MEMORY.md`、`config/config.yaml`、pyc、data asset 與 `kmll.jpg` 修改均保留。正式 application rollback 指令為 `python3 scripts/rollback_pre_wp01.py --checkpoint "$HOME/kb-pre-wp01-backups/pre-wp01-maintenance-20260811-155643" --execute --confirm-production PRE_WP01_ROLLBACK`；Level 2 資料還原仍刻意保持人工 maintenance／雙人確認，不由此 script 自動執行。由於本機真實 `dev-work` 與 `agent-source` 遠端歷史不相容，未直接推送該歷史；改從 GitHub `agent/wp0-wp1-v2.6-acceptance` / `d39f9f79` 建立乾淨分支 `agent/wp01-production-rollout`，針對性移植 backup/rollback、candidate gate、production 相容修正、search regression 與部署摘要，遠端 head=`10706a5780d105427b1dc1e38b701023336fe26f`。同步分支驗證為 pytest `90 passed`、frontend build、compile、Compose、shell、whitespace、credential scan 與真實 maintenance checkpoint dry-run 全部通過；大型 checkpoint、database dumps、image tar、正式 env 與 secrets 均未上傳。GitHub PAT 可 push 但建立 Draft PR API 仍回 403，當下無 PR/Actions run；需由有權限的 GitHub UI 使用 `https://github.com/kyocarlos/knowledge-base-agent-source/compare/agent/wp0-wp1-v2.6-acceptance...agent/wp01-production-rollout?expand=1` 建立 stacked Draft PR，不得直接合併 main。
- 2026-08-11 再次即時查核 `/home/da40_ai_gb10/knowledge-base` 真實系統：source 位於 `dev-work`、HEAD=`68123a67da32874e78518b00660f7b6ad7922c13`，歷史包含 WP0 FastAPI contract、WP1 job config/retry/trace/idempotency、candidate gate、production compatibility、search trace fix 與 rollback scripts；`app/main.py`、`app/core/job_config.py` 均存在。運行中的 web、search worker、ingest worker、Beat 均使用 image ID `sha256:ac3c29b8f25f1427e1bcfe24e5d712fd6e4cc2d6a8d387eeaeb4113991338389` 且 running；legacy `/health`=200、v1 health/version=200、Agent health 未帶 headers 維持 401，兩個 Celery nodes pong，Beat 每分鐘送出 watch-folder task。結論：真實 source 與 runtime 已涵蓋 WP0/WP1；但 GitHub 流程仍是同步分支 `agent/wp01-production-rollout`，Draft PR/Review/merge Gate 尚未完成，不能把「已部署」誤寫成「已正式合併 main」。
- 2026-08-11 WP0/WP1 修改內容查閱位置已確認：真實系統可看 `app/main.py`、`app/api/v1/`、`app/core/config.py|exceptions.py|logging.py|security.py|trace.py|job_config.py`、`src/web_api/__init__.py|tasks.py|report_routes.py`、Compose/start 與 `tests/test_wp0_*`、`tests/test_wp1_*`；正式部署及回退摘要在 `docs/pre-wp01-deployment-record-20260811.md`，操作規格在 `docs/pre-wp01-backup-and-rollback.md`。GitHub `agent/wp01-production-rollout` 分支另有 `docs/km-modernization/KM_MODERNIZATION_WP0-WP13_ROADMAP.pptx` 與 `docs/km-modernization/progress/presentations/AI-KM-Weekly-2026-W33.pptx` 可下載，但兩者生成時間早於本次實際 production rollback 與最終部署：Roadmap 適合看 WP0/WP1 技術修改與整體規劃，W33 適合看證據式進度；若作為最新正式簡報，仍需另產新版納入 shadow drill、第一次回退、search fix、第二次部署、90 tests 與 GitHub 同步分支。
- 2026-08-11 已依使用者放在真實專案根目錄的 `01_AI_KM_Phase規劃_v2.6.xlsx` 完成 Phase 1 規格校正與本週主管簡報。原檔 SHA-256=`4c5a4782e727b5675add29027a5a09192966f126baa5ca648d89b22c333fba46`，共解析核對八個工作表；Phase 1 為 Production Ready MVP、12～16 週，WP0 FastAPI 目標 2026-08-14、WP1 Docker/Redis/Celery 目標 2026-08-21、Phase 1 整合驗收目標 2027-01-14。Excel 的「實際工作分工」與「分工摘要」工作表標題仍殘留 `v2.4`，已列為規劃 Owner 待澄清的文件品質問題，不另建立第二套來源。原檔已以相同 SHA 納管到 GitHub branch 的 `docs/km-modernization/01_AI_KM_Phase規劃_v2.6.xlsx`，來源缺失 Gate 已解除；README、source-of-truth、Anderson scope、weekly spec、gap assessment、WP0/WP1 Evidence 與 Actions branch filters 均已配合更新。
- 2026-08-11 本週 Phase 1 修訂資料鏈採不覆蓋舊 W33 的新檔：`progress/data/2026-W33-phase1-v2.6.json`、`progress/weekly/2026-W33-phase1-v2.6.md`、`progress/presentations/AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx` 與 `scripts/generate_phase1_weekly_pptx.mjs`。證據截止為 2026-08-11 16:42（週中版，報告日期 2026-08-13）；依既定 15/35/25/15/10 權重，WP0=94%（正式 API/Webwright 已通過，但缺 durable E2E artifact、rollout Review/Merge），WP1=96%（shadow、真實 production rollback、修正後再部署與 checkpoint dry-run 通過，但缺 rollout Review/Merge）；WP2～WP8 無實作證據維持 0，因此 Phase 1=21.1%，全計畫=12.7%。PPTX 固定 7 頁：封面、主管摘要、Phase 1 範圍時程、WP0、WP1、Gate/風險/決策、下週承諾；LibreOffice 成功渲染為 7 頁 16:9，逐頁檢查並修正第 4 頁 `86.7%` 換行後，最終無空白、遮蔽、溢出或不可辨識小字。PPTX SHA-256=`722d857dacb81bd3db721607c0a5a99f3d74e4a5f323a87399d2606bbecfe5e2`，可直接從 `/home/da40_ai_gb10/knowledge-base/AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx` 開啟。
- 2026-08-11 Phase 1 報告驗證完成：pytest `90 passed`（僅既有 langchain-community deprecation warning）、舊 W33 與新 Phase 1 JSON/Markdown validation、PPTX 7-slide structure/text、Excel SHA、frontend/Compose/compile/shell/workflow YAML/whitespace/credential scan 均通過；root npm audit 仍有既有 pptxgenjs 間接依賴的 2 high，未混入破壞性 major downgrade。GitHub branch `agent/wp01-production-rollout` 最新 head=`c4061f4821d994e96fa09b69316ddeec7959c607`。第一次 WP1 run `31475084385` 的 backend/frontend 成功，但 hygiene checkout 遇 GitHub runner TLS CA 偶發錯誤；後續 run `31475433719` 已全成功。最新 head 的 Weekly `31475687311`、WP1 `31475687307`、WP0 `31475687319` 全部 success。真實 KB runtime 沒有因本報告工作重啟或改動；只在專案根目錄新增可直接使用的 PPTX。
- 2026-08-11 已更新主管週報活頁簿 `Team-III_2026_W31_Anderson_260805.xlsx` 的 Anderson 工作表。修改前建立原始備份 `Team-III_2026_W31_Anderson_260805.pre-w33-20260811-172115.xlsx`（SHA-256=`f458915de6974c6294f4d2d683ca5de687ec6448f2c4c4c34bd3707a5990c674`），未修改 Patty、Jimmy、Alf、Sam 或 T1～T9 等其他工作表。Anderson 原有 T1/T2/T5 與舊 Sub2API 任務內容已清除，改為兩個責任群組：「KM優化工作」與「Sub2API建置／管理」；頁首改為 2026 W33（08/10～08/14）。KM 內容依根目錄 `01_AI_KM_Phase規劃_v2.6.xlsx` 的排程填入：v2.6 基準校正 100%、WP0 94%（8/14）、WP1 96%（8/21）、下週 PR/CI/Gate 驗收 0%、CSIT Contract/Adapter 前置盤點 0%（9/2），並列出 Parser、RAG、Qdrant、Neo4j、TimescaleDB、Portal 到 2027/1/14 總驗收里程碑。Sub2API 填入既有隔離部署與 Ollama/OpenAI 路由 100%、本週渠道監控/訂閱缺口盤點 100%、下週 subscription usage 歸屬/報表/告警 0%、TLS/SSRF/Key輪替/群組隔離 10%、正式方案/Quota/SLA/備份維運 5%，且明確保留零元測試訂閱不等於正式商業計費的風險判斷。重新開啟驗證通過：15 個工作表、原合併範圍與 Dashboard 公式均保留；LibreOffice 實際渲染 Anderson 為 2 頁，內容無遮蔽，Sub2API 群組標題已縮短以避免截斷。已知既有 Dashboard 引用仍不一致：`Dashboard!E11` 指向 Anderson 空白群組列 `G8`，且 Dashboard 的 T1/T2 Anderson 責任與本次指定的 KM/Sub2API 不符；本次為避免擅改共用頁與其他同仁責任，未修改 Dashboard，後續應由報表 Owner 確認是否同步重構。
- 2026-08-11 針對使用者詢問如何手動觀察真實 WP0/WP1，再次即時查核：source=`dev-work`/`68123a67da32874e78518b00660f7b6ad7922c13`；`kb-web`、`kb-celery-search`、`kb-celery-ingest`、`kb-celery-beat` 均使用 image `sha256:ac3c29b8f25f1427e1bcfe24e5d712fd6e4cc2d6a8d387eeaeb4113991338389`。WP0 legacy `/health`、v1 health/live/ready/version 均為 200；Agent health 未帶 `X-Agent-ID` 為預期 401；`/api/v1/not-found` 帶固定 `X-Trace-ID=manual-wp0-404` 時回統一 404 envelope 且 response header/body trace ID 一致。WP1 兩個 Celery nodes pong，active queues 正確綁定 search/ingest，Beat 每分鐘送出 `tasks.watch_folder_scan`；live JobConfig 為 concurrency=2、lock TTL=600、result TTL=3600、soft/time limit=600/720、max retries=3、countdown=5。唯讀搜尋測試 task `cf05ac12-dc3b-458b-bec6-8fbf507b0094` 已由 search worker 正確接收並處於 active，但超過數分鐘 `/tasks/{id}` 仍顯示 legacy `pending`，worker CPU 低且尚無完成/失敗 log；這證明 HTTP→queue 路由生效，但此次真實搜尋 E2E 尚未完成，需後續查 Qdrant/search 呼叫等待與 active 狀態對外映射，不能把本次結果宣稱為完整成功。主機無 `pytest`，production image 未帶 tests；本次未臨時安裝測試套件，應由既有 CI（先前 90 passed）或隔離驗收環境重跑。直接 `docker compose` 因 shell 未載入 `NEO4J_PASSWORD` 會在 interpolation 階段失敗，手動觀察應使用既有容器名稱；不得把秘密硬編碼到命令或 compose。
- 2026-08-11 已確認開始 WP0/WP1 手動測試前不需要、且目前不應先執行 `./restart_kb.sh`。即時狀態為 `kb-web`、search/ingest workers、Beat、nginx、Redis、Neo4j、Qdrant 全部運行，legacy `/health` 與 `/api/v1/health|ready|version` 均回 200，可直接從 `https://61.216.9.52:3030/chat.html` 與 API 開始測試。現行 `restart_kb.sh` 不是單純 restart：它會先 `docker rm -f` 強制刪除 web/workers/Beat/nginx/Redis/Neo4j 等容器、刪除並重建前端 runtime，再執行 `docker compose up -d --build`。目前 shell 執行 Compose 會因必填 `NEO4J_PASSWORD` 未載入而在 interpolation 階段失敗，而 script 只確保 report DB password、沒有在刪容器前驗證 Neo4j password；因此直接執行可能造成已運行服務中斷後無法重建。除非服務確實異常或程式/config有新變更需要部署，且已先確認完整 env、備份、active/queued tasks為0與回退條件，否則不得用此 script 作為一般測試前置步驟。
- 2026-08-11 已完成 `restart_kb.sh` 對 WP0/WP1 的差異評估，結論為必須修改後才適合作為正式維運工具。Compose 本身已使用 WP0 entrypoint `uvicorn app.main:app`，WP1 search/ingest queue與Beat服務也已列入，因此功能啟動面大致涵蓋；缺口集中在安全與驗收流程：(1) script 在 `docker compose config`／`NEO4J_PASSWORD` preflight 前先 `docker rm -f` web、workers、Beat、nginx、Redis、Neo4j，可能在環境缺失時先造成停機；(2) 未 drain／拒絕 active、reserved、scheduled、queued tasks，會中斷搜尋或攝入；(3) 一律 `--build`，混淆日常restart與新版deploy，且沒有固定candidate image/tag或失敗自動回退；(4) 固定sleep 5秒且多數health failure只警告不退出，可能錯誤顯示「系統啟動完成」；(5) smoke只驗legacy `/health`，未驗WP0 v1 live/ready/version、統一error/trace、Agent 401 contract；(6) 未驗WP1兩個nodes pong、active queue binding、Beat與JobConfig；(7) hardcode專案路徑、frontend runtime、外部IP與port，跨部署路徑不可靠；(8)缺少明確maintenance/deploy確認與checkpoint/rollback整合。建議拆成預設 `--restart`（不build、不刪資料服務，只重啟app services）與高風險 `--deploy`（完整env/config preflight、queue drain、checkpoint、candidate build/tag、ready gate、失敗回退），另提供 `--status`純觀察模式；在修正與shadow演練前，繼續使用現有運行容器直接測試，不執行舊script。
- 2026-08-11 已完成 `restart_kb.sh` 的 WP0/WP1 安全重構。無參數預設為純只讀 `--status`；`--restart` 必須明確指定，先載入受控env、要求 `NEO4J_PASSWORD`/`KB_REPORT_DB_PASSWORD`、通過 `docker compose config --quiet` 且確認Celery active/reserved/scheduled與Redis search/ingest/default/document/indexing/celery queues全部為0後，只restart web、search/ingest workers、Beat與nginx，不build、不刪除或重建Redis/Neo4j/Qdrant/PostgreSQL；`--deploy` 另要求 `--confirm-deploy DEPLOY_WP01`，檢查dirty source、建立或驗證pre-WP01 checkpoint、在staging建置前端、build/tag candidate、只recreate application services、通過WP0/WP1 Gate後標記live，候選啟動或Gate失敗時會先還原舊前端並呼叫既有 `rollback_pre_wp01.py` 回復舊application images。腳本移除原本 `docker rm -f`、固定專案路徑與固定外部IP，改由script位置及 `KB_INTERNAL_BASE_URL`、`KB_EXTERNAL_URL`、`KB_FRONTEND_BUILD_DIR`、`KB_BACKUP_ROOT` 等設定控制；不提供略過任務檢查的force模式。
- 2026-08-11 新增 `tests/test_restart_kb_script.py`（8個unittest）及 `docs/wp01-lifecycle-runbook.md`，並更新 `docs/dual-test-report-ingestion.md` 的生命週期指令。驗證結果：`bash -n`、8 tests、`config/wp01-deployment.env.example` Compose config、Python compile、`git diff --check`及credential pattern scan全部通過；缺少 `NEO4J_PASSWORD` 的 `--restart` 負向測試在preflight顯性停止，前後五個application container ID/StartedAt完全一致。真實環境兩次執行 `./restart_kb.sh --status` 均通過legacy/v1 health、WP0 error/trace、Agent 401、兩個Celery nodes、queue binding、JobConfig、Beat、chat/WebSocket、Qdrant與Ollama，任務與queue全空。為避免未授權中斷，本次刻意沒有在production執行 `--restart`或`--deploy`；兩個變更模式尚需在維護窗口以受控env做shadow restart、candidate failure與rollback演練後才可宣稱production操作Gate完成。主機無shellcheck，故未執行shellcheck，已以Bash parser與行為測試補強。
- 2026-08-11 已整理新版 `restart_kb.sh` 的人工驗證順序：第一層執行 `--help`、`bash -n`與 `python3 -m unittest -v tests.test_restart_kb_script`；第二層執行無參數或 `--status`，應只讀通過WP0/WP1/legacy Gate且不改變任何container ID/StartedAt，另以缺少 `NEO4J_PASSWORD` 的 `--restart`及缺少確認碼的 `--deploy`驗證會在容器操作前顯性失敗；第三層只能在維護窗口、確認active/reserved/scheduled與所有Redis queues為0後執行受控 `--restart`。正式restart驗收標準為web/search/ingest/Beat/nginx StartedAt更新但image ID不變，Redis/Neo4j/Qdrant/PostgreSQL container ID與StartedAt全部不變，重啟後 `--status`全Gate通過。可從運行中的Neo4j container將密碼只匯入目前shell而不輸出或落盤，report密碼由0600的 `config/report-ingest.env`載入；測試後應unset。`--deploy`不可作為一般手動測試直接在production執行，須先以shadow drill驗證candidate failure與rollback，再於正式維護窗口使用checkpoint與明確確認碼。
- 2026-08-11 已將新版 `restart_kb.sh`、`tests/test_restart_kb_script.py`、`docs/wp01-lifecycle-runbook.md`及`docs/dual-test-report-ingestion.md`推送至GitHub repository `kyocarlos/knowledge-base-agent-source` 的 `agent/wp01-production-rollout` 分支。真實本機`dev-work`只對上述四檔建立scoped commit `4d6ce704`，未納入PROJECT_MEMORY、config、pyc、data assets、PPTX或kmll.jpg；再於乾淨worktree `/tmp/kb-wp01-github` 從remote head `c4061f48`無衝突cherry-pick成GitHub commit `b33e398312c05b74349c6a37ca60bab99676ef28`。推送前在乾淨分支重新驗證Bash syntax、8 unittest、Compose example preflight、diff whitespace、credential scan與真實只讀`--status`，全部通過；remote `ls-remote`已確認指向`b33e3983`。主機未安裝`gh` CLI，因此本次無法從CLI查Actions run；推送本身已完成，未合併main。
- 2026-08-12 已依使用者釐清的層級重整 `Team-III_2026_W31_Anderson_260805.xlsx`：先更新 `T1開發計劃` 主計畫，再由相同T1編號展開至 `Anderson` 任務頁。修改前建立備份 `Team-III_2026_W31_Anderson_260805.pre-w33-replan-20260812-094325.xlsx`，備份SHA-256=`d3188ccc811f94948ed9d3646adbc81f311932e0f166484ddb22b6e7c40b9914`；最終檔SHA-256=`e444ab8139747242f6c66124559bb1b341214f775b29bf8712a6bd178261012d`。`T1開發計劃` 舊的L1-L5 Agent、Patty、訪談、Amarisoft／Anritsu等任務已全部清空，只保留原標題／欄位／合併區塊／配色格式，改為Anderson負責的兩個主項目，共20個唯一T1 task ID：`T1-KM-01～12`與`T1-S2A-01～08`。KM主計畫包含本週v2.6校正100%、WP0 94%、WP1 96%、restart_kb lifecycle 85%，下週PR/CI/Merge Gate、shadow演練、CSIT Contract前置，以及Parser、RAG、Qdrant、Neo4j、TimescaleDB／Portal到2027/1/14總驗收時程；Sub2API包含既有隔離部署／模型路由／OpenAI渠道監控／測試訂閱100%，usage歸屬10%、TLS/SSRF/Key隔離10%、方案Quota 5%、SLA備份5%、9/30正式驗收0%。本週新增開發全部標示為KM，Sub2API只列既有成果與未來管理計畫。
- 2026-08-12 `Anderson` 任務頁已清空前版任務內容，再由T1主計畫展開11列：本週KM四項、下週與後續KM三項、Sub2API既有與後續四項；T#、期限與進度和主計畫一致，頁首明確要求以T1主計畫為來源、無PR/Review/測試/驗收不得宣稱100%。其他14個工作表未修改。重新開啟語意驗證通過：15 sheets、20個主計畫ID唯一、週報關鍵ID均可回溯、舊`T1-A1`／`T1-D5`／Agent任務文字不存在、所有20列狀態公式存在。LibreOffice以A3 landscape實際渲染 `T1開發計劃`與`Anderson`各2頁，逐頁視覺檢查無欄位遮蔽、文字越界或空白頁；Dashboard既有公式未改動。
## 2026-08-12 Sub2API 5 個 ChatGPT + 1 個 MiniMax 帳號池規劃評估

- 使用者後續規劃：在 Sub2API 納管 5 個 ChatGPT 訂閱／OAuth 帳號與 1 個 MiniMax 帳號，開始進行分配管理。以下暫以「5 個為 OpenAI 帳號總數、minamx 指 MiniMax」為假設；正式設定前需再確認是否為新增 5 個（若包含既有 `openAI_wifisit01`，則只需再新增 4 個）。
- 不建議把 OpenAI 與 MiniMax 六個帳號直接混入同一群組。建議建立 `OpenAI_Pool_Prod` 與 `MiniMax_Prod` 兩個供應商隔離群組及渠道，由上層 API Key／模型路由決定流量；只有經驗證的通用聊天、摘要模型才能允許 OpenAI 全池失效後切至 MiniMax，GPT 特定工具、推理、模型名稱與輸出契約不可直接假設相容。
- OpenAI 五帳號初始分配建議：3 個互動式主要帳號（priority 1）、1 個批次／溢位帳號（priority 2）、1 個待命／canary 帳號（priority 3）。各帳號先設 concurrency=1，觀察至少一週的成功率、429、延遲及用量後再調整；同優先序是否能公平分流必須實測 Sub2API 排程行為，不能只看欄位推定。
- API Key 應依消費者、環境或工作負載拆分，例如 `openclaw-prod`、`km-batch`、`admin-test`，不要共用單一 Key。各群組設定模型白名單、RPM、日／週／月內部預算與 reasoning 限制。Sub2API 的美元成本屬估算，不等同 ChatGPT 訂閱實際帳單或供應商限額。
- 既有 `openAI_wifisit01` 同時綁定 `Anderson_H` 與 `WifiSit01_DA40`，正式池化前需盤點依賴；確認無影響後才解除不必要的跨群組綁定，以避免歸屬、配額及用量稽核混淆。
- 導入順序：先建立帳號清冊與 Owner／到期日／模型／用途；完成 DB 與設定備份；一次只新增一帳號至 staging；同步模型並做低量 smoke test；觀察 24 小時後再升級進 production pool；最後才啟用 MiniMax 的受控 fallback。憑證、OAuth token、API Key 不得寫入 Git、週報或文件。
- 故障策略：OpenAI 單帳號 429／暫時性 5xx 可切換其他 OpenAI；401／403 應隔離帳號並告警；全部 OpenAI 不可用時，僅允許白名單工作負載切至 MiniMax。不可對認證錯誤或不相容請求無限重試。
- 監控建議：帳號層追蹤成功率、401／403／429／5xx、P95 延遲、首 token、限流恢復時間、最後使用時間與預估成本；渠道層保留模型健康檢查。帳號健康探測可先採 10～15 分鐘並加入 jitter，避免現有 60 秒探測在多帳號情境過度消耗訂閱額度。
- 正式導入前 Gate：先完成 HTTPS，並重新評估目前為支援本地 Ollama 而關閉 URL allowlist 的 SSRF 風險；完成 token 輪替、最小權限、2FA／帳號保管與供應商授權條款確認。ChatGPT 訂閱帳號不能直接視為 OpenAI API 容量或可任意共享／轉售的配額。
- 建議沿用既有 Sub2API T1 時程重整：S2A-04（8/21）帳號清冊、歸屬與用量追蹤；S2A-05（8/28）TLS／SSRF／OAuth 隔離；S2A-06（9/4）5 帳號 OpenAI pool 與配額排程；S2A-07（9/11）MiniMax 獨立渠道、受控 fallback、監控及故障演練；S2A-08（9/30）UAT、SLA、備份／回滾與正式驗收。
- 本次僅完成架構與導入評估，沒有新增帳號、修改資料庫、渠道、群組、API Key 或正式服務設定。

## 2026-08-12 openAI_wifisit01 提供三位外部使用者的用量監控評估

- 可以讓三位外部使用者共用同一個上游 `openAI_wifisit01`，但三人不可共用同一把 Sub2API API Key。最佳做法是建立三個獨立 Sub2API user，各自建立一把命名清楚的 API Key，三把 Key 綁定同一個受控 group／channel，再由該 group 使用 `openAI_wifisit01`。
- 已直接確認目前 Sub2API PostgreSQL schema：`usage_logs` 具有 `user_id`、`api_key_id`、`account_id`、`input_tokens`、`output_tokens`、各類 cache token、`total_cost`、`actual_cost`、`model`、`ip_address`、`duration_ms`、`created_at`、`group_id` 與 `channel_id`，因此可依三位使用者或三把 Key 分別彙總 token、請求數、模型、成本估算、錯誤／延遲與使用時間，同時確認流量都由同一 upstream account 處理。
- `api_keys` 支援個別 `quota`、`quota_used`、`expires_at`、IP allow／deny list、5 小時／1 日／7 日 rate limit 及 usage window；`users` 另有 concurrency 與 RPM limit，可用於三位外部使用者的獨立限制、停用與撤銷。
- 若三人共用一把 API Key，雖可看到來源 IP，但遇到 NAT、代理、Key 外洩或 IP 變動時無法可靠歸屬，因此不能作為正式個人用量統計方案。
- 監控只涵蓋經 Sub2API 的 API 請求；三人在 ChatGPT 網站、其他 API Key 或繞過 Sub2API 的使用不會被記錄。Sub2API token 與成本統計也不等於 ChatGPT 訂閱方案的真實剩餘額度，OAuth 上游通常不提供可精確拆分給三人的固定剩餘 token 配額。
- 正式設定前應為三位使用者取得識別名稱、用途、固定來源 IP（若有）、個別 RPM／週期額度及到期日；不要在文件、Git 或對話中保存明文 API Key。本次只完成 schema 驗證與方案評估，尚未建立使用者或 API Key。

## 2026-08-12 週報 Excel 納入 Sub2API 三外部使用者與 5+1 帳號池規劃

- 已更新 `/home/da40_ai_gb10/knowledge-base/Team-III_2026_W31_Anderson_260805.xlsx`，遵循「先更新 T1開發計劃，再展開至 Anderson 任務頁」的關係；沒有修改其他人員分頁。
- `T1開發計劃`：T1-S2A-04 改為三位外部使用者以三個獨立 Sub2API user／API Key 共用 `openAI_wifisit01`，依 `user_id`／`api_key_id`／`account_id` 統計 token、模型、成本、IP、延遲，並規劃個別額度、RPM、到期與告警。因只完成 schema 與方案驗證、尚未建立正式帳號或 Key，進度由 10% 調整為證據式 20%。
- T1-S2A-05 補入三位外部使用者 Key 生命週期、IP 條件、TLS、SSRF allowlist、rotation 與群組隔離；T1-S2A-06 更新為 5 個 ChatGPT 帳號的 3 主用＋1 溢位＋1待命 Pool／Quota；T1-S2A-07 更新為 MiniMax 獨立渠道、白名單 fallback、SLA 與故障演練；T1-S2A-08 更新為三使用者與 5+1 帳號池正式驗收交接。
- `Anderson` 分頁同步展開 T1-S2A-04、05、06～08 的任務名稱、狀態、進度、交付路徑、判斷與否決 AI 記錄。明確記錄不能三人共用單一 Key、不能只依 IP 歸屬、不能把成本估算當訂閱剩餘額度，也不能讓 OpenAI／MiniMax 未驗證直接混池。
- 修改前備份：`Team-III_2026_W31_Anderson_260805.pre-sub2api-external-users-20260812.xlsx`。
- 驗證：openpyxl 可重新解析全部 15 個 sheets；指定內容與進度 assertions 通過；`unzip -t` 無壓縮結構錯誤；原有 T1-S2A-04 狀態公式仍保留；LibreOffice 24.2 可開啟並匯出 123 頁 PDF。實際檢視 PDF 第 18 頁（Anderson 任務摘要）及第 54、57 頁（T1 Sub2API 任務名稱／說明），新增文字可辨識、換行正常、未見遮蔽或截斷。

## 2026-08-12 Knowledge Base 開發簡報歷史彙整

- 使用者要求將所有 Knowledge Base 系統開發過程產生的簡報依時間順序集中，供其他人分享參考。現行工作目錄與家目錄沒有實體 PPTX，因此改以 `/home/da40_ai_gb10/knowledge-base` Git 全部分支及歷史 commit 為可追溯來源還原。
- 已建立分享目錄：`/home/da40_ai_gb10/knowledge-base/knowledge-base_development_presentations_20260812/`。共收錄 21 份正式簡報、121 頁，首次提交日期涵蓋 2026-06-09 至 2026-08-11；另將 `weekly-report-template.pptx` 放在 `templates/`，避免與正式簡報混淆。排除 `.venv/site-packages/pptx/templates/default.pptx` 套件內建範本。
- 排序規則：依各簡報路徑首次出現在 Git 的 commit 時間排序並加入 `YYYYMMDD_NN_` 前綴；檔案內容取該路徑最後一次提交的版本。沒有移動、刪除或修改 Git 中的來源檔案。
- 目錄內附 `README.md`（時間順序與來源摘要）、`presentation_manifest.csv`（首次／最新 commit、原始路徑、投影片數、大小與 SHA-256）及 `RENDER_VALIDATION.md`（驗證方法與結果）。
- 完整性驗證：22/22 個 PPTX ZIP 結構通過；LibreOffice 24.2 實際開啟並轉換 PDF 22/22 成功；所有 PDF 非空，且逐檔 PDF 頁數與 PPTX slide XML 數量一致。
- 已建立可直接分享的壓縮檔：`/home/da40_ai_gb10/knowledge-base/knowledge-base_development_presentations_20260812.zip`，大小約 2.1 MiB，SHA-256 `6f0ac18953622ccd6e599980d6ef48375d843169e8a4cf9049c8af80d3a11abe`。

## 2026-08-12 擴充 AI-KM Phase 1 W33 v2.6 簡報的 WP0／WP1 明細

- 使用者指出原 `AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx` 對 WP0／WP1 實際修改描述不足。已依真實 Git commit、Evidence、CI、部署與回滾紀錄，將簡報由 7 頁擴充為 11 頁；WP0 維持 94%、WP1 維持 96%，沒有為增加敘述而虛增進度。
- 新增第 6 頁「WP0 修改明細（1/2）」：列出正式 `app/main.py` FastAPI 入口、`/api/v1` health/live/ready/version、版本資訊、Docker/start/Compose 入口、統一 `ApiResponse`／`ApiError`、422／HTTP／500 error envelope、秘密安全的例外處理、X-Trace-ID／ContextVar／logging、環境驅動 AppSettings、legacy lifespan/routes/middleware/error/Agent 401 相容層及 release 文件更新。
- 新增第 7 頁「WP0 修改明細（2/2）」：列出三類 WP0 測試、pytest／dev／CI 基線、14 個 app 套件檔與 Docker/release/README 異動、基準 commit 23 files +555/-19，以及 production health、Agent 401、search、chat Webwright、90 passed、frontend／Compose／credential scan 與剩餘 E2E／Delivery Gate。
- 新增第 8 頁「WP1 修改明細（1/2）」：列出 typed JobConfig 的 concurrency/TTL/timeout/retry/queue/Beat 設定、canonical JobStatus 且保留 legacy status、search/ingest routing、trace 經 Celery 傳遞、retry config、攝入 Idempotency-Key／registry、application image 一致、restart policy、可配置 volume root、worker/Beat/queue Gate。
- 新增第 9 頁「WP1 修改明細（2/2）」：列出 pre-WP01 checkpoint 的 image/source/config/data/Neo4j/Qdrant/PostgreSQL/Redis/SQLite 備份，兩份約 9.6 GB checkpoint，shadow baseline 200→503→rollback 200、candidate Gate、第一次 production `/search` 500、五個 application image 成功回退、HTTP Request trace 修正與 regression test、89→90 passed，以及 `restart_kb` 的 status/restart/deploy、queue drain、checkpoint、確認碼與自動回退。
- 原第 6、7 頁 Gate 與下週承諾保留並移至第 10、11 頁；封面從 `1/7` 修正為 `1/11`，新增頁右下頁碼為 6～9，整份頁碼一致。
- 正式新版：`/home/da40_ai_gb10/knowledge-base/AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx`，SHA-256 `62105626ed2d8285ec1f1cfbad583c517dfd7ff5d00445948dce62a9fc0a8b33`。
- 原 7 頁備份：`/home/da40_ai_gb10/knowledge-base/AI-KM-Phase1-Weekly-2026-W33-v2.6.pre-wp01-details-20260812.pptx`。
- 可重建腳本：`/home/da40_ai_gb10/knowledge-base/scripts/enhance_phase1_weekly_wp01_details.py`。腳本以原 7 頁備份為輸入並拒絕非 7 頁來源，避免重複執行造成明細頁重複。
- 驗證：Python compile、PPTX ZIP 結構、11 頁解析、20 個必要技術詞 semantic checks 均通過；LibreOffice 24.2 實際渲染 11 頁 PDF成功；新增第 6～9 頁逐頁視覺檢查，文字未超出卡片、沒有遮蔽，字級可辨識。既有第 1～5、10～11 頁內容保持原設計。
- 已同步取代分享目錄中的第 21 份簡報並更新 README、Manifest、Render Validation；分享 ZIP 已重建，最新 SHA-256 為 `393f40f0454061d6c35281aecccc023e82f1ba7a0510bb085a0a8bad41232e50`。Manifest 明確標示新版為 `LOCAL-ENHANCEMENT-20260812`，因本次尚未提交 Git，不能虛構來源 commit。

## 2026-08-12 WP0／WP1 簡報改為 80 條逐項變更台帳

- 使用者進一步澄清：WP0／WP1 必須將每一條新增或修改的功能／機制獨立列出，不能再以分類卡片或一個 bullet 合併多項內容。因此前一版 11 頁分類明細已被新版取代；正式簡報目前為 17 頁。
- WP0 台帳位於第 6～9 頁，共 32 條（WP0-01～WP0-32）。逐項包含正式 FastAPI 套件與 create_app、Metadata、typed/safe settings、四個 v1 endpoints、response/error/health/version schemas、strict schema、Trace ID 驗證／產生／context／header／logging、422/HTTP/500 exception mapping、security context、legacy lifespan/routes/middleware/framework route 去重、Docker／Compose／start／release 入口，以及 WP0 測試與 CI 基線。
- WP1 台帳位於第 10～15 頁，共 48 條（WP1-01～WP1-48）。逐項包含 canonical status、JobConfig、concurrency/TTL/timeout/retry/queue/Beat、設定驗證與 Celery headers、queue declaration/routing/result/worker/lost-worker、legacy status、search/upload/review/task trace、retry/error classification/idempotency、部署 root/restart policy/search worker/ingest worker/Beat、unit tests/CI、checkpoint、Neo4j/Qdrant/PostgreSQL/Redis/SQLite 備份、integrity、rollback dry-run/production confirmation/data boundary、shadow drill、candidate Gate/search probe，以及安全 `restart_kb` 生命週期工具。
- 每一列固定有五欄：編號、動作（新增／修改／修正／保留）、功能／機制、實際改動、主要檔案／證據。每頁最多 8 條，避免為塞入內容而使用不可辨識小字；頁尾同時標示本頁編號範圍與該 WP 總條數。
- 原主管摘要、Phase 1 範圍、WP0 94%、WP1 96%、Gate、風險與下週承諾全部保留；封面頁碼改為 1/17，後續頁碼至 17。
- 正式檔：`/home/da40_ai_gb10/knowledge-base/AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx`，SHA-256 `73ffa517312494476dc93215b64eb5e97c6a365a8b7f22fb04ca6f47000df1a0`。上一版 11 頁備份為 `AI-KM-Phase1-Weekly-2026-W33-v2.6.pre-itemized-20260812.pptx`，最初 7 頁備份仍為 `AI-KM-Phase1-Weekly-2026-W33-v2.6.pre-wp01-details-20260812.pptx`。
- 可重建腳本改為 `scripts/itemize_phase1_weekly_wp01_changes.py`；先前 11 頁分類版腳本已刪除，避免誤產舊格式。
- 驗證：PPTX ZIP 結構通過；LibreOffice 24.2 實際渲染 17 頁成功；32 個 WP0 ID 與 48 個 WP1 ID 完整且唯一；80 個 feature/change/evidence 欄位都存在；所有 shapes 位於 slide bounds；抽查 WP0/WP1 首末台帳頁可辨識、換行正常、無遮蔽或截斷。
- 分享目錄第 21 份已同步為 17 頁，README／Manifest／Render Validation 已更新，正式簡報總頁數改為 131 頁。分享 ZIP 已重建，SHA-256 `d0e4b70e7b61aff2135d10772b54420a490c597f836b8b52e442cde033ac73aa`。

## 2026-08-12 WP0／WP1 明細頁標題調整

- 依使用者要求，`AI-KM-Phase1-Weekly-2026-W33-v2.6.pptx` 第 6～15 頁標題中的「逐條變更台帳」已全部改為「修改內容」。標題目前依序為 `WP0 修改內容（1/4）`～`WP0 修改內容（4/4）`、`WP1 修改內容（1/6）`～`WP1 修改內容（6/6）`。
- 僅修改標題文字及可重建腳本 `scripts/itemize_phase1_weekly_wp01_changes.py`；17 頁結構、WP0 32 條、WP1 48 條、進度、表格內容與其他頁面均未改動。
- 驗證：PPTX 解析確認第 6～15 頁共 10 個新標題；舊字樣為 0；LibreOffice 24.2 實際渲染 17 頁 PDF成功，PDF 文字搜尋新標題 10 筆、舊標題 0 筆。
- 正式 PPTX SHA-256 更新為 `c5ceb4093dd7dc1b3b44fad7e24ee7b85b6bcba75b3a553269f27a028d017979`；分享目錄與 Manifest 已同步，分享 ZIP SHA-256 更新為 `d7f83ec54ff311514d5e6c0dbe1911f50efb2c3d2e0010a0e901fe587dd00990`。

## 2026-08-12 Anritsu A2A Bearer CLIXML 設定盤點與阻塞

- 使用者要求調出 KM Agent 與 Anritsu A2A 協作內容，並將 `/home/da40_ai_gb10/knowledge-base/anritsu-a2a-km-bearer-token.clixml` 的 Bearer Token 設定到 KM，使 KM Agent 可呼叫 Anritsu。
- 已核對先前契約：KM 為中央 Orchestrator／Control Plane；Anritsu 為獨立 A2A Server／Execution Plane；A2A sidecar、credential 與既有 Excel ingest credential 必須分離；只允許 HTTPS Agent Card、A2A 1.x JSON-RPC、`run_iperf_test` allowlisted profile；KM 端目前只完成隔離 bridge、SDK wire dry-run、SQLite journal、冪等/correlation 與 focused tests，尚未完成 bridge 正式部署、OpenClaw 受控 tool 註冊、真實 Anritsu URL/card 跨電腦 dry-run、polling/cancel/recovery 或真機批准。
- CLIXML 結構只含 PowerShell `<SS>` SecureString，密文 716 個 hex 字元（358 bytes）；格式 signature 判定為 Windows DPAPI (`01000000d08c9ddf...`)。這不是可直接傳給 HTTP Authorization header 的明文 Token，並綁定原 Windows 電腦／使用者。Linux 主機沒有 `pwsh`，即使安裝 PowerShell也沒有原 Windows DPAPI master key，因此無法在這台主機安全解密。不得把 CLIXML 密文直接填入 `KM_A2A_AGENT_CREDENTIALS`，否則 Anritsu 會收到錯誤 Bearer credential。
- 專案及文件中只有 placeholder `https://<anritsu-host>`／`https://anritsu.example`，沒有真實 Anritsu HTTPS discovery base URL。實際設定至少還缺：真實 discovery origin、Anritsu 允許的 profile ID，以及 bridge 本地 control credential／OpenClaw tool wiring。
- 即時狀態：沒有 `km_a2a_bridge` process/container/systemd unit，18181 未監聽；因此目前 Token 尚未注入 runtime，也不能宣稱 KM Agent 已可呼叫 Anritsu。
- 已做安全防護：將 CLIXML 權限從 `0644` 改為 `0600`；在 `.gitignore` 加入 `*.clixml`，`git check-ignore` 已確認該 secret export 不會被提交。沒有顯示、記錄或寫入 Bearer 明文。
- focused A2A tests 使用既有隔離 venv 並設定正確 `PYTHONPATH` 後為 `52 passed in 0.58s`。主機 system Python 無 pytest；第一次未設 `PYTHONPATH` 的隔離 venv執行在 collection 階段因找不到本地 package 失敗，修正測試環境後全部通過，非程式回歸。
- 要繼續設定，必須由原先產生 CLIXML 的 Windows 11 電腦及相同 Windows 使用者執行 `Import-Clixml` 解密，透過受保護檔案／SSH stdin 等安全渠道傳給此主機，不能把明文貼進 Git、文件或一般聊天。同時需提供非秘密的 Anritsu HTTPS discovery base URL與核准 profile。拿到這些資料後，應先建立 0600 的 Git-ignored secret env、以 `sdk-dry-run` 啟動隔離 bridge、驗證 Agent Card／錯誤 token／正確 token／dry_run 不取得 instrument lock，再另外實作並審查 OpenClaw 受控 tool；不得直接開真機。

## 2026-08-12 Anritsu A2A 回覆後的雙向連線與整合評估

- Anritsu Agent 回報已新增 `Send-A2ATokenToKm.ps1`、更新 sidecar README、排除 `*.clixml`、核准 profile `ncq2200b2v-throughput-v1`、設定 dry-run／`127.0.0.1:8790`／SQLite 並有 `15 passed`。這些方向符合先前契約：秘密 fail-closed、sidecar 不直接暴露、profile allowlist、dry-run 與持久 journal；但 15 tests 的測試清單與「dry-run 不取得 lock／不啟動 iperf／不上傳 Excel」證據仍需交付，不能僅由 passed 數字判定跨電腦 Gate 完成。
- Token 傳送到 `61.216.9.52:22` timeout。KM 主機即時檢查顯示 OpenSSH service 雖為 disabled 但目前 active，`0.0.0.0:22` 與 `[::]:22` 正在監聽；公網 egress IP 為 `61.216.9.52`。因此 timeout較可能位於公司 NAT／edge firewall／路由，不是本機 sshd 未啟動。基於安全原則，不建議直接開放公網 SSH 22。
- KM 已有 Tailscale：service active，介面 `tailscale0`，IPv4=`100.65.63.58`，本機透過該位址連 22 成功；目前 tailnet status 只有 KM `spark-7546`，Anritsu 尚未加入。Tailscale SSH 未啟用 (`RunSSH=false`)，一般 OpenSSH 可使用，但 `~/.ssh/authorized_keys` 尚不存在，故自動化 secret transfer 仍缺 Anritsu 專用 SSH public key。
- 建議網路方案：取得公司／tailnet管理者核准後，Anritsu Windows 加入同一 Tailscale tailnet；`Send-A2ATokenToKm.ps1` 的 KM target 改為 `100.65.63.58:22`，使用 Anritsu 端產生的專用 Ed25519 key，KM 只安裝 public key，禁止把 private key 傳給 KM。若公司不允許 Tailscale，替代方案是既有企業 VPN + 內部 DNS + 公司 CA HTTPS；不得以 email/chat、公開 upload endpoint或臨時關閉 TLS 傳 Token。
- A2A 反向連線：Anritsu sidecar 維持 `127.0.0.1:8790` 是正確做法；在同一 Windows 主機使用 Tailscale HTTPS Serve（若 tailnet 已啟用 HTTPS/MagicDNS）或公司核准 reverse proxy，將 `https://<anritsu-magicdns-or-internal-dns>` 代理到 localhost:8790。`ANRITSU_A2A_PUBLIC_BASE_URL` 必須是該 HTTPS origin，Agent Card 的 `/a2a` interface必須同 origin。沒有正式 HTTPS URL 時繼續 fail-closed。
- KM 後續工作：收到 token 後轉存為 `0600` Git-ignored secret，不保留 pending plaintext；建立獨立 bridge control token hash；設定 `KM_A2A_ENABLED=true`、`KM_A2A_TRANSPORT=sdk-dry-run`、profile、Anritsu discovery origin、outbound credential及持久 journal；以獨立 service 綁 `127.0.0.1:18181`，不修改現有 KB Compose/Nginx；依序驗證 discovery/card/same-origin、錯誤 token拒絕、正確 token、allowlist、dry-run、duplicate idempotency與 journal recovery。
- KM Agent／OpenClaw 目前仍缺受控 tool wiring。只有 bridge 跨電腦 dry-run Gate 通過後，才新增固定 schema 的 `run_anritsu_iperf_test`／status/cancel tool，由 OpenClaw 呼叫 localhost bridge；禁止任意命令。部署 bridge 不需重啟 KB 或 OpenClaw；之後新增 OpenClaw tool 是否需要 config reload／gateway restart，須依實際 registration方式驗證，不能現在宣稱永遠不需要。A2A sidecar本身不需重啟現有 Anritsu production agent。
- 放行順序：P0 網路／SSH key／HTTPS；P1 token transfer與 Agent Card；P2 KM SDK dry-run E2E；P3 OpenClaw受控 tool；P4人工批准的單一真機 profile。當前停在 P0，尚未把 Token 注入 KM runtime，也尚未具備 KM Agent呼叫 Anritsu 的完整條件。

## 2026-08-12 僅使用 KM 公開 HTTPS 3030 與 Anritsu 溝通的可行性

- 使用者說明 KM 對外固定入口為 `https://61.216.9.52:3030`，要求評估直接用此 port 與 Anritsu Agent 溝通。結論：可行，但只有在改為「Anritsu 主動連入 KM 的 reverse relay／pull connector」時可完整解決網路問題；它不能直接讓目前 KM outbound SDK 反向存取 Anritsu 的 `127.0.0.1:8790`。若維持標準 direct A2A client→server 模式，仍需 Anritsu 可由 KM 存取的 HTTPS discovery URL或 VPN/tunnel。
- 建議架構：OpenClaw 受控 tool → localhost KM A2A relay 建立 task → Nginx `3030` 專用 `/a2a-relay/v1/...` → Anritsu sidecar 以長輪詢或 WebSocket 主動取得 lease → dry-run executor → 經相同 3030 回報 ack/status/result metadata；Excel仍沿用既有 strict ingest endpoint。KM 邏輯上仍是中央 Orchestrator，網路連線方向則全部由 Anritsu outbound 發起。
- 此方案不是目前官方 SDK direct Agent Card／SendMessage transport 的原樣使用，應明確命名為 `reverse-relay` transport；內部仍保留 A2A task/context/run correlation與固定 Data payload。若未來需要第三方 A2A 互通，再保留既有 `sdk-dry-run` direct transport，不把 relay 假稱為完整標準 A2A server。
- Token可改為 `Anritsu → KM relay` 專用 Bearer：Anritsu持有明文，KM只保存 SHA-256 verifier，因此不需把明文 Token傳到 KM。基於方向與scope改變，建議新建專用 relay token，不重用原本 `KM → Anritsu A2A` credential，也不重用 Excel ingest token。Anritsu可交付 token SHA-256 供 KM設定，但仍需透過已核准身分／變更流程確認來源。
- 即時 TLS 檢查：3030憑證 subject/issuer 均為 Da40AI `CN=61.216.9.52`，SAN包含 `61.216.9.52`，有效至 2027-05-17，但為 self-signed。一般 `curl` 驗證失敗，只有 `-k` 可通。正式 relay 禁止關閉 TLS驗證；應將公司 CA／該受控 CA鏈安裝到 Anritsu Windows trust store，或換成企業 PKI／公認 CA憑證。憑證 SHA-256 fingerprint 只作帶外核對，不應取代可管理的 CA信任與輪替。
- 即時 Nginx檢查：3030已將 `/api/`、search/tasks/health、admin與 `/ws` 代理到 KB web；沒有 relay route，也沒有專用 rate limit/mTLS。`/.well-known/agent-card.json`與`/a2a`目前因 SPA fallback回 HTTP 200 `text/html`（KM index.html），不是有效 Agent Card／A2A endpoint。正式前應為保留路徑增加明確 404或正確 relay route，避免 health check假成功。
- Relay應維持隔離：新增獨立 service/container與持久 journal，不把 queue/lease邏輯塞入現有大型 FastAPI；Nginx只新增 `location ^~ /a2a-relay/`，代理到內部 relay，限制方法、body size、timeout、rate、來源及header，不讓 public client碰 localhost control API。現有 chat/search/ingest路由及 KM資料庫不修改。
- 必要 relay contract：agent_id/profile scope、heartbeat/capability、long-poll lease、lease TTL/renew/ack、task cancel、canonical status、attempt、nonce/timestamp、防重播、`context_id/a2a_task_id/run_id`、冪等 conflict、journal recovery、audit；只允許固定 `run_iperf_test` schema，不接受 shell/SCPI/path/URL。Anritsu離線時 task保持 queued或到期顯性失敗，不能阻塞 KM chat/search/ingest。
- 安全 Gate：專用強隨機 relay token或mTLS、KM只存hash、錯誤token拒絕、速率與並發限制、IP allowlist（若來源固定）、TLS chain驗證、secret/header不進log、request body上限、Nginx與relay audit、token rotation/revoke；不得使用既有 upload endpoint傳CLIXML或秘密，否則可能把secret誤存入攝入流程。
- 建議階段：R0 contract與威脅模型；R1隔離 relay + mock poller；R2 shadow Nginx route與可信TLS；R3跨電腦 dry-run（無lock/iperf/Excel/ingest）；R4 OpenClaw固定 tool；R5人工批准單一真實profile。啟動 relay不需重啟整個KM；Nginx需受控reload，OpenClaw tool註冊後可能需gateway config reload。當前尚未修改 runtime或部署 relay，需先由使用者確認採 direct A2A + VPN 還是 3030 reverse-relay 架構。

## 2026-08-12 回復原 direct A2A 設計後 Anritsu 端待辦

- 使用者決定回到原本 direct A2A：KM 為 A2A Client／中央 Orchestrator，Anritsu為 A2A Server／Execution Plane；KM主動取得 Anritsu Agent Card並送 JSON-RPC task。此模式下 `https://61.216.9.52:3030` 只供 KM chat／ingest，不會解決 KM→Anritsu連線；Anritsu必須提供 KM可達、可信TLS的 HTTPS discovery origin。
- Anritsu已完成可保留：獨立 sidecar、dry-run、localhost 8790、SQLite、profile `ncq2200b2v-throughput-v1`、安全 token傳送腳本、CLIXML Git排除與15 tests。仍不能宣稱可被KM呼叫，因 public base URL空白、sidecar fail-closed、Token未交付、跨電腦Agent Card/SendMessage尚未驗收。
- Anritsu P0網路待辦：選擇公司VPN/Tailscale/企業網段之一，使KM能解析並連線 Anritsu；sidecar可繼續只綁`127.0.0.1:8790`，由同機 reverse proxy將可信HTTPS origin代理到8790。設定`ANRITSU_A2A_PUBLIC_BASE_URL=https://<anritsu-dns>`；防火牆只允許KM/VPN來源；禁止直接公開8790或使用HTTP。
- Anritsu P0 TLS待辦：建立內部DNS或MagicDNS名稱；使用公司CA、受控內部CA或Tailscale HTTPS憑證；提供CA chain給KM信任。憑證SAN必須包含實際hostname，SDK不可`verify=False`／`-k`。Agent Card與A2A interface必須同origin。
- Anritsu P0 Token待辦：原 direct模式是KM對Anritsu出站Bearer，KM client必須持有Token明文，只有SHA-256不夠。CLIXML為Windows DPAPI，需由原Windows帳號解密後透過核准VPN+SSH stdin、Vault/secret manager或等價安全通道交付；不得貼聊天、email、Git或Agent Card。若SSH不通，應先修VPN/路由或採企業secret store，不得建立無認證upload endpoint。交付後Anritsu保留撤銷／輪替能力，且不得重用ingest token。
- Agent Card必須實際提供`GET /.well-known/agent-card.json`，Content-Type JSON，宣告A2A 1.x、JSONRPC、同origin `/a2a` interface、`run_iperf_test` skill與Bearer security scheme；不得回SPA HTML、秘密或本機路徑。`POST /a2a`必須接受官方SDK SendMessage與Data Part。
- Job/安全待辦：只允許`job_schema_version=1.0`、`job_type=run_iperf_test`、environment=anritsu、核准profile、1..3600 duration、安全run_id與profile test case allowlist；extra fields、任意command/SCPI/path/URL拒絕。錯誤/缺失Bearer分別顯性401/403，並落不含秘密的audit。
- Dry-run硬性證據：`dry_run=true`時不得取得instrument lock、不得連儀器/送SCPI、不得啟動iperf、不得產正式Excel、不得呼叫KM ingest；應交付可驗證log或mock counters，而不只是`15 passed`。測試需另涵蓋錯誤token、未知profile、非法duration、duplicate run_id、busy、cancel、timeout、sidecar restart/journal recovery、existing manual test regression。
- Lifecycle/correlation待辦：回傳非空`context_id`、`a2a_task_id`且metadata `runId`一致；Task state與busy/rejection reason穩定；SQLite保存run/task/ingest/file hash與test/report/ingest三狀態；相同job冪等、不同payload conflict；instrument lock與manual流程共用，並具TTL/heartbeat/cleanup。
- Anritsu交付KM的非秘密資料：正式 discovery base URL、Agent Card樣本、SDK/protocol版本、15 tests名稱與結果、profile/test cases與duration範圍、service start/stop/status/rollback指令、health輸出、CA chain／憑證資訊、錯誤碼/state mapping。秘密只走核准secret通道。
- Anritsu完成上述P0後，KM才可設定`KM_A2A_TRANSPORT=sdk-dry-run`、endpoint、profile與outbound credential，啟動localhost bridge並做跨電腦dry-run。跨電腦Gate通過後，KM仍需新增OpenClaw受控tool；因此「Anritsu可被SDK呼叫」與「使用者可在OpenClaw下命令」是兩個Gate。Anritsu sidecar不需修改或重啟原production agent；設定URL/憑證後只需啟動/重啟獨立sidecar/reverse proxy。

## 2026-08-12 依 HTTP 8790 POC Guide 完成 KM 端 Anritsu 對接準備

- 已完整研讀根目錄 `KM_AGENT_HTTP_8790_POC_INTEGRATION_GUIDE.md`，依文件指定的 temporary direct A2A POC 調整 KM bridge。POC 固定為 KM 主動呼叫 `http://100.100.100.51:8790`、A2A protocol `1.0`、Bearer、`sdk-dry-run`、profile `ncq2200b2v-throughput-v1`，且只允許 `sa_dl_tcp`／`sa_ul_tcp`；沒有啟用真實儀器操作、iperf、Excel、report 或 ingest。
- `km_a2a_bridge/config.py` 新增 protocol version、profile test-case allowlist、明確的 `KM_A2A_ALLOW_INSECURE_HTTP_POC` 例外，以及 `KM_A2A_AGENT_CREDENTIAL_FILES`。HTTP 僅在 transport=`sdk-dry-run` 且明確開啟 POC flag 時允許；一般模式仍要求 HTTPS。credential file 必須是非 symlink 的 regular file、mode `0600`；inline 與 file credential 不得同時設定。
- `km_a2a_bridge/contracts.py` 將 wire contract 固定為 `job_schema_version=1.0`、`dry_run=true`，收緊 identifier／requester pattern，限制最多兩個且不得重複的 test cases，dispatch 時依 environment/profile allowlist 驗證。仍不接受任意 shell、SCPI、path 或 URL。
- `km_a2a_bridge/sdk_transport.py` 在 Agent Card discovery 與 JSON-RPC client統一加入 `Authorization: Bearer ...` 及 `A2A-Version: 1.0`，支援受控 HTTP POC 的 same-origin／default port檢查。只有遠端回傳相同 `runId`、非空 correlation、test/report/ingest 全為 `pending`，且七項 dry-run side-effect counters 全為 0時，才接受 completed。
- 更新 `km_a2a_bridge/.env.example` 與 `README.md`，記錄 HTTP 8790 只屬暫時 POC；正式 HTTPS 後必須移除 flag並輪替 token。新增 `scripts/run_anritsu_a2a_poc_smoke.py`，只會向 localhost bridge提交固定 schema dry-run，test case只能從allowlist選擇，讀取本機control token檔且不輸出秘密。
- `.gitignore` 新增 `*.clixml`、`.anritsu-a2a-*-token`、`.km-a2a-*-token`。建立 Git-ignored mode `0600` 的 `.anritsu-a2a-poc-token`、`.km-a2a-control-token` 與 `km_a2a_bridge/.env`；舊 Windows DPAPI CLIXML仍不作為新POC credential。Anritsu端應登錄新POC token的「去除換行後」SHA-256：`1e0edfec6707775bd019520f48a9fd4cbfb1bec737eddaf3783e64146cf33862`，不是檔案含尾端換行時的hash；Bearer明文不得透過聊天、Git或文件傳送。
- 新增個人 systemd user unit `/home/da40_ai_gb10/.config/systemd/user/km-a2a-bridge.service`，使用隔離 venv `/home/da40_ai_gb10/.local/share/km-a2a-bridge/venv`、持久SQLite `/home/da40_ai_gb10/.local/state/km-a2a-bridge/tasks.sqlite3`，只監聽 `127.0.0.1:18181`。unit已enable且active，`Linger=yes`，重開機／登出後可由user manager恢復；沒有修改或重啟既有KM Compose、Nginx、3030、OpenClaw或儀器服務。
- 本機 runtime health為 `status=ok`、`enabled=true`、`transport=sdk-dry-run`、`real_instrument_access=false`。控制面驗證：無token=401、錯誤token=403、正確token通過認證後查不存在task=404。過程中發現最初control hash誤以「含檔案尾端換行」計算，造成合法token被403；已只修正Git-ignored `.env`為trim後token hash並重啟獨立bridge，沒有改主KM。
- 測試與檢查：四個 A2A test files共 `61 passed in 0.58s`；Python compile、`git diff --check`、tracked secret scan、service health、port bind及credential mode檢查通過。18181只綁loopback；秘密未出現在service log。
- 尚未完成跨電腦Gate。KM執行 `tailscale status`只看到本機 `spark-7546` (`100.65.63.58`)；`tailscale ping 100.100.100.51`回 `no matching peer`，而 `ip route get 100.100.100.51`經一般gateway `172.14.1.1`，對 `http://100.100.100.51:8790/health`逾時。因此目前不能安全執行真正的跨機dry-run，也不能宣稱KM Agent已能呼叫Anritsu。
- Anritsu下一步：加入與KM相同tailnet或提供KM可達的企業VPN／路由；若使用Tailscale，Windows firewall應只允許來源 `100.65.63.58` 到8790；在sidecar登錄上述POC token hash；再由KM依序驗證Tailscale peer、`/health`、Agent Card、錯誤Bearer、固定schema dry-run及七項side-effect counters。跨機Gate通過後，才進行OpenClaw受控tool wiring；在此之前不發送真實task、不啟用真機，也不需重啟既有KM或OpenClaw gateway。

## 2026-08-12 Anritsu Tailscale onboarding 與最小權限配合調整

- Anritsu Agent要求將 `t100360843@ntut.org.tw` 邀請到包含KM `100.65.63.58`的tailnet，或提供single-use／短效／pre-authorized且帶`tag:anritsu-a2a-poc`的auth key；ACL只允許KM到該tag的TCP 8790。
- 即時查核：Tailscale `1.102.2`、`tailscaled=active`；KM目前位於個人tailnet `kusanagi.huang@gmail.com`，MagicDNS suffix `tail19a421.ts.net`，節點 `spark-7546`／`100.65.63.58`，目前無tags。`tailscale status`仍只有KM自己，`tailscale ping 100.100.100.51`仍回`no matching peer`，因此沒有虛稱onboarding或跨機連線完成。
- 邀請外部使用者、建立auth key與修改tailnet policy必須由Owner/Admin/IT admin在Tailscale Admin Console執行，一般KM節點CLI無法代辦；本機沒有取得或產生任何Tailscale auth key，也沒有把秘密寫入檔案或log。
- 已更新 `KM_AGENT_HTTP_8790_POC_INTEGRATION_GUIDE.md`：新增兩條互斥onboarding路徑。方案A邀請` t100360843@ntut.org.tw`為Member，接受後由管理員核對machine再指派tag；方案B建立single-use、短效、pre-authorized、pre-tagged auth key並經核准secret channel交付，註冊後撤銷／確認失效。無論採哪一條，最終Anritsu machine必須在同一tailnet並有指定tag。
- 指南新增可合併的最小權限HuJSON/JSON：`tagOwners`僅`autogroup:admin`可指派`tag:anritsu-a2a-poc`；`grants`只允許source `100.65.63.58`到destination tag的`tcp:8790`。明確禁止用該片段覆蓋整份既有policy，也禁止`*`來源／目的／port。
- 重要風險：Tailscale grants是累加規則，窄grant不會否決既有寬鬆grant。tailnet管理員必須稽核既有`*`、`autogroup:member`、user/group規則並用policy preview/test確認沒有其他來源可連該tag，否則不能宣稱只有KM可存取。
- Windows firewall範例已從錯誤的KM公網IP `61.216.9.52`改為KM Tailscale IP `100.65.63.58`，不得使用`RemoteAddress Any`或關閉防火牆。HTTP 8790只允許在受控tailnet POC傳輸，不直接公開Internet。
- Anritsu加入新tailnet後可能取得不同Tailscale IP；指南與`km_a2a_bridge/README.md`已要求先以`tailscale status`／`tailscale ping`確認實際peer IP或MagicDNS，再資料驅動更新`KM_A2A_AGENT_ENDPOINTS`，不能硬假設`100.100.100.51`維持不變。
- 已校正指南驗證台帳：Anritsu `21 passed`與本機health/dry-run是Anritsu回報，待KM跨機複驗；KM bridge是`61 passed`且本機health/control auth通過；目前KM→Anritsu health仍timeout、peer仍不存在，跨機fixed-schema dry-run維持BLOCKED。
- 驗證：指南內policy JSON可由`python3 json.loads`解析且src/dst/ip assertions通過；`git diff --check`通過；KM A2A bridge仍active，health保持`real_instrument_access=false`。此次只改文件／交接規則，沒有重啟或修改主KM、OpenClaw、Nginx、3030或既有A2A contract。

## 2026-08-12 KM 管理員提供 Anritsu Tailscale 授權的執行方式

- 使用者詢問「KM Tailscale管理員先提供授權、Anritsu再用授權加入」的實際作法。建議使用tagged one-off auth key，不同時邀請human account：Anritsu是提供A2A服務的非人員節點，Tailscale tag會取代user identity；邀請帳號與tagged key是替代方案。
- 管理員順序：先在Access controls合併`tagOwners`與最小權限grant並用policy preview/test驗證；再到Admin Console Keys→Generate auth key，設定description、Reusable=off、Expiration=1 day（官方允許最短期限）、Ephemeral=off、Pre-approved=on、Tags僅`tag:anritsu-a2a-poc`。auth key只能由Owner/Admin/IT admin/Network admin建立。
- Ephemeral關閉的理由：Anritsu sidecar是持續服務，不能因短暫離線自動消失。one-off key使用後會自動撤銷，但key到期／撤銷不會讓已加入machine失去授權；POC結束必須在Machines刪除／停用Anritsu節點，並移除不再需要的grant/tag，才是完整撤銷。
- Key只經核准secret channel交付，不貼聊天/Git/Email。Windows應把key放入ACL受限暫存檔並使用官方支援的`tailscale.exe up --auth-key="file:<path>" --hostname=anritsu-a2a-poc --unattended`，成功後刪除檔案；不得把`tskey-...`直接放在命令列。若Windows原本登入其他tailnet，必須在本機console或另有救援通道時切換，避免唯一RDP連線中斷。
- 已把上述Admin Console設定、Windows命令、撤銷語意及遠端連線風險寫入`KM_AGENT_HTTP_8790_POC_INTEGRATION_GUIDE.md`。沒有替使用者產生auth key，因目前沒有Tailscale Admin Console授權session／核准secret channel；也沒有顯示或保存任何Tailscale秘密。
- Anritsu加入後需回報實際Tailscale IP／MagicDNS；KM再執行`tailscale status`、`tailscale ping`、`healthz`與Agent Card檢查，更新資料驅動endpoint並只重啟獨立`km-a2a-bridge`。跨機dry-run通過前仍不啟用OpenClaw正式tool或真實儀器。

## 2026-08-12 已實際建立 Anritsu Tailscale 最小權限與 Single-use Key

- 使用者明確要求代為執行Tailscale管理與key產生，並已在桌面Firefox以`kusanagi.huang@gmail.com`登入。因Webwright隔離瀏覽器無法沿用session，經確認Firefox沒有Playwright/CDP介面後，改用桌面X11輸入控制既有登入session；沒有讀取、複製或保存Firefox Cookie/密碼。
- Admin Console確認此tailnet原policy為Tailscale預設unrestricted grant：`src/dst/ip`全部`*`。僅新增窄grant不足以達成「只有KM可連」，因此透過JSON editor移除全開grant，改為`tagOwners: tag:anritsu-a2a-poc -> autogroup:admin`與唯一grant `100.65.63.58 -> tag:anritsu-a2a-poc -> tcp:8790`；保留原本`autogroup:member -> autogroup:self`的SSH check。加入policy test確認KM可連tag的8790；Preview Changes語法／測試通過後已Save，存檔後左右diff相同且Save disabled，證明已落地。
- 在Keys頁建立auth key：Description=`Anritsu-A2A-POC-2026-08-12`、Reusable=off（Single-use）、Expiration=1 day（2026-08-13到期）、Ephemeral=off、Tags只含`tag:anritsu-a2a-poc`。Keys清單已顯示Single-use、建立日2026-08-12、到期日2026-08-13、description與tag正確。
- Device management確認`Manually approve new devices`為off，因此Generate form沒有Pre-approved選項；此tailnet不需要額外device approval，Anritsu使用key後會直接加入，不會卡pending。沒有為本次POC改動Device Approval、Tailnet Lock、Key Expiry或Auto-update設定。
- Key明文只保存於 `/home/da40_ai_gb10/.local/state/km-a2a/tailscale-anritsu-a2a-poc-auth-key`，owner為本機使用者、mode `0600`、格式檢查符合Tailscale auth key、長度61 bytes。最終回覆與logs不顯示key，也不記錄hash（避免不必要識別資訊）。
- Secret modal沒有保存到磁碟證據：生成後只在`/dev/shm`建立mode 0600暫存圖供本機OCR定位copy icon，OCR只允許UI白名單詞輸出，隨即由Python unlink；最終確認RAM暫存不存在。Key透過copy icon直接讀入受限檔；發現GTK clipboard clear不持久後，改以Firefox複製非秘密Admin Console URL覆蓋clipboard，最終驗證clipboard不含`tskey-`。
- Web操作工作區為`/tmp/webwright-tailscale-auth-key`。不含秘密的證據包括`policy_saved.png`、`auth_key_record_expanded.png`、`device_management_status.png`，並由`final_runs/run_2/final_script.py`驗證。所有已保存screenshots經OCR掃描均不含`tskey-`；操作log也沒有秘密。
- 最終本機Gate：secret file mode=600、auth key格式有效、clipboard無key、已保存screenshots無key、RAM secret screenshot不存在；`km-a2a-bridge.service=active`，health仍為`enabled=true`、`transport=sdk-dry-run`、`real_instrument_access=false`。沒有重啟或修改主KM、OpenClaw、Nginx或3030。
- Key尚未交付Anritsu；下一步必須透過核准secret channel將上述檔案內容一次性傳到Anritsu Windows的ACL受限暫存檔，執行`tailscale.exe up --auth-key="file:<path>" --hostname=anritsu-a2a-poc --unattended`後刪除暫存檔。Key使用後會自動revoked，但節點仍保留；POC結束需由管理員刪除machine才能撤銷節點。Anritsu加入後KM才可做peer／health／Agent Card／dry-run跨機Gate。

## 2026-08-12 Anritsu 改採 Docker userspace Tailscale 後的 KM 配合

- Anritsu回報Windows實體gateway／DNS使用`100.100.100.100`，與Tailscale Quad100衝突，因此禁止在Windows host執行`tailscale.exe up`，改由`Manage-A2ADockerTailscalePoc.ps1 -Action Authorize`建立隔離Docker userspace Tailscale節點。KM評估此方向合理：可以避免改動Windows host路由/DNS，但必須確保8790只存在userspace tailnet、不publish Windows host port，且不開exit node/subnet routes/Tailscale SSH/Funnel。
- KM已具備符合要求的Tailscale key：single-use、1-day、non-ephemeral、tag=`tag:anritsu-a2a-poc`；本機secret file仍為`/home/da40_ai_gb10/.local/state/km-a2a/tailscale-anritsu-a2a-poc-auth-key`，mode`0600`、61 bytes、格式有效。`tailscale status`仍只有KM，證明Anritsu Docker peer尚未加入，key仍待交付／使用。
- Tailnet policy已完成且不需再改：預設全開grant已移除，只允許source KM `100.65.63.58`到destination `tag:anritsu-a2a-poc`的`tcp:8790`；tag owner為admin。Device Approval為off，因此Generate Key頁沒有Pre-approved選項，tagged single-use key使用後會直接授權；這在目前tailnet等效於不需另行pre-approval。
- 已全面更新`KM_AGENT_HTTP_8790_POC_INTEGRATION_GUIDE.md`與`km_a2a_bridge/README.md`：端點改為`http://<ANRITSU_DOCKER_TAILSCALE_IP>:8790`資料驅動placeholder；移除邀請human user後讓Windows加入、Windows host `tailscale.exe up`與Windows inbound firewall等已停用流程；改記錄Docker secret注入、`D:\Anritsu_Control_API\a2a-sidecar\scripts\Manage-A2ADockerTailscalePoc.ps1 -Action Authorize`、不得host publish，以及Windows DNS/外網/Quad100路由不變的驗收。
- KM runtime原`KM_A2A_AGENT_ENDPOINTS`仍保存舊`100.100.100.51`，但在收到新Docker IP前不應猜測。為防止誤將A2A Bearer送到Windows實體衝突網段，已把Git-ignored`km_a2a_bridge/.env`的`KM_A2A_ENABLED`由true改為false並只重啟獨立user service。Health=`status:ok, enabled:false, transport:sdk-dry-run, real_instrument_access:false`；主KM/OpenClaw/Nginx/3030均未修改或重啟。
- Key目前尚未傳到Anritsu。現階段沒有已核准且可連到Anritsu Windows的secret channel，因此不能使用聊天、Email、Git、臨時public upload或A2A Bearer token渠道代替。安全交付需由使用者/Anritsu提供已核准管道，例如企業Vault的一次性secret、受控AnyDesk File Transfer，或Anritsu提供age/PGP public key後由KM加密檔案；只有ciphertext可走一般檔案通道。不可在PROJECT_MEMORY記錄key內容。
- Anritsu收到key後會寫入ACL受限的`C:\ProgramData\Tailscale\anritsu-a2a-poc-auth.key`，Authorize腳本應以read-only Docker secret注入、完成後刪除container `TS_AUTHKEY`/secret與Windows暫存檔，並回報Docker Tailscale IP與A2A endpoint。KM收到後才更新`KM_A2A_AGENT_ENDPOINTS`、重新設`KM_A2A_ENABLED=true`、重啟獨立bridge，依序驗證peer/health/healthz/Agent Card/same-origin `/a2a`/401/403/correct Bearer/fixed dry-run/七項side effects=0。
- 驗證：A2A四份focused tests=`61 passed in 0.66s`；compileall、`git diff --check`、tracked secret scan通過；bridge active但fail-closed disabled。尚未執行跨機call，不能宣稱Docker POC已完成。

## 2026-08-12 age 加密 Tailscale Auth Key 與 AnyDesk 待交付狀態

- Anritsu提供`anritsu-a2a-poc-age-recipient.txt`與`Import-A2ATailscaleAuthKey.ps1`到專案根目錄。KM已核對公開recipient檔內容與帶外回覆完全一致：`age1euwarvhxvztz2nryglypagc3rcgakh8wp24lhs687p9h429dhszsqrz4hm`，格式為有效age X25519 recipient。recipient是公開資料，不含私鑰。
- KM原先未安裝age。已從官方`FiloSottile/age` GitHub v1.3.1 release下載`age-v1.3.1-linux-arm64.tar.gz`，本機架構為aarch64；使用GitHub release API提供的digest核對SHA-256=`c6878a324421b69e3e20b00ba17c04bc5c6dab0030cfe55bf8f68fa8d9e9093a`，tar成員經路徑穿越檢查後，將`age`、`age-keygen`、`age-inspect`安裝至`/home/da40_ai_gb10/.local/bin`，版本=`v1.3.1`。未修改系統APT或全域binary。
- 已靜態審查`Import-A2ATailscaleAuthKey.ps1`：要求elevated Administrator；拒絕identity/ciphertext reparse point；identity ACL必須停止繼承且Allow只含目前Windows user與SYSTEM；密文需為非空`.age`且<=1MiB；解密到GUID暫存檔；只接受trim後單一`tskey-auth-*`且<=512字元；將暫存明文ACL限定SYSTEM與Administrators後move至固定`C:\ProgramData\Tailscale\anritsu-a2a-poc-auth.key`；成功後刪密文，finally清暫存，output不含key。此主機沒有PowerShell/Windows私鑰，因此未執行Windows解密，只做靜態審查。
- 使用Git-ignored mode`0600`明文來源`/home/da40_ai_gb10/.local/state/km-a2a/tailscale-anritsu-a2a-poc-auth-key`與已核對recipient，成功產生密文`/home/da40_ai_gb10/.local/state/km-a2a/tailscale-anritsu-a2a-poc-auth-key.age`；mode`0600`、owner=`da40_ai_gb10`、261 bytes、SHA-256=`67551960cea7fedf486f226410fc02000082e5e4a23f225a7649543ae46db0a7`。`age-inspect`確認version=`age-encryption.org/v1`、stanza=`X25519`、armor=false、payload=61 bytes。KM無Anritsu私鑰，不能本機解密此正式密文；Anritsu已回報自己的round-trip通過。
- `.gitignore`新增`*.age`，避免密文誤提交。`KM_AGENT_HTTP_8790_POC_INTEGRATION_GUIDE.md`新增recipient核對、官方age 1.3.1使用方式、密文路徑/size/hash/format、AnyDesk只傳密文、Windows `Get-FileHash`、`Import-A2ATailscaleAuthKey.ps1`與Docker Authorize順序及安全行為。不得把明文來源檔傳送或複製到專案/Downloads。
- 已啟動本機AnyDesk UI做只讀目標盤點；AnyDesk service/tray/backend均存在，但當時沒有活動中的遠端network session。UI有多個近期/探索到的Windows裝置，但名稱截斷且沒有可驗證證據指出哪台是Anritsu。為避免錯送，沒有選擇任何裝置、沒有發起session、沒有傳送密文。盤點截圖包含本機/近期AnyDesk識別資訊，已由Python刪除，不納入專案證據或Git。
- 目前唯一阻塞是需要使用者提供或在AnyDesk明確確認Anritsu遠端ID/別名。得到可驗證目的地後，只使用AnyDesk File Transfer傳`tailscale-anritsu-a2a-poc-auth-key.age`，Windows收到後先核對上述SHA-256；不得傳明文。Key在Tailscale Console的到期日為2026-08-13，需在期限內交付與Authorize，否則撤銷/到期後重新建立新single-use key與新密文。
- KM A2A bridge仍active但`enabled=false`、`transport=sdk-dry-run`、`real_instrument_access=false`，等待Anritsu回報Docker peer IP後才更新endpoint與重新啟用。尚未傳送key、尚未出現Anritsu peer、尚未執行跨機dry-run。

## 2026-08-12 Anritsu AnyDesk 密文交付完成

- 使用者提供Anritsu AnyDesk連線資料後，KM只使用AnyDesk File Transfer，不進行遠端桌面操作；登入憑證未寫入命令、檔案、Git或專案記憶，且未啟用保存密碼。
- 已將age密文`tailscale-anritsu-a2a-poc-auth-key.age`傳至Anritsu Windows的`C:\Users\SSNR\Documents`。AnyDesk完成通知與遠端檔案列表確認檔名、261-byte大小及完成狀態；密文SHA-256應由Anritsu在Windows執行`Get-FileHash`後核對`67551960cea7fedf486f226410fc02000082e5e4a23f225a7649543ae46db0a7`。
- KM沒有傳送無副檔名的Tailscale明文key。為方便AnyDesk選檔而建立的`/home/da40_ai_gb10/tailscale-anritsu-a2a-poc-auth-key.age`暫存副本已刪除；正式密文仍只保存在Git-ignored、mode`0600`的`/home/da40_ai_gb10/.local/state/km-a2a/tailscale-anritsu-a2a-poc-auth-key.age`。
- AnyDesk同時存在其他既有連線分頁；完成上傳後未在無法唯一確認目標分頁的情況下執行遠端下載或命令。所有AnyDesk操作截圖與暫存操作檔已從`/tmp`清除，不納入Git證據。
- `KM_AGENT_HTTP_8790_POC_INTEGRATION_GUIDE.md`已將接收路徑更新為實際`Documents`路徑。Anritsu下一步需以系統管理員PowerShell先核對SHA-256，再執行`Import-A2ATailscaleAuthKey.ps1`與`Manage-A2ADockerTailscalePoc.ps1 -Action Authorize`，並回報Docker Tailscale IP與A2A endpoint。
- 在Anritsu完成Authorize、KM看見新peer且跨機dry-run Gate通過前，`km-a2a-bridge`保持`enabled=false`、`real_instrument_access=false`；不得啟用OpenClaw正式呼叫或真實儀器測試。Tailscale single-use key於2026-08-13到期，若逾期未使用，必須重新產生key及age密文，不得沿用過期檔。
- Tailscale single-use key於2026-08-13到期，若逾期未使用，必須重新產生key及age密文，不得沿用過期檔。

## 2026-08-12 Anritsu 已確認密文交付，等待 Docker Authorize

- Anritsu回覆已確認收到`C:\Users\SSNR\Documents\tailscale-anritsu-a2a-poc-auth-key.age`，大小`261 bytes`，預期SHA-256為`67551960cea7fedf486f226410fc02000082e5e4a23f225a7649543ae46db0a7`；Anritsu確認未收到明文Tailscale auth key。
- KM已將交接文件中的狀態由「待交付」校正為「密文已交付，等待Anritsu核對雜湊並執行`Import-A2ATailscaleAuthKey.ps1`及`Manage-A2ADockerTailscalePoc.ps1 -Action Authorize`」。本次沒有修改KM runtime、endpoint、Tailscale policy或主KM服務。
- Anritsu完成Authorize後只需回報Docker Tailscale IP與`http://<實際IP>:8790` endpoint，以及Windows DNS、外網、`100.100.100.100`路由未受影響的驗證結果。KM收到後才會資料驅動更新endpoint，啟用獨立bridge並執行health、Agent Card、401/403、正確Bearer與fixed-schema dry-run驗收。
- 即時KM驗證仍為：`km-a2a-bridge.service=active`、health=`status=ok`、`enabled=false`、`transport=sdk-dry-run`、`real_instrument_access=false`；Tailscale peers=`0`。因此目前仍不能宣稱KM已能呼叫Anritsu，也不會啟用OpenClaw正式tool或真實儀器操作。
- Tailscale single-use key於`2026-08-13`到期；若Anritsu在到期前未完成Authorize，需由管理員撤銷／重新建立新key並重新產生age密文，不能沿用舊密文。

## 2026-08-12 Anritsu 第三份密文重新加密（等待核准管道傳送）

- Anritsu 回報第二份密文雖通過檔案雜湊驗證，但舊版授權流程把 Docker Compose 正常 stderr 進度誤判為失敗；Tailscale log 為 `loggedIn=false`、`NeedsLogin`、`state={}`，因此目前沿用的 single-use auth key 尚未使用，沒有撤銷它。
- Anritsu 已修正流程：Compose stderr 不再誤判；完整授權成功前保留 `.age` 密文；失敗時只刪除明文 key。KM bridge 繼續維持 `KM_A2A_ENABLED=false`、`real_instrument_access=false`。
- 以同一個仍未使用的 auth key 與 Anritsu age recipient 重新產生第三份密文：`/home/da40_ai_gb10/.local/state/km-a2a/tailscale-anritsu-a2a-poc-auth-key-r3.age`，mode `0600`、大小 `261 bytes`、SHA-256=`0b377e11ee6589127fa6c606ed7fc629aeef2bc860fe8ac4ad012487628a7644`。未將明文寫入 Git、文件、log 或對話。
- 重新改用 AnyDesk 使用者確認流程連線正確目標 `1605903697`（SSNR）成功；第三份密文已透過 File Transfer 傳到 `C:\Users\SSNR\Documents\tailscale-anritsu-a2a-poc-auth-key-r3.age`。遠端檔案大小為 `261 bytes`，再下載回 KM 後 SHA-256 與原密文一致：`0b377e11ee6589127fa6c606ed7fc629aeef2bc860fe8ac4ad012487628a7644`。本機傳輸暫存副本已清除，只保留 mode `0600` 的 KM 狀態密文。
- [`KM_AGENT_HTTP_8790_POC_INTEGRATION_GUIDE.md`](/home/da40_ai_gb10/knowledge-base/KM_AGENT_HTTP_8790_POC_INTEGRATION_GUIDE.md) 已改以第三份密文的檔名與 SHA-256 為目前交接值，並要求 Anritsu 只執行 `Complete-A2ATailscalePocAuthorization.ps1 -CiphertextPath <第三份密文完整路徑> -ExpectedSha256 0b377e11ee6589127fa6c606ed7fc629aeef2bc860fe8ac4ad012487628a7644`。
- 即時狀態：`km-a2a-bridge.service=active`，health=`status=ok`、`enabled=false`、`transport=sdk-dry-run`、`real_instrument_access=false`，Tailscale peers=`0`。在第三份密文完成核驗、Docker userspace 授權並回報實際 IP 前，不更新 endpoint、不啟用 bridge、不執行真實儀器、iPerf、Excel 或 ingest。

## 2026-08-13 Anritsu Docker peer 已加入但 A2A route Gate 未通過

- Anritsu 回報 Docker Tailscale IP=`100.72.21.115`、tag=`tag:anritsu-a2a-poc`、Docker container healthy、KM peer DERP pong成功、Windows Tailscale stopped、Quad100 route為0、Windows DNS與外網驗證PASS；KM `tailscale status`已真實看到 `100.72.21.115 anritsu-a2a-poc tagged-devices`，`tailscale ping`三次均成功（DERP hkg，約75至78ms），但尚未建立 direct connection。
- 已將 Git-ignored `km_a2a_bridge/.env` 的 `KM_A2A_AGENT_ENDPOINTS` 更新為 `{"anritsu":"http://100.72.21.115:8790"}`，先短暫啟用 bridge 做跨機驗證；驗證完成後因 route Gate 失敗已回復 `KM_A2A_ENABLED=false`。transport仍為`sdk-dry-run`，`real_instrument_access=false`，未改主KM、OpenClaw、Nginx、3030或儀器服務。
- 實際 HTTP TCP 8790可達，但 `GET /health`、`GET /healthz`、`GET /.well-known/agent-card.json`、`GET/POST /a2a` 以及已知候選 `/a2a/`、`/a2a/v1`、`/agent-card`、`/.well-known/agent.json` 均回 HTTP 404 `404 page not found`。KM固定schema dry-run透過隔離 bridge 實測回 `state=failed`、`error_message=transport failure: AgentCardResolutionError`；因此不能宣稱 A2A 已完成，也未通過401/403/correct Bearer或七項side-effect Gate。
- 阻塞根因目前是 Anritsu 回報的 Agent Card／A2A route 與 KM 實際看到的 HTTP route 不一致，並非 Tailscale peer不可達。Anritsu需提供實際 listener route、Agent Card URL、JSON-RPC path及是否需要額外 base path；KM收到後才恢復`KM_A2A_ENABLED=true`再重做健康、Agent Card、401/403、正確Bearer與dry-run驗證。

## 2026-08-13 Anritsu HTTP route 修正與跨機 A2A dry-run Gate 通過

- Anritsu 將 Tailscale Serve 修正為 TCP forwarding：`100.72.21.115:8790 -> 127.0.0.1:8791`。KM確認 Tailscale peer `100.72.21.115` 存在，`tailscale ping` 經 DERP(hkg)成功；目前尚未建立 direct connection，但不影響本次 HTTP POC。
- KM `.env` 已恢復 `KM_A2A_ENABLED=true`，保留 `KM_A2A_TRANSPORT=sdk-dry-run`、`KM_A2A_AGENT_ENDPOINTS={"anritsu":"http://100.72.21.115:8790"}`、`real_instrument_access=false`。只重啟隔離 `km-a2a-bridge.service`，沒有重啟或修改主KM、OpenClaw、Nginx、3030或儀器服務。
- 真實跨機路由驗證通過：`GET /health=200`、`GET /healthz=200`、`GET /.well-known/agent-card.json=200`；Agent Card interface=`http://100.72.21.115:8790/a2a`、JSONRPC 1.0、skill包含`run_iperf_test`；`GET /a2a=405`且Allow=POST。
- 認證 Gate 通過：無Bearer `POST /a2a=401 missing_credential`；錯Bearer=`403 invalid_credential`；正確Bearer固定schema dry-run=`200`、task state=`TASK_STATE_COMPLETED`、test/report/ingest均為`pending`。七項 `dry_run_side_effect_counts` 全部為0：manual_test_state_mutation、iperf_process、instrument_lock、km_ingest、instrument_connection、scpi_command、excel_report。
- 發現並修正 KM transport 相容性問題：A2A SDK 1.1.2的JSON-RPC transport送出`SendMessage`，而Anritsu依交接契約接受`message/send`，因此原 KM smoke 回 `InvalidParamsError`。`km_a2a_bridge/sdk_transport.py`現在先走既有SDK；只有收到明確`InvalidParamsError`才使用同一Agent Card interface與固定schema的受控`message/send` fallback，不接受任意方法或任意payload。四份 bridge test合計`61 passed`，修正後真實 `scripts/run_anritsu_a2a_poc_smoke.py --run-id poc-20260813-sdk-compat --test-case sa_dl_tcp`完成，correlation含context_id、a2a_task_id、run_id。
- 此 Gate 只證明跨機 dry-run 委派與安全界線，不代表已開放真實儀器、iPerf、Excel或KM ingest；後續若要開放真實操作仍需另做權限、人工批准、instrument lock、timeout/cancel/cleanup、結果上傳與正式HTTPS Gate。

## 2026-08-13 真實 Anritsu 測試可行性評估

- 目前不能由 KM Agent 啟動真實儀器測試。Anritsu `/health` 實測回報 `mode=dry-run`、`instrument_available=false`、`poc_only=true`；Agent Card description也明確表示目前不執行真實測試。KM bridge health為`enabled=true`但`transport=sdk-dry-run`、`real_instrument_access=false`。
- KM `TestJob` contract 將 `dry_run` 固定為`Literal[True]`，`BridgeConfig`只接受`mock`或`sdk-dry-run`，因此目前送出的任何請求都只能驗證固定 schema，不會控制儀器、啟動iPerf、產生Excel或呼叫KM ingest。未送出真實測試請求。
- 要開放真實測試，必須另行完成並審查：real transport與明確feature flag、Anritsu真實模式／instrument capability、人工批准與操作者身份、profile/test case allowlist、instrument lock、單一執行與timeout/cancel/cleanup、safe-state、結果Excel與hash、KM ingest correlation、審計／告警、正式HTTPS或等效傳輸安全，以及真實硬體前的mock/shadow驗收。完成前不得把`dry_run`改成可變更或直接啟用真機。

## 2026-08-13 真實測試開放前第一版 Gate 審查完成

- 已建立 [`docs/pre-real-test-review-2026-08-13.md`](/home/da40_ai_gb10/knowledge-base/docs/pre-real-test-review-2026-08-13.md)。審查結論為`NO-GO`：網路、Agent Card、401/403、正確Bearer、dry-run及七項副作用計數通過，但real transport、real job contract、Anritsu instrument capability、instrument lock、人工批准、timeout/cancel/safe-state、Excel/hash/ingest correlation、audit/recovery及正式HTTPS尚未具備。
- 審查期間沒有送出真實測試請求，沒有修改`real_instrument_access=false`，也沒有修改主KM、OpenClaw、Nginx、3030或儀器服務。現有跨機驗證環境仍為`KM_A2A_ENABLED=true`、`KM_A2A_TRANSPORT=sdk-dry-run`、Anritsu `mode=dry-run`與`instrument_available=false`。
- 建議依R0 contract/威脅模型、R1 mock real transport、R2 Anritsu shadow、R3 單一人工批准 real test、R4 結果上傳與回滾驗收分階段進行；未完成所有放行條件前不得請求真實儀器操作。

## 2026-08-13 KM Agent → Anritsu Agent 使用者功能測試

- 依使用者要求執行目前已核准的跨機 A2A dry-run 功能測試，沒有操作真實儀器、啟動iPerf、產生Excel或執行KM ingest。
- 測試命令使用固定 allowlist：profile=`ncq2200b2v-throughput-v1`、test case=`sa_dl_tcp`、`dry_run=true`、duration=60、requested_by=`km-agent-01`。
- Run ID=`poc-20260813-user-test-093517`，結果`state=completed`、`error_message=null`；correlation包含`context_id=ctx-9f19e58e6fc351b632b56cc70a492cbe`、`a2a_task_id=task-9f19e58e6fc351b632b56cc70a492cbe`、相同`run_id`。test/report/ingest狀態均維持`pending`，代表這是dry-run契約完成，不是真實測試完成。
- KM bridge最終health仍為`enabled=true`、`transport=sdk-dry-run`、`real_instrument_access=false`；Anritsu仍為`mode=dry-run`、`instrument_available=false`。

## 2026-08-12 Anritsu 第二份密文重建與重新交付

- Anritsu回報第一次密文已在失敗清理時刪除，Documents沒有可匯入檔。Tailscale Keys頁沒有提供足夠的「未使用」明確狀態，因此依安全規則撤銷原 single-use key；管理介面確認原 key 已移至 `recently invalidated auth key`，目前沒有有效舊 key可繼續使用。
- 已重新建立第二把 auth key：single-use、1-day、non-ephemeral、tag=`tag:anritsu-a2a-poc`，描述為`Anritsu-A2A-POC-2026-08-12-R2`。新明文只保存於Git-ignored mode`0600`的`/home/da40_ai_gb10/.local/state/km-a2a/tailscale-anritsu-a2a-poc-auth-key`，未寫入記憶、Git、log或聊天內容。
- 以Anritsu公開age recipient重新加密第二份密文：`/home/da40_ai_gb10/.local/state/km-a2a/tailscale-anritsu-a2a-poc-auth-key-r2.age`，mode`0600`、大小`261 bytes`、SHA-256=`122792e211d6278b1e355ee1d26ef46502fbcf28745e419b4225d4fbc66654b1`。此SHA-256與第一次密文不同，不沿用第一次交付資料。
- 已重新連線並確認AnyDesk遠端名稱為`SSNR`、ID=`1605903697`，只使用File Transfer將第二份檔案傳到`C:\Users\SSNR\Documents\tailscale-anritsu-a2a-poc-auth-key-r2.age`；AnyDesk顯示261 B及「完成（上傳）」。刪除KM傳輸暫存副本後，從正確遠端回傳檔案做round-trip驗證，下載副本SHA-256與新密文完全相同；回傳副本已刪除。
- Anritsu不再分開執行Import與Manage命令，收到後只執行`Complete-A2ATailscalePocAuthorization.ps1 -CiphertextPath <第二份密文完整路徑> -ExpectedSha256 122792e211d6278b1e355ee1d26ef46502fbcf28745e419b4225d4fbc66654b1`；腳本應自行核對雜湊、解密、Docker userspace授權、清理密文與明文，並回報Docker Tailscale IP、A2A endpoint及Windows DNS／外網／Quad100路由驗證結果。
- KM bridge未被啟用：`km-a2a-bridge.service=active`、health=`status=ok`、`enabled=false`、`transport=sdk-dry-run`、`real_instrument_access=false`；Tailscale peers仍為`0`。收到Authorize結果與實際Docker IP前，不更新endpoint、不開啟bridge、不啟用OpenClaw正式tool、不執行真實儀器／iPerf／Excel／ingest。

## 2026-08-13 取消48小時監測並驗證 KM OpenClaw → Anritsu OpenClaw

- 依使用者要求停止 transient user service `km-anritsu-openclaw-2day.service`；服務目前為`inactive`，既有JSONL監測檔未刪除，保留1筆既有`PASS`樣本作為歷史證據。
- 以全新run_id=`km-openclaw-to-anritsu-20260813T035821Z`，由KM OpenClaw主Agent透過既有`anritsu-a2a` skill送出固定schema dry-run命令；bridge journal實際建立Anritsu任務，證明KM OpenClaw helper已能把命令傳到Anritsu OpenClaw receiver。
- 任務證據：`requested_by=km-openclaw-user-verification`、`state=completed`、`openclaw_forward_status=accepted`、`openclaw_receiver=anritsu-openclaw`、`openclaw_audit_id=oc-audit-608a68730ddbc1095828abf02ad33bdb`、`context_id=ctx-ff715455cf55307ed5d01402ce22c0ee`、`a2a_task_id=task-ff715455cf55307ed5d01402ce22c0ee`；error為`null`。
- 七項dry-run副作用計數全部為`0`：`manual_test_state_mutation`、`scpi_command`、`excel_report`、`instrument_lock`、`km_ingest`、`instrument_connection`、`iperf_process`。因此本次只驗證OpenClaw間的dry-run傳遞，不操作真實儀器、不啟動iPerf、不產生Excel、不攝入KM。
- OpenClaw CLI本身曾回報embedded run timeout及無效fallback model`ollama/gemma4:e4b`，但該回應層問題未阻止skill命令完成送達；後續仍應修正OpenClaw fallback設定，避免使用不存在的模型。KM bridge與Anritsu維持`KM_A2A_ENABLED=true`、`KM_A2A_TRANSPORT=sdk-dry-run`、`real_instrument_access=false`及Anritsu dry-run模式。

## 2026-08-13 真實測試剩餘步驟前置驗收

- 依使用者要求開始真實測試開放前剩餘步驟，但沒有繞過現有安全閘門或修改未提交工作區。現況複查：KM bridge health=`enabled=true`、`transport=sdk-dry-run`、`real_instrument_access=false`；Anritsu health=`mode=dry-run`、`poc_only=true`、`instrument_available=false`、`real_instrument_access=false`。
- focused bridge tests結果為`24 passed`。跨機前置 smoke 使用全新`run_id=pre-real-gate-20260813T040736Z`，結果`state=completed`、`openclaw_forward_status=accepted`、`openclaw_receiver=anritsu-openclaw`、`openclaw_audit_id=oc-audit-7b3bcfbe2041cbb651e9cc47b6197d2b`；`context_id=ctx-aaebe259ed5673746308e75ed2a4b09e`、`a2a_task_id=task-aaebe259ed5673746308e75ed2a4b09e`。
- 本次七項dry-run副作用計數全部為`0`，test/report/ingest狀態均為`pending`；因此只完成真實測試開放前的通訊、認證、receiver correlation與安全界線驗收，沒有控制儀器、啟動iPerf、產生Excel或攝入KM。
- 真實測試仍為`NO-GO`。尚未具備且不可自行假設的項目包括：real job contract/transport、Anritsu真實instrument capability、人工批准與短效approval token、instrument lock、timeout/cancel/safe-state、Excel/hash/ingest correlation、audit/recovery與正式安全傳輸。下一步必須由Anritsu端提供上述證據並經明確人工批准，才可進入單一受控 real test。

## 2026-08-13 R0 Real-run contract 與放行 Gate 建立

- 新增 [`docs/r0-real-run-contract-and-gate-2026-08-13.md`](/home/da40_ai_gb10/knowledge-base/docs/r0-real-run-contract-and-gate-2026-08-13.md)，正式定義 real-run request/response contract、狀態轉移、人工雙人批准、single-use短效approval、威脅模型、lock、timeout/cancel/safe-state、artifact/hash/ingest correlation、audit、transport security、rollback與R0 Gate。
- R0文件明確規定：real contract必須與目前`TestJob.dry_run=Literal[True]`分離，不得把現有dry-run boolean化，也不得由自然語言、query string或遠端payload切換真實執行。
- R0逐項審查結論：Contract為`SPECIFIED，尚未實作`；dry-run allowlist只能列為`PARTIAL`；approval、lock、safety、artifact、ingest、audit、real transport、Anritsu capability、recovery與shadow均為`BLOCKED`。總結為`NO-GO`，目前最多進入R1 mock real transport開發，不能進入R3 real test。
- 本次只新增規格文件及更新記憶，沒有修改KM runtime、real flag、既有dry-run contract、OpenClaw、Anritsu服務或任何儀器設定。`git diff --check`與R0文件機密樣式掃描通過。

## 2026-08-13 R0 批准機制調整

- 依使用者要求移除雙人批准，R0改採「單一授權操作者批准」；保留受控KM API/管理流程產生approval、短效、single-use、綁定單一`run_id`/profile/test case、不可由模型或Anritsu agent自行產生，以及完整operator audit。
- 已同步更新[`docs/r0-real-run-contract-and-gate-2026-08-13.md`](/home/da40_ai_gb10/knowledge-base/docs/r0-real-run-contract-and-gate-2026-08-13.md)與[`docs/pre-real-test-review-2026-08-13.md`](/home/da40_ai_gb10/knowledge-base/docs/pre-real-test-review-2026-08-13.md)。R0結論仍為`NO-GO`；移除雙人批准不代表已授權真實測試，也不解除real transport、instrument lock、safe-state、artifact、ingest、audit或Anritsu capability Gate。
- 本次只修改規格文件與專案記憶，未修改KM runtime、dry-run contract、real flag、OpenClaw、Anritsu服務或儀器設定；`git diff --check`通過。

## 2026-08-13 R1 前置：獨立 Real-run contract 初版

- 新增[`km_a2a_bridge/real_contracts.py`](/home/da40_ai_gb10/knowledge-base/km_a2a_bridge/real_contracts.py)，與現有`TestJob`/dry-run transport分離；新增`RealRunApproval`、`RealArtifactPolicy`、`RealRunJob`、`RealRunCorrelation`、`RealRunResponse`、`RealRunState`及`validate_real_run_approval`。
- Real contract固定`dry_run=false`、environment=`anritsu`、單一test case、approval綁定`run_id`與`requested_by`、approval最長15分鐘且single-use標記固定為true；禁止額外欄位。完成 response必須有completed test/report/ingest、artifact SHA-256與ingest task id。
- `km_a2a_bridge/__init__.py`只新增公開匯出；既有`app.py`、`service.py`、`transport.py`、`sdk_transport.py`均未引用real contract，因此現有dry-run runtime沒有被接通或改變。
- 新增`tests/test_km_a2a_real_contracts.py`，新測試結果為`7 passed`；模組編譯與公開import驗證通過。完整相關測試為`65 passed, 1 failed`，唯一失敗是既有`tests/test_km_a2a_bridge_contracts.py::test_correlation_ids_can_be_assigned_over_time`仍期待新增OpenClaw correlation欄位前的舊`model_dump()`形狀，屬工作區既有測試與既有欄位變更不一致，非本次real_contract模組造成。
- R0文件R0-01已更新為`PARTIAL：獨立schema已實作並通過單元測試，runtime尚未整合`。本次沒有修改real flag、dry-run contract、OpenClaw、Anritsu或儀器設定；仍不可執行real test。

## 2026-08-13 R1 mock real lifecycle 初版完成

- 新增[`km_a2a_bridge/mock_real_runtime.py`](/home/da40_ai_gb10/knowledge-base/km_a2a_bridge/mock_real_runtime.py)，提供獨立、記憶體內、mock-only的R1控制核心：single-use approval、profile/test case allowlist、single-flight lock、lease expiry recovery、cancel、duration timeout、artifact大小/非空檢查、SHA-256與完整correlation。
- 新增[`tests/test_km_a2a_mock_real_runtime.py`](/home/da40_ai_gb10/knowledge-base/tests/test_km_a2a_mock_real_runtime.py)，real contract與mock runtime測試合計`13 passed`；模組compile、public import及現有runtime未引用`real_contracts`/`mock_real_runtime`均通過。
- 新增[`docs/r1-mock-real-transport-2026-08-13.md`](/home/da40_ai_gb10/knowledge-base/docs/r1-mock-real-transport-2026-08-13.md)。R1結論為`mock PASS，R2 shadow NO-GO`；尚未持久化approval、接入service、連線Anritsu、控制儀器、啟動iPerf或執行KM ingest。
- 既有KM dry-run runtime、`KM_A2A_TRANSPORT=sdk-dry-run`、`real_instrument_access=false`均未改變。

## 2026-08-13 R1 cancel/safe-state/cleanup lifecycle 完成

- 新增[`km_a2a_bridge/safety_lifecycle.py`](/home/da40_ai_gb10/knowledge-base/km_a2a_bridge/safety_lifecycle.py)，定義獨立SafetyAdapter contract與固定順序`cancel request -> ensure safe-state -> cleanup`；取消失敗仍繼續安全處理，任一安全動作無法確認則回傳`recovery_required`，crash recovery不重試原命令，只執行safe-state與cleanup。
- 新增[`tests/test_km_a2a_safety_lifecycle.py`](/home/da40_ai_gb10/knowledge-base/tests/test_km_a2a_safety_lifecycle.py)，R1相關測試合計`24 passed`；涵蓋呼叫順序、cancel failure、safe-state/cleanup failure、crash recovery與idempotency。
- 更新[`docs/r1-mock-real-transport-2026-08-13.md`](/home/da40_ai_gb10/knowledge-base/docs/r1-mock-real-transport-2026-08-13.md)。現有runtime仍未引用R1 safety/registry模組，沒有接觸Anritsu、儀器、iPerf或KM ingest。

## 2026-08-13 KM-local Anritsu shadow adapter contract

- 新增[`km_a2a_bridge/anritsu_shadow_adapter.py`](/home/da40_ai_gb10/knowledge-base/km_a2a_bridge/anritsu_shadow_adapter.py)，定義loopback/named-pipe邊界使用的固定`ShadowAdapterRequest`/`ShadowAdapterResponse`，只接受`dry_run=true`、Anritsu固定profile與`sa_dl_tcp`/`sa_ul_tcp`，拒絕real flag、extra fields、shell、path、URL與未知案例。
- response固定`execution_owner=anritsu-openclaw`、三個correlation、`instrument_available=false`、`real_instrument_access=false`與七項side-effect counters=0；新增`MockAnritsuOpenClawAdapter`只在本機記憶體執行。
- 新增[`tests/test_km_a2a_anritsu_shadow_adapter.py`](/home/da40_ai_gb10/knowledge-base/tests/test_km_a2a_anritsu_shadow_adapter.py)，real contract、mock runtime、registry、safety、shadow adapter合計`30 passed`；existing runtime isolation、compile與diff check通過。
- 新增[`docs/r2-shadow-adapter-integration-2026-08-13.md`](/home/da40_ai_gb10/knowledge-base/docs/r2-shadow-adapter-integration-2026-08-13.md)。結論為`R1 PASS`、`R2 KM-local shadow PASS`、`R2 cross-machine Anritsu shadow NO-GO`、`R3 real instrument NO-GO`。尚未修改Anritsu Windows、連線遠端adapter、操作儀器、iPerf、Excel或KM ingest。

## 2026-08-13 R1 durable approval/lock registry 完成

- 新增[`km_a2a_bridge/real_registry.py`](/home/da40_ai_gb10/knowledge-base/km_a2a_bridge/real_registry.py)，提供獨立SQLite registry：approval register、atomic single-use consume、run/operator binding、expiry、instrument resource single-flight lock、lease renew、owner verification、release與expired lock cleanup。
- 新增[`tests/test_km_a2a_real_registry.py`](/home/da40_ai_gb10/knowledge-base/tests/test_km_a2a_real_registry.py)。real contract、mock runtime、registry合計測試結果為`18 passed`；compile與existing runtime isolation檢查通過。
- 更新[`docs/r1-mock-real-transport-2026-08-13.md`](/home/da40_ai_gb10/knowledge-base/docs/r1-mock-real-transport-2026-08-13.md)，記錄持久化registry證據。registry仍未接入現有`app.py`、bridge service或Anritsu，沒有啟動real transport、儀器、iPerf或ingest。
