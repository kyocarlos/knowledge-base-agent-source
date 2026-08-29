#!/bin/bash
# n8n 停止腳本
# 位置：/home/da40_ai_gb10/knowledge-base/n8n-workflow/stop-n8n.sh

if [ -f /tmp/n8n.pid ]; then
    PID=$(cat /tmp/n8n.pid)
    echo "停止 n8n (PID: $PID)..."
    kill $PID 2>/dev/null
    rm /tmp/n8n.pid
    echo "n8n 已停止"
else
    # 嘗試 killall
    pkill -f "n8n start" 2>/dev/null
    echo "n8n 已停止"
fi
