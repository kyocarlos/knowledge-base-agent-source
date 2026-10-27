# WiFi 助手互動體驗補強（2026-10-25）

定位：嚴格查證型研究助理（每句有依據），在不放寬接地規則的前提下補強互動體驗。四項功能各有獨立旗標，預設全部關閉。

| 功能 | 旗標（web 與 worker 都要一致的以 * 標示） | 內容 |
|---|---|---|
| 串流輸出 * | `KM_WIFI8_STREAM` | LLM 客戶端串流（失敗時退回非串流）；worker 把進度與文字片段寫入 Redis 短期清單（TTL 900 秒、2000 筆上限、依任務編號與擁有者隔離）；頁面以 `GET /api/wifi8/agent/{id}/events?after=N` 每 0.4 秒取增量，最後仍由原本的結果端點取得完整答案（引用、接地檢核、延伸知識）。事件讀不到或 worker 未回報時，頁面退回原本的輪詢。 |
| 對話記憶 | `KM_WIFI8_MEMORY` | 前端以分頁 sessionStorage 保存最多 60 則並隨問題送出；後端最近 6 則原文，更早的由程式壓縮成「問、答開頭、來源標題」摘要（不呼叫模型）；新增「新對話」。關閉旗標時仍只用最近 6 則。 |
| 計算工具 | `KM_WIFI8_CALC` | `calculate`：白名單運算式解析（不用 eval）、dBm↔mW、dB↔倍數、Mbps↔MB/s、百分比、平均等；長度、節點、巢狀、次方上限。結果進入工具證據，答案中的數字算「工具資料」。 |
| 回饋 | 無（隨前端與路由；寫入只在使用者按下時） | 有幫助／沒幫助、原因（由伺服器提供清單）、補充說明（500 字）；`POST /api/wifi8/agent/{id}/feedback`（只有提問者、只限已完成任務）；每任務一個 JSON 檔存在專區資料根目錄 `feedback/`；`GET /api/wifi8/agent-feedback/summary` 只回傳彙總數字。 |

## 驗證（未部署）
- 後端測試：WiFi 與客戶端測試 342 項通過（新增：串流客戶端 4、串流事件 4、進度傳輸 6、計算器 約 40、記憶 6、回饋 7）。
- 前端：以真實 Chromium（Playwright）對模擬 API 做流程測試，13 項通過——即時狀態、串流後換成最終答案、回饋列、歷史帶來源標題、重新整理後還原、新對話、按讚、倒讚附原因與說明、後端不串流時沿用輪詢、事件介面 503 時退回輪詢。唯一的 console 錯誤是故意模擬的 503。
- 尚未做：登入後的真實環境畫面驗證（Webwright／實際帳號）、兩區 worker 內以真實 LLM 的串流實測。

## 部署範圍（待授權）
1. worker 疊層映像：agent.py、graph.py、tasks.py、openai_compatible_client.py（`src/web_api/`）、新增 memory.py、calculator.py、progress.py。
2. web 映像：wifi8_routes.py、新增 progress.py、feedback.py（路由匯入它們）。
3. 前端靜態檔：wifi8.5604c3ea685e.js、wifi8.aa56d3c98042.css 與 index.html（兩區共用 Nginx 目錄，舊檔保留）。
4. 兩區 override 加旗標（預設 0）；開啟順序建議：回饋（無旗標）→ 串流（web 與 worker 同時）→ 記憶 → 計算。
5. 回復：旗標設 0 並重建；前端靜態檔 cp 回備份的 index.html。
