#!/bin/bash
# n8n 啟動腳本（直接安裝版本）
# 位置：<project-root>/knowledge-base/n8n-workflow/start-n8n.sh

# n8n 設定
export N8N_DATA_DIR=<project-root>/n8n
export N8N_BASIC_AUTH_ACTIVE=true
export N8N_BASIC_AUTH_USER=admin
export N8N_BASIC_AUTH_PASSWORD=n8n_admin123
export N8N_HOST=0.0.0.0
export N8N_PORT=5678
export WEBHOOK_URL=http://localhost:5678/
export EXECUTIONS_DATA_SAVE_ON_ERROR=all
export EXECUTIONS_DATA_SAVE_ON_SUCCESS=all
export EXECUTIONS_DATA_SAVE_ON_TIMEOUT=true
export EXECUTIONS_DATA_PRUNE=true
export EXECUTIONS_DATA_MAX_AGE=7

# 日誌目錄
LOG_DIR=<project-root>/knowledge-base/logs
mkdir -p $LOG_DIR

# 啟動 n8n
echo "啟動 n8n..."
n8n start >> $LOG_DIR/n8n.log 2>&1 &
echo $! > /tmp/n8n.pid

echo "n8n 已啟動 (PID: $(cat /tmp/n8n.pid))"
echo "存取網址: http://localhost:5678"
echo "帳號: admin"
echo "密碼: n8n_admin123"
echo "日誌: $LOG_DIR/n8n.log"
