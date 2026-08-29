# Chunk 檢視功能開發報告

## 一、功能目的

`Chunk 檢視` 是系統管理頁的一個獨立分頁，用來檢視文件在攝入後的切塊結果，並同時對照：

- chunk 文字內容
- chunk 所對應的原圖資產
- chunk 的來源檔與章節資訊
- 修改歷史與版本回復

這個功能的設計目標有三個：

1. 讓管理者可以直接檢查文件切塊是否合理
2. 讓 Excel / 報告類文件的原圖可以被還原查看
3. 讓使用者能直接在 chunk 層級做修正，並重新攝入到 Neo4j / QDrant

---

## 二、核心設計原理

### 1. QDrant 只負責檢索，不存圖片本體

QDrant 主要保存：

- chunk 文字
- 文件名稱
- chunk 序號
- 章節標題
- 來源路徑
- 圖片引用索引 `image_refs`

不直接保存：

- 圖片 binary
- 大量頁面快照
- base64 圖片字串作為主要儲存格式

圖片本體改由本地資產目錄保存，Chunk 檢視頁透過 API 讀取再顯示。

### 2. 原圖資產與 chunk 分離

在文件攝入時，Excel 內嵌圖片會先落盤到：

- `data/assets/<doc_name>/excel/<sheet>/image-xx.*`

chunk payload 只保留：

- `image_refs`

這樣可以確保：

- 向量庫保持輕量
- 圖片可以被原樣預覽
- 重新攝入時可以重建資產引用

### 3. 編輯來源檔，而不是只改 QDrant

chunk 修改的正確做法不是直接改 QDrant 裡某筆 chunk，而是：

1. 修改來源 markdown
2. 自動備份上一版
3. 重新攝入
4. 同步更新 Neo4j / QDrant / viewer

這樣可以避免：

- 圖片引用與文字內容不一致
- Neo4j 與 QDrant 不同步
- 重新 ingest 時被舊資料覆蓋

### 4. 版本化回復

每次編輯前，系統先建立一份版本備份：

- 原始來源檔副本
- chunk 當時內容快照
- 版本時間
- 修改原因

回復版本時不是只回寫單一 chunk，而是：

- 還原來源檔
- 重新攝入
- 讓 Neo4j / QDrant / 圖片資產一起回到同一版本

---

## 三、整體資料流

### 1. 文件上傳或 watch 攝入

流程如下：

1. 使用者在 Chunk 檢視頁上傳文件，或將檔案放入 watch 目錄
2. 後端依檔名判斷攝入模式
3. 轉成 markdown
4. 若是 Excel，額外抽出圖片與圖表資訊
5. 產生 chunk
6. 寫入 Neo4j
7. 寫入 QDrant
8. 寫入圖片資產到 `data/assets`
9. 前端透過 admin API 讀取 chunk 與圖片

### 2. Chunk 檢視

Chunk 檢視頁的資料來源是：

- `/admin/chunk-documents`
- `/admin/chunk-documents/{doc_name}/chunks`
- `/admin/chunk-assets/{asset_path}`
- `/admin/chunk-documents/{doc_name}/versions`

頁面會顯示：

- 文件清單
- chunk 文字
- chunk 原圖
- 文件版本歷史

### 3. Chunk 編輯

編輯流程如下：

1. 在 viewer 選擇某個 chunk
2. 修改 chunk 文字
3. 先做版本備份
4. 修改來源 markdown
5. 重建原圖資產
6. 重新 ingest
7. 更新 QDrant / Neo4j
8. 刷新 chunk 清單與版本清單

### 4. 版本回復

版本回復流程如下：

1. 選擇某個歷史版本
2. 還原來源檔
3. 重建原圖資產
4. 重新 ingest
5. 更新資料庫與 viewer

---

## 四、前端實作原理

### 1. ChunkViewerView.vue

前端頁面負責：

- 選擇文件
- 顯示 chunk 列表
- 顯示原圖
- 支援 chunk 編輯
- 支援版本回復
- 顯示成功 / 失敗提示

### 2. 資料刷新機制

儲存或回復後，前端會重新：

- 抓文件清單
- 抓 chunk 明細
- 抓版本歷史

這樣可以確保畫面顯示的是最新 ingest 結果，而不是舊快照。

### 3. 原圖顯示方式

前端不直接顯示 base64 圖片，而是：

- 透過 `<img src="/admin/chunk-assets/...">`
- 讓瀏覽器直接載入原圖檔

這樣的好處是：

- 可直接看完整原圖
- 不會被 base64 字串污染畫面
- 圖片可直接開新分頁查看

### 4. 互動提示

目前儲存與回復完成後，頁面會跳出提示視窗，讓使用者明確知道動作已完成。

---

## 五、後端實作原理

### 1. Chunk 資料 API

後端提供的管理 API 包含：

- `GET /admin/chunk-documents`
- `GET /admin/chunk-documents/{doc_name}/chunks`
- `GET /admin/chunk-documents/{doc_name}/versions`
- `POST /admin/chunk-documents/{doc_name}/chunks/{chunk_id}/edit`
- `POST /admin/chunk-documents/{doc_name}/versions/{version_id}/restore`
- `GET /admin/chunk-assets/{asset_path:path}`

