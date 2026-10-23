# chat-v2.html 來源說明

`frontend/chat-v2.html` 是 DEV 3030 Nginx 網頁目錄
（`/srv/knowledge-base-production-rebaseline-20260829-v3/.frontend-build-runtime-user8/chat-v2.html`）
的部署檔副本，2026-10-16 起納入版本控制以便追溯。

- 2026-10-16 10:55（+08）他人在執行檔加入「知識專區」切換（CSIT／WiFi／4G-5G／技術）。
- 2026-10-16 WiFi 專區改走 `/api/wifi8/agent`（WiFi 知識 Agent），其他專區流程不變。
- 2026-10-16 WiFi 專區不需 OpenClaw 聊天連線即可提問（`canSendWithoutGateway`）；聊天顯示「未連線」時其他專區仍停用。改前備份：`.km-control/wifi8-deploy-20261016/chat-v2.html.pre-offline-fix-20261016`。
  改前備份：`.km-control/wifi8-deploy-20261016/chat-v2.html.pre-wifi-agent-20261016`。

修改執行檔後請同步更新此副本，否則標示為 STALE。
- 2026-10-21 CSIT 知識專區新增「AI 助手選擇列」與「報告查詢助手」（分支 `codex/csit-report-assistant-20261021`，**尚未部署**）：助手清單來自後端 `src/web_api/csit_assistants.json`（`GET /api/csit-assistants`），選到助手時改呼叫 `POST /api/csit-assistants/{id}/query`，不需要 OpenClaw 聊天連線；其他專區與「一般問答」流程不變。部署時須把 `frontend/chat-v2.html` 同步到 Nginx 網頁目錄，並備份部署前的檔案；同步後再更新此說明，否則標示為 STALE。
- 2026-10-21 一般問答新增「知識庫實體檢查」（`checkEntitiesInKnowledgeBase`）：問題點名特定設備／專案代號（2 個以上字母接 3 個以上數字，如 NCQ2200B2V-D294、SCU5050），但最相近的 12 筆知識庫來源都沒有提到它時，直接回覆「查無此項目」，不呼叫聊天模型、不列出無關來源；WiFi 專區（走 `/api/wifi8/agent`）與選了 CSIT 助手時不受影響；檢查本身失敗時照原流程繼續。僅前端（Nginx 靜態檔，兩區共用），部署前備份 `~/.km-control/csit-assistants-deploy-20261021/chat-v2.html.pre-entity-guard`。
- 2026-10-23 WiFi 專區（`frontend/wifi8/`）新增「延伸知識」區塊：主體回答之外，另顯示相關主題與文件（含知識圖譜引用 `[G#]`）、標示為「模型一般知識，未經專區文件驗證」的補充、以及「你可能還想問」按鈕（只填入輸入框，不自動送出）。由後端旗標 `KM_WIFI8_AGENT_EXTENSION` 控制（預設關閉，關閉時畫面與行為與先前相同）。CSS／JS 檔名隨內容雜湊更新（`wifi8.ddab88407a74.js`、`wifi8.fb63684bb30c.css`），`index.html` 已指向新檔名。**尚未部署**。
