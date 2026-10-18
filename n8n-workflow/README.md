# Knowledge-Base n8n Workflow

## 📋 檔案說明

| 檔案 | 說明 |
|------|------|
| `knowledge-base-auto-upload.json` | n8n Workflow 匯入檔案 |
| `README.md` | 本說明檔案 |

---

## 🚀 快速開始

### Step 1: 安裝 n8n

```bash
# Docker 安裝
docker run -d \
  --name n8n \
  -p 5678:5678 \
  -v /home/da40_ai_gb10/n8n:/home/node/.n8n \
  -e N8N_BASIC_AUTH_ACTIVE=true \
  -e N8N_BASIC_AUTH_USER=admin \
  -e N8N_BASIC_AUTH_PASSWORD=n8n_password \
  n8nio/n8n
```

### Step 2: 匯入 Workflow

1. 開啟 n8n (http://localhost:5678)
2. 點擊左側 "Workflows"
3. 點擊右上角 "Import from File"
4. 選擇 `knowledge-base-auto-upload.json`

### Step 3: 設定監控資料夾

1. 開啟 Workflow
2. 雙擊 "Read Watch Folder" 節點
3. 修改路徑：
   ```
   /home/da40_ai_gb10/knowledge-base/data/watch
   ```
4. 點擊 "Save"

### Step 4: 啟動 Workflow

1. 點擊 "Activate" 按鈕（右上角）
2. Workflow 就會在每天 09:00 自動執行

---

## 🔧 Workflow 流程

```
Schedule Trigger (每天 09:00)
    ↓
Read Watch Folder (讀取監控資料夾)
    ↓
Filter New Files (過濾 24 小時內的新檔案)
    ↓
Upload to Knowledge-Base (呼叫上傳 API)
    ↓
Generate Summary (產生報告)
    ↓
Send Email Report (發送 Email)
    ↓
Save Log to File (保存日誌)
```

---

## ⚙️ 設定參數

### 排程時間（預設：每天 09:00）

修改 "Schedule Trigger" 節點：

| 表达式 | 執行時間 |
|--------|----------|
| `0 9 * * *` | 每天 09:00 |
| `0 * * * *` | 每小時 |
| `0 9,12,18 * * *` | 每天 09:00, 12:00, 18:00 |
| `0 9 * * 1-5` | 平日 09:00 |

### 監控資料夾（預設：/home/da40_ai_gb10/knowledge-base/data/watch）

```bash
# 建立監控資料夾
mkdir -p /home/da40_ai_gb10/knowledge-base/data/watch

# 設定權限
chmod 777 /home/da40_ai_gb10/knowledge-base/data/watch
```

### Email 通知

修改 "Send Email Report" 節點：
- `from`: 寄件者信箱
- `to`: 收件者信箱
- `subject`: 郵件主旨

### Knowledge-Base API

預設呼叫：
```
POST http://localhost:8000/upload
```

---

## 📁 日誌位置

```
/home/da40_ai_gb10/knowledge-base/logs/upload-{timestamp}.json
```

---

## 🔍 測試 Workflow

1. 將測試檔案放入監控資料夾：
   ```bash
   cp test.pdf /home/da40_ai_gb10/knowledge-base/data/watch/
   ```

2. 手動執行 Workflow：
   - 點擊 "Test Workflow" 按鈕
   - 觀察執行過程

3. 檢查結果：
   - Knowledge-Base 是否收到檔案
   - Email 是否發送
   - 日誌是否建立

---

## 🛠️ 常見問題

### Q: Workflow 沒有執行？
1. 確認已點擊 "Activate"
2. 檢查 n8n 容器是否運行中
3. 查看 n8n 執行歷史

### Q: 檔案沒有上傳？
1. 確認 Knowledge-Base API 正常運行 (`curl http://localhost:8000/health`)
2. 檢查檔案格式是否支援 (.pdf, .docx, .xlsx, .txt, .md)

### Q: Email 沒有發送？
1. 確認 SMTP 設定正確
2. 檢查垃圾郵件匣

---

## 📊 Workflow 狀態監控

在 Knowledge-Base 系統管理頁面可以看到：
- n8n 容器狀態
- Workflow 執行狀態
- 上傳日誌

---

## 🔗 相關資源

- [n8n 官方文件](https://docs.n8n.io)
- [n8n Workflow 匯入/匯出](https://docs.n8n.io/workflows.html#importing-and-exporting)
- [n8n Schedule Trigger](https://docs.n8n.io/nodes/n8n-nodes-base.scheduleTrigger/)
- [n8n HTTP Request](https://docs.n8n.io/nodes/n8n-nodes-base.httpRequest/)
