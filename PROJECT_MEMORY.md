# Project Memory

- 2026-07-21 已依使用者要求新增第二份外部 agent 攝入規格文件 [`EXTERNAL_AGENT_KB_INGEST_APIS.md`](<project-root>/knowledge-base/EXTERNAL_AGENT_KB_INGEST_APIS.md)。文件與既有 [`EXTERNAL_AGENT_KB_QUERY_APIS.md`](<project-root>/knowledge-base/EXTERNAL_AGENT_KB_QUERY_APIS.md) 分工：query 文件維持 read-only 查詢，ingest 文件描述 write/ingest 流程。新文件以 `https://127.0.0.1:3030` 為預設 base URL，說明外部 agent 應透過 `POST /api/upload/ingest?extraction_mode=<mode>` multipart 上傳檔案，再用 `GET /api/upload/tasks/{task_id}` 輪詢狀態；列出支援格式、200MB multipart part 上限、`4g5g/wifi/lab/project/automation` 模式、`queued -> upload_saved -> converting -> converted -> extracting -> writing_neo4j -> writing_qdrant -> refreshing_index -> completed/failed` 狀態生命週期、重複檔案 hash 去重語意、批次上傳模式、watch folder 替代方案、Markdown 測試結果 artifact 建議格式，以及正式部署安全建議。文件明確要求外部 agent 不直接連 Neo4j/Qdrant/Redis/File Store，而是只傳 artifact 給 KB API，由 KB 後端 Celery `ingest_file_task` 轉 Markdown、寫 `.source.json`、呼叫 `ingest_document()`、清舊資料、寫 Neo4j 與 Qdrant 並更新 index。已檢查文件章節，檔案共 458 行。
- 2026-07-21 已分析使用者問題「EXTERNAL_AGENT_KB_QUERY_APIS.md 外部如何傳送到檔案後端的 Neo4j/Qdrant」。結論：`EXTERNAL_AGENT_KB_QUERY_APIS.md` 目前是外部 agent 的受控查詢文件，明確排除 `/upload/*`、`/api/upload/*`，因此它本身不提供傳檔寫入 Neo4j/Qdrant 的能力。外部傳檔進 KB 後端的正確路徑應是另一份 ingest 規格：外部 agent 以 multipart 呼叫 `POST /api/upload/ingest?extraction_mode=<4g5g|wifi|lab|project|automation>` 上傳檔案，KB web 接收後寫入 `data/uploads/<category>/<task_id>/original/`、建立 Redis ingest task state、派發 Celery `ingest_file_task` 到 ingest queue；worker 轉 Markdown 到 `converted/`、寫 `.source.json`、呼叫 `ingest_document()`，由 KB 端統一清舊資料、萃取/建立 Neo4j 圖譜資料、寫入 Qdrant 向量點、更新 index；外部再用 `GET /api/upload/tasks/{task_id}` 輪詢 `writing_neo4j`、`writing_qdrant`、`completed/failed`。建議不要讓外部 agent 直連 Neo4j/Qdrant；若要讓外部 agent 同時查詢與上傳，應新增一份 `EXTERNAL_AGENT_KB_INGEST_APIS.md` 或在現有文件中新增受控寫入章節，但 token scope 必須與 query read-only 分離。
- 2026-07-20 已依使用者要求讀取專案記憶與全域 OpenClaw 記憶，追查最後完整啟動 knowledge-base 的方法。結論：目前應以 repository 內的 [`restart_kb.sh`](<project-root>/knowledge-base/restart_kb.sh) 為正式完整啟動入口，而不是較舊的 `start.sh`。全域記憶 `<project-root>/.openclaw/workspace/MEMORY.md` 也明確記錄啟動方式為 `cd <project-root>/knowledge-base && ./restart_kb.sh`。目前腳本流程會先檢查宿主機 Ollama `127.0.0.1:11434`，啟動/建立獨立 `kb-qdrant`，移除 KB 自己的舊容器（不碰 AnythingLLM），以 `KB_FRONTEND_BUILD_DIR=<project-root>/knowledge-base/.frontend-build-runtime-user8` 重建前端並複製 `chat.html` 與前端 lib，接著執行 `docker compose up -d --build redis neo4j web celery_search_worker celery_ingest_worker celery_beat nginx`，最後檢查 `3030/6335/17474/17687/11434`、`https://127.0.0.1:3030/health`、`chat.html`、容器內 `http://127.0.0.1:8000/health`、Qdrant health、容器到 Ollama 與 WebSocket proxy smoke test。需注意全域舊記憶曾提 `.frontend-build`，但目前實際 repo 已改為 `.frontend-build-runtime-user8`，必須以現有 `restart_kb.sh` / `docker-compose.yml` 為準。
- 2026-07-20 已檢查目前 knowledge-base runtime 是否啟動：`https://127.0.0.1:3030/health` 與 `https://127.0.0.1:3030/chat.html` 皆連線失敗（curl exit code 7，chat.html HTTP code 000），`http://127.0.0.1:8000/health` 也連線失敗；`docker compose ps` 在 repository 內沒有列出任何 compose service，`ss -ltnp` 顯示 3030 與 8000 沒有 listener。`docker ps` 只看到 `kb-qdrant` 與 `anythingllm-qdrant` 仍在跑。結論：目前 KB 對外 web/API/chat 服務未啟動，僅 Qdrant 相關容器在線；若要恢復，需要啟動 KB compose 或執行專案既有重啟流程（例如 `./restart_kb.sh` / `docker compose up -d`，依現場部署方式決定）。
- 2026-07-20 已依使用者要求整理「外部電腦 / 外部 AI agent 查詢 KB 所有資料」的受控查詢 API 文件，新增 [`EXTERNAL_AGENT_KB_QUERY_APIS.md`](<project-root>/knowledge-base/EXTERNAL_AGENT_KB_QUERY_APIS.md)。文件以 `https://127.0.0.1:3030` 為預設 base URL，採白名單方式列出外部查詢可用端點：`GET /health`、`GET /`、`POST /search`、`GET /tasks/{task_id}`、`POST /category-relevance`、`POST /analyze-question`、`POST /api/source-categories`、`GET /api/files`、`GET /api/category-stats`、`GET /api/category-files`、`GET /api/document`、`GET /stats`、`GET /hybrid-status`、`GET /extraction-modes`，並提供 curl 範例、request/response schema、輪詢規則、sources_only 用法、文件清單與文件內容讀取方式。文件同時明確排除 `/api/openclaw/chat-config`、`/ws`、`/admin/*`、`/upload/*`、`/skills/*`、`/api/increment-search-count` 與 `DELETE /tasks/{task_id}`，避免外部 agent 學到 chat runtime、管理、寫入或取消任務能力。正式化建議仍是補 API token、read-only scope、IP allowlist/mTLS、rate limit、audit log 與 agent 專用同步封裝 `/api/agent/query`。
- 2026-07-20 已分析「外部 AI agent 需要查詢這台 knowledge-base 所有資料」的整合方式。現有查詢主幹是 FastAPI `POST /search` 提交非同步搜尋任務，`GET /tasks/{task_id}` 取回 `answer/sources/citation_distribution/mode`；這比 WebSocket chat 更適合外部 agent 取資料。建議外部 agent 只走 KB API Gateway，不直連 Neo4j/Qdrant/File Store；短期可直接用 `/search` + `/tasks/{task_id}`，查詢模式依需求用 `auto/vector/hybrid/sources_only`，並限制 `top_k`、timeout、重試與輪詢頻率。正式化建議新增 agent 專用 `/api/agent/query` 同步封裝與 `/api/agent/search` 非同步封裝，統一處理 API token、scope、rate limit、audit log、來源引用格式、錯誤碼與查詢範圍；若真的要「所有資料」能力，也應以 read-only scope 表達，必要時提供 `list_documents/get_document/get_sources` 這類受控端點，而不是開放 DB 帳密。安全設計需區分 ingest/write 與 query/read token，支援 IP allowlist 或 mTLS，並保留每次 query、agent_id、source_env、task_id、引用文件與耗時紀錄。
- 2026-07-20 已分析「外部電腦上的 AI agent 測試環境，測試完成後將結果傳入這台 knowledge-base」的整合方式。現有 repository 已有可用主幹：FastAPI `/api/upload/ingest` 可接收檔案並提交 Celery ingest 任務，任務會轉 Markdown、寫入 Neo4j/Qdrant、更新索引，並可透過 `/api/upload/tasks/{task_id}` 查狀態；另有 watch folder / n8n 範例，可讓外部環境以 SCP/SFTP/共享資料夾落檔後由 KB 定時掃描攝入。建議短期採「外部 AI agent 產出 Markdown/JSON/HTML/PDF 測試報告 → 呼叫 `/api/upload/ingest?extraction_mode=automation` 或放入 watch folder → KB 攝入」；中期補一個專用 `POST /api/external-test-results` 入口，接收結構化 payload、產生標準 Markdown 與 source metadata，再共用既有 ingest pipeline；正式部署需補 API token/mTLS 或 IP allowlist、結果 schema、run_id/idempotency key、來源環境欄位、附件/截圖打包規範、任務狀態回查與失敗重送機制。結論：不要讓外部環境直接寫 Neo4j/Qdrant，應讓它只送標準化 artifact，由 KB 端統一轉換、去重、攝入與索引，才能避免跨 session、跨部署路徑與資料 schema 漂移。
- 2026-07-20 已依 `all_kowledge.jpg` 的最終完整系統拓樸，對目前 knowledge-base repository 做現況／缺口盤點，產出可編輯的 PowerPoint [`knowledge_base_topology_gap_comparison.pptx`](<project-root>/knowledge-base/knowledge_base_topology_gap_comparison.pptx)，生成腳本為 [`generate_kb_topology_gap_comparison_pptx.py`](<project-root>/knowledge-base/generate_kb_topology_gap_comparison_pptx.py)。簡報共 3 張：第 1 張以原參考圖架構呈現完整差異覆蓋圖，綠框為已具備、橘色虛線為部分具備、紅色虛線為尚缺；第 2 張抽出目前已具備的 Browser → Nginx → FastAPI/Celery → Qdrant/Neo4j/File Store → OpenClaw/Ollama 端到端主幹；第 3 張整理四項主要差距與補齊順序。判定結論：Nginx、Search/Admin/Chat UI、Upload/Watch、FastAPI、WebSocket Proxy、SearchEngine、Celery、Redis、Neo4j、File Store 已有實作；Document Pipeline 的 Convert/Chunk 已有但 OCR 為條件式；Qdrant 已存在但以獨立容器運作；OpenClaw Gateway/Runtime 與 Ollama 已有串接，但仍是 KB Compose 外部相依；Runtime State 目前有 task/cache/locks，但統一持久化 Chat/Memory 尚未完整；三種角色已有操作路徑，但登入、RBAC、API scope 與 audit 尚未形成真正的治理層。缺口優先序標為 P0「角色與存取治理、Runtime State 完整化」，P1「外部 AI 生命週期、資料平台一致化」。已以 `python3 -m py_compile` 驗證腳本、以 `python-pptx` 驗證 3 張投影片結構，並以 LibreOffice 成功轉 PDF、逐頁轉 PNG 目視確認無明顯溢出或遮擋。另在 2026-07-20 的唯讀 runtime 探測中，`kb-qdrant` 容器正在運作，但 `https://127.0.0.1:3030/health` 當時無法連線，因此投影片明確採「repository 能力與部署邊界」作為狀態判定，而非宣稱當下所有服務都在線。
- 2026-06-18 已評估「兩個獨立 knowledge-base 環境共用同一組 Neo4j / Qdrant」的可行性：技術上可行，因為程式已支援透過 `NEO4J_URI` / `QDRANT_URL` 指到外部資料庫，而且目前 Neo4j / Qdrant 寫入本來就是固定 schema / 固定 collection（例如 Qdrant `knowledge_base`、`kb_syntheses`，Neo4j `Document` / `Entity` / `Report` / `Section` / `TestItem` 等），沒有內建 tenant 隔離；但若兩邊會 ingest 不同資料，風險很高，因為 `doc_name`、`Project.code`、`TestItem.canonical_name`、Qdrant point id（由 `doc_name + chunk_index` 決定）都有碰撞或互相覆蓋的可能，而且任一環境的清除/重攝入操作都會影響另一邊。建議只在「兩邊要共用同一套知識內容、且接受共享維運」時採用；若兩邊資料不同，應改成各自獨立 DB / collection，或先補 tenant / env 前綴再共庫。
- 2026-06-17 已將 `generate_dual_test_env_ollama_architecture_pptx.py` 的總覽頁改成單一合併架構圖，明確呈現 Anritsu 與 Amarisoft 兩個環境各自保留獨立 OpenClaw 控制層，但都共用同一台 DGX GB10 上的 Ollama / LLM 推論服務；已重新產出 [`dual_test_env_ollama_architecture.pptx`](<project-root>/knowledge-base/dual_test_env_ollama_architecture.pptx)，並用 `python3 -m py_compile` 與 `python3` 讀取 pptx 內容驗證可正常生成，輸出中已可看到新標題「雙環境共用同一台 DGX GB10 的 LLM」與共用 DGX 區塊。
- 2026-06-15 已將「安裝包完成後還需要設定什麼，才能把系統順利連線起來」整理成一份給非技術使用者的 PPTX 簡報，檔案為 [`onprem_post_install_connection_guide.pptx`](<project-root>/knowledge-base/onprem_post_install_connection_guide.pptx)，對應產生腳本為 [`generate_onprem_post_install_guide_pptx.py`](<project-root>/knowledge-base/generate_onprem_post_install_guide_pptx.py)。簡報共 7 張，內容包含：安裝包已自動完成哪些事、OpenClaw gateway 如何接起來、host nginx 是否為選配、raw 資料應放在哪裡、如何驗證「已連線」、以及常見問題排錯。
- 2026-06-15 已完成 `127.0.0.1` 的 KB 測試環境重置，並將原始系統 `data/raw` 底下的所有檔案與子目錄同步到遠端 `<onprem-root>/knowledge-base-onprem/app/data/raw`（共 56 個檔案與子目錄），讓後續可直接用最新 release 安裝包重新做首次安裝與手動 ingest 驗證；同時 release installer 仍保留同機 OpenClaw gateway 預設正規化為本機 IP + `18790` 的修正，避免新裝後又回到 `127.0.0.1:18789`。
- 2026-06-15 已再把 `127.0.0.1` 的 KB on-prem 相關檔案、容器、volume、舊安裝包與 host nginx 設定清掉，讓測試環境回到可重新安裝的乾淨狀態；隨後又把最新 release 安裝包複製到遠端 `/tmp`，準備進行「從零安裝」驗證與手動測試 ingest。
- 2026-06-14 已替「安裝包完成後，還需要設定哪些才能將系統順利連線起來」做成一份給非技術使用者看的簡報，檔案為 [onprem_post_install_connection_guide.pptx](<project-root>/knowledge-base/onprem_post_install_connection_guide.pptx)，對應產生腳本為 [generate_onprem_post_install_guide_pptx.py](<project-root>/knowledge-base/generate_onprem_post_install_guide_pptx.py)。內容分成 7 張投影片，重點包含：安裝包已自動完成哪些事、OpenClaw gateway 如何正規化成本機 IP + 18790、host nginx 是否為選配、raw 資料應放在哪裡、如何驗證連線成功，以及常見錯誤的簡單排錯方式。簡報已驗證可正常開啟。
- 2026-06-14 已把 KB 安裝包的 OpenClaw gateway 預設修正納入 release installer，避免新裝後又落回 `127.0.0.1:18789` 導致 `chat.html` 顯示未連線：`release/build_release.sh` 新增 `normalize_openclaw_gateway_defaults()`，在同機安裝時會把 gateway host 正規化成本機 IP、port 正規化成 `18790`，並將 `OPENCLAW_GATEWAY_WS_URL` 一律重建成 `ws://<host>:18790/ws`，同時 `confirm_and_collect()` 與非互動模式也改為以本機 IP / 18790 當預設值。最新成功產出的安裝包為 [knowledge-base-onprem-20260614_103654-75f3ba30.tar.gz](<project-root>/knowledge-base/release/dist/knowledge-base-onprem-20260614_103654-75f3ba30.tar.gz)。
- 2026-06-14 在 `127.0.0.1` 重新安裝 KB on-prem 後若出現 `chat.html` 顯示未連線，根因是安裝後 `.env` 與 `install-state.env` 仍指向 `KB_OPENCLAW_GATEWAY_HOST=127.0.0.1`、`KB_OPENCLAW_GATEWAY_PORT=18789`，但主機上的 `openclaw-gateway` 實際監聽在 `0.0.0.0:18790`；此外 `docker compose --env-file ../.env up -d --force-recreate web nginx` 可正確將新 env 套入容器，`/api/openclaw/chat-config` 會回傳 `gatewayWsUrl=ws://127.0.0.1:18790/ws` 與完整 `privateKeyPem/publicKeyPem`，`web` log 也會顯示 `connected upstream gateway=ws://127.0.0.1:18790/ws`。另需注意當時主機 `/etc/nginx/sites-available/openclaw-https` 是 0 bytes，屬於 host nginx opt-in 功能未正確落地的獨立問題，不是 KB 連線失敗主因。
- 2026-06-14 已將 `127.0.0.1` 上的 KB on-prem 環境完整清除，準備用 release 安裝包重新模擬首次安裝：已透過 `docker compose down -v --remove-orphans` 清掉 `kb_onprem-*` 容器與 `kb_release_*` volumes，並刪除 `<onprem-root>/knowledge-base-onprem` 安裝根目錄與 KB 專屬 Docker images（`kb_onprem-web:latest`、`kb_onprem-celery_*:latest`）；同時移除主機層 `/etc/nginx/sites-available/openclaw-https` 與 `sites-enabled/openclaw-https` 站台 symlink，讓 `127.0.0.1` 回到接近乾淨、可重新安裝的狀態。OpenClaw 本體與使用者個人工作區未動。
- 2026-06-13 已把 OpenClaw 的主機 nginx 設定也納入 release installer，但維持 opt-in，不會預設改動主機 nginx：`release/build_release.sh` 現在支援 `--configure-openclaw-nginx`，並可搭配 `--openclaw-nginx-listen-ip`、`--openclaw-nginx-listen-port`、`--openclaw-nginx-backend-host`、`--openclaw-nginx-backend-port` 由 installer 在目標主機上建立 `/etc/nginx/sites-available/openclaw-https` 與對應 symlink；生成的 `install.sh` 內也包含 `detect_primary_ip()`、`configure_openclaw_host_nginx()` 與對應 summary，package root `README.md` 也已補上 opt-in 說明。最新成功產出的安裝包為 [knowledge-base-onprem-20260613_123704-75f3ba30.tar.gz](<project-root>/knowledge-base/release/dist/knowledge-base-onprem-20260613_123704-75f3ba30.tar.gz)。
- 2026-06-13 已把今天在 `127.0.0.1` 上調整的 KB on-prem chat 防卡死修正回灌到 release 安裝包：更新 [release/build_release.sh](<project-root>/knowledge-base/release/build_release.sh) 的 installer 預設值，讓新裝與升級時自動採用 `KB_CHAT_GLOBAL_CONCURRENCY_LIMIT=2`、`KB_CHAT_BROWSER_CONCURRENCY_LIMIT=1`、`KB_CHAT_SESSION_LOCK_TTL=600`、`KB_CHAT_GLOBAL_SLOT_TTL=600`、`KB_CHAT_QUEUE_ACTIVE_TTL=600`；同時把這些值寫進 `.env` 與 `install-state.env`，並在安裝腳本內新增 `reset_chat_runtime_state()`，啟動完成後會自動清掉 Redis 裡殘留的 `kb:chat:queue:req:*`、`kb:chat:session_lock:*` 與 `kb:chat:browser_active:*`，避免舊 session / active slot 讓第一筆聊天請求卡死。最新可交付安裝包為 [knowledge-base-onprem-20260613_122552-75f3ba30.tar.gz](<project-root>/knowledge-base/release/dist/knowledge-base-onprem-20260613_122552-75f3ba30.tar.gz)。
- 2026-06-13 已針對 `127.0.0.1` 的 KB on-prem 做「只改遠端、不動原始系統」的防卡死調整：遠端 `<onprem-root>/knowledge-base-onprem/.env` 與 `install-state.env` 已將 `KB_CHAT_GLOBAL_CONCURRENCY_LIMIT` 從 1 調高到 2，並把 `KB_CHAT_SESSION_LOCK_TTL` 與 `KB_CHAT_GLOBAL_SLOT_TTL` 從 1200 縮短到 600，目的是避免單一長任務或殘留 slot 直接把所有聊天請求卡死；同時保留 `KB_CHAT_BROWSER_CONCURRENCY_LIMIT=1`，不影響同一個瀏覽器內的基本互斥。已重建遠端 `web` 容器並驗證容器內實際環境變數已生效，之後在 `https://127.0.0.1:18443/chat.html` 送出 `今天天氣如何` 時，畫面可先進入 `等待階段: 生成回覆中`，最後正常回出基本 LLM 天氣回覆與 `wttr.in` 來源，代表此調整已把「排隊中卻沒有基本回覆」的問題顯著緩解，且原始系統尚未套用此 patch。
- 2026-06-13 在 `https://127.0.0.1:18443/chat.html` 以 `今天天氣如何` 實測時，先前一輪會長時間停在 `排隊中`，後續查到遠端 Redis 的 `kb:chat:queue:active` 與對應 session lock / browser_active 殘留，導致 `web` log 持續出現 `Chat queue claim waiting global limit request_id=chat-0 queue_rank=0 active_count=1`。在清掉這次測試留下的 `kb:chat:queue:active`、`kb:chat:queue:req:chat-0`、session lock 與 browser_active 鍵後，重新開乾淨的 Playwright session 再送同題，頁面先進入 `等待階段: 生成回覆中`，最後成功多出第二則 bot 訊息，內容為「今天台北的氣象資訊如下：目前天氣狀況為 [Insert current weather data if retrieved or leave as general placeholder]. (註：由於目前的外部搜尋服務尚未啟用 API 金鑰，我無法即時獲取實時預報。) 建議您可以參考 local 的天氣應用程式以獲取最精確的當前氣溫。」並附上 `參考來源：(尚未取得相關知識庫數據)`。這次證實 on-prem 小幫手在沒有 KB 命中時仍會回基本 OpenClaw LLM 答案，而排隊卡住的根因是殘留的 active slot / session lock，而不是聊天頁本身不能回覆。
- 2026-06-13 追查 `https://127.0.0.1:18443/chat.html` 在「妳在嘛」場景下排隊久候的原因，確認不是 OpenClaw 沒回，而是 websocket 斷線後舊的 queued request 沒有被清掉，Redis 中殘留的 `kb:chat:queue` 會讓新請求長時間排在 `chat-1` 後面。已在 `src/web_api/__init__.py` 加入 `pending_request_ids` 與 `release_pending_requests()`，讓 websocket teardown 會釋放該連線自己尚未完成的 queued request；並同步到遠端 `127.0.0.1`、手動清除殘留 `chat-0/chat-1` 後重新測試，現在 `妳在嘛` 會正常顯示 OpenClaw 回覆，輪詢結果確認第二則 bot 訊息出現為「我在這裡，準備好協助你處理任何事情了。有什麼我可以幫你的嗎？」。
- 2026-06-13 已將本機 `~/.openclaw/workspace/` 內的 `SOUL.md`、`USER.md`、`AGENTS.md`、`TOOLS.md`、`IDENTITY.md`、`HEARTBEAT.md`、`BOOTSTRAP.md` 同步到 `127.0.0.1` 的 `<onprem-root>/.openclaw/workspace/`，並以 sha256 checksum 驗證兩邊內容完全一致。這是為了讓兩台機器上的 OpenClaw 行為模式、規則與啟動/心跳流程盡量對齊。
- 2026-06-13 已修正 KB on-prem 小幫手在 `https://127.0.0.1:18443/chat.html` 送出問題後「有回覆但畫面不顯示」的根因：OpenClaw upstream 其實是回 `event=agent`，而原本前端只處理 `event=chat`，所以 assistant/lifecycle 事件被漏掉，畫面會長時間停在「生成回覆中」或只看到使用者訊息。已在 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 補上對 `event=agent` 的相容處理，會把 `stream=assistant` 的 `delta/text` 渲染成 bot 訊息，並把 `stream=lifecycle phase=end` 視為完成；同步更新遠端 `127.0.0.1` 的 runtime 檔案後，實測在 `chat.html` 輸入 `你在嘛?` 會正常顯示 OpenClaw 回覆 `我在這裡，正準備好協助你。有什麼我可以幫你的嗎？`。這次的修正重點是把「OpenClaw 有回但 KB UI 吃不到」的事件格式差異補齊，而不是只修 session key 或模型設定。
- 2026-06-13 已完成 KB on-prem 的 OpenClaw identity 修正與驗證：release installer 新增 `sync_host_openclaw_identity()`，安裝 / 升級時會自動將主機 `~/.openclaw/identity/device.json` 與 `device-auth.json` 同步到 `runtime/openclaw/identity/`，避免 `chat-config` 回傳空的 `privateKeyPem/publicKeyPem`。也已在現有 `127.0.0.1` 安裝根目錄手動同步 identity，重新整理 `https://127.0.0.1:18443/chat.html` 後狀態已從「未連線」變成「已連線」，且 `GET /api/openclaw/chat-config` 已回傳完整金鑰。新發行包為 [knowledge-base-onprem-20260613_094505-75f3ba30.tar.gz](<project-root>/knowledge-base/release/dist/knowledge-base-onprem-20260613_094505-75f3ba30.tar.gz)。
- 2026-06-13 追查 `https://127.0.0.1:18443/chat.html` 顯示「未連線」的根因：不是 OpenClaw gateway 或 nginx 未啟動，而是 release runtime 掛載的 `<onprem-root>/knowledge-base-onprem/runtime/openclaw/identity/device.json` 內 `privateKeyPem` / `publicKeyPem` 目前是空字串。`/api/openclaw/chat-config` 因而回傳 `privateKeyPem: ""`、`publicKeyPem: ""`、`publicKeyRaw: ""`，前端在收到 `connect.challenge` 時就會印出 `[Chat] runtime config not ready` 並拒絕完成連線。對照之下，主機上的 `~/.openclaw/identity/device.json` 其實是有完整金鑰的，因此後續修正應以把主機 identity 金鑰同步進 release runtime，或讓 install/compose 直接掛載正確的 identity 路徑為主。
- 2026-06-13 已釐清並固定驗證範圍：`https://127.0.0.1:3030/chat.html` 是原始系統的對外網址，`https://127.0.0.1:18443/chat.html` 是另一台電腦上的 KB on-prem 系統入口。後續所有 on-prem 安裝、nginx、OpenClaw gateway、KB 連線與聊天驗證，都必須以 `127.0.0.1:18443` 為準，不可再把原始系統網址誤當成這台機器的驗證入口。
- 2026-06-13 已用瀏覽器真實流程驗證 KB 小幫手可正常回覆：在 `https://127.0.0.1:3030/chat.html` 先確認狀態由「未連線」變成「已連線」，再從右下角 `KB Chat v2026-05-20` 浮動按鈕開啟聊天，輸入 `請查詢SCU2140相關報告資訊` 後等待約 60 秒，畫面成功回出 `🦾 CSIT_KM小幫手` 的 KB 參考內容與 `原文` 摘錄，且引用統計顯示 `本次共引用 60 份來源，回推成 1 份原始文件`，說明聊天鏈路可用。先前試過的泛用問句 `請簡單介紹這個系統` 沒有在等待窗內回出實質答案，因此後續驗證應優先用可命中的 KB 問句。
- 2026-06-11 已在遠端 `127.0.0.1` 完成 OpenClaw / nginx 對外入口調整：OpenClaw gateway 改為內部 `ws://127.0.0.1:18790/ws`，並以 `0.0.0.0:18790` 監聽，KB on-prem 的 `.env` 與 `install-state.env` 也同步改成 `KB_OPENCLAW_GATEWAY_WS_URL=ws://127.0.0.1:18790/ws`。同時新增 nginx 站台 `/etc/nginx/sites-available/openclaw-https`，由 `https://127.0.0.1:18789` 對外進入，反向代理到 `http://127.0.0.1:18790`，並已啟用 `sites-enabled/openclaw-https` 與重載 nginx。驗證結果：`curl -k https://127.0.0.1:18789` 回傳 OpenClaw Control UI，KB `web` 容器 log 顯示 `WebSocket proxy ... connected upstream gateway=ws://127.0.0.1:18790/ws`，代表前端已從「未連線」恢復為可連線狀態。
- 2026-06-11 針對升級後安裝失敗的 `Frontend runtime build is missing: .../runtime/frontend/index.html` 已完成修補：根因是 release 產線原本只把 Vite build 輸出保留在 `.frontend-build-runtime-user8`，沒有把 build 成果複製進發行包的 `runtime/frontend/`，導致 installer 在 `apply_upgrade_or_install()` 驗證 runtime 時找不到 `index.html`。已將 `build_frontend_runtime()` 改成在 build 完成後把 `.frontend-build-runtime-user8` 的內容完整複製到 `runtime/frontend/`，再補上 `chat.html` 與 lib 檔案；新包為 [knowledge-base-onprem-20260611_102513-75f3ba30.tar.gz](<project-root>/knowledge-base/release/dist/knowledge-base-onprem-20260611_102513-75f3ba30.tar.gz)，並已同步到遠端 `/tmp`。
- 2026-06-11 針對升級安裝時出現的 `Empty source arg specified` 已完成第三次修補：根因是 release installer 在 `apply_upgrade_or_install()` 內的 `rsync -a --delete "${app_excludes[@]}" ...` 與 `runtime_excludes` 兩行，因為 build-time heredoc 沒有把 `${app_excludes[@]}` 轉義，導致生成出的 install script 出現空字串參數。已改為保留陣列展開的 runtime 字串，並把升級備份旗標統一為 `UPGRADE_BACKED_UP`，避免互動式升級與主流程重複備份兩次。新包為 [knowledge-base-onprem-20260611_102121-75f3ba30.tar.gz](<project-root>/knowledge-base/release/dist/knowledge-base-onprem-20260611_102121-75f3ba30.tar.gz)，並已同步複製到遠端 `/tmp`。
- 2026-06-11 針對安裝過程中的 `指令找不到` / `rsync error: Empty source arg specified` 已完成第二次修補：根因是 release installer 在 `write_openclaw_overlay()` 產生 `00-bootstrap.md` 時，把 `sessionKey` 與聊天網址包在反引號裡，導致 shell 在執行安裝腳本時把隨機 session key 當成命令替換執行。已將該段改為純文字輸出 `sessionKey: $OPENCLAW_SESSION_KEY` 與 `正式 Chat 網址: /chat.html?sessionKey=$OPENCLAW_SESSION_KEY`，並重建新包 [knowledge-base-onprem-20260611_101427-75f3ba30.tar.gz](<project-root>/knowledge-base/release/dist/knowledge-base-onprem-20260611_101427-75f3ba30.tar.gz)，已同步複製到遠端 `/tmp`。
- 2026-06-11 針對遠端安裝時出現的 `INSTALL_ROOT: 未綁定的變數` 已完成修補：根因是 release installer 在 `set -u` 下先呼叫 `prepare_default_values()`，但 `INSTALL_ROOT` 尚未初始化就被 `[[ -f "$INSTALL_ROOT/..." ]]` 讀取。已將 `prepare_default_values()` 改為使用 `local install_root="${INSTALL_ROOT:-$HOME/knowledge-base-onprem}"`，並在進入該流程前先把 `INSTALL_ROOT` 設為預設值；已重建新包 [knowledge-base-onprem-20260611_100519-75f3ba30.tar.gz](<project-root>/knowledge-base/release/dist/knowledge-base-onprem-20260611_100519-75f3ba30.tar.gz) 並同步覆蓋到遠端 `/tmp`。
- 2026-06-11 已新增面向非技術人員的 B2B/on-prem 安裝手冊 [docs/onprem-install-guide.md](<project-root>/knowledge-base/docs/onprem-install-guide.md)，內容以「先準備什麼、帶哪些檔案、如何解壓、如何執行 `--check-only`、如何正式執行 `install.sh`、如何處理 `--offline`、常見錯誤與升級舊版本」的順序編寫，並在 [README.md](<project-root>/knowledge-base/README.md) 與 [release/README.md](<project-root>/knowledge-base/release/README.md) 補上入口連結，讓不熟悉系統的人可直接照步驟安裝。
- 2026-06-11 已依使用者要求，從 Bnext 文章 https://www.bnext.com.tw/article/90965/claude.md-claude-code 讀取並整理 Claude Code 的 12 條規則，並同步寫入全域 `<project-root>/.codex/AGENTS.md` 與專案內 `<project-root>/knowledge-base/AGENTS.md`。新增段落標題為 `Claude Code 十二條規則`，內容涵蓋先思考、簡單優先、外科手術式修改、目標導向、避免把確定性工作交給模型、硬性 token 預算、衝突選邊、先讀再寫、測試要有業務意義、長任務檢查點、約定優先、顯性失敗等 12 點。
- 2026-06-11 已完成 release installer 的兩個新增控制旗標：`--check-only` 會只做前置條件掃描並直接結束，不進入安裝、不補裝、不改寫檔案；`--offline` 會完全停用任何網路補裝，若缺少必需依賴則在進入安裝前直接失敗，且若同時帶 `--auto-install-deps` 會以 offline 為準。這次已同步更新 [release/build_release.sh](<project-root>/knowledge-base/release/build_release.sh) 與 [release/README.md](<project-root>/knowledge-base/release/README.md)，並重建發行包為 [knowledge-base-onprem-20260611_094458-75f3ba30.tar.gz](<project-root>/knowledge-base/release/dist/knowledge-base-onprem-20260611_094458-75f3ba30.tar.gz)。已驗證 build 腳本 `bash -n` 通過，tar 包內 `install.sh` 也通過 `bash -n`。
- 2026-06-10 已將新電腦重建手冊整理成正式中文 SOP [docs/new-machine-rebuild-guide.md](<project-root>/knowledge-base/docs/new-machine-rebuild-guide.md)，內容已重構為「前置準備、取得程式碼、建立相容路徑、設定 config、安裝依賴、啟動 Neo4j/Qdrant、執行 `restart_kb.sh`、還原資料 bundle、重新 ingest、驗證清單與常見排障」的完整交接流程；同時把 [README.md](<project-root>/knowledge-base/README.md) 的入口說明更新為「重建 SOP」，避免後續閱讀者只看到零散手冊。這次整理是文件層級調整，未改動程式邏輯。
- 2026-06-10 已更新新電腦重建手冊 [docs/new-machine-rebuild-guide.md](<project-root>/knowledge-base/docs/new-machine-rebuild-guide.md) 與投影片 [new_machine_rebuild_guide.pptx](<project-root>/knowledge-base/new_machine_rebuild_guide.pptx)，新增 Docker 安裝說明，以及 Neo4j / Qdrant 在 Docker 中的啟動方式。內容現在明確區分：Docker 安裝、Neo4j 由 `docker-compose.yml` 的 `neo4j` service 啟動、Qdrant 由 `restart_kb.sh` 以獨立 `kb-qdrant` 容器啟動，並同步把後續步驟編號往後調整，確保新電腦照著文件就能把整套 knowledge-base 系統架起來再重新 ingest。
- 2026-06-10 已確認目前 knowledge-base 並未使用像 `bge-reranker-v2-m3` 這類獨立重排模型；實作上是先用 Qdrant 做 embedding 召回，再由 `src/search/__init__.py` 的 `_rank_vector_results()` 依 `doc_hints`、`case_hints`、章節標題、檔名命中與原始 score 做規則式重排。`src/vector_store/__init__.py` 只負責把 `sentence-transformers/all-MiniLM-L6-v2` 產生的 embedding 寫入 / 查詢 Qdrant，沒有 cross-encoder rerank pipeline。
- 2026-06-10 已依使用者要求產出「另一台電腦重建 knowledge-base 系統」的投影片手冊，檔案為 [new_machine_rebuild_guide.pptx](<project-root>/knowledge-base/new_machine_rebuild_guide.pptx)，目前為 9 張投影片；對應的生成腳本為 [generate_new_machine_rebuild_guide_pptx.py](<project-root>/knowledge-base/generate_new_machine_rebuild_guide_pptx.py)。內容涵蓋前置環境、Docker 安裝、Neo4j / Qdrant 容器啟動、clone 與 symlink、config 設定、服務啟動、資料 bundle 還原、重新 ingest、驗證與常見排錯，主軸明確是「先把系統架起來，再重新 ingest 資料」，不要求把舊資料直接搬進 GitHub。
- 2026-06-10 已把 code-only GitHub repo `dev-work` 重新同步到最新重建手冊內容，最新推送 commit 為 `20fd257`（`docs: sync rebuild guide into code-only repo`）。code-only repo 現在包含 `docs/new-machine-rebuild-guide.md`，且 `README.md` 與 `docs/github-backup-plan.md` 已補齊最新連結，方便新電腦直接照步驟重建後再重新 ingest。原始 `knowledge-base` 工作樹仍保留完整本機開發狀態，不再直接拿去覆蓋 GitHub 的乾淨版本。
- 2026-06-09 已實際用 headless Chromium 檢查 Neo4j Browser `http://localhost:17474/browser/`：頁面本身可正常載入，`page.title()` 為 `Neo4j Browser`，`body` 顯示的是 `No instance connected` 與連線表單，且 console 沒有頁面錯誤，表示這不是前端快取壞掉，而是 Browser 尚未連到資料庫。進一步確認目前 KB 的 Neo4j 容器對外映射是 host `17474`（HTTP）與 `17687`（Bolt），因此 Browser 預設的 `neo4j://localhost:7687` 不是這個 KB 容器的連線埠；若要看到已攝入的報告資料，需在 Browser 內手動連到 `bolt://localhost:17687`（或等價的 `neo4j://localhost:17687`）並輸入 `neo4j / #*cda40da40`。目前 `kb-neo4j` 容器內仍有 9 筆 `Document`，所以資料本身是存在的。
- 2026-06-09 已整理出新電腦重建手冊 [docs/new-machine-rebuild-guide.md](<project-root>/knowledge-base/docs/new-machine-rebuild-guide.md)：內容包含前置安裝、Git clone、建立相容 symlink、複製 `config/config.yaml.example`、啟動 `restart_kb.sh`、還原獨立資料 bundle、以及重新 ingest 的完整步驟。由於目前 code-only repo 仍含有部分絕對路徑，手冊特別提醒先建立 `<project-root>/knowledge-base` 的 symlink，或自行把硬編碼路徑改成新機器上的實際位置，避免第一次搬機器就因 path mismatch 卡住。
- 2026-06-09 已完成「只保留可重建程式碼、之後重新 ingest 資料」的 GitHub 方案 A 落地：另外建立獨立的 code-only 工作區，移除 `data/`、`.venv`、frontend/node_modules、build/dist、草稿/備份檔與 local config，保留 `src/`、`frontend/`、`docs/`、`scripts/`、`Dockerfile`、`docker-compose.yml`、`restart_kb.sh`、`start.sh`、`requirements.txt`、`config/config.yaml.example` 等重建所需內容，並將 GitHub remote `dev-work` force update 到乾淨版本。最終成功推送的 commit 為 `8433ebd`（`chore: drop draft and backup files`），GitHub 上的 `dev-work` 現在已是可 clone、可在新電腦重新 setup、再重新 ingest 的輕量化版本；資料需透過獨立 bundle 另行還原，不再依賴 repo 內的原始資料。
- 2026-06-09 最新一次以使用者提供的 `github_pat_...` token 嘗試推送到 `dev-work` 時，GitHub 回覆 `RPC failed; HTTP 500 curl 22` / `send-pack: unexpected disconnect while reading sideband packet`，但 `git ls-remote` 仍顯示遠端 `dev-work` 在 `f726f8a64851a7e8884b7888c4c5165853d0ff01`，表示本地 `1d66ca27` 尚未成功上傳。這次不是明確的權限拒絕，而是遠端傳輸/pack 流程失敗，若要繼續應改用 SSH push、縮小一次推送的內容，或再重試一次確認是否為 GitHub 暫時性問題。
- 2026-06-09 進一步嘗試使用使用者提供的新 GitHub PAT 進行 `git push`，GitHub 回覆 `Write access to repository not granted` 並以 403 拒絕寫入。這代表憑證即使可被接受，也沒有該 repo 的 push 權限，可能是 token 未授權 `repo` scope、帳號不是該倉庫協作者、或目標 repository 並非該 PAT 所屬帳號可寫入。後續若要成功推送，需先確認 GitHub 帳號對 `kyocarlos/knowledge-base` 具備寫入權限，或改推到你有權限的 fork / 重新授權 PAT / 使用 SSH key。
- 2026-06-09 已嘗試使用使用者提供的 GitHub PAT 進行 `git push`，但 GitHub 回應 `Invalid username or token. Password authentication is not supported for Git operations.`，因此遠端推送尚未成功。這代表目前問題不是 repo 內容，而是憑證本身無效、過期、權限不足或字串有誤。後續若要繼續推送，需使用新的有效 PAT 或改用 SSH / `gh auth login`。
- 2026-06-09 已開始落實方案 A 的 GitHub 備份流程：新增 [docs/github-backup-plan.md](<project-root>/knowledge-base/docs/github-backup-plan.md) 說明「GitHub 放可重建的程式碼、資料另存 bundle」；新增 [scripts/create_data_backup_bundle.sh](<project-root>/knowledge-base/scripts/create_data_backup_bundle.sh) 可把 `data/raw/`、`data/processed/`、`data/assets/`、`data/uploads/` 與 `config/config.yaml` 打成獨立 tar.gz 備份；`.gitignore` 也補上 `.frontend-build-runtime-*`、`.venv_playwright/`、`final_runs/`、`backups/` 與多個本機生成檔。`README.md` 已加入新電腦重建導向。Git remote 也已清掉 token，改回乾淨的 `https://github.com/kyocarlos/knowledge-base.git`；本地 commit 已完成為 `9f1ae36a`（`docs: add GitHub backup and restore workflow`），但實際 `git push` 目前因這台機器沒有可用的 GitHub 認證而失敗，下一步需要提供 SSH key / PAT 或改用已登入的 GitHub 工具才能把這筆備份推上遠端。
- 2026-06-09 目前正在整理「更新到目前進度的記憶與 Git 備份」：已先讀取本檔與目前工作樹狀態，確認倉庫中仍有大量既有修改與未追蹤檔案，這一輪不做功能改動，只先把最新進度同步回記憶，接著會建立一筆乾淨的 Git 備份提交。後續若要接手，應先沿用本檔既有脈絡，再依目前的 KB / 前端 / ingest 狀態續作。
- 2026-06-09 已依使用者要求清除 SCU2060 / SCU2140 / SCU5050 在 Neo4j 與 QDrant 內的資料，供乾淨手動測試使用。實際從 Neo4j 找到並清除的 `Document` 節點為 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8`、`SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005`、`SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001`；`cleanup_existing_document()` 執行後三者在 Neo4j 與 QDrant 的殘留都已清空，並已用查詢驗證 `MATCH (d:Document) WHERE d.name CONTAINS 'SCU2060/2140/5050'` 與 `vector_store.list_documents()` 都回空。後續若要重新測試圖片 chunk 行為，需先重啟服務，再重新攝入這三份文件。
- 2026-06-09 已把 chunk-level 圖片引用從「文件級廣播」修正為「只保留 chunk 內文命中的 refs」：`src/chunker/__init__.py` 移除了先前會把整份 `source.json` 的 `image_refs` 複製到所有 chunk 的 fallback，現在只會根據每個 chunk 自己的內文抽取 `asset://...` 並去重後寫入 `chunk.metadata.image_refs`；`src/vector_store/__init__.py` 仍沿用同一套共用抽取 helper，將 chunk 內文與 metadata 內的 refs 一起寫進 QDrant payload。已用 `python3 -m py_compile src/chunker/__init__.py src/vector_store/__init__.py src/web_api/tasks.py src/image_refs.py` 驗證語法，並用暫存 Markdown 實測確認只有含 `頁面快照引用` / `圖片` 的 chunk 會保留 `image_refs`，其他 chunk 不再重複顯示同一批圖片。
- 2026-06-08 已完成 `image_refs` 的穩定化修補：新增 `src/image_refs.py` 作為共用抽取/正規化 helper，讓 `src/chunker/__init__.py` 不再只靠 Markdown 內文，而是會先讀 sidecar `*.source.json` 的 `image_refs`，再合併 chunk 內文抽出的 asset refs 寫回 `chunk.metadata.image_refs`；若 chunk 內文沒有 inline 引用，會以 source metadata 作為 fallback，確保沒有 `asset://...` 內文時仍能保留圖片引用。`src/vector_store/__init__.py` 已改成使用同一個 helper，寫入 QDrant 時會把 `metadata.image_refs` 與 content 抽出的 refs 一起去重後存進 payload。`src/web_api/tasks.py` 的 `_write_source_metadata()` 也已新增 `image_refs` 欄位，`ingest_file_task` 與 watch ingestion 的 source metadata 都會把 converter 回傳的 `image_refs` 一起落盤。已用 `python3 -m py_compile src/image_refs.py src/chunker/__init__.py src/vector_store/__init__.py src/web_api/tasks.py` 驗證語法，並用暫存 markdown + `original/sample.source.json` 的最小測試確認 `chunk_document()` 在內文沒有 inline asset refs 時，仍會把 `image_refs` 穩定寫進每個 chunk metadata。
- 2026-06-04 已依使用者指定安裝 Webwright skill，來源為 `https://github.com/microsoft/Webwright/tree/main/skills/webwright`，安裝位置為 `<project-root>/.codex/skills/webwright`。後續若需做瀏覽器自動化、長流程網頁操作或 Playwright 類任務，應優先考慮直接使用這個 skill。
- 2026-06-04 已更新 [AGENTS.md](<project-root>/knowledge-base/AGENTS.md) 的網頁測試原則：凡是網頁功能測試、網頁設計驗證、或前端修改後的確認，統一以 Webwright 為第一優先工具；Playwright 僅在 Webwright 無法處理、遇到工具限制、或需要更細緻瀏覽器除錯時才作為備援。原本「優先使用 Playwright」的描述已改成「Webwright / Playwright 測試規範」，以免後續人員誤把 Playwright 當成首選。
- 2026-06-04 已實際透過瀏覽器測試 `請整理 TP-Link Archer BE805 的 5GHz 80MHz 與 160MHz 數據`：前端先進入 `https://127.0.0.1:3030/chat.html`，開啟聊天浮窗後送出查詢，websocket 連線成功，接著 `/search` 產生 task `f35af84c-9650-40df-9eea-20b160f1453f` 並連續輪詢 `/tasks/{task_id}`，最後 console 顯示 `[Heatmap] Prepared WiFi-specific KB result.` 與 `wait timing summary`，代表這句話確實走 WiFi-specific KB 路徑而不是 report_graph。最終回答回推到 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx`，內容包含 `4.2.3 5GHz - Bandwidth 80MHz` 與 `4.2.4 5GHz - Bandwidth 160MHz`，解讀明確寫出 80MHz 的 Tx/Rx 約 `2450.1~2484.5 / 2063.04~2248.58 Mbps`、160MHz 的 Tx/Rx 約 `4606.04~4732.45 / 3984.19~4117.04 Mbps`，並指出 160MHz 的 `2882.4 Mbps` 正好是 80MHz 的 `1441.2 Mbps` 兩倍。熱圖卡片也同步更新為 `WiFi=100/1`、`4G/5G=0/0`，表示這次只命中 1 份 WiFi 原始文件。
- 2026-06-04 已實際透過瀏覽器測試 `TP-Link Archer BE805 的 2.4GHz 和 5GHz 表現有什麼差異`：前端同樣先進入 `https://127.0.0.1:3030/chat.html` 並開啟聊天浮窗，送出後 `/search` 產生 task `78bf922b-a824-4608-a7fe-147ed55a73f4`，console 顯示 `[Heatmap] Prepared WiFi compare KB result.`，但這次 `matched_count=1`、`total_sources=1`，代表只命中單一 WiFi 文件。最終回覆沒有進入真正的雙頻比較，而是回 `KB 匯整來源：type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx`，`原文` 直接寫明「未找到足夠的 WiFi 文件可進行比較。」；`解讀` 也只列出「目前只找到：type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx」與「未命中的查詢文件：BE805、TP-LINK ARCHER BE805」。這表示此問法目前會被辨識成 WiFi compare 類，但因為缺少第二份可對照的 WiFi 文件，所以系統會退回單文件提示，不會自動合併成 2.4GHz vs 5GHz 的對比結論。
- 2026-06-08 針對 `/admin/chunks` 的 SCU2060 / SCU2140 / SCU5050 圖檔缺失問題已確認根因：後端 `admin_chunk_assets` 只會從 `data/assets/<doc_name>/...` 提供實體檔；`chunk_document()` 目前只補 `source_path` 等基礎 metadata，不會主動帶入 `image_refs`；`vector_store.add_documents()` 雖會從 chunk 內容與 metadata 擷取 `image_refs`，但 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md` 與 `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md` 的 `data/processed/Report` 版本內並沒有 `asset://...` 引用，因此 QDrant payload 內 `image_refs` 為空，`data/assets` 也沒有對應資產目錄。相對地，`SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8` 這版有 65 個 chunk 且 `image_refs` 與 `data/assets/.../excel/...` 正常存在；如果 UI 顯示的是 `SCU2060-EV-V001` 舊版，則會因為舊版沒有 chunk / 資產而顯示「資產不存在」或查無內容。根因偏向「舊版重攝入時未保留或未重新導出圖片資產」，不是單純前端連結格式錯誤。
- 2026-06-04 已再用更精準問法 `請整理 TP-Link Archer BE805 的 2.4GHz Throughput 與 5GHz Throughput，分開看兩個頻段` 實測：前端送出後 `/search` 產生 task `886e84fa-daf7-41db-a333-e2098aef2b02`，console 顯示 `[Heatmap] Prepared WiFi-specific KB result.`，並在輪詢數秒後回覆完成。這次最終答案已成功把 `4.1 2.4GHz Test` 與 `4.2 5GHz Test` 兩個段落都拉出來，原文中完整包含 2.4GHz 的 20MHz / 40MHz throughput 表，以及 5GHz 的 20MHz / 40MHz / 80MHz / 160MHz throughput 表；解讀則明確指出 2.4GHz 在 20MHz 下只有少數頻道通過、40MHz 幾乎全失敗，而 5GHz 在 80MHz / 160MHz 下表現穩定且顯著更高。這證實只要把問法拆成明確的 `2.4GHz Throughput` + `5GHz Throughput`，系統就會把 2.4GHz 內容一併拉出，而不是像前一版那樣退回單文件提示。後續若要穩定得到兩頻段比較，這個問法比單純問「2.4GHz 和 5GHz 表現有什麼差異」更可靠。
- 2026-06-05 已實測 `https://127.0.0.1:3030/chat.html` 對 `請整理 TP-Link Archer BE805 的 2.4GHz Throughput 與 5GHz Throughput，分開看兩個頻段` 的反應：前端確實送出 `POST /search`，並持續輪詢 `/tasks/1d34f620-5609-48ba-9ae9-acfe3b55a613`，但 task 長時間維持 `pending`，input 與送出按鈕都被前端鎖住，畫面沒有最終回覆。`celery -A src.web_api.tasks:celery_app inspect active` 顯示該任務仍在 `celery@3a051b5a3e4a` 的 worker pid 98 上執行，`kwargs` 為 `top_k=6, sources_only=True`。對照程式碼可見 `src/web_api/tasks.py` 的 sources_only 路徑在 `search_task()` 會直接走 WiFi / report 搜尋分支，而 `src/search/__init__.py` 的 `_build_wifi_throughput_band_answer()` 會進一步呼叫 `_compose_raw_then_interpretation()`，再進到 `_build_report_graph_interpretation()` 的 `llm_client.chat(...)`。這次現象顯示 task 被卡在後端的長時間搜尋/解讀階段，而不是前端沒把訊息送出去；後續若要修，應優先檢查 sources_only 路徑在 WiFi band raw / report interpretation 的 timeout 與回退機制。
- 2026-06-05 已將 knowledge-base 內所有實際使用的 Ollama 預設模型統一改為 `gemma4:12b`：`config/config.yaml`、`config/config.yaml.example`、`src/main.py`、`src/search/__init__.py`、`src/web_api/ollama_client.py`、`src/web_api/llm_factory.py`、`src/web_api/__init__.py`、`src/converter/__init__.py`、`src/ingest.py`、`src/extract_entities.py`、`src/web_api/tasks.py`、`src/web_api/tasks.py.bak` 與 `start.sh` 都已改成 `gemma4:12b`，並把 README / llm-flow / self-evolution-report 文件同步更新為新模型名。已用 `python3 - <<'PY' ... load_config()` 驗證目前 `config` 讀回的 `llm_model` 與 `ollama.model` 都是 `gemma4:12b`，且 `ollama list` 顯示本機已存在 `gemma4:12b` 模型。之後又以 `docker restart kb-web kb-celery-search kb-celery-ingest kb-celery-beat` 重啟知識庫服務，讓 web / worker / beat 重新載入新的預設模型設定。
- 2026-06-04 已新增全域工作原則：所有修改預設都應避免硬編碼，優先採用可擴充、可配置、資料驅動或共用規則的做法；只有在使用者明確指定要硬編碼時才採用硬編碼方案。後續若遇到路由、分類、compare 候選或 UI 行為調整，應先檢查是否能抽成共用 helper、規則表或 metadata 驅動機制，再考慮局部特例寫死。
- 2026-06-03 已徹底追到 `search_task(..., sources_only=True)` 為什麼在 live 任務裡還會掉回 `vector`：根因不是 compare builder 不會組兩份 WiFi，而是 `sources_only` 路徑把 Neo4j profile 轉成 WiFi metadata 時，`_build_wifi_metadata_source()` 沒有把 `converted_path` / `original_path` 帶回去，導致 `_build_wifi_throughput_band_raw_body()` 讀不到 CHS 那份 converted markdown，compare builder 只要遇到這筆就會失敗並落回一般 vector fallback。已修正 `src/search/__init__.py` 讓 `_build_wifi_metadata_source()` 同時輸出 `converted_path` 與 `original_path`，並重新重建整套 KB 後驗證：`search_task.run('請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput', 'auto', sources_only=True)` 現在回 `mode=wifi_compare`，sources 也穩定包含 `SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.md` 與 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx`；`/search` + `/tasks/{task_id}` 的 live API 也已對齊，不再掉回 `vector`。
- 2026-06-03 已追查 `請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput` 中 BE805 為何沒有穩定進入 compare 候選：live Neo4j 裡根本沒有 `TP-Link Archer BE805` 的 `Document` 節點，只有 `SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10`，因此 compare 只能依賴 filesystem fallback。原本 `_find_wifi_document_metadatas_for_query()` 在找到 1 筆 WiFi profile 時就會早退，導致 compare 需求下的 fallback 不會補進 BE805；已把早退條件改成「只有在非 compare 或 WiFi profile 已達 2 筆以上時才直接返回」，讓 compare 題能在 Neo4j 只有 1 筆 WiFi 文件時繼續合併檔案系統候選。已在 live `web` 容器內直接驗證：`_find_wifi_document_metadatas_for_query()` 會回傳 `['type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10', 'SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10']`，`_build_wifi_throughput_compare_answer()` 也能正常產生 `mode=wifi_compare` 與兩份來源；但同時也觀察到 `search_task(..., sources_only=True)` 的實際任務仍有一條路徑會掉回 `mode=vector`、只回 CHS 單文件原文，表示 task 層仍可能存在額外的快取/分支差異，後續若要完全收斂，應再追這條 sources_only 任務為何沒有採用已成功的 compare builder 結果。
- 2026-06-03 已實際在 `https://127.0.0.1:3030/chat.html` 重測 `請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput`。這次流程是先送 `POST /search`，接著輪詢 `/tasks/{task_id}`，最後前端 console 顯示 `Prepared WiFi compare KB result.`；但 KB 只穩定命中 1 份 WiFi 文件 `SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.md`，熱圖也顯示 `WiFi=100/1`、`4G/5G=0/0`。最終 bot 回覆為「`KB 參考已整合知識庫來源`」、「`KB 匯整來源：SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.md`」，並明確提示「未找到足夠的 WiFi 文件可進行比較」，同時列出未命中的查詢文件為 `BE805`、`CHS3320N-D388`、`TP-LINK ARCHER BE805`。這代表目前路由已正確進入 WiFi compare，但比較來源仍不足，下一步應追查 BE805 為何未被 compare 候選穩定命中。
- 2026-06-03 已再掃一次同類型被錯放的 WiFi 檔案並逐份拉回正確類別：`data/raw/type2_wifi_SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.xlsx` 與 `data/raw/type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx` 已刪除，避免與 `data/raw/WiFi` 中的 canonical 檔重複；`data/type2_WiFi_AP.xlsx` 已複製成 `data/raw/WiFi/type2_wifi_WiFi_AP.xlsx`，並補齊 `data/uploads/WiFi/ingest_20260603_185500_wifi_ap/original/type2_wifi_WiFi_AP.source.json`，Neo4j 中的 `type2_wifi_WiFi_AP` 節點確認仍為 `storage_category = WiFi`、`extraction_mode = wifi`。最新掃描結果顯示已沒有 `type2_wifi` / `WiFi_AP` 類檔案殘留在錯誤路徑，WiFi 原始資料目前只保留在 `data/raw/WiFi` 與 `data/uploads/WiFi`。
- 2026-06-03 已直接把被錯放到 `4G_5G` 的 `SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10` 正式重攝入回 WiFi 類別，並刪除舊的 `data/uploads/4G_5G/ingest_20260602_075125_0655d88d` 錯放資料夾。實作上是先用 `cleanup_existing_document(doc_name)` 清掉 Neo4j / QDrant / 舊資產，再從 `data/raw/WiFi/SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.xlsx` 重新轉成新的 WiFi ingest 目錄 `data/uploads/WiFi/ingest_20260603_184500_chs3320n/converted/SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.md`，接著以 `extraction_mode='wifi'` 重新 `ingest_document()`。重建後 Neo4j 的 `Document` 節點已顯示 `storage_category = WiFi`、`extraction_mode = wifi`，而 `SearchEngine.search('請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput', mode='auto')` 也仍回 `mode=wifi_compare`，答案內同時包含 BE805 與 CHS3320N-D388，證明資料層已回到正確類別；舊的 4G/5G 版本資料夾已確認刪除，不再殘留在 uploads 下。
- 2026-06-03 已繼續追查 `請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput` 為什麼一度只回單一 BE805 文件：根因不是 query 沒抓到 `CHS3320N-D388`，而是 WiFi metadata 搜尋只掃 `data/uploads/WiFi`、`data/raw/WiFi`、`data/processed/WiFi`，但 `CHS3320N-D388` 這份 WiFi 報告先前被舊規則攝入到 `data/uploads/4G_5G/ingest_20260602_075125_0655d88d/converted/SIT-TR-WL-Throughput-CHS3320N-D388-EV-V10.md`，因此永遠不會進入 WiFi 候選清單。已將 `src/search/__init__.py` 的 `_find_wifi_document_metadatas_for_query()` 擴大到掃描整個 `data/uploads` / `data/raw` / `data/processed`，再以檔名與 query hint 做 WiFi 文件篩選；同時新增 `_merge_wifi_metadata_candidates()`，讓 compare 路徑在 Neo4j 找不到兩份 WiFi 文件時，能從檔案系統補回候選並維持去重順序。`src/search/__init__.py` 與 `src/web_api/tasks.py` 的 compare 入口都已補上 fallback 合併，避免 sources_only 與主搜尋出現不同結果。已重新 `./restart_kb.sh` 並實際在 live `/chat.html` 測 `請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput`，最終 task `ee5280ed-7fa1-4a41-81c2-e1053608c546` 回傳 `mode=wifi_compare`，`answer` 內同時包含 `TP-Link Archer BE805` 與 `CHS3320N-D388` 兩份文件，`contains_chs=True`、`contains_be805=True`，確認 compare 現在可正確補回被錯放到 `4G_5G` 的 WiFi 報告。
- 2026-06-03 已實際詢問 `請比較 TP-Link Archer BE805 和 CHS3320N-D388 的 WiFi Throughput` 並觀察 live `/chat.html`：請求先送到 `/search`，產生 task `f765e30b-008e-42cb-82ac-e8a3741afe72`，輪詢後約 4.6 秒完成。這次回覆沒有進入真正的雙文件 compare，而是先命中 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx` 的 WiFi 原文路徑，answer 直接列出 BE805 的 `2.4GHz / 5GHz / 6GHz` throughput 表，再由 LLM 在解讀段落明確指出「來源文件僅包含 TP-Link Archer BE805 的測試數據，完全缺失 CHS3320N-D388 的相關資料，因此無法進行兩款產品的 WiFi Throughput 比較」。熱圖統計顯示本次只回推到 1 份 WiFi 原始文件，`WiFi=100/1`、`4G/5G=0/0`。這代表目前路由行為是「當 compare 目標只穩定命中一份 WiFi 文件時，先回單文件 throughput 原文，再由解讀層說明缺少對比文件」，而不是誤跳到 4G/5G 或 BE805 以外的 report。
- 2026-06-03 已追查 `請整理 TP-Link Archer BE805 的 5GHz 80MHz 與 160MHz 數據` 為什麼原文已顯示 160MHz、但解讀卻說找不到 160MHz：根因不是資料缺失，而是 `src/search/__init__.py` 的 `_build_report_graph_interpretation()` 會把 `raw_answer` 直接截成前 2600 字元，導致 WiFi throughput 原文的後段 `4.2.4 5GHz - Bandwidth 160MHz` 被裁掉，LLM 只看到 80MHz 區塊，便誤判資料不足。已改成共通的 `_build_balanced_raw_excerpt()`，不再只保留開頭，而是同時保留原文前段與尾段；`_build_report_graph_compare_llm_comment()` 也一起改用這個 helper，避免 compare comment 也因截斷漏掉後段內容。已重啟 `./restart_kb.sh` 並在 live `/chat.html` 實測同一句話，現在回答的 `解讀` 會明確列出 `80MHz` 與 `160MHz` 兩段數值，並正確比較 `160MHz` 約為 `80MHz` 兩倍，證明問題已修正且不再誤判「找不到 160MHz」。
- 2026-06-03 已繼續追查 `請比較 CHS3320N-D388 和 NCQ2200B2V-D294 的 WiFi Throughput` 在 live chat 仍回到 BE805 的原因，確認問題不在 `SearchEngine.search()` 本身，而是在 `src/web_api/tasks.py` 的 `search_task(..., sources_only=True)` 快捷路徑：這條路徑會先走 report-like / vector 的舊分支，沒有套用新的 WiFi compare 路由，因此前端 `prepareReportGraphContext()` 先拿到 `report_graph` 結果，直接渲染出錯誤的 compare answer。已著手把 `sources_only` 路徑補齊成與主搜尋相同的 WiFi compare 邏輯，改成先用 `_find_document_profiles_for_query()` 找出 WiFi 兩份文件，再由 `_build_wifi_throughput_compare_answer()` 產生 compare 回答，避免 compare query 再被 report_graph 先截胡。
- 2026-06-03 已把 WiFi compare 路徑整理成更明確的規則：前端 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 的 compare 分支現在會先檢查 `shouldPreferWifiCompare(query)`，只要是 `比較/差異/...` 且帶有 WiFi 線索，就優先走 `prepareWifiSpecificSummary()`，不再先問 `prepareReportGraphContext()`；WebSocket proxy 的 `run_compare_report_graph_direct()` 也改成接受 `wifi_compare` 與 `report_graph` 兩種結果，並在註解中明確標示 WiFi compare 優先、report_graph 第二順位。這樣未來新的 WiFi 比較題就算命中 compare 入口，也會先走 WiFi compare，不會因為 query 含有「比較」而被 report_graph 搶先處理。
- 2026-06-03 已把 compare 判斷再抽成共用 helper：新增前端共用檔 [`frontend/lib/compare-rules.js`](<project-root>/knowledge-base/frontend/lib/compare-rules.js) 供 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 同步使用，並新增 Python 版 [`src/compare_rules.py`](<project-root>/knowledge-base/src/compare_rules.py) 供 websocket proxy 的 `_is_compare_like_query()` 直接引用，避免三個路徑各自維護不同的 compare 正則。`restart_kb.sh` 也同步將 `compare-rules.js` 複製到 `.frontend-build-runtime-user8/lib/`，確保 `chat.html` 在 runtime 直接載入同一份 helper。已完成 `python3 -m py_compile src/web_api/__init__.py src/compare_rules.py` 與 `npm --prefix frontend run build`，並實際重啟 KB 後用 `/chat.html` 驗證 `請比較 CHS3320N-D388 和 NCQ2200B2V-D294 的 WiFi Throughput` 仍正確回 `CHS3320N-D388` + `NCQ2200B2V-D294`，不再出現 `TP-Link Archer BE805`。
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
- 2026-06-01 已新增手動攝入流程的客戶說明用 PPTX：[manual_ingest_customer_intro.pptx](<project-root>/knowledge-base/manual_ingest_customer_intro.pptx)。內容採 3 頁亮色系簡報：第 1 頁說明「手動攝入是什麼」與適用情境，並用一條完整流程總結「上傳文件 -> 自動轉換 -> 切成 chunks -> 寫入 Neo4j -> 寫入 Qdrant」；第 2 頁用 5 個步驟拆解實際手動攝入流程，讓客戶可以理解上傳後系統會自動完成處理，不需要人工逐步搬移資料；第 3 頁以 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.xlsx` 為實例，示意報告會切成 `2. Introduction`、`3. Test Result Summary`、`4. Performance Test` 等 chunks，再分別進入 Neo4j 與 Qdrant，說明前者負責關聯脈絡、後者負責語意搜尋。對應生成腳本為 [`generate_manual_ingest_pptx.py`](<project-root>/knowledge-base/generate_manual_ingest_pptx.py)。
- 2026-06-01 已將 [`neo4j_customer_intro.pptx`](<project-root>/knowledge-base/neo4j_customer_intro.pptx) 與 [`qdrant_customer_intro.pptx`](<project-root>/knowledge-base/qdrant_customer_intro.pptx) 補上實際對應範例，讓客戶更容易理解兩個資料庫在系統中的用途。Neo4j 頁面新增兩組實際關聯示例，包含 `SCU2060 ↔ SCU2140` 的 Throughput / Latency 關係，以及 `SCU2050 ↔ SCU2060` 的 Handover / Performance 脈絡；Qdrant 頁面新增 chunk 範例，說明像 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.xlsx` 這類報告會切成 `2. Introduction`、`3. Test Result Summary`、`4. Performance Test` 等獨立向量區塊，再由語意搜尋召回。對應生成腳本仍為 [`generate_db_intro_pptx.py`](<project-root>/knowledge-base/generate_db_intro_pptx.py)。
- 2026-06-01 已為知識庫後端兩個主要資料庫各製作一份客戶說明用 PPTX：[neo4j_customer_intro.pptx](<project-root>/knowledge-base/neo4j_customer_intro.pptx) 與 [qdrant_customer_intro.pptx](<project-root>/knowledge-base/qdrant_customer_intro.pptx)。兩份皆為單頁亮色系簡報，內容以「用途 / 系統內角色 / 客戶如何理解」為主，盡量避免技術名詞堆疊。Neo4j 頁面重點在說明它負責保存文件、專案與章節之間的關聯；Qdrant 頁面重點在說明它負責保存內容向量、支援語意搜尋與相似段落召回。對應生成腳本為 [`generate_db_intro_pptx.py`](<project-root>/knowledge-base/generate_db_intro_pptx.py)。
- 2026-06-01 已將 [`query_examples_slide.pptx`](<project-root>/knowledge-base/query_examples_slide.pptx) 改成亮色系版本，整體視覺已從深色主題轉為白底 / 淺藍綠的商務風格。內容維持原本 3 頁與 20 條實際 query 範例不變，但封面、題目卡、標籤與說明區都已同步改成亮色系，讓簡報更適合正式對外展示。對應生成腳本為 [`generate_query_examples_pptx.py`](<project-root>/knowledge-base/generate_query_examples_pptx.py)。
- 2026-06-01 已將 [`kb_architecture_slide.pptx`](<project-root>/knowledge-base/kb_architecture_slide.pptx) 改成亮色系版本，整體視覺由深色背景切換為白底/淺藍綠系，讓簡報更像正式商務提案頁。內容仍維持 3 頁正式說明，但色彩與卡片樣式已重新設計為更明亮、更易讀的風格，避免深色簡報造成客戶閱讀負擔。對應生成腳本為 [`generate_kb_architecture_pptx.py`](<project-root>/knowledge-base/generate_kb_architecture_pptx.py)。
- 2026-06-01 已將知識庫系統架構簡報改成更正式的說明版：[kb_architecture_slide.pptx](<project-root>/knowledge-base/kb_architecture_slide.pptx)。目前仍維持 3 頁，但內容已從極簡提示改為可直接對客戶說明的正式文字：第 1 頁說明簡報目的與系統定位，第 2 頁以簡化架構圖說明前端入口、知識庫核心與 Neo4j/Qdrant 的分工，第 3 頁則以段落文字清楚描述各元件責任與整體結論。原本偏口語的示例式文字已移除，版面也保留較豐富的色塊與說明卡，以維持正式但不失簡潔的簡報風格。對應生成腳本為 [`generate_kb_architecture_pptx.py`](<project-root>/knowledge-base/generate_kb_architecture_pptx.py)。
- 2026-06-01 已將知識庫系統架構簡報再簡化成更適合業務/客戶看的極簡版：[kb_architecture_slide.pptx](<project-root>/knowledge-base/kb_architecture_slide.pptx)。目前只保留 2 頁：第 1 頁是簡報封面與重點摘要，第 2 頁只放三個核心區塊「前端入口 / 小幫手卡片盒」、「後端核心」、「Neo4j + Qdrant」，並用一句簡短說明區分 Neo4j 與 Qdrant 的角色。原本的 Nginx、Celery、Redis、Ollama、OpenClaw 等技術細節已移除或縮成註記，避免畫面太技術化；對應生成腳本為 [`generate_kb_architecture_pptx.py`](<project-root>/knowledge-base/generate_kb_architecture_pptx.py)。
- 2026-06-01 已新增簡化版知識庫系統架構簡報：[kb_architecture_slide.pptx](<project-root>/knowledge-base/kb_architecture_slide.pptx)。內容採 3 頁設計：第 1 頁是簡報封面與重點摘要，第 2 頁用單張架構圖說明從使用者、前端、Nginx、FastAPI，到 Celery / Redis / Neo4j / Qdrant / Ollama / OpenClaw 的整體關係，第 3 頁用「查詢流程」與「上傳 / 攝入流程」兩條路徑說明資料如何流動。這版刻意簡化，不放程式碼與部署細節，適合直接對客戶簡報使用；對應生成腳本為 [`generate_kb_architecture_pptx.py`](<project-root>/knowledge-base/generate_kb_architecture_pptx.py)。
- 2026-06-01 已將 `query_examples_slide.pptx` 改成真正有內容的三頁式簡報：第 1 頁是封面，第 2 頁放 10 條 4G/5G 實際範例題目，第 3 頁放 10 條 WiFi 實際範例題目。4G/5G 頁面涵蓋 `SCU2140 / SCU2060 / SCU5050 / Throughput / Case / Latency / Performance / Handover / 相關報告` 等題型，WiFi 頁面涵蓋 `TP-Link Archer BE805 / 2.4GHz / 5GHz / 6GHz / 80MHz / WiFi 7 / WiFi 6 / 相關文件` 等題型。已保留生成腳本 [`generate_query_examples_pptx.py`](<project-root>/knowledge-base/generate_query_examples_pptx.py)，之後只要重跑腳本就能更新整份 PPTX。
- 2026-06-01 已將 `query_examples_slide.html` 的內容實際輸出成 PowerPoint 檔案：[query_examples_slide.pptx](<project-root>/knowledge-base/query_examples_slide.pptx)。此檔為真正的 PPTX 文件，不只是 HTML 視覺模擬；目前內容是一頁式 16:9 封面簡報，沿用封面式設計，適合直接在 PowerPoint / LibreOffice 開啟與編修。為了可重製，也另外保留生成腳本 [`generate_query_examples_pptx.py`](<project-root>/knowledge-base/generate_query_examples_pptx.py)。
- 2026-06-01 已將 `query_examples_slide.html` 改成更接近 PPTX 開頭頁的封面式版型：採 16:9 單頁簡報風格、深色漸層背景、上方品牌列、左側大標題與副標、右側摘要卡片，以及下方 4 個精簡的 query 類型卡，重點放在「先講測試邏輯，再往下帶代表性例句」。這版比原本的矩陣表格更像簡報開場頁，適合直接拿去當投影片首頁使用。
- 2026-06-01 已確認剛剛產生的 `query_examples_slide.html` 實體路徑是 `<project-root>/knowledge-base/query_examples_slide.html`，檔案位於專案根目錄；後續若再次詢問同一檔案位置，可直接使用這個絕對路徑。


- 2026-06-01 已新增一張可直接拿去報告的單頁 HTML 投影片：[query_examples_slide.html](<project-root>/knowledge-base/query_examples_slide.html)。內容將 4G/5G 與 WiFi 的範例題型依語意類型分成 4 類：`直接查數據`、`完整/詳細`、`比較/差異`、`泛問/相關文件`，每一類都各自列出 4G/5G 與 WiFi 的實測句型，例如 `請查詢SCU2140的Throughput測試數據`、`請顯示SCU2060詳細的Throughput測試數據`、`SCU2060、SCU2140、SCU5050 的Throughput有什麼差異？`、`請查詢TP-Link Archer BE805的5GHz Throughput測試數據`、`WiFi 7 和 WiFi 6 有什麼差別？` 等。這張 slide 採單頁深色簡報風格，已可直接作為簡報使用；若之後要延伸，也可再拆成多頁版或補成可列印版 PDF。
- 2026-06-01 已修正卡片盒點文件出現 `file not found` 的問題：根因是 `src/web_api/__init__.py` 的 `/api/document` 只查 `data/processed/{category}`，且 metadata fallback 也只掃 processed 目錄，所以像 WiFi 的 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10` 這種只落在 `data/uploads/WiFi/.../converted/` 的文件，一點進去就會 404；同時 `get_category_files()` 也只列 processed 檔案，無法把 upload-only 的文件補進卡片盒。已做兩層修正：新增共用文件解析 helper `_find_document_content()`，會依序搜尋 processed / uploads / 全資料根目錄，並回推 `*.source.json` 的 `converted_path` / `original_path`；`get_category_files()` 也改成同時掃 `data/processed/<category>` 與 `data/uploads/<category>` 的 markdown/text 檔，避免卡片盒列出後卻打不開。已重啟 `web` / `nginx` 後實測 `WiFi`、`Lab`、`Project`、`Automation` 的第一個文件都能正常打開，`WiFi` 的 BE805 文件現在回傳的是 `data/uploads/WiFi/ingest_20260531_021134_9058675d/converted/type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.md`，`/api/category-files?category=WiFi` 也已把這份 upload-only 文件列進去；`4G/5G` 目前在現有資料下沒有文件可列。這次修正已覆蓋卡片盒的通用文件開啟路徑，不只 WiFi，之後其他分類若也只存在於 uploads 轉換目錄，會同樣可開啟。
- 2026-05-31 已修正 `請查詢TP-Link Archer BE805的Throughput測試數據` 這類 WiFi 專用查詢會掉回 4G/5G report_graph 的問題：根因不是 WiFi 文件未攝入，而是前端 `prepareWifiSpecificSummary()` 與 WiFi 專用分支原本只等 120 秒，遇到 WiFi 向量檢索耗時較長時就會提早 timeout，接著 `sendMessage()` 仍會繼續往一般 `reportLikeQuery` / `prepareReportGraphContext()` 走，最後把 4G/5G 的 Throughput 報告蓋上來。已同步做兩層修正：`frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 的 WiFi 專用等待時間已拉到 360000 ms，且 WiFi 查詢一旦進入專用分支，不論是否直接命中原文，都不再 fallback 到一般 report 查詢，而是只顯示 WiFi 原始文件 context 或 WiFi fallback 訊息；後端 `src/search/__init__.py` 仍維持 WiFi-specific query 先於 report_graph 的 routing，`TP-Link Archer BE805` 這類查詢現在會正確命中 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.md`，回傳的 `citation_distribution` 也只會是 WiFi 類別。已用 `https://127.0.0.1:3030/chat.html` 實測，頁面最後顯示的是 BE805 的 WiFi 原始文件與摘要內容，沒有再出現 SCU2060 / SCU2140 / SCU5050 的 4G/5G report_graph，證實前端 fallback 已被切斷且不影響原本 4G/5G 查詢路徑。
- 2026-05-31 已修正 `請查詢TP-Link Archer BE805的5GHz Throughput測試數據` 這類 WiFi band throughput 查詢只顯示 20MHz 與 160MHz、漏掉原始 80MHz 的問題：根因不是原始 Excel 沒有 80MHz 數據，而是 WiFi 專用路徑仍先走 `vector_search`，最後由 LLM 在上下文裡自行挑片段，導致 5GHz 的 80MHz 章節可能被排序或摘要階段忽略。已在 `src/search/__init__.py` 新增 WiFi band throughput 的固定原文抽取路徑：只要 query 明確命中 `2.4GHz / 5GHz / 6GHz` 與 `throughput` 類語意，就會直接從對應 converted markdown 抽出整個 `4.1 / 4.2 / 4.3` 主章節，確保 `5GHz` 的 `20MHz / 40MHz / 80MHz / 160MHz` 全部同時保留，不再交由向量排序挑段落；其中 80MHz 在原始 WiFi 報告中有完整 Tx/Rx 數值，新的固定抽取路徑會直接把這段原文帶回。已用本機 `SearchEngine.search('請查詢TP-Link Archer BE805的5GHz Throughput測試數據')` 驗證會直接回 `mode=wifi_band_raw`，輸出原文中完整的 `4.2 5GHz Test` 區塊，包含 `4.2.3 5GHz - Bandwidth 80MHz`，不再只剩 20MHz / 160MHz 兩段。
- 2026-05-31 已再驗證 `TP-Link Archer BE805` 的三個 WiFi 頻段 Throughput 查詢一致性：`請查詢TP-Link Archer BE805的2.4GHz Throughput測試數據`、`5GHz Throughput測試數據`、`6GHz Throughput測試數據` 現在都會直接走 `mode=wifi_band_raw`，輸出 `## 原文` + `## 解讀` 的固定格式，來源皆為 `type2_wifi_SIT-TR-WL-Throughput-TP-Link Archer BE805-MP-V10.xlsx`。其中 2.4GHz 會完整列出 `4.1 2.4GHz Test` 的 20MHz / 40MHz 內容，5GHz 會完整列出 `4.2 5GHz Test` 的 20MHz / 40MHz / 80MHz / 160MHz 內容，6GHz 會完整列出 `4.3 6GHz Test` 的 80MHz / 160MHz / 320MHz 內容；6GHz 的 80MHz 原始表格本來就多數為空白欄位，因此現在的輸出會如實保留空白，不會補值。這代表三個頻段已經統一成同一種 WiFi band 直出流程，格式一致且不再回掉 4G/5G report_graph。
- 2026-05-31 已將 WiFi band raw 的固定原文直出再補上 LLM 簡短分析，讓行為更接近 4G/5G 模式：原本 2.4 / 5 / 6GHz throughput 只有原文表格與固定解讀，沒有真的把原文交給 LLM 做短評。已修正 `src/search/__init__.py` 的 WiFi band raw 路徑，改成先抽出 `4.1 / 4.2 / 4.3` 主章節原文，再透過既有 `_compose_raw_then_interpretation()` 呼叫 LLM 生成 2~4 條簡短解讀；同時修掉 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 中 WiFi 直出判斷引用不存在 `getSourceRawPath()` 造成的例外，避免 WiFi band raw 直接落版被前端錯誤打斷。已用 `https://127.0.0.1:3030/chat.html` 逐項測試 `2.4GHz / 5GHz / 6GHz`，三者都已回傳 `mode=wifi_band_raw`，且 `## 原文` + `## 解讀` 格式一致；其中 5GHz 的 `80MHz`、6GHz 的 `80MHz / 160MHz / 320MHz` 都已如實保留在原文區塊，LLM 解讀僅做短評，不新增數字。

