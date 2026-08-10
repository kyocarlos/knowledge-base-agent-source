#!/bin/bash
#===============================================================================
# 知識庫系統 - 啟動腳本 (優化版)
# 
# 優化設定：
#   - 6 個 Ollama 實例（DGX GB10 128GB VRAM 優化）
#   - 16 個 Celery Workers
#   - 16 個 FastAPI Workers
#   - 支援約 50-100 人同時使用
#
# 使用方式：./start.sh [command]
# 
# Commands:
#   start       啟動所有服務（預設）
#   stop        停止所有服務
#   restart     重啟所有服務
#   status      檢查服務狀態
#   test        執行快速測試
#   clean       清除所有容器和資料
#   help        顯示說明
#===============================================================================

set -e  # 遇到錯誤就停止

# 顏色設定
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 路徑設定
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FRONTEND_DIR="$PROJECT_DIR/frontend"
CONFIG_FILE="$PROJECT_DIR/config/config.yaml"

# ===== 高並發優化設定 =====
# 
# VRAM 分析：
#   gemma4:12b（較小模型）可提高單機並發與回應速度
#   128GB VRAM 可支撐更多實例或更高的上下文長度
#
# Workers 分析：
#   16 workers = 可同時處理 16 個任務
#   6 Ollama instances = 最多 6 個 LLM 請求並行
#   其他人排隊等待，適合 50-100 人同時使用

OLLAMA_BASE_PORT=11434
OLLAMA_INSTANCE_COUNT=6
OLLAMA_MODEL="gemma4:12b"

CELERY_SEARCH_CONCURRENCY=16
CELERY_INGEST_CONCURRENCY=1
FASTAPI_WORKERS=16

# 服務連接埠設定
REDIS_PORT=6379
NEO4J_HTTP_PORT=7474
NEO4J_BOLT_PORT=7687
FASTAPI_PORT=8000
FRONTEND_PORT=3000

# Neo4j 設定
NEO4J_USER="neo4j"
NEO4J_PASSWORD="change-me"
NEO4J_AUTH="$NEO4J_USER/$NEO4J_PASSWORD"

#===============================================================================
# 訊息函數
#===============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

#===============================================================================
# 檢查函數
#===============================================================================

check_command() {
    if ! command -v $1 &> /dev/null; then
        log_error "$1 未安裝，請先安裝後再執行"
        exit 1
    fi
}

check_docker() {
    if ! docker info &> /dev/null; then
        log_error "Docker 未運行，請先啟動 Docker"
        exit 1
    fi
}

#===============================================================================
# Ollama 實例管理
#===============================================================================

stop_ollama_instances() {
    log_info "停止所有 Ollama 實例..."
    # 停止所有 ollama serve 程序
    pkill -f "ollama serve" 2>/dev/null || true
    sleep 1
}

start_ollama_instances() {
    log_step "啟動 $OLLAMA_INSTANCE_COUNT 個 Ollama 實例"
    
    if ! command -v ollama &> /dev/null; then
        log_error "Ollama 未安裝，請從 https://ollama.ai 安裝"
        return 1
    fi
    
    # 先停止所有現有的實例
    stop_ollama_instances
    
    # 檢查模型是否存在
    log_info "檢查模型: $OLLAMA_MODEL..."
    
    if ! ollama list | grep -q "$OLLAMA_MODEL"; then
        log_warn "模型 $OLLAMA_MODEL 不存在，開始下載..."
        log_warn "約 8GB，下載可能需要幾分鐘"
        ollama pull $OLLAMA_MODEL
        log_success "模型下載完成"
    else
        log_success "模型 $OLLAMA_MODEL 已存在"
    fi
    
    # 啟動多個 Ollama 實例
    log_info "啟動 $OLLAMA_INSTANCE_COUNT 個 Ollama 實例..."
    
    for i in $(seq 1 $OLLAMA_INSTANCE_COUNT); do
        PORT=$((OLLAMA_BASE_PORT + i - 1))
        
        # 每個實例使用不同 port
        OLLAMA_HOST="0.0.0.0:$PORT" \
        nohup ollama serve > logs/ollama-$i.log 2>&1 &
        
        log_info "  實例 $i: localhost:$PORT (PID: $!)"
    done
    
    # 等待所有實例啟動
    sleep 5
    
    # 驗證至少有第一個實例正常運行
    if curl -s http://localhost:$OLLAMA_BASE_PORT/api/tags &> /dev/null; then
        log_success "已啟動 $OLLAMA_INSTANCE_COUNT 個 Ollama 實例"
        log_info "Ollama 實例範圍: $OLLAMA_BASE_PORT - $((OLLAMA_BASE_PORT + OLLAMA_INSTANCE_COUNT - 1))"
    else
        log_error "Ollama 實例啟動失敗"
        return 1
    fi
}

