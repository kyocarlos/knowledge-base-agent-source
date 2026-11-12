# KM × CSIT:.patch／PNG 解析、四筆 Failed 工作恢復契約、Callback 可靠性與時間戳查核

日期:2026-11-12(所有時間為 UTC)
範圍:回覆 CSIT 補齊文件解析能力與失敗工作恢復契約。未重跑四筆 Failed,未改 CSIT DB、Outbox、Production、Shared Identity。

## 1. .patch Parser 驗收

- 以純文字讀取,**不套用、不執行**任何 Patch 或內容。
- 原 diff 完整保留。每個 hunk 前插入一行 `[file: 路徑]`,讓從長 diff 中間切出的 chunk 仍帶檔案路徑。每個檔案的新增/刪除/hunk 數另存表格。
- 同時支援 `.patch` 與 `.diff`,v2 路由(KM-ING)與文件庫路由(KM-DOC,即 KM-DOC-000024 走的路由)都適用。
- 防護:大小與字元上限、非 UTF-8 → `CORRUPT_FILE`、含 NUL 的二進位 → `CORRUPT_FILE`、`#!` 腳本或 zip → `MALWARE_DETECTED`、`MZ`/ELF 可執行檔 → `MALWARE_DETECTED`、空白內容 → `EMPTY_EXTRACTION`。以上都不會建立任何索引。
- 回報:`method=Text`、`ocrUsed=false`、`sourceFormat=patch`、實際 `chunkCount`。
- 驗收:測試內含 `system("touch /tmp/must-not-run")` 的 patch,確認內容被保留而未被執行。

## 2. PNG OCR／Vision 真實處理結果

流程(v2 路由,圖片格式 png/jpg/jpeg/gif/bmp/tif/tiff/webp):

1. 先檢查內容與副檔名一致(PNG 副檔名但內容是 JPEG → `MALWARE_DETECTED`;不是圖片 → `CORRUPT_FILE`)、像素上限(超過 → `PARSER_LIMIT_EXCEEDED`),再沿用既有的大小與 SHA256 檢查。
2. 重新編碼成單純 RGB PNG(去除透明度、動畫、中繼資料),交給 **Tesseract OCR**(繁體中文+英文)以子行程、參數陣列方式執行,有逾時。
3. OCR 可讀出足夠文字(預設 20 個有意義字元)→ `method=OCR`、`ocrUsed=true`,**不送 Vision**。
4. 文字太少(照片、圖表、示意圖)→ 才呼叫既有的 LLM 閘道做 Vision。結果標示為描述,不是逐字轉錄:只有 Vision → `method=Visual`、`ocrUsed=false`;OCR 與 Vision 都有內容 → `method=Mixed`、`ocrUsed=true`;`warnings` 會寫明「文字為模型描述,非逐字轉錄」。
5. 完全讀不到 → Failed `EMPTY_EXTRACTION`,不建立索引、不產生假 Chunk。Vision 服務故障 → 可重試的 `VISION_UNAVAILABLE`,不會變成空的 Completed。
6. 圖片內的文字一律當作內容描述,Vision 提示詞明確要求不執行圖中的任何指令。

實測(在新版 worker 映像內,以真實元件執行):

| 輸入 | 結果 |
|---|---|
| 含中英文的文字截圖 | `method=OCR`、`ocrUsed=true`、約 0.2 秒;辨識出「錯誤 0x80070057 : 參數不正確」「AP-7300」「2.4.1」「5GHz 80MHz」「1.2 Gbps」 |
| 無文字的漸層圖 | OCR 無文字 → 呼叫 Vision → `method=Visual`、`ocrUsed=false`,產出圖像描述與警告 |

已知限制(照實說明):Tesseract 對繁體中文有少量誤辨(測試中「韌體」讀成「惑體」、「吞吐量」讀成亂碼)。數字與英文型號辨識良好。若要更高的中文辨識品質,需要另評估專用中文 OCR 或以 Vision 逐字轉錄,這會讓圖片內容送到 LLM 閘道,需要 CSIT 與 KM 共同決定。

## 3. 四筆 Failed 工作的安全恢復方案

### 現況(唯讀查詢)

