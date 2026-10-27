# WiFi 知識專區開發交接（2026-10-27）

> 本倉庫為 PUBLIC。不得提交密碼、金鑰、內部主機位址、測試報告原文、`WiFi_Test_report/`、`KM_Modify` 內容或備份。

## 1. 分支與內容
| 分支 | 內容 |
|---|---|
| `merge/wifi8-km-runtime-to-main-20261019` | 已公開基底（WiFi 專區後端 v1 + 前端） |
| `codex/wifi8-ui-polish-20261026` | 前端：深色介面、頁首固定「WiFi 知識專區」、`\boxed` 修正（commit 7bdf88a） |
| `handoff/wifi8-backend-20261027`（本分支） | 在上列前端分支上疊加後端：清單題列舉輔助、串流、計算、記憶、回饋、概念工具、數值報告模組與測試 |

本分支只放 WiFi 專區相關程式與文件；不含本機 122 個後端歷史 commit、不含 CSIT 整合、不含概念先導試驗報告（含大量原文衍生內容）。

## 2. 後端模組（`src/wifi8/`）
- `agent.py`：Agent 主流程（工具迴圈、串流、引用）。
- `listing.py` + `list_hints.json`：清單題列舉輔助（旗標 `KM_WIFI8_LIST_ASSIST`，上線為 1；黃金集清單題召回約 0.80 → 1.00）。
- `calculator.py`、`memory.py`、`feedback.py`、`progress.py`：計算、對話記憶、使用者回饋、進度。
- `concepts.py`、`concept_graph.py`、`concept_merge.py`、`concept_tools.py`、`concept_rules.json`：概念圖譜與工具（旗標 `KM_WIFI8_CONCEPTS`，上線為 0；Phase 2 圖表未做）。
- `extension.py`、`graph.py`：擴充點與 Neo4j 圖查詢（環境變數取得連線資訊）。
- `src/report_numeric/`：測試報告數值入庫（解析、Timescale schema、向量、圖、Agent）；`metric_dictionary.json` 是草稿，單位與判定規則待領域人員確認。
- `src/web_api/`：`wifi8_routes.py`、`tasks.py`（Celery）、`openai_compatible_client.py`（LLM 閘道客戶端）。
- 設計說明：`docs/wifi8-extension-design-20261022.md`、`wifi8-interaction-20261025.md`、`wifi8-concept-tools-20261025.md`。

## 3. 測試
`tests/test_wifi8_*.py` 與 `tests/test_openai_compatible_llm.py` 共 360 項，在本分支工作樹實測全通過。需要 Python 3.12、pytest、httpx 與專案相依套件（原驗證在 Docker 映像內以 `PYTHONPATH=/work` 執行）。
評測：`scripts/eval_wifi8_agent.py`（黃金集 94 題；上線驗收通過率約 96%、hit@10 97.3%、錯誤 0）。

## 4. 上線現況（TEST 與 DA40 兩區機制必須一致）
- 兩區：TEST（kb-web、kb-celery-search）與 DA40（km-da40-*），共用 Nginx，依 cookie 分流；前端靜態檔兩區共用，後端各自重建。
- 旗標現況：`KM_WIFI8_LIST_ASSIST=1`、`CONCEPTS=0`、`STREAM／MEMORY／CALC=1`；web 的 `STREAM／FEEDBACK=1`。
- LLM 走內部 OpenAI 相容閘道（位址與金鑰由環境變數提供，不在倉庫內）。search worker 用 KM 專用金鑰；web／ingest worker 仍用舊共用金鑰（待換）。
- 前端變更需換檔名雜湊並同步 `index.html`；部署用「先放資產、最後原子替換 index.html」，並保留備份。

## 5. 待辦
1. DA40 真實瀏覽器畫面需有 DA40 權限者手動驗證（列舉輔助、互動功能、新介面、chat-v2 導覽）。
2. 「Confluence / Jira / TestRail 查詢專區」目前只有前端入口，後端（KM 保存使用者帳密、以本人身分查詢）未實作。
3. 是否開啟 `KM_WIFI8_CONCEPTS`；概念圖 Phase 2 未做。
4. 兩區 Timescale 資料表不一致；TEST Neo4j 映像標籤浮動；一般問答不讀 `ai_km_knowledge_v1`。
5. 數值報告：Q1～Q8 領域問卷待回覆（Tx/Rx 視角、RSSI 單位、RvR Best Angle 等）前，不要決定入庫格式。
6. `\boxed` 以外的 LaTeX 寫法未涵蓋。

## 6. 工作規則（沿用專案 AGENTS.md）
全程繁體中文；避免硬編碼（資料驅動／可設定）；TEST 與 DA40 兩區一致並雙區驗收；修改前先確認前次修正不受影響、修正後先自行驗證再回報；不得啟用 rerank；不同時送大量並行 LLM 請求；未獲明確授權不 commit／push／部署／刪除；機密只從環境變數或受保護 secret 檔讀取，不寫入倉庫、輸出或日誌。