### 2. 資產路徑解析

Chunk 原圖是透過本地檔案系統回傳，不是直接從 QDrant 讀圖。

系統會優先尋找可用的資產根目錄，例如：

- `KB_ASSETS_ROOT`
- `/home/da40_ai_gb10/knowledge-base/data/assets`
- `/app/data/assets`

這樣可以同時支援：

- 主機環境
- Docker runtime

### 3. 編輯與回復

後端編輯時會：

- 找到 chunk 對應的來源檔
- 建立版本備份
- 嘗試精準替換 chunk 內容
- 若無法精準替換，退回到 section-based fallback
- 重建 Excel 原圖資產
- 重新 ingest

回復時會：

- 還原版本備份
- 重建資產
- 重新 ingest

### 4. 為什麼不能只改 QDrant

因為 QDrant 是檢索層，不是來源層。

只改 QDrant 會造成：

- 來源 markdown 不一致
- Neo4j 不一致
- 原圖資產不一致
- 重新攝入時又被原始來源覆蓋

---

## 六、文件型態與原圖處理原理

### 1. Excel 文件

Excel 攝入時會：

- 轉成 markdown
- 抽出 worksheet 中的 embedded images
- 另存原圖到 assets 目錄
- 在 chunk 中保存 `image_refs`

### 2. 文字 chunk

chunk 只保存可檢索文字與索引資訊。

### 3. 原圖 viewer

viewer 透過 `image_refs` 對應到真實圖檔。

因此即使 chunk 被編輯，原圖仍可在資產目錄中保留，並透過 API 顯示。

---

## 七、使用到的工具與技術

### 1. 後端框架

- **FastAPI**
  - 提供 Chunk Viewer 管理 API
  - 提供 chunk / asset / version 讀取與編輯 API

- **Uvicorn**
  - 啟動 FastAPI 服務

### 2. 前端框架

- **Vue 3**
  - 建立 `/admin/chunks` UI
  - 管理文件清單、chunk 內容、圖片預覽、版本歷史

- **Vite**
  - 前端建置與打包

### 3. 向量資料庫與圖資料庫

- **QDrant**
  - 存 chunk 向量與 payload
  - 提供文件與 chunk 檢視的索引來源

- **Neo4j**
  - 存 Document / TextUnit / Entity / Relationship
  - 與 chunk 檢視共享來源資料

### 4. 文件轉換工具

- **MarkItDown**
  - 將 PDF / Excel / 其他格式轉成 Markdown

- **OpenPyXL**
  - 解析 Excel 檔
  - 抽取圖表與 embedded images

### 5. 圖片與資產管理

- **本地檔案系統**
  - 存放 `data/assets`
  - 存放原圖、頁面快照與 chunk 關聯資產

### 6. 容器與部署

- **Docker / Docker Compose**
  - 啟動 web、celery、neo4j、redis、nginx
  - 管理 runtime 與 volume 掛載

- **Nginx**
  - 反向代理 `/admin/chunk-*` 與其他 API
  - 提供前端 SPA 與管理頁

### 7. 開發與驗證工具

- `restart_kb.sh`
  - 重建前端 runtime
  - 重啟 KB 服務
  - 驗證 nginx / API / websocket / QDrant / Neo4j 狀態

- `curl`
  - 驗證 API 是否回 JSON
  - 驗證原圖 asset 是否能直接回傳

- `docker exec`
  - 檢查容器內檔案系統與 runtime 狀態

- `python3`
  - 用來做快速 smoke test
  - 驗證 chunk edit / restore / asset rebuild

---

## 八、主要開發成果

### 1. Chunk 檢視頁

已完成：

- 文件清單
- chunk 文字
- 原圖預覽
- 文件搜尋
- 上傳並攝入
- 編輯 chunk
- 版本回復

### 2. 原圖資產鏈路

已完成：

- Excel embedded image 落盤
- QDrant `image_refs`
- `/admin/chunk-assets` 原圖回傳

### 3. 編輯與回復鏈路

已完成：

- 版本備份
- chunk 編輯
- section-based fallback
- 原圖資產重建
- 重新 ingest
- restore

---

## 九、目前限制與後續可再加強項目

### 目前限制

- PDF 頁面快照尚未完整做到
- OCR 裁切圖尚未全面導入
- 目前主要針對 Excel 圖片與 Markdown 文字 chunk 最完整

### 後續可再加強

- PDF 頁面快照 viewer
- chunk 差異比對 UI
- LLM 協助改寫 chunk
- 更細的 artifact index
- 只看有原圖的 chunk 篩選器

---

## 十、結論

Chunk 檢視頁不是單純的「看文字」功能，而是一個把：

- 文件來源
- chunk 內容
- 原圖資產
- 版本歷史
- 編輯與回復

整合在一起的管理工具。

它的核心價值是：

1. 讓知識庫內容可視化
2. 讓 chunk 修正可追溯
3. 讓圖片與文字保持一致
4. 讓資料庫更新可以被驗證

這套設計最重要的原則是：

- **QDrant 負責檢索**
- **來源檔負責真實內容**
- **資產檔負責原圖**
- **編輯與回復以版本化方式維持一致性**

