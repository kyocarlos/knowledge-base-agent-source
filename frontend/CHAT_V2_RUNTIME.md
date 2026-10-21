# chat-v2.html 來源說明

`frontend/chat-v2.html` 是 DEV 3030 Nginx 網頁目錄
（`/srv/knowledge-base-production-rebaseline-20260829-v3/.frontend-build-runtime-user8/chat-v2.html`）
的部署檔副本，2026-10-16 起納入版本控制以便追溯。

- 2026-10-16 10:55（+08）他人在執行檔加入「知識專區」切換（CSIT／WiFi／4G-5G／技術）。
- 2026-10-16 WiFi 專區改走 `/api/wifi8/agent`（WiFi 知識 Agent），其他專區流程不變。
- 2026-10-16 WiFi 專區不需 OpenClaw 聊天連線即可提問（`canSendWithoutGateway`）；聊天顯示「未連線」時其他專區仍停用。改前備份：`.km-control/wifi8-deploy-20261016/chat-v2.html.pre-offline-fix-20261016`。
  改前備份：`.km-control/wifi8-deploy-20261016/chat-v2.html.pre-wifi-agent-20261016`。

修改執行檔後請同步更新此副本，否則標示為 STALE。
- 2026-10-21 CSIT 知識專區新增「AI 助手選擇列」與「報告查詢助手」（分支 `codex/csit-report-assistant-20261021`，**尚未部署**）：助手清單來自後端 `src/csit/assistants.json`（`GET /api/csit-assistants`），選到助手時改呼叫 `POST /api/csit-assistants/{id}/query`，不需要 OpenClaw 聊天連線；其他專區與「一般問答」流程不變。部署時須把 `frontend/chat-v2.html` 同步到 Nginx 網頁目錄，並備份部署前的檔案；同步後再更新此說明，否則標示為 STALE。
