# Daily Changelog - 2026-05-18

## 總結

今天主要完成三件事：

1. 將 AnythingLLM 對外入口穩定到 `https://61.216.9.52/`。
2. 讓 `AnythingLLM` 與 `knowledge-base` 的啟動腳本都只管理各自服務，不再修改共用入口檔案。
3. 將兩套系統的 Qdrant 完全隔離，避免資料層互相干擾。

## 重要結論

- AnythingLLM 的公開入口現在由宿主機 `nginx` 直接提供，`443` 正常轉發到本機 `3001`。
- knowledge-base 的公開入口維持在 `/kb/` 路徑，不再被 AnythingLLM 腳本改寫。
- 兩邊的 Qdrant 已經分離為兩個獨立容器與兩組 host port。

## 詳細修改內容

### 1. AnythingLLM 啟動與公開入口

修改檔案：

- [`/home/da40_ai_gb10/anything-llm/start-anythingllm.sh`](/home/da40_ai_gb10/anything-llm/start-anythingllm.sh)
- [`/home/da40_ai_gb10/anything-llm/systemd/anythingllm-start.service`](/home/da40_ai_gb10/anything-llm/systemd/anythingllm-start.service)
- [`/home/da40_ai_gb10/anything-llm/systemd/README.md`](/home/da40_ai_gb10/anything-llm/systemd/README.md)

做法：

- 移除 `start-anythingllm.sh` 對 nginx 共用入口的管理邏輯。
- 保留 AnythingLLM 自己的啟動流程。
- 保留公開入口健康檢查，啟動後主動測 `https://61.216.9.52/`。
- 新增 systemd oneshot 服務 `anythingllm-start.service`，讓開機可自動執行 `start-anythingllm.sh`。

結果：

- `anythingllm-start.service` 已啟用。
- `https://61.216.9.52/` 可以正常回應。
- `start-anythingllm.sh` 已縮成只管理 AnythingLLM 自己，不會再碰 shared nginx 設定。

### 2. knowledge-base 啟動腳本與入口

修改檔案：

- [`/home/da40_ai_gb10/knowledge-base/restart_kb.sh`](/home/da40_ai_gb10/knowledge-base/restart_kb.sh)

做法：

- 移除會去停止宿主機 nginx 或處理共用入口的邏輯。
- 保留 knowledge-base 自己的 Docker stack 重啟流程。
- 保留對 `https://127.0.0.1:3030/` 的本機驗證。
- 讓腳本只管 knowledge-base 服務本身。

結果：

- knowledge-base 不再主動碰 AnythingLLM 的入口設定。
- 共享 nginx 主設定仍維持 `/` 給 AnythingLLM、`/kb/` 給 knowledge-base。

### 3. Qdrant 完全隔離

修改檔案：

- [`/home/da40_ai_gb10/anything-llm/start-anythingllm.sh`](/home/da40_ai_gb10/anything-llm/start-anythingllm.sh)
- [`/home/da40_ai_gb10/knowledge-base/config/config.yaml`](/home/da40_ai_gb10/knowledge-base/config/config.yaml)
- [`/home/da40_ai_gb10/knowledge-base/restart_kb.sh`](/home/da40_ai_gb10/knowledge-base/restart_kb.sh)

做法：

- AnythingLLM 使用獨立容器 `anythingllm-qdrant`。
- knowledge-base 使用獨立容器 `kb-qdrant`。
- knowledge-base 的 Qdrant 連線從 `6333` 改為 `6335`。
- knowledge-base 容器對應的 Qdrant host port 改為 `6335/6336`。

結果：

- `anythingllm-qdrant` 對外映射在 `6333/6334`。
- `kb-qdrant` 對外映射在 `6335/6336`。
- 兩套系統現在不共用同一組 Qdrant 資料層。

## 驗證結果

- `curl -k -I https://61.216.9.52/` 成功。
- `curl -k -I https://61.216.9.52/kb/` 成功。
- `curl http://127.0.0.1:6333/healthz` 成功。
- `curl http://127.0.0.1:6335/healthz` 成功。
- `docker ps` 顯示：
  - `anythingllm-qdrant`
  - `kb-qdrant`

## 下次處理順序

如果之後要接續這個環境，先讀這份檔案，再看對應腳本：

1. 先讀 [`/home/da40_ai_gb10/knowledge-base/DAILY_CHANGELOG_2026-05-18.md`](/home/da40_ai_gb10/knowledge-base/DAILY_CHANGELOG_2026-05-18.md)
2. AnythingLLM 相關操作只看 [`/home/da40_ai_gb10/anything-llm/start-anythingllm.sh`](/home/da40_ai_gb10/anything-llm/start-anythingllm.sh)
3. knowledge-base 相關操作只看 [`/home/da40_ai_gb10/knowledge-base/restart_kb.sh`](/home/da40_ai_gb10/knowledge-base/restart_kb.sh)
4. 不要讓任何腳本去改寫共用 nginx 入口
5. 不要讓兩邊共用同一個 Qdrant container 或 host port