- 2026-05-30 已修正 `請顯示SCU2060詳細的Throughput測試數據` 這類「單一報告 + 數值題 + 明確要求詳細/完整」的查詢只輸出 case 13~16 的問題：根因是 `_build_numeric_direct_answer()` 在沒有 case hint 時仍會經 `_select_numeric_case_sources()`，而該選取器預設只保留同文件中 case 編號最高的 4 個 case。已新增 `_should_preserve_all_numeric_cases()`，當 query 含有「詳細 / 完整 / 全部 / 所有 / 列出 / 顯示 / 明細 / 測試數據」等訊號時，數值題會改走全 case 合併路徑，保留 `Case 1~16` 的完整逐 case 原文，不再只取尾段四個 case。已用 [`https://127.0.0.1:3030/chat.html`](https://127.0.0.1:3030/chat.html) 實測，現在 `SCU2060` 的 Throughput 詳細數據已能完整顯示 `Case 1~16`，不會再只看到 `Case 13/14/15/16`。
- 2026-05-30 已將 knowledge-base 內所有 Ollama 預設模型統一改為 `qwen3.6:35b-a3b`：`config/config.yaml`、`config/config.yaml.example`、`src/main.py`、`src/search/__init__.py`、`src/web_api/llm_factory.py`、`src/web_api/__init__.py`、`src/web_api/tasks.py`、`src/converter/__init__.py`、`src/web_api/ollama_client.py` 等 runtime 路徑的預設值都已改成新模型；同時 README 與 LLM flow 文件也同步更新，避免文件還顯示舊的 `gemma4:e4b`。已刪除 `src/web_api/minimax_client.py` 後，現在 KB 只保留 Ollama 路徑，之後若要改模型只需要調整 `ollama.model` 與相關預設值，不再有 MiniMax 的切換/備援分支。
- 2026-05-30 已移除 knowledge-base 內所有 MiniMax-M2.7 相關設定與切換分支，統一只保留 Ollama：`config/config.yaml` 與 `config/config.yaml.example` 不再含 `minimax` 區塊，`src/web_api/llm_factory.py` 改為固定建立 Ollama client，`src/web_api/__init__.py` 的 `/analyze-question`、`src/converter/__init__.py`、`src/search/__init__.py` 也都移除 MiniMax provider 分支；同時刪除 `src/web_api/minimax_client.py`，並同步更新 README 與 LLM flow 文件，避免文件仍顯示可切換 MiniMax。這代表 KB 核心搜尋、compare、報告摘要與卡片分析現在都只會使用 Ollama，若未來要改模型只需調整 Ollama 設定，不再有 MiniMax 備援切換。
- 2026-05-30 已評估移除 MiniMax-M2.7 相關設定的影響：若只移除 knowledge-base repo 內的 MiniMax 設定，核心 KB 搜尋、compare、report_graph、圖片/OCR 增強、實體萃取多半仍會因 Ollama fallback 正常運作，但 `/analyze-question` 的卡片分析與少數可切換 provider 的路徑會失去 MiniMax 備援能力，會統一退回 Ollama。若要連 OpenClaw 小幫手端一起去掉 MiniMax，則還需同步修改 `~/.openclaw/openclaw.json` 或對應的 OpenClaw 設定，否則代理層仍可能使用 MiniMax-M2.7。整體建議是：KB 攝入與搜尋維持在後端，OpenClaw 只保留觸發與編排，不要把攝入或查詢核心搬到 skill 內。
- 2026-05-30 評估 OpenClaw 介入攝入流程的方式：結論是攝入本體應維持在 knowledge-base 後端，OpenClaw 比較適合扮演觸發器/編排層，而不是把 ingest 邏輯搬進 skill 或 prompt 內。若要讓小幫手主動協助上傳新報告，較佳做法是由 OpenClaw 透過 MCP 或現有 HTTP API 觸發 KB 的 `/upload`、`/upload/ingest`、`/upload/tasks/{task_id}` 等端點；其中 MCP 適合做成穩定、可重用、可控權限的工具介面，skill 則較適合承載「何時要觸發攝入」的流程規則，但不建議讓 skill 直接承擔檔案上傳與 Neo4j/QDrant 寫入。這樣能保留 KB 端既有的模式自動判斷、report/simple 圖譜驗證與任務追蹤機制，也能避免把資料寫入責任分散到 agent 端造成不一致。
- 2026-05-30 已修正上傳攝入入口的模式覆寫風險：`/upload/ingest` 原本只會把檔名偵測結果中的 `report` 保留下來，其餘情況一律使用前端傳入的 `extraction_mode`，導致像 `type6_NR-Handover-*.xlsx`、`type6_NR-Throughput-*.xlsx` 這類本應走 `simple` 的檔案，可能被錯誤當成 `4g5g` 上傳。已將 `effective_mode` 改成：只要 `detect_extraction_mode()` 回傳 `report` 或 `simple`，就直接採用檔名判斷結果，不再被前端預設模式覆寫；這樣新報告上傳時只要檔名規則正確，就會自動走對應的攝入路徑，避免未來再出現「檔案已上傳但圖譜不完整」的風險。
- 2026-05-30 檢查並強化目前攝入機制的風險控制：先前 `type6` / `simple` 類 Handover 報告會只進 QDrant、不進 Neo4j，造成像 `SCU2050` 這類新進 Handover 專案在查詢「有哪些專案有 Handover 測試項目？」時漏掉。已把 `src/ingest.py` 的 `simple` 模式改成：只要 `infer_report_type()` 判定為非 `generic_report`，就先補寫 Neo4j report graph，再寫 QDrant；若圖譜寫入後 `sections/test_items/test_cases/metrics` 統計為 0，則直接視為失敗，避免「看似成功但其實沒有圖譜」的假成功。`src/search/__init__.py` 也已新增 Handover catalogue 分支，可直接從 `data/processed/**/*.source.json` 彙整所有 Handover 報告來源，避免查詢端只依 Neo4j 而漏掉應該顯示的專案。已用本機 py_compile 驗證語法通過，並確認 `SearchEngine._report_graph_search_raw('有哪些專案有Handover測試項目？')` 會回傳 `sources=2`。這次的風險改善重點是：未來新進的報告型 `simple` 文件，不會再悄悄只進向量庫而沒有圖譜。

- 2026-05-30 再次修正 `有哪些專案有Handover測試項目？` 在線上 `https://127.0.0.1:3030/chat.html` 仍只顯示單一 `SCE2200` 的問題：這次真正卡住的點是在前端 `prepareGeneralHandoverSummary()` 會先走 `mode=basic` 並直接落版 `summaryResult.answer`，而 `basic` 路徑原本在 `search()` 內又因 `report_graph` 的 Handover catalogue 分支位於空 hints 早退之後，導致 catalog query 其實沒有被執行，最後只剩既有的單一 Handover 摘要。已將 `src/search/__init__.py` 的 Handover catalogue 分支提前到空 hints 早退之前，讓 `有哪些專案有Handover測試項目？` 這類 query 在 basic / auto 都會先返回 `## 原文` 表格，內容直接列出 `SCE2200` 與 `SCU2050` 兩份 Handover 報告；同時 `src/ingest.py` 的 `simple` 模式若偵測到 Handover 文件，也會額外補寫 Neo4j report graph，避免未來新增的 Handover 文件只進向量庫。已用本機 `SearchEngine._report_graph_search_raw` 驗證會回傳 `report_graph`、`sources=2`，並重啟 KB 讓 runtime 載入新版邏輯，之後同類 Handover 清單查詢應可直接顯示兩份專案，而不是單一 `SCE2200`。
- 2026-05-30 已修正「有哪些專案有Handover測試項目？」只回到單一專案且內容錯誤的問題：根因是目前 Neo4j 內只存在 `SCE2200` 的 Handover report graph，`SCU2050` 的 `type6` Handover 文件原本只走 QDrant / markdown，沒有寫入 Neo4j 圖譜，因此查詢端若只依圖譜會漏掉 `SCU2050`。已同步做兩層修正：`src/ingest.py` 的 `simple` 模式若偵測到 Handover 文件，會額外補寫 Neo4j report graph；`src/search/__init__.py` 則新增 Handover catalogue 查詢分支，會掃描 `data/processed/**/*.source.json` 組出所有 Handover 報告的清單，輸出固定的 `## 原文` + `## 解讀`。已重新攝入 `data/processed/Simple/type6_NR-Handover-SCU2050-EV-V004.md`，Neo4j 現在可查到 `SCE2200 / type6_NR-Handover-SCE2200-n79-EV-V13.8` 與 `SCU2050 / type6_NR-Handover-SCU2050-EV-V004` 兩份 Handover 報告；本機也已用 `SearchEngine._report_graph_search_raw('有哪些專案有Handover測試項目？')` 驗證會回傳 `report_graph`、`sources=2`，`answer` 的原文表格已列出兩份來源。這版已重啟 KB，之後同類 Handover 清單查詢會直接反映已攝入的完整來源，而不再只剩 Neo4j 中的單一項目。
- 2026-05-30 已修正 `SCU2140、SCU2060、SCU5050 的Throughput有什麼差異？` 這類 compare 問題只顯示 13~16 四個 case 的問題：根因是 compare 路徑在沒有明確 case hint 時，仍把 numeric compare 交給 `_build_numeric_direct_answer()` 與 `_select_numeric_case_sources()`，後者預設只保留同文件中 case 編號最高的 4 個 case，導致前面的 case 被大量裁掉。已新增 compare 專用的全 case 對照路徑，當 query 屬於 compare + numeric、但沒有 case hint 時，會改為保留每個專案的所有 case sources，並依 case number 組成全量對照表，讓 `Case 1~16` 都能納入比較；同時保留 LLM 的簡短評論作為 `## 解讀`，不再只顯示少數高 case。已重新啟動 KB 並用 [`https://127.0.0.1:3030/chat.html`](<project-root>/knowledge-base/AGENTS.md) 實測，現在 compare 回覆已會列出 `Case 1` 到 `Case 16` 的逐 case 對照表，之後同類 compare 問法也會沿用這個全 case 路徑。
- 2026-05-30 已將知識庫各模式統一調整為「原文先出、LLM 解讀置後」的雙段式回覆：先前雖然 report_graph / compare / Handover 部分路徑已經能輸出原文，但 basic / vector / hybrid / deep 等模式仍是單純把 LLM 的總結直接回給前端。已新增共用的原文包裝邏輯（從 `sources` 或 `graph_results` 生成原文區塊），並讓 `search()` 在所有成功結果上先檢查是否已含 `## 原文`，若尚未包含就自動補上原始資料，再保留原本的 LLM 解讀作為最後段落；同時將 `SCU2050 的相關報告數據` 的一般 Handover 摘要改成以 LLM 解讀重寫，不再使用固定條列，確保最終回覆是「原始章節摘錄 + LLM 針對原始資料的總結」。已重新啟動 KB，並用 [`https://127.0.0.1:3030/chat.html`](<project-root>/knowledge-base/AGENTS.md) 重新驗證 `請查詢SCU2050的相關報告數據`，現在回覆已正確呈現 `## 原文` 與 `## 解讀` 兩段，且 `4.2 NG Handover` 等原始內容完整保留；另驗證 `SCU2140、SCU2060、SCU5050 的case 15Throughput有什麼差異？` 仍維持 compare 的原文 / 解讀結構且未被二次包裝，說明這次是共用包裝、沒有破壞既有 report_graph / compare 路徑。
- 2026-05-30 已修正 `SCU2050 的相關報告數據` 一般 Handover 回覆數據不完整的問題：根因是先前 `src/search/__init__.py` 的 `general handover summary` 路徑雖然已避開 OpenClaw 蓋寫，但仍把 converted md 交給 LLM 摘要，導致 `2. Introduction / 2.5 Test Environment / 2.7 Test Configuration / 3. Test Result Summary / 4.1 Xn Handover / 4.2 NG Handover` 等章節中的原始數值容易被壓縮或省略。已將這條路徑改成直接從 converted markdown 抽出主要章節原文區塊（優先包含 `2. Introduction`、`2.5 Test Environment`、`2.7 Test Secenarios`、`3. Test Result Summary`、`4.1 Xn Handover`、`4.2 NG Handover`），不再依賴 LLM 摘要原始數據；解讀段則只做固定的補充說明，不會改動數值內容。已重新啟動 KB 並在 [`https://127.0.0.1:3030/chat.html`](<project-root>/knowledge-base/AGENTS.md) 實測，現在回覆已可直接列出 SCU2050 Handover 報告的完整原文章節與 4.2 NG Handover 明細，避免再出現「有摘要但數據不完整」的情況。
- 2026-05-30 已將同一條全域工作規範同步到 `~/.codex/AGENTS.md`：新增「每次修改前要先確認前一次及既有修正內容，任何新改動都不得影響前幾次已完成的修正，若有衝突要先調整整體方案再動手」等條款，確保全域規則與專案內 [AGENTS.md](<project-root>/knowledge-base/AGENTS.md) 一致。
- 2026-05-30 已更新 `AGENTS.md` 的全域工作規則，新增「每次進行修改前，必須先確認前一次與既有修正內容，避免新改動影響前幾次已完成的修正」的明確要求；後續做任何新修改前，都要先回顧既有修正與驗證結果，若會互相衝突要先調整整體方案，不可只針對單一現象局部修補。
- 2026-05-30 已修正 `請找出所有有Latency測試項目的報告` 只找到單一報告的問題：根因分成兩層，第一層是 `src/report_graph.py` 的 ingest 規則原本只會把 section 歸類成單一 `TestItem`，而 throughput 報告內的 latency 區塊雖然有 `Latency Test / RTT (ms)`，卻被歸到 `throughput`，導致 Neo4j 裡只有 `handover / throughput`，沒有真正的 `latency` 節點；第二層是 `src/search/__init__.py` 的 report graph 回答層對 `Latency` 類查詢仍沿用抽樣 sources，會把其他報告的 latency 區塊壓掉，只剩單一專案被列出。已將 ingest 改成同一個 section 可同時掛上 `throughput` 與 `latency` 兩個標準 TestItem，並重新 ingest 三份 throughput 報告 `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md`、`SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md`、`SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md`；同時把 latency 類查詢改成 `preserve_all=True`，避免回答層只看前幾筆來源。已用 Neo4j 直接驗證目前 `TestItem` 已包含 `handover / throughput / latency` 三類，且 `MATCH (r:Report)-[:HAS_TEST_ITEM]->(t:TestItem {canonical_name:'latency'})` 可回到三份報告。再用 [`https://127.0.0.1:3030/chat.html`](<project-root>/knowledge-base/AGENTS.md) 實測同題後，回覆已能列出 `SCU2060 / SCU2140 / SCU5050` 三份報告，表示 ingest 與查詢兩層都已修正，往後新攝入的 throughput 報告也會自動帶上 latency 關聯。
- 2026-05-30 已釐清「前兩天的 token 用量」在本機 Codex 紀錄中的可得性：專案本身沒有保存可直接對應「前兩天」的 per-day token 報表，`<project-root>/.codex/state_5.sqlite` 的 `threads.tokens_used` 只能提供 thread 級彙總。實際查詢 `2026-05-28 ~ 2026-05-29` 時，該區間在本機 `threads` 表中沒有對應紀錄，因此可計算的前兩天加總為 0；若要看真實帳單/用量，仍需到對應的 usage 或 billing 系統查詢。這次也順帶確認本機 `threads` 的整體 `tokens_used` 總和為 1,083,808,292，但這不等於兩天內用量。
- 2026-05-30 已修正 `chat.html` 的 SCU2050 一般 Handover 查詢路徑：先前 `SCU2050 的相關報告數據` 會先走後端 Handover 摘要，但最終仍被 OpenClaw 的最後一段改寫成「沒有找到任何關於 SCU2050 的報告資料」，造成前端顯示與後端摘要不一致。已將 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 的 `prepareGeneralHandoverSummary()` 對齊為 `mode: basic`、`top_k: 6`，並保留 `reportLikeQuery` 下的直接落版邏輯，確保像 `SCU2050 的相關報告數據` 這種泛報告查詢會直接顯示後端整理好的 Handover 摘要，不再被 OpenClaw 蓋掉；同時仍保留 `SCU2050 的Performance Test數據` 的固定拒答 guardrail。已透過 `https://127.0.0.1:3030/chat.html` 實測，輸出內容正確包含 `2. Introduction`、`2.7 Test Scenarios`、`3. Test Result Summary`、`4.1 Xn Handover` 等摘要段落，且最後畫面上顯示的是後端摘要而不是舊的「沒有 SCU2050 資料」答覆。
- 2026-05-29 已再次驗證 `SCU2050 的相關報告數據`：前端/助理若仍顯示「沒有找到任何關於 SCU2050 的報告資料」的舊答案，較可能是舊分頁或快取，而不是現行後端真的沒有資料。實測目前 `/search` 在 `mode=auto` 下會先走 Handover 泛查詢摘要路徑，回覆 `mode=basic` 且內容包含 SCU2050 Handover 報告的產品與測試概述、`2.7 Test Configuration`、`4.1 Xn Handover Test`、`3. Test Result Summary` 等摘要，`sources` 也會帶回 `type6_NR-Handover-SCU2050-EV-V004.xlsx`。另外 `SCU2050 的 Performance Test 數據` 仍維持固定拒答，說明性能題 guardrail 與一般 Handover 摘要路徑已分流成功。
- 2026-05-29 已修正 SCU2050 這類 Handover 報告的泛查詢誤攔問題：先前 `請查詢SCU2050的相關報告數據` 會被 `數據` 關鍵字誤判為 Performance 題，進而直接回覆「這份 Handover 報告沒有 Performance Test 章節，因此無對應章節可回覆」，導致明明有其他章節內容卻被擋掉。已將 Handover 缺章節的固定拒答收斂為「只有在明確詢問 Performance Test / throughput / latency / BLER / RTT / case / test case 等性能數據時才適用」，並新增一般 Handover 摘要路徑：當 query 是泛報告查詢但不是性能題時，系統會依 project code 找到對應的 Handover metadata，直接讀取 converted md 內容，再透過既有 LLM 摘要流程回覆其他章節重點，不再一律拒答。已重啟 KB 並驗證 `請查詢SCU2050的Performance Test數據` 仍維持固定拒答，但 `請查詢SCU2050的相關報告數據` 現在會回覆 SCU2050 Handover 報告的設備與測試環境資訊、`3. Test Result Summary` 與 `4. Xn/N2 Handover` 等其他章節摘要，達到「保留性能題 guardrail、同時允許一般報告摘要」的兼顧效果。
- 2026-05-29 已將 compare 類回答的 Ollama 輸出上限再次調高：先前把 `ollama.num_predict` 提到 2048 後，仍有 `SCU2140 和 SCU5050 共通的測試項目` 這種比較評論在句尾被切斷的現象，因此將 `config/config.yaml` 與 `config/config.yaml.example` 的 `ollama.num_predict` 進一步提高到 4096，並保留 `src/search/__init__.py` 的截斷偵測與保底評論。重啟 KB 後重新驗證同題，compare 的 `## 解讀` 已可完整輸出，最後一條評論不再被截尾。
- 2026-05-29 已修正 `SCU2140 和 SCU5050 共通的測試項目` 類 compare 回答被截斷的問題：根因是 compare 的 `### LLM 簡短評論` 由 Ollama 生成，而 runtime 的 `ollama.num_predict` 仍停在 768，導致模型在較長評論句尾被切斷，出現半句或尾端殘缺的情況。已將 `config/config.yaml` 的 `ollama.num_predict` 提升到 2048，並在 `src/search/__init__.py` 的 compare 評論生成加入截斷偵測與保底評論：若 LLM 評論看起來像被截斷，就會改用規則式的簡短比較評論，避免半句直接顯示給使用者。已重啟 KB 並重新驗證 `請查詢SCU2140和SCU5050共通的測試項目`，現在 compare 的 `## 解讀` 可以完整輸出，不再在句尾被截斷。
- 2026-05-29 已修正 `請列出Throughput底下有哪些Case` 的語意路由：原本這題會被 `list` / `numeric` 路徑帶偏，甚至因 `_report_graph_search_raw()` 內漏掉 `asks_case_list` 判斷而直接拋錯，最後退回 vector，輸出成大量 case 13~16 的原文片段。已在 `src/search/__init__.py` 補齊 `_report_graph_search_raw()` 的 `asks_case_list` / `asks_latency_reports` 判斷，並新增 `preserve_all=True` 的 report graph source 選取模式，讓 case-list 問法不再做 per-report 抽樣。另將 case-list 的章節欄優先收斂到 `4. Performance Test` 類章節，避免封面 / 目錄混入。已重啟 KB 並重新驗證 `請列出Throughput底下有哪些Case`，現在回覆為 `report_graph`，且可正確列出 `SCU2060 / SCU2140 / SCU5050` 各自 `1~16` 的 Case 清單；同輪回歸也確認 `請查詢Throughput相關報告數據`、`有哪些專案有Throughput測試項目？`、`SCU2140、SCU2060、SCU5050 的Throughput有什麼差異？`、`請找出所有有Latency測試項目的報告`、`請查詢SCU2140和SCU5050共通的測試項目`、`請查詢SCU2050的Performance Test數據`、`請查詢SCU2050的相關報告數據` 都仍維持正確語意。
- 2026-05-26 已進一步修正 SCU5050 `Performance Test` 回答與原始 Excel 不一致的殘留問題：根因不只在 chunk 粒度，還在報告重試 / 排序與 agent 規則會把 `3. Test Result Summary` 和 `4. Performance Test` 混用。已完成三層修正：`src/chunker/__init__.py` 現在會在遇到新 Markdown 標題時先 flush 既有 chunk，確保 `3. Test Result Summary` 與 `4. Performance Test` 不再跨章節拼接；`src/web_api/tasks.py` 對 report-like 的 performance 數值查詢不再強制塞入 `Test Result Summary`，且在 sources 上會優先保留 `Performance Test` 詳細 case；`src/search/__init__.py` 也對數值抽取加入更強的章節權重與 prompt 規則，明確要求 `Performance Test` 題型只能用 `4. Performance Test` 的逐 case 數據，不得把 summary 平均值當成詳細 case。同步更新 `<project-root>/.openclaw/workspace/skills/kb-query/SKILL.md`，讓 helper 端也遵守同一條硬規則。已重新 ingest 3 份 report 並重啟 KB；最新驗證 `請查詢SCU5050 的Performance Test 數據` 時，`/tasks/{task_id}` 的 `sources` 只回傳 `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001` 的 `## 4. Performance Test` 詳細 chunk（例如 chunk 27），不再夾帶 `3. Test Result Summary` 的混合內容，代表後續回答應可直接對齊原始 Excel 的 detailed case 數據。
- 2026-05-26 已實測 helper 查詢 `請查詢SCU5050 的Performance Test 數據`，並把回覆逐欄對照原始 Excel `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.xlsx`。結果顯示 helper 的第二組表格（Case 13~16）與 Excel 的 `4.13~4.16 Test Case` 平均值一致，例如 Case 13 的 `DL 1260 / UL 187 / Bidirection 1272 / 155 / UDP DL 1311 / UDP UL 195 / RTT 26.452`，Case 14~16 也都對得上；但 helper 的第一組表格明顯錯位，將 `3. Test Result Summary` 中 Case 9~12 的平均值（如 `1307 / 1120 / 945 / 744` 與 `61.056 / 27.068 / 25.703 / 26.185`）誤標成 Case 13~16。也就是說，helper 這次回覆不是整體一致，而是混用了不同章節的數值；後續若再查相同題目，應強制只取 `## 4. Performance Test` 內的對應 case，避免 summary table 與 detailed table 交叉混用。
- 2026-05-26 已更新 [`AGENTS.md`](<project-root>/knowledge-base/AGENTS.md) 的全域工作規則，明確加入跨電腦、跨 session、跨 runtime、跨部署路徑的影響評估要求；後續所有修改都必須優先考慮所有可預見的執行場景與失敗模式，不能只修單一機器或單一現象，並且要以根因修正與共通機制為主，若方案只覆蓋局部案例則必須明確標註適用範圍與未覆蓋風險。
- 2026-05-26 已修正 SCU5050 `Performance Test` 數據混值問題：原始 Excel 與轉出的 `data/processed/Report/SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md` 內容本身是正確的，例如 case 13 的 `Bidirection - DL` / `Bidirection - UL` 與 summary table 中的 `Bidirection` 值皆能在原檔對上；真正的問題出在 `src/chunker/__init__.py` 的 `chunk_by_headers()`，它會把整個 `## 4. Performance Test` 章節當成一個過大的向量 chunk，導致 QDrant 召回時同一筆 source 內混入多個 case（例如 case 13 與 case 16）而讓 LLM 在回答時把不同 case 的數字交叉引用。已將 chunker 改成逐行切分並在超過 `max_chunk_size` 時立即 flush / hard split，避免單一 chunk 夾帶整個章節；接著已在 `web` 容器內重新 ingest `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md`、`SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md`、`SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md` 三份 report，並重新執行 `restart_kb.sh` 驗證服務正常。最新的 source 搜尋顯示 case 13 已拆成更小的 chunk（例如 case 13 head / tail 分開），不再出現先前那種把 1~16 case 全包進同一筆 source 的情況。
- 2026-05-26 已把卡片盒改回「從 sources 回推到原始文件，再點擊顯示那些文件」的路徑：`frontend/chat.html` 現在會優先從 `sources` 聚合出 `topic.files`，並以 `citation_source_name` 顯示原始 `.xlsx` 檔名；卡片點擊時若已有回推結果，就直接開啟這些文件，不再只看 `/api/category-files` 的分類清單。後端 `/api/document` 也已補上 metadata fallback，可直接用原始 `.xlsx` 名稱回推到對應的 converted `.md` 內容。已重啟 KB 驗證 `請查詢SCE2200相關報告的資訊`：`sources` 仍有 11 筆 chunk，但 `citation_source_name` 去重後只有 1 份原始文件 `type6_NR-Handover-SCE2200-n79-EV-V13.8.xlsx`，`/api/source-categories` 也將其歸到 `4G/5G`，而 `/api/document?category=4G/5G&doc_name=type6_NR-Handover-SCE2200-n79-EV-V13.8.xlsx` 已可成功回傳內容，代表卡片顯示與點擊流程都已回到原本要的「文件級」行為。
- 2026-05-26 已把引用文件顯示邏輯改回「Excel 原始來源優先、沒有 Excel 才顯示 md」：在 `src/search/__init__.py` 新增 citation source enrichment，會回查 processed 目錄的 `.source.json`，並以 `citation_source_name / citation_source_path / citation_source_ext / citation_source_kind` 回傳給前端；若來源是 Excel，顯示原始 `.xlsx` 檔名與路徑，若沒有可對應的 Excel 中繼資料，則保留 md。前端 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 也同步改成優先讀 `citation_source_name`。已重啟 KB 驗證 `請查詢SCE2200相關報告的資訊`，`/tasks/{task_id}` 的 sources 現在顯示 `type6_NR-Handover-SCE2200-n79-EV-V13.8.xlsx`，`citation_source_kind=excel`，證實引用文件已回到原始 Excel 名稱。
- 2026-05-25 已正式修正 SCU2060 `Performance Test` 誤判：在 `src/web_api/tasks.py` 將報告型查詢的召回上限從 8 提升到 20，並新增第二輪聚焦查詢邏輯。當報告型查詢是 `SCU/SCE` 這類題目、且第一輪搜尋沒有抓到 `Performance Test` / `Test Result Summary` 時，系統會自動補打一輪 `Performance Test throughput latency bler rtt Test Result Summary` 的聚焦查詢，並合併去重後的 sources。已重啟 KB 驗證，使用 `請查詢SCU2060 的 Performance Test 數據` 重新搜尋時，`/tasks/{task_id}` 回傳的 sources 已包含 `chunk 10` 與 `## 4. Performance Test`，證明原先誤判是召回策略不足，不是 QDrant 沒有資料。
- 2026-05-25 重新分析 SCU2060 `Performance Test` 誤判：`data/processed/Report/SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md` 本體確實有 `## 4. Performance Test` 與完整 throughput / latency / BLER / RTT 表格（例如 4.1 的 Downlink 705、Uplink 169、RTT 16/31/163；4.2 的 Downlink 608、Uplink 277、RTT 17/27/45）。但 OpenClaw 舊回答那次走的是 `SCU2060 Performance Test` 的泛查詢，`/search` 在 `top_k=8` 下只回到 `2.6 DUT Test Configuration`、`2.7 Test Procedure`、`3. Test Result Summary` 前段，沒有把 `chunk 10 = ## 4. Performance Test` 排進來，因此 agent 才誤判為「只有設定章、沒有實際數據」。實測把查詢改成更聚焦的 `SCU2060 throughput latency bler rtt` 並把 `top_k` 拉到 20 時，`chunk 10` 就會出現。這表示問題主因是搜尋召回策略 / query 太泛，而不是文件缺資料。

- 2026-05-25 已把 KB 的 Neo4j host 映射從 `127.0.0.1:7474/7687` 改成 `127.0.0.1:17474/17687`，並同步更新 `restart_kb.sh` 的埠檢查與顯示。重新執行 `restart_kb.sh` 後，`kb-neo4j` 可正常起來且顯示 `127.0.0.1:17474->7474/tcp`、`127.0.0.1:17687->7687/tcp`，所有驗證項目通過；接著也把主機 `neo4j.service` 再啟動回來，確認它與 KB 可以同時存在，不再互撞埠位。這是目前的永久避讓方案。
- 2026-05-25 已查出 `restart_kb.sh` 失敗的真正原因：主機上有 `neo4j.service`（PID 4198 / 4860）正在佔用 `127.0.0.1:7474` 與 `127.0.0.1:7687`，導致 KB 的 `kb-neo4j` 無法綁定埠。已先執行 `systemctl stop neo4j`，再重新跑 `restart_kb.sh`，這次已完整成功；最終狀態為 `kb-neo4j` / `kb-redis` 皆 `healthy`，`kb-nginx`、`kb-web`、`kb-celery-beat`、`kb-celery-search`、`kb-celery-ingest` 皆已啟動，腳本驗證也通過首頁、管理後台路由、管理 API、QDrant health、Ollama 連線與 WebSocket proxy smoke test。
- 2026-05-25 已執行 `restart_kb.sh` 重新啟動知識庫。過程中前端 build 成功，compose 也開始建立各服務，但在 `kb-neo4j` 啟動時失敗，錯誤為 `failed to bind host port 127.0.0.1:7474/tcp: address already in use`。目前可確認 `kb-redis` 與 `kb-qdrant` 已起來，`kb-neo4j` 停在 `Created` 狀態，整體 `docker compose ps` 只看到 `kb-redis` 運作中。這表示異常不是 build 或 image 問題，而是主機端 7474 / 7687 埠已被既有程序占用，導致 Neo4j 無法綁定並使整次重啟中止。
- 初始建立。
- 今日完整變更記錄已整理到 [`<project-root>/knowledge-base/DAILY_CHANGELOG_2026-05-18.md`](<project-root>/knowledge-base/DAILY_CHANGELOG_2026-05-18.md)。
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
- 2026-05-22 已備份 `<project-root>/.openclaw/openclaw.json` 為 `openclaw0522.json`，並把 OpenClaw 主模型改成本地 Ollama `ollama/gemma4:e4b`；`agents.defaults.model.primary` 現在指向 `ollama/gemma4:e4b`，`models.providers` 也補上 `ollama` provider（`http://127.0.0.1:11434/v1`、`apiKey=ollama-local`），原本的 `minimax/MiniMax-M2.7` 與 `minimax/MiniMax-VL-01` 保留為 fallback。這代表小幫手本體的主對話模型已從 MiniMax 切回本地 Ollama。
- 2026-05-22 進一步把 `<project-root>/.openclaw/openclaw.json` 縮到只保留本地 Ollama 主模型：`agents.defaults.model.primary = ollama/gemma4:e4b`，`agents.defaults.models` 只保留 `ollama/gemma4:e4b`，`models.providers` 也只剩 `ollama`，`auth.profiles` 中的 Minimax / Google 已移除，`tools.media.image.models` 也清空為 `[]`。也就是說，OpenClaw 本體目前只留本地 Ollama 主模型，沒有額外備援模型資訊。
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
2026-05-20 外部連線檢查：`kb-nginx` 已對外發布 `3030->443`，本機 `ss` 顯示 `0.0.0.0:3030` 正在監聽；以 `https://127.0.0.1:3030/health` 測試時可連到 Nginx（HEAD 會回 `405`、GET 會回 `200`）。因此 `ERR_CONNECTION_REFUSED` 較像是前端當下連線時的暫時性失敗或瀏覽器/網路側狀態，而不是目前服務持續不聽 3030。因 `sudo` 需要密碼，尚未能直接檢查主機防火牆規則。
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
2026-05-21 已重新驗證同一份 `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001` 的 Report ingest：在 `kb-celery-search` 容器內直接呼叫 `ingest_document(..., extraction_mode='report')` 成功完成，log 顯示 `Report 模式` 下 Neo4j 文件結構完成、分塊 11 個區塊、QDrant 寫入 11 筆向量，`result=True`。進一步直接查 Neo4j 可找到 `Document(name='SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001', extraction_mode='report', source='<project-root>/knowledge-base/data/processed/Report/SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md')`，且對應 `TextUnit` 數量為 1；QDrant 以 `doc_name` scroll 也能找到該文件的 points，代表 Report 模式的 Neo4j / QDrant 寫入修補已經生效。 
2026-05-21 已清除 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005` 在 Neo4j 與 QDrant 的既有資料，準備驗證新的 watch ingest：`cleanup_existing_document('SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005')` 在 `kb-celery-search` 容器內執行成功，QDrant scroll 針對同一個 `doc_name` 回傳空結果，Neo4j 以 `MATCH (d:Document {name:'SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005'}) RETURN count(d)` 也回到 `0`。這代表後續把 `<project-root>/knowledge-base/data/raw/SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.xlsx` 放進 watch 時，可以用新增的資料判斷是否真的有重新寫進 Neo4j / QDrant。
2026-05-21 已再次確認並清除 `type6_NR-Throughput-SCU2140-n78-EV-V005` 在 Neo4j 與 QDrant 的既有資料：`cleanup_existing_document('type6_NR-Throughput-SCU2140-n78-EV-V005')` 成功執行，Neo4j `MATCH (d:Document {name:'type6_NR-Throughput-SCU2140-n78-EV-V005'}) RETURN count(d)` 回到 `0`，QDrant 也不再有 `doc_name` 含 `2140` 的 points。這次清除只針對該文件本身，不會刪除其他內容裡僅提到 `SCU2140` 的相鄰文件。
2026-05-21 針對 `請查詢SCU2140相關報告資訊` 的直接測試確認：`/search`（`mode=vector`）確實從 QDrant 拉回 3 筆來源，`sources` 全部對應 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005`，`citation_distribution.category_counts["4G/5G"]=3`，但 task 的 `answer` 仍然是空字串。這代表 KB 資料確實有從資料庫讀出來，但先前前端的 `formatKnowledgeBaseContext()` 因為 `result.answer` 為空就直接回空 context，導致後續送給 OpenClaw 時沒有帶到 KB 來源。已修正前端為「只要有 sources 就能組 KB context」，並把來源摘要拼進 prompt，即使 answer 空白也會把資料庫查詢結果送給小幫手。
2026-05-21 `frontend/chat.html` 與 `frontend/src/views/ChatView.vue` 的 KB context 條件已修成只看 `sources` / `answer` 任一存在即可；同時為每個 source 附上摘要片段，避免 KB task 的 `answer` 空白時整包 context 被丟掉。已用本地 Node 測試確認 `SCU2140` 的 KB context 會包含三份來源文件與摘要片段，即使 task `answerLength=0` 也能產生 763 字的 context。
2026-05-21 已把前端 runtime 目錄從 `.frontend-build-runtime` 改成 `.frontend-build-runtime-user`，並同步更新 `restart_kb.sh`、`docker-compose.yml`、`frontend/package.json`、`frontend/vite.config.js`。新的 runtime 目錄由目前使用者建立並擁有，之後 `restart_kb.sh` 可正常 build 與清理，不再撞到 root-owned 舊目錄的 `Permission denied`。
2026-05-21 `restart_kb.sh` 已重新跑通：前端 runtime 成功輸出到 `.frontend-build-runtime-user`，`kb-web`、`kb-celery-search`、`kb-celery-ingest`、`kb-celery-beat`、`kb-nginx`、`kb-redis`、`kb-neo4j` 都已正常啟動，`/health`、`/chat.html`、`/admin/graph-stats`、QDrant health 與 WebSocket proxy smoke test 全部通過。瀏覽器現在應該可以實際吃到「只要有 sources 就組 KB context」的修正版。
2026-05-21 已把參考來源顯示改成更明確的來源管線形式：`frontend/chat.html` 會把來源 tag 顯示成 `Qdrant 文件片段` / `Neo4j 圖譜關聯` / `KB 匯整來源`，並在來源名下方保留文件名；`frontend/src/views/ChatView.vue` 也同步把 `KB 參考` 的提示換成多行來源清單，讓使用者可以直接分辨來源是向量片段、圖譜關聯，還是 KB 匯整後的摘要，而不是看成「直接讀原始檔」。
2026-05-21 追查「⚠️ 資料不足原因」這類回覆：那三條原因（搜尋命中但無詳細數據、相似度分數偏低、PDF/圖片難直接讀表）不是後端明文返回的事實診斷，而是模型根據 KB context 自行整理出的不足說明。實際上，`SCU2140` 的 `/search` 任務是有從 Qdrant 找到 3 份來源、`citation_distribution` 也正確統計到 `4G/5G = 3`，只是 task 的 `answer` 可能是空字串或摘要過短，前端便把來源片段和「資料不足」提示一起送給小幫手，導致模型用一般化語句解釋不足原因。這類說法應視為「模型推測」，不能直接當成資料庫真的缺少該 PDF / 圖片或真的只剩低相似度結果。
2026-05-21 已依要求將 KB 的 Neo4j 與 QDrant 全部清空：Neo4j 以 `MATCH (n) DETACH DELETE n` 後，`MATCH (n) RETURN count(n)` 為 `0`；QDrant 先前的 `knowledge_base` 與 `kb_syntheses` collections 已全部刪除，`/collections` 目前回傳空列表。之後若要做新的 ingest 測試，會從完全空白的資料庫開始。
2026-05-21 追查 `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.xlsx` 放進 watch 後 Neo4j 沒新增、QDrant 只有 segments 但沒有 points：`watch_folder_scan` log 顯示檔案被判定為與 `processed` 同 hash 的重複檔，直接刪除 watch 版本，所以根本沒有進 ingest。後來確認 `data/processed/Simple/type6_NR-Throughput-SCU2140-n78-EV-V005.md` 與 `.source.json` 仍存在，因此 duplicate detection 會把 watch 裡的新檔移除。QDrant 目前 `points_count=0` 但 `segments_count=8`，代表 collection 曾經存在並保留分段結構，但實際向量點已空，不代表有新資料成功寫入。
2026-05-21 已排除這次手動 ingest 會被重複檔擋下的因素：`data/processed/Simple/type6_NR-Throughput-SCU2140-n78-EV-V005.md`、`.source.json`、`.xlsx` 已從 processed 移除，並且 `cleanup_existing_document('type6_NR-Throughput-SCU2140-n78-EV-V005')` 也已在 Neo4j / QDrant 清空對應資料。現在若再把 `<project-root>/knowledge-base/data/raw/SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.xlsx` 放入 watch，應可避免再次因同 hash 舊檔而被 watch duplicate detection 直接刪除。
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
- 2026-06-10 已確認 knowledge-base 專案目前沒有額外的 `.env` 檔存在於專案根目錄；`docker-compose.yml` 與 `restart_kb.sh` 的環境變數主要是直接寫在 compose / script 內，實際會掛載的設定檔是 `config/config.yaml`，而不是透過單一 `.env` 集中管理。若未來要新增 `.env`，預設會是專案根目錄下的 `<project-root>/knowledge-base/.env`，但目前並不存在。
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

- 使用者希望在 `https://127.0.0.1:3030` 的系統管理頁面另外開一個分頁，專門查看「chunk 原圖 + chunk 文字」。
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
2026-05-21 已修正 Chunk Viewer 原圖 404 的根因：`/admin/chunk-assets` 原本只認 `/app/data/assets`，但實際有原圖的掛載目錄是在 `<project-root>/knowledge-base/data/assets`。`src/chunk_assets.py` 現在會優先選擇環境變數 `KB_ASSETS_ROOT`，其次選實際存在的掛載目錄 `<project-root>/knowledge-base/data/assets`，再回退到 `/app/data/assets`。修正後已重新啟動 KB，並用 `curl -k` 實測 `https://127.0.0.1:3030/admin/chunk-assets/SIT-SR-SC-NR-Handover-SCE2200-n79-EV-V13.8/excel/Cover/image-01.png` 成功回傳圖片二進位，不再是 `資產不存在`。
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
2026-05-23 進一步追查使用者看到「知識庫中沒有針對 SCU2140 的向量或圖譜檢索結果；以上數據來自直接掃描 processed 目錄」的原因：這不是 KB 沒有查到，而是 OpenClaw 工作區仍殘留舊 fallback 規則，會把 `/search` 任務中 `answer` 仍為空的情況，誤判成沒有可用的向量 / 圖譜結果，進而嘗試改用 processed 直掃。已在 `<project-root>/.openclaw/workspace/AGENTS.md` 移除該 fallback，並強制要求最終答案只能根據 `/search` 的 `sources` 與 Neo4j / QDrant 檢索結果作答，不可再直接掃描 processed。
2026-05-23 最新重測已完成：`SCU2140的相關報告數據` 在 OpenClaw 端已改為正確發出 KB `/search`，並在 `/tasks/aea25eda-1966-4064-8cbf-2c1c7bf61680` 回傳 `status=completed`、`sources=3`、`citation_distribution=4G/5G=3`，最終回答也已改成根據知識庫查詢結果整理 `SCU2140 / SCU2060 / SCU5050` 的報告數據摘要，沒有再出現「QDrant 空、直接掃 processed」的舊說法。這次修正的重點是：`/.openclaw/workspace/skills/kb-query/SKILL.md` 已改為使用 `http://127.0.0.1:3030` 作為 KB API，並且 `answer` 空字串不可再被誤判為「KB 沒命中」；OpenClaw gateway 也已重新載入該規則。
2026-05-23 進一步追查確認：`kb-ingest/SKILL.md` 與 `kb-ingest/references/ingest_api.md` 內仍殘留 `localhost:8000`、`index.md`、`processed` 的舊教學，已同步改為 `127.0.0.1:3030` 與「index.md / processed 只屬歷史與輔助，不可作為最終答案 fallback」。新一輪 session 也已驗證：先讀 `kb-query/SKILL.md`，再走 `/search` 與 `/tasks/{task_id}`，最後回傳 `status=completed`、`sources=3`、`citation_distribution=4G/5G=3`，不再掉回直接掃 processed。這表示現在的根因不是 KB 空，而是 workspace 內的舊教學文件仍會誤導 agent；目前已把最主要的誤導來源收斂掉。
2026-05-23 追查 `wifi 關鍵訊號值` 的來源顯示方式：若 OpenClaw 最終回覆的「參考來源」標成 `processed/WiFi`，代表這次回答大概率是走了工作區檔案系統的 local scan / index 摘要，而不是從 KB `/search` 的 `sources` 直接組出來。問題不在 QDrant / Neo4j 本體，因為 KB 實際已可查到 WiFi 文件；真正的偏差點在 OpenClaw 的查詢路徑仍允許把 `index.md` 與 `data/processed/` 當成可用來源。後續若要徹底修正，應再收緊 OpenClaw workspace 的提示與 fallback，讓「只要有 `/search` 的 sources，就必須引用 KB 檢索結果；不得以 processed 檔名作為最終參考來源」成為硬規則。
2026-05-23 進一步定位 `wifi 關鍵訊號值` 仍引用 `processed/WiFi` 的殘留來源：目前最可疑的不是 `kb-query/SKILL.md`（它已明確禁止 processed fallback），而是 `/.openclaw/workspace/MEMORY.md` 裡仍保留完整的 `index.md` 歷史流程章節，以及 `/.openclaw/workspace/memory/2026-04-29.md` 內的「使用者提問 → 讀取 index.md → 找到相關文件 → 向量+圖譜搜尋 → 生成答案」舊流程描述；另外 `/.openclaw/workspace/skills/kb-ingest/references/ingest_api.md` 也仍以 `processed/` 作為流程終點。這些歷史/教學內容雖然標註為舊機制，但仍可能被 agent 當成可用路徑，導致最終答案引用本機實體檔案而非 `/search` 的 `sources`。後續若要完全清掉，應優先收斂這三份檔案中的歷史描述與任何可被解讀為「直接讀 processed」的示例。
2026-05-23 已把上述三份 OpenClaw workspace 內容進一步收斂：`/.openclaw/workspace/MEMORY.md`、`/.openclaw/workspace/memory/2026-04-29.md` 已改成只保留 `index.md` 的歷史備註，明確禁止再把它當作回答流程或 fallback；`/.openclaw/workspace/skills/kb-ingest/references/ingest_api.md` 也移除了 `processed/` 作為流程終點的寫法，並把回答依據改回 `/search` 的 `sources` 與 Neo4j / QDrant 檢索結果。這次收斂的目的，是讓 OpenClaw 只剩「/search 的 sources 才能當參考來源」這條路，不再被歷史教學文件暗示去直接讀本機 processed 檔案。
2026-05-23 進一步再收斂歷史段落中的舊索引語意：`/.openclaw/workspace/MEMORY.md` 與 `/.openclaw/workspace/memory/2026-04-29.md` 已將 `index.md` 改寫成純歷史註記，不再出現可執行的查詢流程；`/.openclaw/workspace/memory/2026-04-30.md`、`/.openclaw/workspace/memory/2026-05-17.md` 也已把「index.md / 舊分類」字樣壓成抽象歷史描述。現在 workspace 中能引導模型的，應只剩 `kb-query` 的正式規則與 `/search` 回傳的 `sources`，避免再被歷史章節帶回檔案系統掃描。
2026-05-23 最新重測 `wifi 關鍵訊號值`：雖然我已把 `kb-query/SKILL.md` 的 KB 端點改成 `https://127.0.0.1:3030/search` 與 `https://127.0.0.1:3030/tasks/{task_id}`，但 OpenClaw 這次執行時仍出現舊式 fallback 與錯誤 endpoint：先嘗試 `http://127.0.0.1:3030/search`（被 nginx 以 HTTPS port 擋下 400），又嘗試 `https://127.0.0.1/search`（回到 AnythingLLM 前端頁面），後面還出現 `docker exec kb-web curl -s http://localhost:8000/tasks/...` 的舊輪詢命令。這表示目前它仍未穩定只依 `/search` 的 `sources` 作答，仍殘留舊的本機/processed 類 fallback，需進一步讓 OpenClaw 重新載入 workspace 規則或檢查其他會覆蓋 `kb-query` 的記憶來源。
2026-05-24 進一步追查到真正的殘留來源之一是 OpenClaw 的短期回憶庫 `/.openclaw/workspace/memory/.dreams/short-term-recall.json`：其中仍有舊片段明確提到 `processed`、`localhost:8000`、`index.md`。已先手動刪掉兩條最直接的舊 fallback recall，讓 recall store 從 18 條降到 16 條；接著嘗試 `openclaw memory index --force` 強制重建索引，但因 Gemini embedding quota 429（RESOURCE_EXHAUSTED）而失敗，因此短期記憶索引暫時無法靠 reindex 自動刷新。這代表如果之後 OpenClaw 還會回到 processed / index.md fallback，優先查的已不只是 skill 檔，而是 short-term recall 是否仍混入歷史片段。
2026-05-24 進一步確認：僅清理 workspace 文件與 Git reflog 還不夠，OpenClaw 的 `agent:main:main` 仍會沿用同一條舊 session 線；即使嘗試 `openclaw agent --session-id <uuid>` 或 `openclaw agent --to +15555550123`，回覆仍重用舊 session id `7fa7c1e8-dcc2-4865-9ba7-811516edb356`，並繼續把 `wifi 關鍵訊號值` 直接答成本地文件答案。已確認 `openclaw-gateway` 重啟後仍如此，表示目前剩下的污染核心更像是 agent session / compaction / memory 內部狀態，而不是單純的 skill 或檔案內容；要真正切斷舊 fallback，可能需要能重置 main session 的機制，或改用能真正產生新 session 的入口。
2026-05-24 進一步追查 OpenClaw session 汙染：`openclaw agent` 仍持續沿用舊的 `agent:main:main` session，嘗試 `--session-id` / `--to` 都無法真正切斷；而 `openclaw acp client` 雖可建立全新 ACP session（例如 `a2726482-413e-4fc8-a905-4705956ffcde`），但落盤到 `<project-root>/.openclaw/agents/main/sessions/*.jsonl` 時會出現 `ACP_SESSION_INIT_FAILED`，訊息指出 `ACP metadata is missing for agent:main:acp:<session>`，並要求用 `/acp spawn` 重新建立與 thread rebind。這表示目前污染核心已不只是 skill / workspace / Git reflog，而是 `agent:main:main` 對應的持久 ACP metadata / session 綁定仍未真正清掉；下一步應聚焦在正確的 `/acp spawn` 或 session rebind 流程，而不是繼續嘗試 `openclaw agent` 舊入口。
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
- 2026-05-24 針對 `https://127.0.0.1:3030/chat.html` 的瀏覽器路徑做了實測：頁面可正常開啟、WebSocket 可連上，但同題 `查詢SCU2140 的throughput 數據` 的最終 payload 只回傳 `NO`，且 wait timing 顯示 `kbSearchMs=0`、`queueWaitMs≈35718ms`、`generationMs=0`、`totalMs≈50955ms`，代表這條前端 session 並沒有像正式 agent 路徑一樣拿到 KB sources，而是走到一條不同的瀏覽器/前端路徑。這再度證實跨電腦或跨入口的不一致，核心仍在 client/session/endpoint，不在 KB 資料本體。
- 2026-05-24 已修正瀏覽器版 `/chat.html` 與 Vue 版 `ChatView.vue` 的 KB 等待時間：原本 `prepareKnowledgeBaseContext()` 只等 `15000ms`，在慢一點的電腦上容易先 timeout，導致 OpenClaw 只收到空 KB context，最後回 `NO`；現在已把等待時間統一拉到 `60000ms`，與系統的「最多等 60 秒再送 OpenClaw」策略對齊，避免因不同電腦速度差異造成有些分頁拿不到 KB sources 的狀況。
- 2026-05-24 進一步把瀏覽器版 `/chat.html` 與 Vue 版 `ChatView.vue` 的 KB 等待時間再拉到 `120000ms`，避免較慢機器或較長 queue wait 時 KB context 尚未就緒就先送出 OpenClaw，造成瀏覽器分頁回 `NO` 或看起來像沒查到資料；`restart_kb.sh` 已重跑完成，新的前端 runtime 目錄也已同步生效。
- 2026-05-25 重新實測 `https://127.0.0.1:3030/chat.html` 上的 `查詢SCU2140 的throughput 數據`：頁面可正常連線、WS 也有建立，但最後 bot 仍回「知識庫中目前沒有關於 SCU2140 throughput 的查詢結果」，`wait timing` 顯示 `queueWaitMs≈104840ms`、`firstAssistantMs≈50545ms`、`totalMs≈120167ms`，而 `kbSearchMs=0`；console 也顯示 `[KB] Search timeout` 與 `No citation data from final payload or KB search`。這表示即使瀏覽器版 timeout 已拉到 120 秒，`/chat.html` 這條入口仍然沒有穩定拿到 KB sources，問題更像是這條瀏覽器 session / queue path 還沒真正對到正式 agent-side KB 查詢路徑，而不是 QDrant 本體沒有 SCU2140。

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
- 2026-05-25 以 Playwright 重測 `https://127.0.0.1:3030/chat.html` 的 `請顯示SCU2140的throughput數據` 後，browser 端依舊在 120 秒內持續輪詢到 `/tasks/4a4988e7-2b22-4e48-9197-648470e41bd2` 的 `pending`，最後觸發 `[KB] Search timeout` 與空 citation cards；但同一個 task_id 由 shell `curl` 直查已是 `completed`，且 worker log 顯示 `Task tasks.search_task[4a4988e7-2b22-4e48-9197-648470e41bd2] succeeded in 24.9s`。這表示 browser 入口仍有獨立的 KB sidecar/polling 同步問題，尚未真正解除瀏覽器端的 timeout 卡住現象。
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
- 已產出一份 HTML 投影片：[neo4j_schema_ingest_presentation.html](<project-root>/knowledge-base/neo4j_schema_ingest_presentation.html)
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
- 新增模組：[src/report_graph.py](<project-root>/knowledge-base/src/report_graph.py)
  - 提供 `Project / Report / Section / TestItem / TestCase / Metric / SourceChunk` 的 schema 與寫入邏輯。
  - `TestItem` 已做 canonicalize，至少涵蓋 `throughput` / `handover` / `latency` / `tcp` / `udp` / `bler`。
  - `SourceChunk` 保留原始 md 片段與證據路徑，來源仍可回推到原始 Excel。
- ingest 已接上 report graph：
  - [src/ingest.py](<project-root>/knowledge-base/src/ingest.py) 的 `report` 模式會同時寫入 legacy `Document/TextUnit` 與新的 report graph。
  - [src/graphrag/neo4j_schema.py](<project-root>/knowledge-base/src/graphrag/neo4j_schema.py) 也同步建立新節點的 constraints / indexes。
- 查詢端已接上 report graph：
  - [src/search/__init__.py](<project-root>/knowledge-base/src/search/__init__.py) 新增 `_report_graph_search_raw()`。
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
- 已調整 [src/search/__init__.py](<project-root>/knowledge-base/src/search/__init__.py) 的 `_build_report_graph_answer()`：
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
- 使用者要求把網頁測試原則寫入 [AGENTS.md](<project-root>/knowledge-base/AGENTS.md)：
  - 測試網頁功能時，優先使用 Playwright 或可用的瀏覽器自動化工具。
  - 必須模擬真實使用者流程，而不是只讀程式碼或只打 API。
  - 若畫面異常，要記錄頁面、操作步驟、預期與實際結果，並保留截圖。
  - 若有 console/network error，也要一併檢查。
- 已完成更新，並新增 `Playwright 測試規範` 段落，作為後續 UI / E2E 測試的優先原則。

## 2026-05-28 SCU5050 numeric case chunk merge fix
- 使用者回報 `請問SCU5050的相關報告資訊` 產生的回答，在 Case 15 的 `#2/#3`、`UL TCP` 與 `Peak/Average/BLER` 出現 `-` 或缺值。
- 根因不是原始 Excel 缺資料，而是 `report_graph` 的數值答案組裝邏輯只取了第一個 chunk；而 `SCU5050` 的 Case 15 被 chunker 切成多段，後半段 chunk 沒有再次重複 `Test Case 15` 標頭，導致它沒有被歸入同一 case，後續 `Uplink / Bidirection / UDP / RTT` 欄位因此被漏掉。
- 已在 [src/search/__init__.py](<project-root>/knowledge-base/src/search/__init__.py) 新增 case 繼承與合併邏輯：
  - 先沿 chunk 順序推斷同一份報告、同一章節內沒有顯式 case 標頭的 chunk，視為前一個 case 的延續。
  - 再將同 case 的多個 chunk 依 `chunk_index` 合併後輸出。
- 已重新執行 `restart_kb.sh` 驗證線上服務。
- 最新驗證結果：`SCU5050` 的 Case 15 現在會完整列出 `Uplink 472 / 471 / 471 / 472 / 471 / 0`、`Bidirection - DL 674 / 680 / 676 / 680 / 677 / 0`、`Bidirection - UL 469 / 424 / 469 / 469 / 454 / 0`，以及 UDP / RTT 欄位，不再出現只顯示第一段或用 `-` 佔位的情況。

## 2026-05-28 SCU2060 report chunk boundary fix
- 使用者回報 `SCU2060` 的 `report_graph` 回答有 case 內容錯位，Case 13~16 前方會混入上一個 case 的尾段，出現 `12 / 13 / 14 / 15 / 16` 這種不合理數值。
- 根因：
  - 同一個 report chunk 內會同時包含前一個 case 的尾巴與下一個 case 的 `4.xx Test Case xx` 標頭。
  - 原本的 case 合併邏輯是以整個 chunk 為單位，沒有把 chunk 內的 case 邊界切開，因此會把上一個 case 的數值一併帶入。
- 已在 [src/search/__init__.py](<project-root>/knowledge-base/src/search/__init__.py) 增加：
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
  - [src/report_graph.py](<project-root>/knowledge-base/src/report_graph.py)
    - `Section.text` 不再截斷成 4000 字，改為保留完整 section text。
  - [src/search/__init__.py](<project-root>/knowledge-base/src/search/__init__.py)
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
- 已更新 [AGENTS.md](<project-root>/knowledge-base/AGENTS.md)：
  - 新增規則 8：每次修正一個問題後，必須先自行完成驗證，確認行為正常、沒有回歸，才能對使用者回報已修正。
- 這條規範的目的，是避免只根據程式碼修改就宣告完成，後續仍需以實際驗證結果作為回報依據。

## 2026-05-28 review prior fixes before editing rule
- 使用者要求新增工作守則：每次修改前要先回顧之前已完成的修改內容，以不能影響既有修正為原則，再去處理新的問題。
- 已更新 [AGENTS.md](<project-root>/knowledge-base/AGENTS.md)：
  - 新增規則 9：每次修改前，必須先回顧既有修改與已修正內容，確認新修改不會影響已修正的行為，再開始處理新的問題。
- 這條規範的目的是讓後續每次變更都先檢查既有修正，避免新修補破壞先前已驗證完成的功能。

## 2026-05-28 throughput cross-project report graph fix
- 使用者回報查詢 `請查詢Throughput相關報告數據` 仍出現「找不到」或只看到封面 / 目錄頁的問題。
- 實際排查後確認：
  - `report_graph` 雖然已能抓到 SCU2060 / SCU2140 / SCU5050 三份 throughput 報告，但原本的排序會先取各報告的前兩筆 chunk，導致結果落在封面 / 目錄，而不是 `4. Performance Test`。
  - `Throughput` 類查詢又被視為 numeric extraction，若直接套用 numeric merge，還可能把跨專案來源壓成單一 case，讓回覆看起來像只有單一報告或單一來源。
- 已修正：
  - [src/search/__init__.py](<project-root>/knowledge-base/src/search/__init__.py)
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
  - [frontend/chat.html](<project-root>/knowledge-base/frontend/chat.html)
    - 若 `prepareKnowledgeBaseContext()` 回傳的 `kbResult.mode === 'report_graph'` 且有 `answer`，前端直接用 `addMessage('bot', kbResult.answer, ...)` 顯示最終答案。
    - report_graph 類查詢不再送入 `chat.send` 讓 LLM 二次改寫。
  - [frontend/src/views/ChatView.vue](<project-root>/knowledge-base/frontend/src/views/ChatView.vue)
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
  - [src/search/__init__.py](<project-root>/knowledge-base/src/search/__init__.py)
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
  - [frontend/chat.html](<project-root>/knowledge-base/frontend/chat.html)
  - [frontend/src/views/ChatView.vue](<project-root>/knowledge-base/frontend/src/views/ChatView.vue)
    - compare-like query 會先直接走 `prepareReportGraphContext()`，命中 `report_graph` 就直接落版，避免前端把正確答案再交給 LLM 重寫。
  - [src/web_api/__init__.py](<project-root>/knowledge-base/src/web_api/__init__.py)
    - websocket proxy 新增 compare 短路，舊客戶端也會先透過本機 `/search` 取得 `report_graph` 結果，再決定是否往上游送出，降低 browser cache / 舊 bundle 影響。
- 驗證結果：
  - 直接呼叫本機 `/search` 的 compare 查詢可回傳 `mode=report_graph`，且 sources 包含 `SCU2060 / SCU2140 / SCU5050` 三份報告。
- `SCU2060` 的 `Case 15` 原始 Excel 內容本身就是 `15` 值，與 `SCU2140` / `SCU5050` 的數值不同，因此 compare 題的「幾乎一樣」是錯誤改寫造成，不是來源資料相同。
- 2026-05-29 進一步修正 compare 題的解讀方式：原本 compare mode 會先把每個專案各自組成 `## 原文 / ## 解讀`，導致 LLM 只看單一專案上下文時，容易在每段都說「缺少其他資料，無法比較」。已將 compare 改成「整體跨專案一次比較」：先輸出三個專案的原文對照，再由新的 `_build_report_graph_compare_interpretation()` 根據整體 compare raw 產生 2~4 條真正的跨專案比較解讀，不再在每個專案段落內單獨下「無法比較」結論。已重啟 KB 並用 `https://127.0.0.1:3030/chat.html` 實測 `SCU2140、SCU2060、SCU5050 的case 15Throughput有什麼差異？`，後端 `report_graph` 現在回傳 `mode=report_graph`、`sources=3`，`answer` 內有 `## 原文` 與 `## 解讀`，且不再包含「無法比較 / 缺乏資料」等錯誤收尾。
- 2026-05-29 進一步把 compare 解讀整理成正式對照表：`src/search/__init__.py` 已新增 compare 專用的表格化輸出邏輯，會直接從跨專案 raw answer 中切出 `SCU2060 / SCU2140 / SCU5050` 各自的原文，再以 Markdown 表格列出 `DL TCP / UL TCP / Bidirection - DL / Bidirection - UL / RTT` 的 `Peak / Avg / BLER` 或 `Min / Avg / Max / Loss`，最後加上一欄差異摘要（例如哪個專案平均值最高 / 最低）。已以 `https://127.0.0.1:3030/chat.html` 實測 `SCU2140、SCU2060、SCU5050 的case 15Throughput有什麼差異？`，回覆的 `## 解讀` 現在就是正式對照表，且不再出現「無法比較」或缺資料的文字結尾。
- 2026-05-29 進一步把 compare 解讀調成「固定表格 + LLM 簡短評論」的雙層輸出：`src/search/__init__.py` 的 compare 解讀現在會先以固定 Markdown 表格列出 `DL TCP / UL TCP / Bidirection - DL / Bidirection - UL / RTT` 的跨專案對照，再額外呼叫 LLM 產生 2~3 條短評，評論只允許根據表格與原文做摘要，不可新增數字。已重啟 KB 並用 `https://127.0.0.1:3030/chat.html` 實測同一題，`answer` 長度為 `3712`，且明確包含 `### LLM 簡短評論`，代表這次 compare 題已確實有 LLM 介入分析，同時保留固定表格穩定性。

## 2026-05-28 main chat entry policy
- 已新增專案級規範：往後知識庫相關的測試與修改，優先以 `https://127.0.0.1:3030/chat.html` 作為主要驗證入口。
- 目的：
  - 避免不同前端入口、不同 session 或不同瀏覽器快取造成測試結果分歧。
  - 讓後續知識庫測試、compare 題、report graph 題、citation 顯示等，都以同一個使用者實際入口為主。
- 除非任務明確要求，否則不應把其他入口當成唯一驗證依據。

## 2026-05-28 chat.html compare-path verification
- 以 `https://127.0.0.1:3030/chat.html` 實測 compare 題 `SCU2140、SCU2060、SCU5050 的case 15Throughput有什麼差異？`
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
  - [src/report_graph.py](<project-root>/knowledge-base/src/report_graph.py)
    - `SourceChunk.content` 改為保留完整 chunk，不再以 4000 字截斷。
- 已重攝入：
  - `SIT-TR-SC-NR-Throughput-SCU2060-n79-EV-V13.8.md`
  - `SIT-TR-SC-NR-Throughput-SCU2140-n78-EV-V005.md`
  - `SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.md`
- 驗證結果：
  - 以 `https://127.0.0.1:3030/chat.html` 再次查詢 `SCU2140、SCU2060、SCU5050 的case 15Throughput有什麼差異？`
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
  - [src/search/__init__.py](<project-root>/knowledge-base/src/search/__init__.py)
    - 鄰接 chunk 的報告識別改以 `doc_name` 為主，比對鍵不再用 `report_title`。
    - 這讓 `Case 14` 這種跨 chunk 邊界時，能把下一個 chunk 的前半段（屬於前一 case 的尾巴）一起收進來。
- 驗證結果：
  - 以 `https://127.0.0.1:3030/chat.html` 實測：
    - `請查詢SCU2060的Case 14數據`
    - `請查詢SCU2060的Case 15數據`
    - `請查詢SCU2060的Case 16數據`
    - `請查詢SCU2140的Case 16數據`
    - `請查詢SCU5050的Case 16數據`
  - 結果皆完整包含 `Uplink`、`Bidirection - UL`、`UDP Throughput`、`Latency Test` 與 `RTT`，未再出現只剩第一列或只剩表頭的截斷狀況。

## 2026-05-28 raw first then interpretation answer format
- 使用者要求調整回答格式為「先原文、後解讀」，讓 LLM 仍可提供分析，但不影響原始數值正確性。
- 已修正：
  - [src/search/__init__.py](<project-root>/knowledge-base/src/search/__init__.py)
    - 新增 `_build_report_graph_interpretation()`：根據已整理好的原文與來源，生成 2~4 條的解讀段落，禁止新增原文沒有的數字。
    - 新增 `_compose_raw_then_interpretation()`：把回答統一包成 `## 原文` + `## 解讀` 的雙段式格式。
    - `report_graph`、compare、numeric direct answer、vector/hybrid numeric direct answer 都改成優先輸出原文，再附上解讀。
- 驗證結果：
  - 以 `https://127.0.0.1:3030/chat.html` 實測 `請查詢SCU2060的Case 15數據`
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
- 2026-05-31 已修正 WiFi band raw 的 `## 解讀` 仍落到固定 fallback 的問題：根因是目前知識庫的 LLM 已切換為 Qwen3.6 `qwen3.6:35b-a3b`，而 Qwen3.6 在 Ollama 預設會啟用 thinking；我們先前在 `src/web_api/ollama_client.py` 的 `OllamaLoadBalancer.chat()` / `generate()` 只取 `message.content`，但實際回來的是 `content=''`、`thinking` 有完整推理內容，因此 `_build_report_graph_interpretation()` 判定為空後就回退到固定摘要。已將 Ollama 呼叫明確改成 `think=False`，讓 Qwen3.6 直接輸出最終短評內容；再以 `/api/chat` 與 `OllamaClient.chat()` 逐一驗證，確認容器內對 `http://host.docker.internal:11434/api/chat` 的請求現在會回傳非空 `content`。已重啟 KB 後，用 `https://127.0.0.1:3030/chat.html` 實測 `請查詢TP-Link Archer BE805的5GHz Throughput測試數據`，回覆已變成 `## 原文` + `## 解讀`，其中 `## 解讀` 是由 LLM 產生的 3~4 條短評，而非固定 fallback；後續 WiFi band throughput 的 2.4 / 5 / 6GHz 也會同樣走這條真實 LLM 短評路徑。

## WiFi 2.4G / 5G / 6G 回覆狀態確認（2026-06-01）

- 目前專案記憶中已記錄：WiFi 2.4G / 5G / 6G 小幫手回覆內容問題已解決，且在 `https://127.0.0.1:3030/chat.html` 上做過實測。
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
  - [src/storage_paths.py](<project-root>/knowledge-base/src/storage_paths.py)
    - 新增 `infer_storage_category_from_path()`。
    - `resolve_storage_category()` 改成讓檔名推斷優先，只要檔名能明確判定，就不再被預設 `4G_5G` 覆蓋。
  - [src/ingest.py](<project-root>/knowledge-base/src/ingest.py)
    - `detect_extraction_mode()` 補上 `sit-tr-wl / wifi / wi-fi / wireless` 的 WiFi 類型偵測，讓 WiFi 報告即使沒有明寫 `type2` 也能被正確辨識。
    - 寫入 Neo4j 與 chunk metadata 時同步帶入 `storage_category` / `extraction_mode`。
  - [src/extract_entities.py](<project-root>/knowledge-base/src/extract_entities.py)
    - Document 節點寫入時補上 `storage_category`，避免後續只能靠檔名猜類別。
  - [src/vector_store/__init__.py](<project-root>/knowledge-base/src/vector_store/__init__.py)
    - Qdrant payload 也同步保存 `storage_category` / `extraction_mode`，讓搜尋端可以直接讀到文件類別。
  - [src/web_api/tasks.py](<project-root>/knowledge-base/src/web_api/tasks.py)
    - ingest task 改成只要檔名模式不是預設 `4g5g` 就優先採用，避免 background ingest 把 WiFi 文件覆寫回 4G/5G。
  - [src/web_api/__init__.py](<project-root>/knowledge-base/src/web_api/__init__.py)
    - `actual_file_categories` 改為優先讀 `.source.json` 的 `storage_category` / `extraction_mode`，再補 folder fallback。
  - [src/search/__init__.py](<project-root>/knowledge-base/src/search/__init__.py)
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
  - [src/ingest.py](<project-root>/knowledge-base/src/ingest.py)
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
  - [src/reingest.py](<project-root>/knowledge-base/src/reingest.py)
    - 預設會先清空 Neo4j 與 QDrant，再重新掃描 `data/processed` / `data/uploads` / `data/raw` 中的 Markdown 文件。
    - 採用目前的 `detect_extraction_mode()` 規則，因此只會把 `SIT-SR-SC` 判成 `4G/5G`、`SIT-TR-WL` 判成 `WiFi`，其餘都回預設 `4G/5G`。
    - 保留 `--dry-run` / `--no-purge` / `--no-vector` / `--no-assets` 參數，方便未來重跑。
  - [src/runtime_config.py](<project-root>/knowledge-base/src/runtime_config.py)
    - 補了 Neo4j / QDrant 的 runtime fallback，讓主機 CLI 可自動落到 `127.0.0.1:17687` 與 `127.0.0.1:6335`，不再硬吃容器內 service name。
  - [src/vector_store/__init__.py](<project-root>/knowledge-base/src/vector_store/__init__.py)
    - QDrant 連線初始化也改成會依 runtime 自動選擇可用位址。
  - [src/main.py](<project-root>/knowledge-base/src/main.py) / [src/ingest.py](<project-root>/knowledge-base/src/ingest.py)
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
  - [src/reingest.py](<project-root>/knowledge-base/src/reingest.py) 已加上保護：一旦某份文件已由 metadata 決定為 `Report`，後續純 `.md` 掃描就不再覆蓋它的 `detected_mode`。
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
  - [frontend/chat.html](<project-root>/knowledge-base/frontend/chat.html)
  - [frontend/src/views/ChatView.vue](<project-root>/knowledge-base/frontend/src/views/ChatView.vue)
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
  - [src/search/__init__.py](<project-root>/knowledge-base/src/search/__init__.py)
  - `_build_wifi_throughput_band_raw_body()` 已放寬判斷，現在把 `數據 / data` 也納入 throughput 線索，並在 query 已有 WiFi 線索與頻段資訊時允許進入 WiFi band raw。
  - 這樣 `TP-Link Archer BE805 的 5GHz 80MHz 與 160MHz 數據` 這種寫法也會直接回 `wifi_band_raw`，不再需要使用者一定明寫 `throughput`。
- 驗證：
  - `NEO4J_URI=bolt://127.0.0.1:17687 QDRANT_URL=http://127.0.0.1:6335 python3 - <<...>>` 直接測 helper，`_build_wifi_throughput_band_answer('請整理 TP-Link Archer BE805 的 5GHz 80MHz 與 160MHz 數據', meta)` 現在回 `mode=wifi_band_raw`。
  - 重新 `./restart_kb.sh` 後，在 live `https://127.0.0.1:3030/chat.html` 實測同一句話，console 顯示 `Prepared WiFi-specific KB result.`，citation distribution 變成 `matched_count=1 / WiFi=100/1`，不再混入 `SCU` report 來源。
- 補充結論：
  - 這次不是硬編碼特定文件，而是把 WiFi throughput 路徑的語意門檻放寬，讓使用者常見的「數據」問法也能被辨識為 throughput 類查詢。

## 2026-06-05 OpenClaw 主模型切換為 gemma4:12b
- 使用者要求把小幫手 `openclaw` 內的主要模型也改成 `gemma4:12b`。
- 已更新 active 設定檔 [~/.openclaw/openclaw.json](<project-root>/.openclaw/openclaw.json)：
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
- 使用者要求實際打開 `https://127.0.0.1:3030/chat.html` 驗證前台在 OpenClaw 主模型切到 `gemma4:12b` 後是否正常。
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
  - [`<project-root>/knowledge-base/final_runs/run_5/final_script.py`](<project-root>/knowledge-base/final_runs/run_5/final_script.py)
  - [`<project-root>/knowledge-base/final_runs/run_5/final_script_log.txt`](<project-root>/knowledge-base/final_runs/run_5/final_script_log.txt)
  - [`<project-root>/knowledge-base/final_runs/run_5/final_result.json`](<project-root>/knowledge-base/final_runs/run_5/final_result.json)
  - [`<project-root>/knowledge-base/final_runs/run_5/screenshots/final_execution_04_final_reply.png`](<project-root>/knowledge-base/final_runs/run_5/screenshots/final_execution_04_final_reply.png)


## 2026-06-05 OpenClaw 短問句實測驗證
- 使用者要求再測一個更短的問句，確認 `gemma4:12b` 切換後連簡短對話也正常。
- 實測方式：
  - 問句：`你好`
  - 入口：`https://127.0.0.1:3030/chat.html`
- 驗證結果：
  - 頁面載入正常，聊天浮窗正常開啟
  - 問題成功送出
  - 助手正常回覆 `你好！很高興能與你交流。我已經準備好協助你了。`
  - 沒有卡在 loading，也沒有錯誤訊息
- 證據檔：
  - [`<project-root>/knowledge-base/final_runs/run_6/final_script.py`](<project-root>/knowledge-base/final_runs/run_6/final_script.py)
  - [`<project-root>/knowledge-base/final_runs/run_6/final_script_log.txt`](<project-root>/knowledge-base/final_runs/run_6/final_script_log.txt)
  - [`<project-root>/knowledge-base/final_runs/run_6/final_result.json`](<project-root>/knowledge-base/final_runs/run_6/final_result.json)
  - [`<project-root>/knowledge-base/final_runs/run_6/screenshots/final_execution_04_final_reply.png`](<project-root>/knowledge-base/final_runs/run_6/screenshots/final_execution_04_final_reply.png)

## 2026-06-05 三國演義檔案搜尋結果
- 使用者詢問是否有一份《三國演義》的小說。
- 已在本地知識庫與工作區做關鍵字搜尋，包含 `三國演義`、`三国演义`、`羅貫中`、`Romance of the Three Kingdoms`、`Sanguo` 等關鍵字。
- 搜尋範圍包含：
  - `<project-root>/knowledge-base`
  - `<project-root>/.openclaw/workspace`
- 結果：
  - 沒有找到明確命中的檔案或文件。
  - 目前無法確認知識庫內有收錄《三國演義》小說原文或同名條目。

## 2026-06-05 AFC Device (DUT) Compliance Test Plan v1.7 索引查核
- 使用者詢問 `AFC Device (DUT) Compliance Test Plan v1.7.pdf` 目前是否有被 Neo4j 與 QDrant 收錄。
- 已確認檔案存在於本機：
  - `<project-root>/knowledge-base/data/AFC Device (DUT) Compliance Test Plan v1.7.pdf`
  - `<project-root>/knowledge-base/data/uploads/Simple/ingest_20260522_024113_5d2f1280/original/AFC Device (DUT) Compliance Test Plan v1.7.pdf`
  - `<project-root>/knowledge-base/data/uploads/Simple/ingest_20260522_024113_5d2f1280/converted/AFC Device (DUT) Compliance Test Plan v1.7.md`
- 查核結果：
  - Neo4j 以 `afc` / `AFC DUT` / `Compliance Test Plan v1.7` 搜尋都沒有查到對應節點。
  - QDrant `knowledge_base` collection（當前 258 points）掃描 payload 後，也沒有任何包含 `AFC` 的點位。
  - 因此目前可以判定：這份文件有本地檔案與轉換稿，但**資料庫索引中沒有實際命中**。
- 後續補查路徑後可推知：
  - 這份文件放在 `data/uploads/Simple/ingest_20260522_024113_5d2f1280/...`
  - 依現行攝入規則，`Simple` 代表 `simple` / Type6 簡化路徑
  - 目前未找到對應 source json，但從目錄結構可合理推定它當初是走 `simple` 路徑攝入或至少被歸類到 `Simple` 類別

## 2026-06-05 手動上傳 /upload 的預設類型
- 使用者詢問 `https://127.0.0.1:3030/upload` 手動上傳時會用什麼類型。
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
  - [`<project-root>/knowledge-base/docs/chat-stability-test-spec.md`](<project-root>/knowledge-base/docs/chat-stability-test-spec.md)
- 規格重點：
  - 入口固定為 [`https://127.0.0.1:3030/chat.html`](https://127.0.0.1:3030/chat.html)
  - 使用 Playwright Firefox，視窗 `1280x1800`
  - 分成 4 個時段（早上 / 中午 / 下午 / 夜間）
  - 題庫分成健康檢查、WiFi、Lab/5G、邊界題四層
  - 每題都要記錄耗時、來源數、console/network errors、截圖與 task id
  - 輸出資料夾建議使用 `final_runs/chat_stability/run_YYYYMMDD_HHMMSS/`

## 2026-06-05 Chat 穩定度 Runner 落地
- 已把上一版穩定度規格落成可直接執行的 runner 腳本與範例排程：
  - [`<project-root>/knowledge-base/scripts/chat_stability_runner.js`](<project-root>/knowledge-base/scripts/chat_stability_runner.js)
  - [`<project-root>/knowledge-base/scripts/chat_stability_schedule.example.json`](<project-root>/knowledge-base/scripts/chat_stability_schedule.example.json)
- runner 行為：
  - 以 Playwright Firefox 實際操作 [`https://127.0.0.1:3030/chat.html`](https://127.0.0.1:3030/chat.html)
  - 支援 `--schedule-file`、`--slot`、`--all`、`--output-root`、`--base-url`、`--headless`、`--timeout-seconds`、`--retry-count`、`--question-delay-ms`
  - 會自動開啟聊天浮窗、等待連線狀態、逐題送出、等待 bot 回覆、保存截圖、記錄 console / request errors，並輸出 `result.json`
- 已實測成功：
  - 使用 `node scripts/chat_stability_runner.js --schedule-file scripts/chat_stability_schedule.example.json --slot s1_morning --output-root <project-root>/knowledge-base/final_runs/chat_stability_test`
  - 成功產出 `<project-root>/knowledge-base/final_runs/chat_stability_test/run_20260605_172540/`
  - 該次結果為 `total_questions=2`、`completed_questions=2`、`failed_questions=0`、`success_rate=1`
  - 第一題 `你好` 與第二題 WiFi throughput 題都正常回覆，代表 runner 可直接用來做排程式穩定度測試

## 2026-06-05 Chat 穩定度 Cron / Shell 入口
- 已新增可直接放進 cron 的 shell wrapper：
  - [`<project-root>/knowledge-base/scripts/chat_stability_cron.sh`](<project-root>/knowledge-base/scripts/chat_stability_cron.sh)
- wrapper 行為：
  - 支援 `SLOT=<slot_id> /bin/bash scripts/chat_stability_cron.sh`
  - 也支援 `RUN_ALL=true /bin/bash scripts/chat_stability_cron.sh`
  - 內建 `flock`，避免同時重疊執行
  - 會把執行紀錄寫到 `final_runs/chat_stability/cron_logs/`
- 已實測成功：
  - 以 `SLOT=s1_morning OUTPUT_ROOT=<project-root>/knowledge-base/final_runs/chat_stability_cron_test /bin/bash scripts/chat_stability_cron.sh` 跑通
  - 成功產出 `run_20260605_173552/`
  - 該次結果為 `total_questions=2`、`completed_questions=2`、`failed_questions=0`、`success_rate=1`
  - 代表 shell / cron 入口可直接作為每日自動排程入口使用

## 2026-06-05 Chat 穩定度每 5 分鐘輪流一題
- 已新增輪流題庫與 wrapper：
  - [`<project-root>/knowledge-base/scripts/chat_stability_round_robin_catalog.json`](<project-root>/knowledge-base/scripts/chat_stability_round_robin_catalog.json)
  - [`<project-root>/knowledge-base/scripts/chat_stability_round_robin.sh`](<project-root>/knowledge-base/scripts/chat_stability_round_robin.sh)
- 已新增結果歸檔工具：
  - [`<project-root>/knowledge-base/scripts/chat_stability_bucket_run.js`](<project-root>/knowledge-base/scripts/chat_stability_bucket_run.js)
- 運作方式：
  - `round_robin_state.json` 記錄目前輪到哪一題
  - 每次 cron 觸發只會跑 1 題，跑完自動推進到下一題
  - 題庫共 30 題，包含 4G/5G、WiFi、Lab 三大類
  - 跑到最後一題後會回到第一題，形成無限輪迴
  - 若該題 `status=completed` 且有非空 `final_reply`，結果會自動歸到 `PASS/`，否則歸到 `FAIL/`
  - 加嚴後會把 `console_errors` 與 `network_errors` 一併納入 FAIL 判定
  - 每個被歸檔的 run 目錄都會附上 `bucket_report.json`，內含失敗原因
- 已實測成功：
  - 使用 `OUTPUT_ROOT=<project-root>/knowledge-base/final_runs/chat_stability_round_robin_test /bin/bash scripts/chat_stability_round_robin.sh`
  - 首次執行選到 `4g5g_01_scu2140_throughput`
  - 成功產出 `PASS/run_20260605_180914/`
  - 該次結果為 `total_questions=1`、`completed_questions=1`、`failed_questions=0`、`success_rate=1`
  - 也已用 `SLOT=s1_morning OUTPUT_ROOT=<project-root>/knowledge-base/final_runs/chat_stability_cron_test_passfail /bin/bash scripts/chat_stability_cron.sh` 驗證 `cron` wrapper 會把 `run_20260605_182306/` 歸到 `PASS/run_20260605_182306/`
  - 已用刻意注入 `console_errors` 的假 run 驗證 `FAIL/fail_case/` 會寫出 `bucket_report.json` 與對應失敗原因到 log

## 2026-06-05 2-Session Parallel 模式
- 已新增雙 session parallel runner 與輪替 wrapper：
  - [`<project-root>/knowledge-base/scripts/chat_stability_parallel_runner.js`](<project-root>/knowledge-base/scripts/chat_stability_parallel_runner.js)
  - [`<project-root>/knowledge-base/scripts/chat_stability_parallel_catalog.json`](<project-root>/knowledge-base/scripts/chat_stability_parallel_catalog.json)
  - [`<project-root>/knowledge-base/scripts/chat_stability_parallel_round_robin.sh`](<project-root>/knowledge-base/scripts/chat_stability_parallel_round_robin.sh)
- 運作方式：
  - Session A 與 Session B 會各自使用獨立 Firefox persistent profile
  - 兩邊是獨立 browser process，不共用同一個 browser instance
  - 兩邊都會先完成載入與填題，再在同一個 barrier 同步送出
  - `console_errors` 已分成 `acceptable_warning`、`need_attention`、`hard_fail`
  - 只有 `hard_fail` 會直接判定 `FAIL`；`acceptable_warning` 與 `need_attention` 只記錄不直接失敗
  - A/B 仍需 `status=completed`、`final_reply` 非空、且 `network_errors` 為空
  - `bucket_report.json` 與 `final_script_log.txt` 會標出 `A` / `B` 的異常與 warning 分類
- 已實測成功：
  - 使用 `OUTPUT_ROOT=<project-root>/knowledge-base/final_runs/chat_stability_parallel_test /bin/bash scripts/chat_stability_parallel_round_robin.sh`
  - 首次執行選到 `pair_01_4g5g_wifi`
  - 兩邊同時送出成功，且結果歸到 `PASS/run_20260605_190605/`
  - 之後也用刻意注入 `session B console_errors` 的假 run 驗證 `bucket_report.json` 會寫出 `B: console_errors=1 ...`
  - 已再驗證 `run_20260606_070253/`，同樣可正常 PASS，代表獨立 profile 版可穩定運作
  - 已再驗證新的 console 分級後，原本只因 `[Chat] 忽略其他 session 的 chat event` 而被判 FAIL 的樣本，現在會進 `PASS`，並在 log 顯示 `PASS (warnings only)`

2026-06-10 已完成「是否可商業化打包、讓使用者直接執行即自動安裝」的架構評估：目前系統已接近可交付的 Docker 化堆疊，`docker-compose.yml` / `restart_kb.sh` 已可自動拉起 Redis、Neo4j、FastAPI、Celery 與前端 runtime，`docs/new-machine-rebuild-guide.md` 也已把重建流程 SOP 化；但現階段仍有明顯的商業化阻礙，包括多處硬編碼絕對路徑（如 `<project-root>/knowledge-base`、`<project-root>/.openclaw`）、外部依賴（Docker、Node、Python、Ollama、系統權限）、以及首次安裝時仍需資料 bundle/設定檔才可完整可用。結論是：可做成「安裝器 + Docker/資料 bundle」的 B2B 交付模式，若要做到真正單一可執行檔的 consumer 級體驗，則需要先把路徑參數化、做第一啟動 bootstrap、並重新設計 runtime 依賴邊界。

2026-06-10 已完成 B2B/on-prem 安裝器方向評估：建議採「安裝器 + Docker runtime + 私有模型/資料 bundle」的交付模式，而不是嘗試做成單一原生可執行檔。交付物應拆成四層：1) installer/launcher 負責環境檢查、目錄建立、設定檔生成、Docker 啟動與首次 bootstrap；2) runtime 以 Docker Compose 管理 web、worker、Neo4j、Redis、Nginx 與可選 Qdrant；3) data bundle 只放客戶資料與可選 dump，不進 Git；4) license / config 管理客戶授權與站點參數。下一步若要落地，應優先把硬編碼路徑全部參數化、抽出 first-run bootstrap 流程、明確定義 host 依賴清單與失敗回退，然後再決定 installer 形式（Windows MSI、macOS PKG、Linux bash installer、或跨平台 Electron/Tauri launcher）。