#===============================================================================
# 服務啟動函數
#===============================================================================

start_redis() {
    log_step "啟動 Redis"
    
    if docker ps --format '{{.Names}}' | grep -q "^kb-redis$"; then
        log_info "Redis 容器已在運行，跳過"
        return 0
    fi
    
    docker run -d \
        --name kb-redis \
        -p $REDIS_PORT:6379 \
        -v kb-redis-data:/data \
        redis:7-alpine \
        --appendonly yes
    
    log_success "Redis 已啟動 (port $REDIS_PORT)"
}

start_neo4j() {
    log_step "啟動 Neo4j"
    
    if docker ps --format '{{.Names}}' | grep -q "^kb-neo4j$"; then
        log_info "Neo4j 容器已在運行，跳過"
        return 0
    fi
    
    docker run -d \
        --name kb-neo4j \
        -p $NEO4J_HTTP_PORT:7474 \
        -p $NEO4J_BOLT_PORT:7687 \
        -e NEO4J_AUTH=$NEO4J_AUTH \
        -e NEO4J_PLUGINS='["apoc"]' \
        -v kb-neo4j-data:/data \
        -v kb-neo4j-logs:/logs \
        neo4j:latest
    
    log_success "Neo4j 已啟動 (HTTP: $NEO4J_HTTP_PORT, Bolt: $NEO4J_BOLT_PORT)"
    log_info "請訪問 http://localhost:$NEO4J_HTTP_PORT 登入"
    log_info "帳號: $NEO4J_USER / 密碼: $NEO4J_PASSWORD"
}

init_neo4j_schema() {
    log_step "初始化 Neo4j Schema"
    
    # 等待 Neo4j 就緒
    log_info "等待 Neo4j 啟動就緒..."
    sleep 5
    
    cd "$PROJECT_DIR"
    
    # 安裝必要的套件
    log_info "檢查並安裝相依套件..."
    pip install -q neo4j pyyaml
    
    # 執行 Schema 初始化
    log_info "執行 Schema 初始化..."
    python3 -m src.graphrag.neo4j_schema
    
    log_success "Neo4j Schema 初始化完成"
}

start_fastapi() {
    log_step "啟動 FastAPI (Workers: $FASTAPI_WORKERS)"
    
    # 檢查程序是否已運行
    if pgrep -f "uvicorn.*app.main:app" &> /dev/null; then
        log_info "FastAPI 已在運行，跳過"
        return 0
    fi
    
    cd "$PROJECT_DIR"
    
    # 安裝相依套件
    log_info "安裝 Python 相依套件..."
    pip install -q -r requirements.txt 2>/dev/null || true
    
    # 啟動 FastAPI（背景執行，16 workers）
    log_info "啟動 FastAPI server (workers: $FASTAPI_WORKERS)..."
    nohup uvicorn app.main:app \
        --host 0.0.0.0 \
        --port $FASTAPI_PORT \
        --workers $FASTAPI_WORKERS \
        --log-level info \
        > logs/fastapi.log 2>&1 &
    
    sleep 3
    
    # 檢查是否啟動成功
    if curl -s http://localhost:$FASTAPI_PORT/health &> /dev/null; then
        log_success "FastAPI 已啟動 (port $FASTAPI_PORT, workers: $FASTAPI_WORKERS)"
        log_info "API 文件：http://localhost:$FASTAPI_PORT/docs"
    else
        log_error "FastAPI 啟動失敗，請檢查 logs/fastapi.log"
        return 1
    fi
}