## 注意事項

- 這份記錄是今天這輪調整的唯一總結檔。
- 若之後 Qdrant 或入口設定再變動，請先更新本檔，再改程式。

## 4. knowledge-base 效能分析與優化方向

這一段是後續接續工作的重點，僅針對 `knowledge-base` 本體，不包含 `AnythingLLM`。

### 已確認的現況

- `knowledge-base` 的公開入口目前在 `/kb/`，與 AnythingLLM 入口分離。
- Qdrant 已完全隔離，因此資料層不是目前兩台電腦同時提問時的主要瓶頸。
- chat 流程有全域與單瀏覽器併發限制，會在同時提問時形成排隊。
- Ollama 生成目前使用單一實例，且已調整為 `num_predict=2048`；若仍偏慢，下一步才考慮再擴實例或換更小模型。
- 檢索端會先做 CPU embedding，再查 Qdrant，`top_k` 已調整為 `basic=3`、`deep=6`，上下文長度比原先短。
- `syntheses` 快取只對重複問題有效，第一次或第二次問答不會因此明顯提速。

### 優化優先順序

1. 先降低 `num_predict`，這是最不影響回覆格式、但最可能直接提速的項目。
2. 再縮小 `basic_top_k` 與 `deep_top_k`，減少 prompt 長度與檢索成本。
3. 再評估是否需要提高 chat 併發上限，但前提是 Ollama 本身吞吐撐得住。
4. 如果仍然偏慢，再考慮真正增加 Ollama 實例或改成 GPU 推理。
5. `syntheses` 與其他快取機制只作為輔助，不應當成第一優化手段。

### 目前已落地的調整

- `config/config.yaml` 與 `config/config.yaml.example` 已把 `basic_top_k` 改成 `3`、`deep_top_k` 改成 `6`。
- `ollama.num_predict` 已設為 `2048`，並由 `src/web_api/ollama_client.py` 實際套用。
- `src/main.py`、`src/search/__init__.py`、`src/vector_store/__init__.py`、`src/graphrag/__init__.py` 已同步對齊新的預設值。
- `docker-compose.yml` 的 web 服務已加入 `CHAT_GLOBAL_CONCURRENCY_LIMIT=1`。
- `ollama.service` 已透過 systemd drop-in 加上 `OLLAMA_NUM_PARALLEL=1` 與 `OLLAMA_MAX_LOADED_MODELS=1`。
- 這一版沒有改動任何回覆模板、前端格式或輸出結構。

### 不建議先動的地方

- 不要改回覆模板或前端渲染格式。
- 不要先放大 chat 併發，只會把後端壓力一起拉高。
- 不要再讓 KB 腳本碰 AnythingLLM 或共用 nginx。

### 5. OpenClaw chat 的 KB 保護機制

修改檔案：

- [`/home/da40_ai_gb10/knowledge-base/frontend/chat.html`](/home/da40_ai_gb10/knowledge-base/frontend/chat.html)
- [`/home/da40_ai_gb10/knowledge-base/frontend/src/views/ChatView.vue`](/home/da40_ai_gb10/knowledge-base/frontend/src/views/ChatView.vue)

做法：

- 將 OpenClaw 送出流程改成「先等 KB 搜尋完成，再決定是否送出」。
- 若 KB context 尚未準備好，直接停在本地，不把純問題送給 OpenClaw。
- 這樣可以避免兩台電腦在不同時序下，走到不同的回答來源。
- Vue 版 `ChatView` 也同步套用同樣的保護機制，避免不同前端路由產生來源分岔。

結果：

- KB 尚未完成時，不會再把只有原始問題的內容送往 OpenClaw。
- 回覆來源會更一致，不會因為一台快、一台慢而出現明顯分岔。
- Vue 前端已完成 production build 驗證，輸出更新到 `.frontend-build-live`。
- `restart_kb.sh` 不需要再額外補 Vue 對齊邏輯；只要保留前端 build 步驟，就會把 `ChatView.vue` 的保護機制帶進部署輸出。
- 先前 build 曾讓 `/chat.html` 回退到 SPA 入口，已手動把 `frontend/chat.html` 與 `frontend/lib/marked.min.js` 補回 `.frontend-build-live`，讓小幫手頁面恢復正常。
- KB 保護機制已調整為最多等待 60 秒，再將 KB context 送給 OpenClaw；不再是立即拒送，超時才顯示明確提示。
- 新增可調參數 `openclaw_chat.kb_search_timeout_seconds`，由 `/admin/chat-settings` 與系統管理頁調整，前端 `chat.html` 與 Vue `ChatView` 共用同一個 runtime 值。
- `/admin/chat-settings` 的 405/500 問題已修正：nginx 已加入轉發規則，後端也改成把 runtime 設定寫到 `data/chat_settings.yaml`，不再寫入唯讀的 `config/config.yaml`。
