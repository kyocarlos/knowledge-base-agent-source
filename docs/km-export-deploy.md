# 回答匯出（km-export）部署說明

把助理的回答整理成簡報、文件、表格等檔案下載。獨立的小服務，不改動 `kb-web`。**尚未部署**；以下是上線步驟與回復方式。

## 權限

- 與「WiFi 知識助理上傳檔案」共用同一項能力 `wifi8_user_files`（`config/km_capabilities.json`，名稱已改為「知識助理：上傳檔案與匯出回答」）。管理員在 KM Control 授權一次，兩項功能同時開放。
- 已有上傳授權的帳號，上線後會同時得到匯出。上線前先列出名單給負責人確認。
- 後端每個端點都檢查（`/config` 回報是否開放；`/plan`、`/build`、`/files/*` 沒有授權回 403）。前端沒有授權時不載入樣式、不顯示按鈕。
- 授權目錄檔由 **control_auth** 容器讀取（管理頁列出可授權項目），資料面服務只查授權表，不讀目錄檔。更新名稱要改 control_auth 那份 `km_capabilities.json`。

## 流程（使用者視角）

回答下方「匯出為檔案」 → 選格式或描述需求 → 產生大綱（此時才呼叫語言模型）→ 使用者修改標題／章節 → 確認後產生檔案（不再呼叫模型）→ 下載（預設 1 小時失效，只有本人可下載）。

## 多則回答整合成一份報告

每則回答旁有「加入多則匯出」勾選框；勾選後畫面下方出現「已選 N / 5 則回答」與「匯出所選回答」。

- 上限 5 則（`planner.MAX_ANSWERS`，由 `/config` 的 `max_answers` 告知頁面）；滿 5 則時其餘勾選框反灰並提示，後端同樣拒絕第 6 則（422）。所選回答合計超過 4 萬字回 413。
- 一律經語言模型重新整理成一份報告：依主題編排；各回答說法不一致時並列標示、不自行擇一（提示詞 `MULTI_RULES`）。
- 各回答的來源編號都從 `[S1]` 起算，合併前會改成整份報告共用的編號 `[1]…`；同一份來源只編一個號，清單裡沒有的標記改成 `[Q<第幾則>-S<n>]`（`planner.merge_answers`）。
- 沒有來源資料的回答（頁面重新整理後復原的歷史回答、OpenClaw 聊天）會在對話框提醒「這些內容不會附來源」。
- 每人每小時另有較低的次數上限：`KM_EXPORT_MULTI_PLANS_PER_HOUR`（預設 4；單則仍是 `KM_EXPORT_PLANS_PER_HOUR`，預設 12）。
- 與單則共用同一項授權；API 向下相容（舊頁面仍只送 `answer`）。

## 元件

| 項目 | 位置 |
|---|---|
| 服務 | `src/km_export/`（`app.py` 入口；`spec.py` 內容描述；`planner.py` 模型整理；`builders.py` 六種格式；`store.py` 暫存與限流） |
| 前端 | `frontend/km-export.<hash>.js`（來源 `frontend/zones/src/km-export.js`，由 `scripts/build_zone_demo.js` 產生） |
| 頁面引入 | WiFi 專區 `frontend/wifi8/index.html`（1 行）、示範專區頁（產生器自動加）、`frontend/chat-v2.html`（首頁助理 1 行） |
| 映像檔 | `deploy/dev-3030/docker/Dockerfile.km-export`（以 kb-web 映像檔為基底，不新增套件） |

格式：PPTX（python-pptx）、DOCX（直接寫 XML）、XLSX（openpyxl）、Markdown、CSV、HTML。沒有 PDF（伺服器沒有中文字型與 LibreOffice）。

## 服務設定（環境變數）

沿用 kb-web 的名稱與值（key 一律用 secret 掛入，不寫進 compose）：

- 身分驗證：`KM_INSTANCE_ID`、`KM_ENTRY_SESSION_SIGNING_KEY`、`KM_CONTROL_DB_URL`
- 語言模型：`KM_LLM_PRIMARY_MODEL`、`KM_LLM_PRIMARY_BASE_URL`、`KM_LLM_PRIMARY_API_KEY_ENV` 所指的金鑰變數、`KM_LLM_PRIMARY_TIMEOUT_SECONDS`（可用 `KM_EXPORT_LLM_*` 覆寫）
- 匯出：`KM_EXPORT_DIR`（暫存目錄，掛 volume 或 tmpfs）、`KM_EXPORT_TTL_SECONDS`（預設 3600）、`KM_EXPORT_MAX_FILES`（每人，預設 20）、`KM_EXPORT_PLANS_PER_HOUR`（預設 12）、`KM_EXPORT_BUILDS_PER_HOUR`（預設 40）

語言模型閘道在主機上（`host.docker.internal:18080`），容器必須加 `--add-host host.docker.internal:host-gateway`（compose 的 `extra_hosts`），否則會連不到而回「語言模型暫時無法使用」。

DA40 實際啟動指令（2026-10-28 部署，環境檔 `~/.km-control/km-export-da40.env` 由 `km-da40-web-1` 的設定複製，權限 600）：

```bash
docker run -d --name km-export-da40 --restart unless-stopped --network km-control-private \
  --add-host host.docker.internal:host-gateway --env-file ~/.km-control/km-export-da40.env \
  --read-only --tmpfs /tmp --tmpfs /export:size=512m,mode=1777 --memory 2g --cpus 1 \
  --cap-drop ALL --security-opt no-new-privileges km-export:ddef899
```

TEST 與 DA40 各需一個服務（各自的 `KM_INSTANCE_ID` 與控制資料庫）。服務要加入 `km-control-private`（連控制資料庫）與 nginx 所在的網路，並設記憶體上限。**只跑 1 個 worker**（限流在程序內）。

## 上線步驟

1. 建映像檔、起服務（此時沒有任何流量進來）。
2. nginx：在 `location /api/` 之前加 `location /api/export/ { proxy_pass http://<km-export 服務>:8000; }`。TEST 與 DA40 用 `km_instance_route` 的 map 各導到自己的服務。先備份設定、`nginx -t`、再 reload。
3. 用測試帳號驗證：未授權 → `/config` 為 `enabled:false` 且 `/plan` 回 403；管理員授權後 → 能走完整流程；撤銷後立即失效。
4. 部署前端：先放新的 `km-export.<hash>.js`，再換 `chat-v2.html`、示範專區頁、最後才是 `wifi8/index.html`（動到 WiFi 專區頁，需負責人同意）。服務不存在時前端自動隱藏，順序錯了也不會壞。

## 回復

- 移除 `wifi8/index.html`、`chat-v2.html` 與示範頁的那一行 script，或還原備份；按鈕立即消失。
- 停掉服務、移除 nginx 那一段並 reload。`kb-web` 與所有現有功能不受影響，也沒有資料庫遷移要還原。

## 已知限制

- 只匯出文字、清單、表格；回答中的圖片不會放進檔案。
- 內容經語言模型重新整理，每個檔案開頭或結尾都有「由 AI 整理、請對照來源」的提示。
- 限流在單一程序內；重啟服務會重置計數。
- 匯出消耗與聊天共用的語言模型額度；額度不足時畫面會顯示「語言模型暫時無法使用」。