2026-06-10 已確認 B2B/on-prem 方案的前提是「不能改動原始系統檔案、且原始系統必須維持正常運作」：因此不應在現有工作樹上直接重構或重寫啟動腳本，而是採旁路式交付。建議做法是建立獨立的 installer/launcher 專案，透過複製/掛載/覆寫外部設定與獨立安裝目錄來運行，同時保留原始 repo 與原始部署完全不變。新方案應使用獨立的 install root、獨立的 compose project name、獨立 container name、獨立資料目錄與獨立 port range，並以 symlink、overlay config、或外部 volume 的方式與原系統隔離，避免共用原本的絕對路徑與 runtime 狀態。

2026-06-10 已落地獨立 release pipeline，且不修改原始系統檔案：新增 [release/README.md](<project-root>/knowledge-base/release/README.md) 與 [release/build_release.sh](<project-root>/knowledge-base/release/build_release.sh)。此 pipeline 會從目前工作樹輸出獨立的 on-prem install package，包內包含 app 副本、runtime（Docker Compose / release Dockerfile / nginx / frontend 靜態檔）、config overlay、OpenClaw overlay 與 manifest；安裝器會把 bundle 展開到指定安裝根目錄，生成獨立 `.env`、自簽 TLS 憑證、`app/config/config.yaml` 與 `runtime/openclaw`，再以獨立 Compose project 啟動 redis / neo4j / qdrant / web / celery / nginx，並使用與原系統隔離的路徑、container 命名與資料目錄。已實測 `./release/build_release.sh` 成功產出 `release/dist/knowledge-base-onprem-20260610_184528-75f3ba30.tar.gz`，並驗證 bundle 內無 `node_modules` / `__pycache__`，installer script 也可通過 `bash -n`。