| 工作 | 檔案 | 狀態 | 原因 | 歷史 Callback |
|---|---|---|---|---|
| KM-ING-000017 | 螢幕擷取畫面…png | Failed | UNSUPPORTED_FORMAT(當時無 OCR/Vision) | Processing、Failed 皆 Delivered |
| KM-ING-000018 | 同上 | Failed | 同上 | 同上 |
| KM-ING-000020 | 同上 | Failed | 同上 | 同上 |
| KM-DOC-000024 | p2-case-delete-review.patch | Failed | UNSUPPORTED_DOCUMENT_FORMAT | Processing、Failed 皆 Delivered |

四筆都在下載之前就失敗,沒有 checkpoint、沒有 Qdrant 點。三筆 PNG 是三個不同 EventId、相同內容(同一個檔案),恢復後會是三份獨立文件;若 CSIT 只想要一份,請在恢復前決定。

### 現有機制與缺口

- KM 現有 operator `resume` 只涵蓋 v1 ingestion job(要求管理員、身分比對、Failed 且無進行中 Callback、寫稽核事件、狀態回 Accepted)。**v2 與文件庫工作沒有對應指令。**
- KM 重新處理時會再送 `Processing` Callback。**CSIT 現行狀態機不允許 Failed 之後再收到 Processing/Completed**,所以只在 KM 端恢復,CSIT 仍會拒絕或忽略,雙方狀態會不一致。

### 最小跨系統恢復契約(建議)

原則:同一 EventId、同一 KM Job、同一 CSIT Job;歷史 Callback 與失敗紀錄保留;不新增 Job。

**KM 端(KM 負責實作與測試)**

1. 新增 v2/文件庫 operator `resume`,條件比照 v1:管理員身分、`event_id`/文件/版本完整比對、Job 為終態 Failed、無進行中 Callback、無 lease;並限制失敗碼只能是 `UNSUPPORTED_FORMAT`、`UNSUPPORTED_DOCUMENT_FORMAT` 這類「KM 能力不足」的碼,且 KM 目前版本確實支援該副檔名。
2. 在同一交易內寫稽核事件(操作者、原因、前一狀態、前一組 Callback、時間),Job 狀態改回 `Accepted`,`attempt_count` 保留並遞增,另記 `recovery_id`(新 UUID)與 `recovery_attempt`(第幾次恢復)。
3. 之後所有 Callback 帶 `recovery: { recoveryId, attempt }`,Callback 序號持續遞增,`callbackId` 各自唯一。
4. 不重複:Qdrant 寫入本來就先依來源身分刪除、再用確定性點 ID 寫入(同一份內容重做結果相同);Job 不新增;結果 JSON 以最後一次成功為準,失敗歷史留在 Callback 與稽核紀錄。

**CSIT 端(需 CSIT 修改)**

1. 狀態機新增一條受控轉換:`Failed → Processing`,**僅當** Callback 帶有效的 `recovery.recoveryId`,且該 EventId 目前為 Failed。沒有 `recovery` 的 Failed 後 Callback 仍維持拒絕(409)。
2. 以 `(eventId, recoveryId)` 做冪等:同一 recoveryId 重送回 204 且不重複建立狀態。
3. 保留原 Failed 紀錄(狀態歷史 append-only,不覆寫),Outbox 顯示為「恢復處理中」,之後 `Completed` 或再次 `Failed`。
4. 較舊的 attempt 或序號較小的遲到 Callback 一律忽略(回 204 不改狀態)。
5. 不得因此建立新的 Outbox 或新的 Job。

**CSIT 測試要求**

- 無 `recovery` 的 Failed→Processing:409。
- 有 `recovery` 的 Failed→Processing→Completed:204,Outbox 最終 Completed,歷史保留 Failed。
- 同一 `recoveryId` 重送:204,不產生第二筆狀態。
- 遲到的舊 Failed Callback 不會覆蓋已恢復的狀態。
- 缺少 `csit.km.status.write` scope:403。
- 恢復中再度 Failed:狀態回 Failed,可再次恢復(新的 `recoveryId`)。

**執行順序**:CSIT 先上線轉換規則並通過契約測試 → KM 上線 `resume` 並完成隔離測試 → 由操作員逐筆(先一筆 KM-DOC-000024)恢復並由雙方核對 → 其餘三筆。**在 CSIT 確認之前,KM 不會執行任何恢復。**

