# 模型選單(第二階段,前端)

導覽助理(`/hub/`)與各專區助理(`/zones/<專區>/`)的問題框旁多一個「模型」下拉選單。

## 運作方式
- 腳本 `frontend/km-llm-select.<hash>.js` 只在頁面加一個 `<script>` 標籤載入,**不修改頁面原本的程式**(正式環境的 `hub.*.js`、`zone.*.js`、`zones-live.*.js` 不在 git 裡,所以用外掛方式)。
- 載入後讀 `GET /api/llm/profiles?zone=`,在問題框旁放選單;提問時在 `POST /api/keeper/route` 與 `POST /api/wifi8/agent`(專區頁會改寫成 `/api/zones/<專區>/agent`)的 JSON 加上 `llm: <編號>`。
- 只送模型**編號**,不送模型名稱、網址或金鑰;選「自動(預設)」時請求完全不變。
- 這個專區不允許的模型顯示為停用並說明原因;可選項少於兩個(例如 WiFi 或 API 不可用)時**不顯示選單**,頁面維持原樣。
- 選擇存在瀏覽器(`localStorage: km.llm.profile`);該專區不允許已存的選擇時自動回到預設。
- 首次選「實驗」的外部模型時會跳出確認(問題與文件節錄會送到外部算力平台)。
- 回答下方顯示「回答模型:…」;伺服器回 403/422/429 時,把錯誤轉成頁面看得懂的文字,並在期限已到、專區禁止等情況回到預設模型。
- 不裝在:`/wifi8/`(工具呼叫 agent,第三階段)、示範的部門文管頁、舊的 cpe/smallcell 頁。

## 部署
`scripts/deploy_llm_select.sh`(在 DA40 上執行):複製腳本到前端執行目錄,在 8 個頁面(`hub` 與 7 個專區頁)的 `</body>` 前加一行 `<script>`;頁面先備份到 `~/.km-control/llm-select-ui-20261116/`,可重複執行,`--verify` 只驗證,`--rollback` 還原。前端目錄 TEST 與 DA40 共用;TEST 的後端沒有 `/api/llm/profiles`,選單不會出現。

## 驗證
`tests/test_llm_select_ui.py`(檔名雜湊、只送編號、不裝在 WiFi 與示範頁、錯誤處理、部署腳本目標);瀏覽器測試用假的 API 伺服器驗證:預設不加 `llm`、選模型後請求帶 `llm`、回答顯示模型名稱、禁止專區顯示停用且已存選擇回到預設、期限已到的錯誤顯示為文字並回到預設。
