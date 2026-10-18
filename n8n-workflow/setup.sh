#!/bin/bash
# n8n 安裝與設定腳本
# 位置: /home/da40_ai_gb10/knowledge-base/n8n-workflow/setup.sh

set -e

echo "====================================="
echo "  Knowledge-Base n8n 自動上傳設定精靈"
echo "====================================="
echo ""

# 1. 建立監控資料夾
WATCH_FOLDER="/home/da40_ai_gb10/knowledge-base/data/watch"
LOG_FOLDER="/home/da40_ai_gb10/knowledge-base/logs"

echo "1. 建立資料夾..."
mkdir -p "$WATCH_FOLDER"
mkdir -p "$LOG_FOLDER"
chmod 777 "$WATCH_FOLDER"
chmod 777 "$LOG_FOLDER"
echo "   ✅ 監控資料夾: $WATCH_FOLDER"
echo "   ✅ 日誌資料夾: $LOG_FOLDER"
echo ""

# 2. 建立 n8n 設定檔
echo "2. 建立 n8n docker-compose.yml..."
cat > /home/da40_ai_gb10/knowledge-base/n8n-workflow/docker-compose.yml << 'EOF'
version: '3'
services:
  n8n:
    image: n8nio/n8n
    container_name: n8n
    restart: unless-stopped
    ports:
      - "5678:5678"
    environment:
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=admin
      - N8N_BASIC_AUTH_PASSWORD=n8n_admin123
      - N8N_HOST=localhost
      - N8N_PORT=5678
      - N8N_PROTOCOL=http
      - WEBHOOK_URL=http://localhost:5678/
      - EXECUTIONS_DATA_PRUNE=true
      - EXECUTIONS_DATA_MAX_AGE=7
    volumes:
      - /home/da40_ai_gb10/n8n:/home/node/.n8n
      - /home/da40_ai_gb10/knowledge-base/data/watch:/watch
      - /home/da40_ai_gb10/knowledge-base/logs:/logs
EOF
echo "   ✅ docker-compose.yml 已建立"
echo ""

# 3. 檢查 Docker
echo "3. 檢查 Docker 狀態..."
if command -v docker &> /dev/null; then
    echo "   ✅ Docker 已安裝"
    docker --version
else
    echo "   ⚠️  Docker 未安裝，請先安裝 Docker"
fi
echo ""

# 4. 顯示完成訊息
echo "====================================="
echo "  設定完成！"
echo "====================================="
echo ""
echo "下一步："
echo "1. 進入 n8n-workflow 目錄:"
echo "   cd /home/da40_ai_gb10/knowledge-base/n8n-workflow"
echo ""
echo "2. 啟動 n8n:"
echo "   docker-compose up -d"
echo ""
echo "3. 開啟瀏覽器:"
echo "   http://localhost:5678"
echo "   帳號: admin"
echo "   密碼: n8n_admin123"
echo ""
echo "4. 匯入 Workflow:"
echo "   - 點擊 Workflows"
echo "   - 點擊 Import from File"
echo "   - 選擇 simple-upload.json 或 knowledge-base-auto-upload.json"
echo ""
echo "5. 放入測試檔案到監控資料夾:"
echo "   cp test.pdf $WATCH_FOLDER/"
echo ""
echo "6. 點擊 Test Workflow 測試"
echo ""