替代方案:若 CSIT 不想改狀態機,只能由 CSIT 以新的 EventId 重新派送同一份文件,這會產生新的 KM Job,與本次「保留原 EventId、Job」的要求衝突,所以不建議。

## 4. CSIT 是否需要最小程式修改

需要。僅限上面「CSIT 端」五點(受控的 Failed→Processing 轉換、`recoveryId` 冪等、歷史保留、遲到 Callback 忽略、契約測試)。不需要改授權、不需要新 scope、不需要改 Idempotency-Key 規則。

## 5. Callback 重試與時間戳查核

### 重試政策(以 14 個測試實際驗證,測試用 CSIT 替身與隔離 PostgreSQL)

| 失敗類型 | 處置 |
|---|---|
| HTTP 500／502／503、429 | 可重試 |
| 逾時、連線失敗、連線被拒 | 可重試 |
| 400、401、403、404、409 | 永久失敗,不重試(401/403 回報 `CSIT_AUTH_FORBIDDEN`) |

- 重試間隔 10、60、300、900 秒,共 5 次嘗試,**總視窗約 21 分鐘**。重試時送的是同一個 Callback(同 `callbackId`、同 Idempotency-Key),分析不會重跑。
- 同一個 Job 的後一個 Callback 會等前一個送完,不會超車(Processing 沒送出前,Completed 不會先到)。
- **缺口一**:CSIT 中斷超過約 21 分鐘,即使原因是暫時的,Callback 也會變成終態 Failed,之後不會自動補送。(Gate 1 的兩筆 Callback 就是因授權被拒而進入終態 Failed。)
- **缺口二**:401 一律視為永久失敗。若是 token 過期這類暫時情形,也不會重試。

### 建議的最小查核與受控補送

1. **查核**(唯讀):定期列出「Pending／Delivering 超過 N 分鐘」與「Failed 且錯誤碼屬暫時性(`CSIT_HTTP_ERROR`、`CSIT_CALLBACK_NETWORK_ERROR`、`CALLBACK_FAILED`)」的 Callback,附 callbackId、種類、Job、嘗試次數、最後錯誤時間。
2. **受控補送**:新增 operator 指令,只能把「同一個 callbackId」從 Failed 改回 Pending,條件為原錯誤屬暫時性或授權已修正、之後的 Callback 尚未送出、寫稽核事件、需管理員;不建立新 Callback、不改 Job 狀態、不重跑分析。Gate 1 當時是手動做同樣的事,建議正式化並留稽核。
3. **延長視窗**:把重試間隔延長(例如再加 1800、3600 秒及更長),並讓間隔可由設定調整。
4. 這三項我還沒實作,需要你們同意方向後再做。

### KM-ING-000019 時間戳(原始值,全為 UTC)

| 事件 | 原始值 |
|---|---|
| Job 建立 | 2026-11-12 08:07:16.391016+00 |
| 開始處理(Processing Callback 的 startedAt) | 2026-11-12T08:07:17.881298Z |
| Qdrant checkpoint 完成 | 2026-11-12 08:07:34.448185+00 |
| 結果的 `indexedAt` | 2026-11-12T08:07:34Z |
| Job `completed_at`(= Completed Callback 的 completedAt) | 2026-11-12T08:07:34.462488Z |
| Completed Callback 建立 | 2026-11-12 08:07:34.463973+00 |
| Completed Callback 送達(KM 收到 204) | 2026-11-12 08:07:35.940119+00 |

判定:
- 順序正確:索引寫入 → checkpoint → Job 完成 → Callback 建立 → 送達,總差距小於 1.5 秒。
- `indexedAt` 只有秒精度,是因為輸出格式固定為 `YYYY-MM-DDTHH:MM:SSZ`(去掉小數秒),不是時鐘差異,也不是程式順序問題。實際取值時間在 Qdrant 寫入完成後、早於 checkpoint。
- KM 端只有一台主機,資料庫與程式皆用 UTC 儲存,主機時鐘為 NTP 同步(系統顯示時區 Asia/Taipei,不影響儲存值)。
- **KM 端沒有 CSIT 的接收時間**。若 CSIT 畫面顯示與上表差 8 小時,多半是 CSIT 顯示成本地時間(UTC+8)。請 CSIT 提供它對這兩筆 Callback 的原始接收時間(UTC)與原始儲存值,我再做逐欄比對。未憑推測修改任何時間。