start_celery() {
    log_step "啟動 Celery Workers (search: $CELERY_SEARCH_CONCURRENCY, ingest: $CELERY_INGEST_CONCURRENCY)"
    
    # 檢查程序是否已運行
    if pgrep -f "celery.*worker.*-Q search" &> /dev/null && pgrep -f "celery.*worker.*-Q ingest" &> /dev/null; then
        log_info "Celery Workers 已在運行，跳過"
        return 0
    fi
    
    cd "$PROJECT_DIR"
    
    # 建立 logs 目錄
    mkdir -p logs
    
    # 啟動 Search Worker（多工，處理搜尋任務）
    log_info "啟動 Celery Search Worker (concurrency: $CELERY_SEARCH_CONCURRENCY)..."
    nohup celery -A src.web_api.tasks:celery_app worker \
        --loglevel=info \
        --concurrency=$CELERY_SEARCH_CONCURRENCY \
        -Q search \
        > logs/celery-search.log 2>&1 &

    # 啟動 Ingest Worker（單工，避免多檔同時攝入互搶 Neo4j/QDrant/index.md）
    log_info "啟動 Celery Ingest Worker (concurrency: $CELERY_INGEST_CONCURRENCY)..."
    nohup celery -A src.web_api.tasks:celery_app worker \
        --loglevel=info \
        --concurrency=$CELERY_INGEST_CONCURRENCY \
        -Q ingest \
        > logs/celery-ingest.log 2>&1 &
    
    sleep 3
    
    # 檢查是否啟動成功
    if pgrep -f "celery.*worker.*-Q search" &> /dev/null && pgrep -f "celery.*worker.*-Q ingest" &> /dev/null; then
        log_success "Celery Workers 已啟動 (search: $CELERY_SEARCH_CONCURRENCY, ingest: $CELERY_INGEST_CONCURRENCY)"
        log_info "可用佇列：search, ingest（ingest 單工）"
    else
        log_error "Celery Workers 啟動失敗，請檢查 logs/celery-search.log / logs/celery-ingest.log"
        return 1
    fi
}

start_frontend() {
    log_step "啟動 Vue 前端"
    
    # 檢查是否已運行
    if curl -s http://localhost:$FRONTEND_PORT &> /dev/null; then
        log_info "前端已在運行，跳過"
        return 0
    fi
    
    # 檢查 Node.js
    if ! command -v npm &> /dev/null; then
        log_error "Node.js 未安裝，前端無法啟動"
        log_info "請從 https://nodejs.org 安裝 Node.js"
        return 1
    fi
    
    cd "$FRONTEND_DIR"
    
    # 安裝相依套件
    log_info "安裝前端相依套件..."
    npm install --silent 2>/dev/null || npm install
    
    # 啟動 Vite 開發伺服器（背景執行）
    log_info "啟動前端開發伺服器..."
    nohup npm run dev > ../logs/frontend.log 2>&1 &
    
    sleep 5
    
    # 檢查是否啟動成功
    if curl -s http://localhost:$FRONTEND_PORT &> /dev/null; then
        log_success "Vue 前端已啟動 (port $FRONTEND_PORT)"
        log_info "請訪問：http://localhost:$FRONTEND_PORT"
    else
        log_error "前端啟動失敗，請檢查 logs/frontend.log"
        return 1
    fi
}

#===============================================================================
# 服務停止函數
#===============================================================================

stop_services() {
    log_step "停止所有服務"
    
    # 停止 Python 程序
    log_info "停止 FastAPI 和 Celery..."
    pkill -f "uvicorn.*app.main:app" 2>/dev/null || true
    pkill -f "celery.*worker" 2>/dev/null || true
    
    # 停止 Ollama 實例
    log_info "停止所有 Ollama 實例..."
    pkill -f "ollama serve" 2>/dev/null || true
    
    # 停止 Docker 容器
    log_info "停止 Docker 容器..."
    docker stop kb-redis 2>/dev/null || true
    docker stop kb-neo4j 2>/dev/null || true
    
    log_success "所有服務已停止"
}

#===============================================================================
# 服務狀態檢查
#===============================================================================