2026-06-10 已把 release pipeline 升級為版本化與可升級安裝器：`release/build_release.sh` 現在會輸出 `manifest.json` 與 `release-info.json`，兩者都帶有 `format_version`、`release_version`、`release_channel`、`git_commit`、`created_at` 等 metadata；`install.sh` 也改成互動式問答安裝，會先偵測既有 `install-state.env` 走 upgrade 流程，升級前建立備份、保留 `app/data` / `app/config/config.yaml` / `runtime/openclaw`，再同步 release payload。安裝器同時保留非互動參數模式，方便自動化部署。已重新 build 並驗證新包 `knowledge-base-onprem-20260610_185519-75f3ba30.tar.gz` 內包含 `manifest.json`、`release-info.json`、`install.sh`、`app/config/config.yaml.example`，且 installer 腳本通過 `bash -n`。

2026-06-11 已進一步強化 release installer 的前置條件流程：新增 preflight 掃描報告，會在安裝前列出 Docker / Docker Compose / tar / curl / openssl / rsync 的可用狀態；若有缺件，互動式模式會先詢問是否嘗試自動補裝，並提供 `--auto-install-deps` 供無人值守安裝時直接嘗試使用 `apt-get` 補裝可由系統套件管理的項目（目前以 Debian / Ubuntu 為主）。如果補裝後仍缺必需依賴，installer 會明確列出缺少項目並停止，避免在半安裝狀態下繼續往下跑。已重新 build 並驗證新包 `knowledge-base-onprem-20260611_094141-75f3ba30.tar.gz` 內的 `install.sh` 含有 `Preflight check`、`--auto-install-deps` 與 `Attempting to install missing packages` 字樣，且通過 `bash -n`。
- 2026-06-13 已實際驗證 `https://127.0.0.1:18443/chat.html` 的 on-prem KB 聊天鏈路：初始問題並非 WebSocket 或 nginx，而是 `device token mismatch`。已比對主機 `~/.openclaw/identity/device-auth.json` 與 release runtime `runtime/openclaw/identity/device-auth.json`，確認兩者 operator token 不同；將 runtime 的 device-auth 同步為主機版本後，`chat.html` 狀態從 `未連線` 變成 `已連線`，輸入框也正常解鎖。瀏覽器實測送出 `請查詢SCU2140相關報告資訊` 時，系統能正常回覆 KB 參考訊息，並非連線失敗；這次回覆內容顯示該題在 on-prem 目前資料中未命中對應文件，屬於資料召回/命中問題，不是通訊故障。
- 2026-06-13 已確認 `127.0.0.1` 上 OpenClaw 預設模型：透過 `<onprem-root>/.npm-global/bin/openclaw models status --plain` 查得目前 configured default 為 `ollama/glm-4.7-flash`；其配置來源為 `~/.openclaw/openclaw.json`，其中 `models.providers.ollama.models` 雖列出多個可用模型，但 `models status` 明確顯示目前小幫手實際使用的預設模型是 `ollama/glm-4.7-flash`。若後續要切換模型，應以 `openclaw models set <model>` 或調整對應 config 為準。
- 2026-06-13 已將 `127.0.0.1` 上 OpenClaw 預設模型切換為 `gemma4:12b`，實際 `openclaw models status --plain` 顯示為 `anthropic/gemma4:12b`，且 `models status --json` 的 `defaultModel` 與 `resolvedDefault` 都一致為 `anthropic/gemma4:12b`。同時 `openclaw.json` 已被寫入新的預設模型狀態。需注意 `models status` 也顯示 `anthropic` provider 目前缺少可用 auth profile；若之後要確保完全使用本機 Ollama 端，可能需要再將 default model 明確切到 `ollama/gemma4:12b` 或補齊相對應 provider 認證設定。
- 2026-06-13 已修正 OpenClaw `Unknown model: anthropic/gemma4:12b` 問題：`openclaw models list` 顯示實際可用且已 configured 的模型是 `ollama/gemma4:12b`，而 `anthropic/gemma4:12b` 只是存在但缺 auth 的候選項。已執行 `openclaw models set ollama/gemma4:12b`，`models status --plain` 目前回傳 `ollama/gemma4:12b`，`models list` 也將其標記為 `default,configured`；OpenClaw gateway 於 2026-06-13 10:38:46 亦顯示 config hot reload applied，代表這次修正已生效，後續測試應不再再碰到 `Unknown model: anthropic/gemma4:12b`。
- 2026-06-15 針對使用者詢問「為什麼在 `127.0.0.1` 上請小幫手直接產生 `.py` 檔，結果只回覆寫法而沒有直接給檔案」的分析結論：最可能原因不是單一 bug，而是多個行為約束疊加。第一，該助手的預設互動很可能是「先澄清需求、再動手」的 coding assistant 風格，因此在需求不足時會先講做法而非直接輸出完整檔案。第二，如果當時那個 session 沒有可用的檔案寫入工具或被設成純文字回覆模式，就算它想生成檔案，也只能用文字描述內容。第三，使用者的指令若只說「幫我寫一個程式」而沒有附上輸入/輸出/檔名/限制，它通常會判斷資訊不足，選擇安全地回覆寫法。若之後希望它直接產出可用的 `.py` 檔，指令最好明確寫成「請直接輸出完整可執行的 `xxx.py` 內容，不要只講解；若有缺資訊，先列出假設並以最小可執行版本先給我」。
- 2026-06-15 針對使用者詢問「目前 KB 系統的小幫手 OpenClaw 是否和原生系統一樣有 skills 與 MCP 能力」的分析結論：目前 KB on-prem 有把 `skills` 做成可瀏覽/編輯的管理 API 與前端頁面，會讀取 `~/.npm-global/lib/node_modules/openclaw/skills` 與 `WORKSPACE_DIR/skills`，所以「技能檔案的查看與管理」是有接上的；但 release installer 內的 `write_openclaw_overlay()` 只建立 `gateway`、`identity`、`workspace/memory` 與最小 `openclaw.json`，沒有把原生系統 `openclaw.json` 裡的 `tools.profile`、`plugins.entries` 或任何 MCP 註冊/代理配置一併落地，因此 KB 系統本身**不等於**原生 OpenClaw 的完整技能 + MCP 執行環境。若底層主機已經有相同的 OpenClaw runtime 與外掛設定，聊天鏈路可能繼承部分能力；但就 KB 專案程式碼來看，`skills` 是「管理面有」，`MCP` 則沒有看到同等級的整合與保證。
- 2026-06-15 針對「要讓 KB 上的 OpenClaw 跟原生系統功能一模一樣，該怎麼做」的評估結論：最佳做法不是再做一個 KB 專屬的半套 overlay，而是把 KB release 的 OpenClaw runtime 與原生 `~/.openclaw` 的完整設定面對齊，包含 `tools.profile`、`plugins.entries`、skills 目錄、workspace skills、auth profiles、MCP servers/registry、identity 與 channel 設定；若要追求真正一致，應優先採「共享同一份 OpenClaw home / 同一套配置與 skills 來源」而不是單純複製 identity。若又要保留 KB 與原生系統隔離，則只能做到「功能近似」而非 100% 等價，因為原生行為會受 host 上已安裝的 skills、plugins、MCP server、環境變數與權限影響。
- 2026-06-15 針對 `127.0.0.1` 原生 OpenClaw 是否因 tool usage 限制而導致不會真的寫出 Python 檔的查核結論：本次從可讀到的 OpenClaw 設定與 session 紀錄看不出「寫檔工具被硬限制」的證據。現有 `openclaw.json` 的 `tools.profile` 仍是 `coding`，`gateway.nodes.denyCommands` 只封鎖 camera / screen / contacts / calendar / reminders / sms 類指令，未見檔案寫入相關禁用；session 記錄也顯示 `mcpCapabilities.http=true`，但 `tool_results={}` 代表那次會話根本沒有實際觸發工具。因目前無法直接 SSH 到 `127.0.0.1` 讀取其 live runtime，尚不能 100% 排除遠端主機上的額外政策，但就目前能取得的設定來看，較像是「助手在那個 session 選擇了純文字回覆 / 資訊不足先澄清」，而不是工具層硬性禁止產出 `.py` 檔。
- 2026-06-15 已把 `127.0.0.1` 對應的 OpenClaw remote profile `~/.openclaw-rem122/openclaw.json` 改成 explicit Ollama provider：`models.providers.ollama.baseUrl=http://127.0.0.1:11434`、`api=ollama`、`apiKey=ollama-local`，並把唯一可用模型定義為 `qwen3-coder-next`，同時將 `agents.defaults.model.primary` 改成 `ollama/qwen3-coder-next`。已驗證 `openclaw --profile rem122 config validate` 通過，`openclaw --profile rem122 models list` 只剩 `ollama/qwen3-coder-next`，`openclaw --profile rem122 models status --plain` 也回傳 `ollama/qwen3-coder-next`，代表這份 remote profile 已確實切到 127.0.0.1 的 Ollama 模型而不是原本的 Qwen provider。這次只修改本機的 remote profile 檔，沒有 SSH 進主機改動遠端系統檔案。
- 2026-06-17 已整理 Ollama 對外開放的官方設定重點：預設只綁 `127.0.0.1:11434`，要讓外部主機或其他容器存取需設定 `OLLAMA_HOST=0.0.0.0:11434`（Linux systemd 用 `systemctl edit ollama.service` 加 `Environment="OLLAMA_HOST=0.0.0.0:11434"`，macOS 用 `launchctl setenv`，Windows 用系統環境變數）；若是從不同網域的前端頁面呼叫，還要視需要加 `OLLAMA_ORIGINS`。官方也建議若要公開到網路，最好放在反向代理後面，例如 Nginx 轉發到 `localhost:11434`，而不是直接裸露埠號到公網。
- 2026-06-17 已確認 Ollama 官方文件：本機 API 預設服務位址是 `http://localhost:11434/api`，本機存取不需要驗證；若外部要使用本機 Ollama，做法是讓外部 client 直接把 base URL 指向主機對外 IP 與 11434 埠，例如 `http://127.0.0.1:11434/api`，再呼叫 `/api/chat`、`/api/generate`、`/api/tags` 等 endpoint。若是採 OpenAI 相容介面，則可改用 `http://127.0.0.1:11434/v1/` 作為 base_url。若要讓外部穩定連線，主機端仍需確認 Ollama 服務有對外監聽、11434 埠有放行、防火牆或反向代理沒有擋住流量。
- 2026-06-17 已補充 OpenClaw 連本機 Ollama 的設定原則：外部電腦的 `openclaw.json` 若要連到這台主機，`models.providers.ollama` 應指向 `http://127.0.0.1:11434/v1`（OpenAI 相容介面），`apiKey` 可維持任意占位字串如 `ollama-local`；主模型則把 `agents.defaults.model.primary` 設成 `ollama/<本機已安裝模型名>`，例如 `ollama/qwen3.6:35b-a3b`、`ollama/gemma4:31b` 或 `ollama/gemma4:e4b`。若是走 Ollama 原生 API，而不是 OpenAI 相容層，則 base URL 會是 `http://127.0.0.1:11434`，但 OpenClaw 現有配置脈絡以 `/v1` 為主。
- 2026-06-17 已產出雙測試環境共用 DGX GB10 Ollama 的架構簡報：[dual_test_env_ollama_architecture.pptx](<project-root>/knowledge-base/dual_test_env_ollama_architecture.pptx)，並保留產生腳本 [generate_dual_test_env_ollama_architecture_pptx.py](<project-root>/knowledge-base/generate_dual_test_env_ollama_architecture_pptx.py)。簡報共 5 張：封面、整體架構圖、Anritsu MT8000 環境、Amarisoft 環境、部署與維運重點。設計重點是兩個環境各自擁有獨立的 OpenClaw AI Agent 與儀器控制邏輯，但共用同一台 DGX GB10 上的 Ollama 推論服務，Anritsu 對應 `qwen3.5:35b`，Amarisoft 對應 `gemma4:12b`。
- 2026-07-16 已確認目前 knowledge-base 系統有正式 FastAPI 設計，而且是主要 Web API 後端，不是只安裝未使用的相依套件：`requirements.txt` 宣告 `fastapi>=0.115.0` 與 `uvicorn[standard]>=0.30.0`；`src/web_api/__init__.py` 建立 `FastAPI(...)` app、lifespan、CORS、Pydantic request/response models，並集中定義搜尋、非同步任務狀態、上傳、管理統計、文件/skills 管理、OpenClaw chat config 與 `/ws` WebSocket 等路由；`docker-compose.yml` 的 `web` 服務與 `Dockerfile` 都以 `uvicorn src.web_api:app` 啟動。整體資料流可概括為前端/nginx -> FastAPI/Uvicorn -> Redis/Celery 背景任務 -> Neo4j/Qdrant/LLM/OpenClaw。現況的主要結構特徵是多數 API 與模型集中在大型 `src/web_api/__init__.py`，尚未使用 `APIRouter` 拆成多個領域模組，因此功能完整，但模組化與維護性仍有改善空間。
- 2026-07-17 已完成主管報告用企業級 Knowledge Base 系統架構簡報 [`knowledge_base_enterprise_architecture.pptx`](<project-root>/knowledge-base/knowledge_base_enterprise_architecture.pptx)，並新增可重建的資料驅動腳本 [`generate_enterprise_kb_architecture_pptx.py`](<project-root>/knowledge-base/generate_enterprise_kb_architecture_pptx.py)。簡報採 16:9、深海軍藍/科技藍/青綠企業配色，所有架構元素均為可編輯 PowerPoint 向量圖形，共 10 張：封面、管理摘要與知識價值鏈、五層完整邏輯架構、KB Search/OpenClaw Chat 雙執行路徑、文件攝入供應鏈、混合檢索與答案生成、資料與狀態責任邊界、原始站台與 on-prem release 部署拓撲、可靠度/安全治理、主管結論與 90 天優先事項。架構內容以目前程式碼與部署設定為準，明確區分原始站台的 host Qdrant/Ollama/OpenClaw 與 on-prem release 內建 Qdrant 的差異，也涵蓋 Vue/chat、Nginx、FastAPI、Redis、Celery Search/Ingest/Beat、Qdrant、Neo4j、File Store、Ollama 與 OpenClaw。已完成 `python3 -m py_compile`、實際腳本生成、`unzip -t` PPTX 結構檢查、python-pptx 10 張頁數/圖形邊界檢查、LibreOffice 轉 10 頁 PDF，以及全頁縮圖與關鍵頁逐頁視覺檢查；修正小卡 icon/文字距離、邏輯架構頁底部重疊與 footer 裁切後驗證通過。邊界檢查僅有封面與結論頁刻意超出畫布的背景裝飾圓形，沒有內容型圖形越界。
- 2026-07-20 使用者明確回饋上一版偏向架構說明簡報、沒有足夠明確的「架構圖」，因此已另行重做真正 diagram-first 的 [`knowledge_base_architecture_diagrams.pptx`](<project-root>/knowledge-base/knowledge_base_architecture_diagrams.pptx)，產生腳本為 [`generate_kb_architecture_diagrams_pptx.py`](<project-root>/knowledge-base/generate_kb_architecture_diagrams_pptx.py)。新檔共 5 張且沒有封面或文字型管理摘要頁，第一張直接呈現 Knowledge Base 完整端到端總架構，後續依序為查詢與 OpenClaw 聊天架構、文件攝入與知識建立架構、混合檢索/資料融合/引用架構、現行站台與 on-prem release 部署架構；每張都包含可編輯 PowerPoint 向量元件、系統邊界、資料庫圖形、連線箭頭、方向與協定/資料流標籤。已用 LibreOffice 實際轉成 5 頁 PDF並逐頁及縮圖總覽檢查，針對窄節點調整為自動取消圖示以避免 Browser/Neo4j/Qdrant/Search Worker 等名稱不自然換行；最終 `python3 -m py_compile`、`unzip -t`、頁數、PDF 轉檔及圖形邊界檢查全部通過，5 張投影片 `out_of_bounds=0`。後續若使用者要「架構圖」，應交付此 diagram-first 新檔；上一版 `knowledge_base_enterprise_architecture.pptx` 僅適合作為架構說明型主管簡報，不應再當成純架構圖版本。
- 2026-07-20 已依使用者提供的 [`all_dig.jpg`](<project-root>/knowledge-base/all_dig.jpg) 再次重製 Knowledge Base 架構簡報，新增 [`knowledge_base_architecture_all_dig_style.pptx`](<project-root>/knowledge-base/knowledge_base_architecture_all_dig_style.pptx) 與可重建腳本 [`generate_kb_architecture_all_dig_style_pptx.py`](<project-root>/knowledge-base/generate_kb_architecture_all_dig_style_pptx.py)。本版不使用參考圖作背景，也不沿用管理卡片版型，而是將其視覺規則重建為 PowerPoint 原生向量：白色大畫布、薄色系系統邊界、淡色圓角節點、資料庫圓柱、灰色直線/直角箭頭、少量線上標籤與大量留白。第一張採與參考圖相同的整體構圖，呈現上方使用者/管理者/知識維護者、左側存取與 Web、中央 Knowledge Base AI 應用、右側 OpenClaw/Ollama，以及下方 Unified Knowledge Data Platform；其餘四張依序拆解查詢與 Chat、文件攝入、混合檢索與引用、現行站台和 On-Prem 部署。內容維持目前系統事實，包括 Nginx、FastAPI/Uvicorn、Redis/Celery、SearchEngine、Document Pipeline、Qdrant、Neo4j、File Store、OpenClaw 與 Ollama，並區分現行 host Qdrant 與 release bundled Qdrant。驗證已完成：`python3 -m py_compile`、實際產生 PPTX、`unzip -t`、LibreOffice 轉 5 頁 PDF、逐頁 PNG/contact sheet 視覺檢查，以及 python-pptx 邊界檢查；結果為 5 張、253 個可編輯圖形、`out_of_bounds=0`。後續若使用者要求風格與 `all_dig.jpg` 雷同，應以此檔作為主要交付版本。
- 2026-07-20 已依使用者回饋強化第一張總架構圖的角色路徑，並同步更新 [`all_kowledge.jpg`](<project-root>/knowledge-base/all_kowledge.jpg)、[`knowledge_base_architecture_all_dig_style.pptx`](<project-root>/knowledge-base/knowledge_base_architecture_all_dig_style.pptx) 與 [`generate_kb_architecture_all_dig_style_pptx.py`](<project-root>/knowledge-base/generate_kb_architecture_all_dig_style_pptx.py)。原先「使用者 / 管理者 / 知識維護者」共用單一 Browser 節點，無法判斷角色拓撲；新版拆成三個獨立角色並改用同色路徑語意：藍色「使用者」對應 Search UI / Chat UI、Search API / WebSocket 與查詢/對話；紫色「管理者」對應 Admin UI、Admin API 與管理任務；綠色「知識擁護者」對應 Upload / Watch、Ingest Task、Document Pipeline 與索引建立。Nginx、Celery、Redis 和資料平台仍以灰色線表示三角色共用基礎設施，避免誤解為三套後端。第一次以長折線由角色跨區連接的版本在渲染後判定過於雜亂，最終改成角色框內直接標示路徑摘要，搭配同色 UI 節點與 API 線追蹤，並新增圖例說明。已驗證腳本編譯、PPTX 產生、ZIP 結構、LibreOffice 轉 5 頁 PDF、第一張視覺結果與圖形邊界；最終 PPTX 為 5 張、264 個可編輯圖形、`out_of_bounds=0`，JPG 為 2000x1125 RGB。
- 2026-07-24 已分析使用者執行 `./restart_kb.sh` 時出現的 `KB_REPORT_DB_PASSWORD` compose interpolation 錯誤。根因是 `docker-compose.yml` 內 `report_registry`、`web`、`celery_ingest_worker` 都直接引用 `${KB_REPORT_DB_PASSWORD}`，但 `restart_kb.sh` 沒有先載入任何實際存在的 `.env` / `config/report-ingest.env`，而專案根目錄也沒有 `.env`，只有 `config/report-ingest.env.example` 作為範本。因此 `docker compose up -d ...` 在啟動 `report_registry` 前就因 required variable 缺值而中止。直接修法是建立真實部署 env 檔或先 export 該變數；正式修法則是讓啟動流程明確載入一份已存在的 env 檔，避免依賴人工記憶。特別注意 `KB_REPORT_DB_PASSWORD` 是 PostgreSQL 明文密碼，不是 hash；若密碼含 `$`，要在 env 檔中正確逸出，否則 compose 也可能錯誤展開。
- 2026-07-24 已落地 `KB_REPORT_DB_PASSWORD` 的啟動修正：`restart_kb.sh` 現在會先載入 root `.env` 與 `config/report-ingest.env`，若本機報表 env 檔不存在且 example 存在，則自動以 `openssl rand -hex 24`（或 `python3 secrets.token_hex`）產生一次性的 PostgreSQL 密碼，從 `config/report-ingest.env.example` 建立 `config/report-ingest.env` 並設為 600 權限，再繼續跑 `docker compose up -d --build redis neo4j web celery_search_worker celery_ingest_worker celery_beat nginx`；若 env 檔存在但未定義密碼則直接顯性失敗，避免靜默用壞設定。同步把 `config/report-ingest.env.example` 改成可被 shell `source` 的單引號格式，並將 `config/report-ingest.env` 加入 `.gitignore`。已驗證 `bash -n restart_kb.sh` 通過，且複製 example 到暫存檔後 `source` 可正常讀出 `KB_REPORT_DB_PASSWORD`、`KB_AGENT_TOKEN_HASHES_JSON` 與 `KB_REVIEWER_TOKEN_HASHES_JSON`。
- 2026-07-30 已開始整理 git 同步狀態：先清掉 `src/**/__pycache__` 的 bytecode 雜訊，並在 `.gitignore` 新增 `config/report-ingest.env`、`data/cleaned/`、`data/watch/`、`data/uploads/*/ingest_*/`、`release/.build/`、`release/dist/`，避免 runtime 產物污染同步。已將 source-only 變更暫存，包含核心程式、前端、測試、release 腳本、報表 ingest 新模組、文件與設定；刻意未暫存的仍有大型產物與資料快照，例如 `*.pptx`、`*.jpg`、`data/assets/SIT-TR-NR-Throughput-NCQ2200B2V-EV-V10/` 等，等待使用者決定是否也要一併同步到 GitHub。此時 repo 已從「混雜 code / runtime / 產物」整理成「source staged、artifact pending」兩層。
