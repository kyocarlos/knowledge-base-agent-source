# 給 Codex：網頁風格修改說明

分支：`codex/frontend-style-20261023`（基底為 PR #63 `merge/wifi8-km-runtime-to-main-20261019` 的最新提交 `338520f4`，再加上 CSIT 知識專區助手選擇列與 WiFi 專區延伸知識畫面）。

## 任務範圍：只改「視覺風格」，不改功能
- 可改：顏色、字型、間距、圓角、陰影、動效、版面排列、圖示、深淺色主題、行動版排版。
- **不可改**：後端 API 路徑與請求格式、登入／授權流程、WebSocket 協定、資料處理邏輯、繁體中文文案（要調整用字請先在說明中列出）。

## 要改的檔案
| 畫面 | 檔案 | 備註 |
|---|---|---|
| 知識中樞／一般問答／專區切換／CSIT 助手選擇列 | `frontend/chat-v2.html` | 單一 HTML（內嵌 CSS 與 JS） |
| WiFi 知識專區 | `frontend/wifi8/index.html`、`frontend/wifi8/wifi8.fb63684bb30c.css`、`frontend/wifi8/wifi8.ddab88407a74.js` | 純 JS，無建置步驟 |
| 登入／管理 | `frontend/login.html`、`control-login.html`、`control-admin.html`、`oidc-binding.html` | 若需要一致風格再改 |
| Vue 版（舊，非正式入口） | `frontend/src/` | 除非另行說明，不要動 |

WiFi 專區 CSS 的設計變數在 `:root`：`--ink --ink-soft --muted --line --line-soft --canvas --paper --navy --navy-raised --green --blue --purple --amber --red`（含各自的 `-soft`）、`--radius`。請優先改變數，不要在各處硬編碼顏色。

## 絕對不能弄壞的 JavaScript 依賴（DOM 識別碼）
- `chat-v2.html`：`cardGrid chatFab chatInput chatMessages chatSendBtn chatStatus chatWindow citationSummary connectionBadge connectionText csitAssistantBar csitAssistantNote docContentBody docContentModal docContentTitle docListContainer docModal docSearchInput knowledgeZoneStatus mediumCount modalContent modalTitle noneCount qualityMeta qualityNote qualityStatus queueCount queueStatus stageStatus strongCount weakCount`
- `wifi8/*.js`：`agent-question agent-submit agent-wait app auto-check-host auto-check-message auto-check-toggle close-dialog conversation document-dialog document-dialog-body document-dialog-title document-filters document-results hybrid-history hybrid-query hybrid-results hybrid-submit nav-toggle page-content page-section page-title page-updated primary-nav quality-schedule-host quality-schedule-hour quality-schedule-message quality-schedule-minute quality-schedule-save refresh-page update-banner upload-form upload-status zone-status`
- 還有以 class 為鉤子的元素，改名前請先在檔案內搜尋用法：`.message .assistant .markdown .cite-ref .graph-ref .extension .ext-section .ext-general .followups .followup .citation-list .grounding .g-chip .g-flags .trace-list`。
- 「延伸知識」區塊的三層標示（文件依據／圖譜關聯／一般知識補充）是產品規則：**一般知識補充必須始終有「未經專區文件驗證」的標示**，樣式可以改，標示不能拿掉。

## 資產檔名規則（改了 CSS／JS 就要做）
`frontend/wifi8/` 的 CSS、JS 檔名帶內容雜湊（`wifi8.<內容 sha256 前 12 碼>.<css|js>`），`index.html` 以檔名引用。修改內容後請：
1. 以新內容的 sha256 前 12 碼重新命名檔案；
2. 更新 `frontend/wifi8/index.html` 的引用；
3. 更新 `docs/handoff/source-manifest.json`（變更檔案的 sha256、移除舊檔名、加入新檔名），並執行 `python3 scripts/verify-handoff-source.py`，必須顯示 PASS。

## 安全與品質要求
- 不得引入外部 CDN、第三方字型服務或追蹤碼（內網環境）；字型請用系統字型或隨檔提供。
- 所有 LLM 回答文字都經過 `escapeHtml` 與受限的 Markdown 轉換才進入頁面；**不得**改成直接 `innerHTML` 插入未轉義內容。
- 版面需在 390 px 寬度無水平捲動；鍵盤可操作；文字與背景對比符合 WCAG AA；尊重 `prefers-reduced-motion`。
- 避免硬編碼：顏色、間距請走 CSS 變數；不要新增只對單一畫面有效的魔術數字。
- 不要提交任何帳號、密碼、金鑰、內部主機名稱或 IP。

## 驗證（請在回報中附上結果）
```bash
node --check frontend/wifi8/wifi8.*.js        # JS 語法
python3 scripts/verify-handoff-source.py       # 來源清單
python3 -m pytest tests/test_wifi8_extension.py tests/test_csit_assistants.py tests/test_frontend_runtime_artifacts.py -q
```
並用瀏覽器實際載入 `chat-v2.html` 與 `wifi8/index.html`（後端可用假資料），截圖：①一般問答 ②選了 CSIT 助手 ③WiFi 專區問答（含延伸知識區塊）④390 px 寬度。若無法連後端，請在說明中註明哪些畫面未驗證。

## 部署
Codex **不要部署**。`chat-v2.html` 是 Nginx 網頁目錄的副本（TEST 與 DA40 共用），部署由維護者備份後同步，兩區必須一致。
