#!/bin/bash
# 知識庫壓力測試腳本
# 同時 10 個使用者，每個問不同問題

echo "=============================================="
echo "     知識庫壓力測試 - 10 並發使用者"
echo "=============================================="
echo ""

# 10 個真實問題（基於已攝入的 35 份文件）
declare -a QUESTIONS=(
    "NSA 和 SA 架構有什麼差別？"
    "LTE 參數規劃要注意什麼？"
    "WiFi 7 和 WiFi 6 的差異？"
    "設備借用流程是什麼？"
    "CI/CD Pipeline 流程？"
    "專案風險值怎麼計算？"
    "WPA3 安全強化要怎麼做？"
    "Mesh 網路如何設計？"
    "NR Beamforming 如何設定？"
    "實驗室安全規範有哪些？"
)

# 任務 ID 陣列
declare -a TASK_IDS=()

echo "🚀 提交 10 個搜尋任務..."
echo ""

for i in "${!QUESTIONS[@]}"; do
    QUESTION="${QUESTIONS[$i]}"
    TASK_NUM=$((i+1))
    
    echo "[$TASK_NUM/10] 提交: $QUESTION"
    
    RESPONSE=$(curl -s -X POST http://localhost:8000/search \
        -H "Content-Type: application/json" \
        -d "{\"query\":\"$QUESTION\",\"mode\":\"hybrid\"}")
    
    TASK_ID=$(echo $RESPONSE | python3 -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null)
    
    if [ -n "$TASK_ID" ]; then
        TASK_IDS+=("$TASK_ID")
        echo "   ✓ Task ID: $TASK_ID"
    else
        echo "   ✗ 提交失敗"
    fi
done

echo ""
echo "⏳ 等待所有任務完成..."
echo ""

START_TIME=$(date +%s)
COMPLETED=0
TOTAL=${#TASK_IDS[@]}

# 等待所有任務完成（最多 180 秒）
while [ $COMPLETED -lt $TOTAL ]; do
    COMPLETED=0
    for TASK_ID in "${TASK_IDS[@]}"; do
        STATUS=$(curl -s "http://localhost:8000/tasks/$TASK_ID" 2>/dev/null | \
            python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
        
        if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
            COMPLETED=$((COMPLETED + 1))
        fi
    done
    
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))
    
    echo -ne "\r  已完成: $COMPLETED/$TOTAL | 已等待: ${ELAPSED}秒"
    
    if [ $ELAPSED -gt 180 ]; then
        echo ""
        echo "⚠️  超過 180 秒，取消等待"
        break
    fi
    
    sleep 2
done

echo ""
echo ""
echo "=============================================="
echo "              測試結果"
echo "=============================================="
echo ""

# 收集結果
SUCCESS=0
FAIL=0
TOTAL_TIME=0

for i in "${!TASK_IDS[@]}"; do
    TASK_ID="${TASK_IDS[$i]}"
    QUESTION="${QUESTIONS[$i]}"
    
    RESULT=$(curl -s "http://localhost:8000/tasks/$TASK_ID" 2>/dev/null)
    
    STATUS=$(echo $RESULT | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
    MODE=$(echo $RESULT | python3 -c "import sys,json; print(json.load(sys.stdin).get('mode',''))" 2>/dev/null)
    ANSWER=$(echo $RESULT | python3 -c "import sys,json; d=json.load(sys.stdin); a=d.get('answer',''); print(a[:80]+'...' if a else 'N/A')" 2>/dev/null)
    
    if [ "$STATUS" = "completed" ]; then
        SUCCESS=$((SUCCESS + 1))
        echo "[✅ 成功] $QUESTION"
        echo "         模式: $MODE | 回答: $ANSWER"
    else
        FAIL=$((FAIL + 1))
        echo "[❌ 失敗] $QUESTION"
        echo "         狀態: $STATUS"
    fi
done

END_TIME=$(date +%s)
TOTAL_ELAPSED=$((END_TIME - START_TIME))

echo ""
echo "=============================================="
echo "              統計摘要"
echo "=============================================="
echo ""
echo "  總任務數:    $TOTAL"
echo "  成功:        $SUCCESS"
echo "  失敗:        $FAIL"
echo "  總耗時:      ${TOTAL_ELAPSED}秒"
echo "  平均回應:     $((TOTAL_ELAPSED / TOTAL))秒/任務"
echo ""
echo "=============================================="