## 6. KM DEV 部署與回歸測試證據


### Commit

分支 `agent/csit-patch-png-ocr-20261112`(基於 `670e7c8`),本機提交,尚未推送:

| Commit | 內容 |
|---|---|
| `19891a4` | .patch/.diff 純文字解析;圖片 OCR 優先、無文字才用 Vision;Dockerfile worker 安裝 Tesseract;real override 啟用圖片與 `csit.km.status.write` |
| `ac6737c` | Callback 重試矩陣測試 |
| `269a5c0` | `image_reader` 關閉 OCR 的語意修正與測試(**部署的程式碼 commit**) |

### Runtime／映像識別

| 項目 | 值 |
|---|---|
| 程式碼 commit | `269a5c0` |
| API 映像 | `km-csit-integration:269a5c0-ocr-20261112`,ID `sha256:f94dfb7080e3…` |
| Worker 映像 | `km-csit-worker:269a5c0-ocr-20261112`,ID `sha256:c259fac9cb0f…` |
| 前一版(可回復) | `670e7c8-clean-20261111`(API `sha256:6efff66be6a5…`、Worker `sha256:76b24de8232c…`) |
| 模式 | real,以 `csit-mode.sh reapply` 套用,未使用 `--force`;套用前進行中工作為 0 |
| 設定變更 | 新增 `KM_CSIT_IMAGES_ENABLED=1`、`KM_CSIT_VISION_ENABLED=1`(outbound scopes 已含 `csit.km.status.write`) |
| 備份 | 部署前的 `images.env`、override、state 已備份,回復方式為還原 `images.env` 後 reapply |

### 回歸測試

- 基準(部署前,670e7c8):522 通過、5 失敗、4 略過。
- 新版(269a5c0):**556 通過**、同樣 5 失敗、4 略過。多出的 34 個通過為本次新增測試(.patch 6 類情境、圖片 OCR/Vision/拒絕情境 11 項含真實 Tesseract、Callback 重試 14 項)。
- 5 個失敗在部署前就存在,都需要隔離環境沒有的外部資源:Neo4j 與 Timescale 真實連線測試各 1、區域專區授權選擇測試 3(需要正式資料)。與本次變更無關。

### Smoke Test(已部署的 worker 容器內)

- 旗標正確、`tesseract` 已安裝。
- 文字截圖:`method=OCR`、`ocrUsed=true`,約 0.2 秒,文字與型號 `AP-7300`、`0x80070057` 正確。
- 無文字圖片:OCR 無文字 → Vision,`method=Visual`、`ocrUsed=false`,附描述警告,約 3.4 秒。
- `.patch`:解析出檔案表格與 `[file: …]` 標註。
- Outbound token:Issuer、Audience、Client 正確,scope 含 `csit.km.status.write`。
- 部署後唯讀確認:KM-ING-000016、000019 仍為 Completed;000017、000018、000020、KM-DOC-000024 仍為 Failed(狀態與更新時間未變);所有 208 筆 Callback 皆為 Delivered;Worker 與 API 日誌無錯誤。

### 尚未驗證

- 尚未用真實 CSIT 派送新的 PNG 或 patch 做端對端。要驗證需 CSIT 以**新的 EventId** 送一筆(不是重送四筆 Failed);請 CSIT 確認後再送。
- 四筆 Failed 沒有動,等 CSIT 對第 3 節恢復契約回覆。

### 需要 CSIT 回覆的事項

1. 同意第 3 節的恢復契約,並排定 CSIT 端「受控 Failed→Processing 轉換」的修改與測試。
2. 三筆 PNG 內容相同,恢復時要保留三份還是只恢復一份。
3. 提供 KM-ING-000019 兩筆 Callback 在 CSIT 的原始接收時間(UTC)與儲存值,供時間戳比對。
4. 是否同意第 5 節的 Callback 查核、受控補送與延長重試視窗。
5. 圖片 Vision 會把圖片內容送到 KM 的 LLM 閘道(僅在 OCR 讀不到文字時),請確認可接受。