check_status() {
    log_step "檢查服務狀態"
    
    echo ""
    echo -e "  ${BLUE}服務${NC}              ${BLUE}狀態${NC}          ${BLUE}連接埠/設定${NC}"
    echo -e "  ${BLUE}────────────────────────────────────────────────────────────${NC}"
    
    # Redis
    if docker ps --format '{{.Names}}' | grep -q "^kb-redis$"; then
        echo -e "  Redis               ${GREEN}運行中${NC}        port $REDIS_PORT"
    else
        echo -e "  Redis               ${RED}未運行${NC}        port $REDIS_PORT"
    fi
    
    # Neo4j
    if docker ps --format '{{.Names}}' | grep -q "^kb-neo4j$"; then
        echo -e "  Neo4j               ${GREEN}運行中${NC}        HTTP: $NEO4J_HTTP_PORT, Bolt: $NEO4J_BOLT_PORT"
    else
        echo -e "  Neo4j               ${RED}未運行${NC}        HTTP: $NEO4J_HTTP_PORT, Bolt: $NEO4J_BOLT_PORT"
    fi
    
    # Ollama Instances
    OLLAMA_RUNNING=0
    for i in $(seq 1 $OLLAMA_INSTANCE_COUNT); do
        PORT=$((OLLAMA_BASE_PORT + i - 1))
        if curl -s http://localhost:$PORT/api/tags &> /dev/null; then
            OLLAMA_RUNNING=$((OLLAMA_RUNNING + 1))
        fi
    done
    if [ $OLLAMA_RUNNING -eq $OLLAMA_INSTANCE_COUNT ]; then
        echo -e "  Ollama (${OLLAMA_INSTANCE_COUNT} instances) ${GREEN}運行中${NC}   ports $OLLAMA_BASE_PORT-$((OLLAMA_BASE_PORT + OLLAMA_INSTANCE_COUNT - 1))"
    else
        echo -e "  Ollama (${OLLAMA_INSTANCE_COUNT} instances) ${YELLOW}部分運行${NC}  $OLLAMA_RUNNING/$OLLAMA_INSTANCE_COUNT"
    fi
    
    # FastAPI
    if curl -s http://localhost:$FASTAPI_PORT/health &> /dev/null; then
        echo -e "  FastAPI             ${GREEN}運行中${NC}        port $FASTAPI_PORT, workers: $FASTAPI_WORKERS"
    else
        echo -e "  FastAPI             ${RED}未運行${NC}        port $FASTAPI_PORT"
    fi
    
    # Celery
    if pgrep -f "celery.*worker" &> /dev/null; then
        echo -e "  Celery Worker       ${GREEN}運行中${NC}        concurrency: $CELERY_CONCURRENCY"
    else
        echo -e "  Celery Worker       ${RED}未運行${NC}        concurrency: $CELERY_CONCURRENCY"
    fi
    
    # Frontend
    if curl -s http://localhost:$FRONTEND_PORT &> /dev/null; then
        echo -e "  Vue Frontend        ${GREEN}運行中${NC}        port $FRONTEND_PORT"
    else
        echo -e "  Vue Frontend        ${RED}未運行${NC}        port $FRONTEND_PORT"
    fi
    
    echo ""
}

#===============================================================================
# 快速測試
#===============================================================================

run_tests() {
    log_step "執行快速測試"
    
    echo ""
    log_info "1. 健康檢查..."
    curl -s http://localhost:$FASTAPI_PORT/health | python3 -m json.tool 2>/dev/null || echo "失敗"
    
    echo ""
    log_info "2. 系統狀態..."
    curl -s http://localhost:$FASTAPI_PORT/stats | python3 -m json.tool 2>/dev/null || echo "失敗"
    
    echo ""
    log_info "3. 提交測試任務..."
    RESPONSE=$(curl -s -X POST http://localhost:$FASTAPI_PORT/search \
        -H "Content-Type: application/json" \
        -d '{"query": "測試問題：GraphRAG是什麼？", "mode": "basic"}')
    
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
    
    TASK_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null)
    
    if [ -n "$TASK_ID" ] && [ "$TASK_ID" != "cached" ]; then
        echo ""
        log_info "4. 等待任務完成（8秒）..."
        sleep 8
        
        echo ""
        log_info "5. 查詢任務結果..."
        curl -s http://localhost:$FASTAPI_PORT/tasks/$TASK_ID | python3 -m json.tool 2>/dev/null || echo "失敗"
    fi
    
    echo ""
    log_info "6. 圖譜統計..."
    curl -s http://localhost:$FASTAPI_PORT/admin/graph-stats | python3 -m json.tool 2>/dev/null || echo "失敗"
    
    echo ""
    log_success "測試完成！"
}

#===============================================================================
# 清除所有資料
#===============================================================================

clean_all() {
    log_step "清除所有資料"
    
    read -p "確定要清除所有 Docker 容器和資料嗎？(y/N): " confirm
    
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        log_info "取消清除"
        return
    fi
    
    log_info "停止並移除所有容器..."
    docker stop kb-redis kb-neo4j 2>/dev/null || true
    docker rm kb-redis kb-neo4j 2>/dev/null || true
    
    log_info "停止所有 Ollama 實例..."
    pkill -f "ollama serve" 2>/dev/null || true
    
    log_info "移除資料卷..."
    docker volume rm kb-redis-data kb-neo4j-data kb-neo4j-logs 2>/dev/null || true
    
    log_info "清除日誌..."
    rm -f "$PROJECT_DIR/logs/"*.log
    
    log_success "清除完成"
}

#===============================================================================
# 顯示說明
#===============================================================================

show_help() {
    echo ""
    echo -e "${GREEN}知識庫系統 - 啟動腳本 (高並發優化版)${NC}"
    echo ""
    echo "使用方式：./start.sh [command]"
    echo ""
    echo -e "${YELLOW}優化設定：${NC}"
    echo "  - 6 個 Ollama 實例（DGX GB10 128GB VRAM）"
    echo "  - 16 個 Celery Workers"
    echo "  - 16 個 FastAPI Workers"
    echo "  - 預計可支援 50-100 人同時使用"
    echo ""
    echo -e "${YELLOW}指令：${NC}"
    echo "  start     啟動所有服務（預設）"
    echo "  stop      停止所有服務"
    echo "  restart   重啟所有服務"
    echo "  status    檢查服務狀態"
    echo "  test      執行快速測試"
    echo "  clean     清除所有容器和資料"
    echo "  help      顯示說明"
    echo ""
    echo -e "${YELLOW}服務URL：${NC}"
    echo "  Neo4j Browser    http://localhost:$NEO4J_HTTP_PORT"
    echo "  FastAPI Docs     http://localhost:$FASTAPI_PORT/docs"
    echo "  Vue Frontend     http://localhost:$FRONTEND_PORT"
    echo ""
    echo -e "${YELLOW}Ollama 實例：${NC}"
    echo "  6 個實例运行在 ports $OLLAMA_BASE_PORT - $((OLLAMA_BASE_PORT + OLLAMA_INSTANCE_COUNT - 1))"
    echo ""
    echo -e "${YELLOW}預設帳號：${NC}"
    echo "  Neo4j:  neo4j / $NEO4J_PASSWORD"
    echo ""
}

#===============================================================================
# 主程式
#===============================================================================

main() {
    # 建立必要的目錄
    mkdir -p "$PROJECT_DIR/logs"
    mkdir -p "$PROJECT_DIR/data/raw"
    mkdir -p "$PROJECT_DIR/data/markdown"
    
    # 解析指令
    COMMAND=${1:-start}
    
    case $COMMAND in
        start)
            log_step "啟動知識庫系統 (高並發模式)"
            
            check_docker
            start_redis
            start_neo4j
            init_neo4j_schema
            start_ollama_instances  # 改為啟動多個實例
            start_fastapi
            start_celery
            start_frontend
            
            echo ""
            log_success "============================================"
            log_success "  所有服務已啟動！"
            log_success "============================================"
            echo ""
            echo -e "  ${BLUE}Neo4j:${NC}       http://localhost:$NEO4J_HTTP_PORT"
            echo -e "  ${BLUE}FastAPI:${NC}    http://localhost:$FASTAPI_PORT/docs"
            echo -e "  ${BLUE}前端:${NC}       http://localhost:$FRONTEND_PORT"
            echo ""
            echo -e "  ${BLUE}Ollama:${NC}     $OLLAMA_INSTANCE_COUNT 個實例"
            echo -e "  ${BLUE}Workers:${NC}    Celery $CELERY_CONCURRENCY, FastAPI $FASTAPI_WORKERS"
            echo ""
            echo -e "  ${YELLOW}預計容量：${NC} 約 50-100 人同時使用"
            echo ""
            ;;
            
        stop)
            stop_services
            ;;
            
        restart)
            stop_services
            sleep 2
            $0 start
            ;;
            
        status)
            check_status
            ;;
            
        test)
            run_tests
            ;;
            
        clean)
            clean_all
            ;;
            
        help|--help|-h)
            show_help
            ;;
            
        *)
            log_error "未知指令: $COMMAND"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

main "$@"
