#!/bin/bash
#===============================================================================
# Knowledge Base 一鍵重啟腳本
# 用途: 只重啟 knowledge-base 自己的 Docker stack
# 這支腳本只管理 knowledge-base，不碰 AnythingLLM：
# - 不修改任何共用 nginx / 對外入口設定
# - 不停止宿主機上的 nginx 或其他共用服務
# - 不動 AnythingLLM 的服務、腳本、容器、QDrant 或 systemd
# - web:8000: FastAPI 容器內服務，由容器內 nginx 反向代理
# - redis / neo4j: 資料與任務服務
# - host.docker.internal:11434: 容器連到宿主機 Ollama
# - QDrant: 獨立容器 kb-qdrant，對外只在本機 6335
#===============================================================================

set -e

ROOT_DIR="/home/da40_ai_gb10/knowledge-base"
cd "$ROOT_DIR"
REPORT_ENV_FILE="$ROOT_DIR/config/report-ingest.env"
REPORT_ENV_EXAMPLE="$ROOT_DIR/config/report-ingest.env.example"

echo "=========================================="
echo "   Knowledge Base 系統重啟中..."
echo "=========================================="

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker 未安裝，無法啟動容器服務。"
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    echo "npm 未安裝，無法建置前端。"
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
else
    echo "找不到 docker compose。"
    exit 1
fi

load_env_file() {
    local env_file="$1"
    if [[ -f "$env_file" ]]; then
        echo "  • 載入 $(basename "$env_file")"
        set -a
        # shellcheck disable=SC1090
        . "$env_file"
        set +a
    fi
}

ensure_report_env_file() {
    if [[ -n "${KB_REPORT_DB_PASSWORD:-}" ]]; then
        return 0
    fi

    if [[ -f "$REPORT_ENV_FILE" ]]; then
        echo "  ❌ $REPORT_ENV_FILE 存在，但未設定 KB_REPORT_DB_PASSWORD"
        echo "     請修正該檔案，或刪除後重新執行讓腳本自動建立。"
        exit 1
    fi

    if [[ ! -f "$REPORT_ENV_EXAMPLE" ]]; then
        echo "  ❌ 缺少 KB_REPORT_DB_PASSWORD，且找不到 $REPORT_ENV_EXAMPLE"
        echo "     請先手動建立 $REPORT_ENV_FILE 或 export KB_REPORT_DB_PASSWORD 後再執行。"
        exit 1
    fi

    local generated_password
    if command -v openssl >/dev/null 2>&1; then
        generated_password=$(openssl rand -hex 24)
    elif command -v python3 >/dev/null 2>&1; then
        generated_password=$(python3 - <<'PY'
import secrets
print(secrets.token_hex(24))
PY
        )
    else
        echo "  ❌ 無法產生 KB_REPORT_DB_PASSWORD，請先安裝 openssl 或 python3，或手動設定環境變數。"
        exit 1
    fi

    install -m 600 "$REPORT_ENV_EXAMPLE" "$REPORT_ENV_FILE"
    sed -i "s|^KB_REPORT_DB_PASSWORD=.*|KB_REPORT_DB_PASSWORD='$generated_password'|" "$REPORT_ENV_FILE"
    export KB_REPORT_DB_PASSWORD="$generated_password"
    echo "  ✅ 已自動建立 $(basename "$REPORT_ENV_FILE")"
}

load_env_file ".env"
load_env_file "$REPORT_ENV_FILE"
ensure_report_env_file

check_websocket_proxy() {
    local auth_token
    auth_token=$(docker exec kb-web python3 -c "from src.web_api import load_openclaw_chat_config; print(load_openclaw_chat_config().get('authToken', ''))" 2>/dev/null | tr -d '\r\n')

    if [[ -z "$auth_token" ]]; then
        echo "  ⚠️  無法取得 WebSocket 驗證 token，略過 websocket smoke test"
        return 0
    fi

    if docker exec kb-web python3 - "$auth_token" <<'PY'
import base64
import hashlib
import json
import secrets
import socket
import ssl
import struct
import sys

host = "nginx"
port = 443
path = "/ws"
auth_token = sys.argv[1]

def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise RuntimeError("socket closed unexpectedly")
        data += chunk
    return data

def read_http_response(sock):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data.decode("utf-8", errors="replace")

def send_ws_text(sock, text):
    payload = text.encode("utf-8")
    mask = secrets.token_bytes(4)
    first = 0x81
    length = len(payload)
    header = bytearray([first])
    if length < 126:
        header.append(0x80 | length)
    elif length < (1 << 16):
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes(header) + mask + masked)

def read_ws_message(sock):
    while True:
        first_two = recv_exact(sock, 2)
        fin = first_two[0] & 0x80
        opcode = first_two[0] & 0x0F
        masked = first_two[1] & 0x80
        length = first_two[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", recv_exact(sock, 8))[0]
        mask = recv_exact(sock, 4) if masked else b""
        payload = recv_exact(sock, length) if length else b""
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 0x8:
            raise RuntimeError("websocket closed by server")
        if opcode == 0x9:
            pong = bytearray([0x8A])
            if len(payload) < 126:
                pong.append(len(payload))
            else:
                pong.append(126)
                pong.extend(struct.pack("!H", len(payload)))
            sock.sendall(bytes(pong) + payload)
            continue
        if opcode == 0x1:
            return payload.decode("utf-8", errors="replace")
        if opcode == 0x2:
            return payload
        if not fin:
            continue

ctx = ssl._create_unverified_context()
raw_sock = socket.create_connection((host, port), timeout=10)
sock = ctx.wrap_socket(raw_sock, server_hostname=host)
key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
request = (
    f"GET {path} HTTP/1.1\r\n"
    f"Host: {host}\r\n"
    "Upgrade: websocket\r\n"
    "Connection: Upgrade\r\n"
    f"Sec-WebSocket-Key: {key}\r\n"
    "Sec-WebSocket-Version: 13\r\n"
    "\r\n"
)
sock.sendall(request.encode("ascii"))
response = read_http_response(sock)
if "101 Switching Protocols" not in response:
    raise RuntimeError(f"websocket handshake failed: {response.splitlines()[0] if response else 'empty response'}")

send_ws_text(sock, json.dumps({"type": "auth", "token": auth_token}, ensure_ascii=False))
message = read_ws_message(sock)
try:
    payload = json.loads(message)
except Exception as exc:
    raise RuntimeError(f"unexpected websocket payload: {message[:200]}") from exc

if payload.get("type") == "event" and payload.get("event") == "connect.challenge":
    print("WS OK")
else:
    raise RuntimeError(f"unexpected websocket payload: {payload}")
PY
    then
        echo "  ✅ WebSocket proxy smoke test 通過"
    else
        echo "  ⚠️  WebSocket proxy smoke test 失敗，請檢查 logs/fastapi.log 與 nginx 日誌"
    fi
}

echo ""
echo "[0/4] 檢查宿主機 Ollama..."
if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null; then
    echo "  ✅ Ollama 11434 正常"
else
    echo "  ⚠️  Ollama 11434 未回應；攝入流程的 LLM 萃取會失敗"
fi

# QDrant 只給 knowledge-base 使用，名稱與 host port 都和 AnythingLLM 分開。
if docker container inspect kb-qdrant >/dev/null 2>&1; then
    echo "[0/4] 啟動既有 kb-qdrant 容器..."
    docker start kb-qdrant >/dev/null 2>&1 || true
    docker update --restart unless-stopped kb-qdrant >/dev/null 2>&1 || true
else
    echo "[0/4] 建立 kb-qdrant 容器..."
    docker run -d --name kb-qdrant --restart unless-stopped -p 6335:6333 -p 6336:6334 qdrant/qdrant:latest >/dev/null
fi

# 只清理 knowledge-base 自己的容器，不會碰 AnythingLLM 的任何容器。
docker rm -f kb-web kb-celery-search kb-celery-ingest kb-celery-beat kb-nginx kb-redis kb-neo4j kb-celery 2>/dev/null || true

echo ""
echo "[1/4] 建置前端靜態檔..."
export KB_FRONTEND_BUILD_DIR="/home/da40_ai_gb10/knowledge-base/.frontend-build-runtime-user8"
rm -rf "$KB_FRONTEND_BUILD_DIR"
npm --prefix frontend run build
mkdir -p "$KB_FRONTEND_BUILD_DIR/lib"
cp frontend/chat.html "$KB_FRONTEND_BUILD_DIR/chat.html"
cp frontend/lib/marked.min.js "$KB_FRONTEND_BUILD_DIR/lib/marked.min.js"
cp frontend/lib/compare-rules.js "$KB_FRONTEND_BUILD_DIR/lib/compare-rules.js"
echo "  ✅ 前端已建置"

echo ""
echo "[2/4] 重啟 compose 服務..."
$DC up -d --build redis neo4j web celery_search_worker celery_ingest_worker celery_beat nginx

echo ""
echo "[3/4] 等待服務穩定..."
sleep 5

echo ""
echo "[4/4] 檢查服務狀態..."
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "kb-web|kb-celery-search|kb-celery-ingest|kb-celery-beat|kb-nginx|kb-redis|kb-neo4j" || true

echo ""
echo "[5/5] 檢查關鍵埠..."
for port in 3030 6335 17474 17687 11434; do
    if ss -ltn 2>/dev/null | grep -q ":$port "; then
        echo "  ✅ Port $port 已監聽"
    else
        echo "  ⚠️  Port $port 未在本機監聽"
    fi
done

echo ""
echo "驗證前端與 API..."
curl -k -fsS https://127.0.0.1:3030/ >/dev/null && echo "  ✅ 首頁正常"
curl -k -fsS https://127.0.0.1:3030/admin >/dev/null && echo "  ✅ 管理後台路由正常"
curl -k -fsS https://127.0.0.1:3030/admin/graph-stats >/dev/null && echo "  ✅ 管理 API 正常"
curl -k -fsS https://127.0.0.1:3030/chat.html >/dev/null && echo "  ✅ 前端入口正常"
curl -k -fsS https://127.0.0.1:3030/health >/dev/null && echo "  ✅ API health 正常（nginx）" || echo "  ⚠️  API health 尚未就緒（nginx）"
docker exec kb-web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read()" >/dev/null && echo "  ✅ API health 正常（容器內）" || echo "  ⚠️  API health 尚未就緒（容器內）"
curl -fsS http://127.0.0.1:6335/healthz >/dev/null && echo "  ✅ QDrant health 正常" || echo "  ⚠️  QDrant health 尚未就緒"
docker exec kb-web python -c "import urllib.request; urllib.request.urlopen('http://host.docker.internal:11434/api/tags', timeout=5).read()" >/dev/null && echo "  ✅ 容器可連到 Ollama" || echo "  ⚠️  容器無法連到 Ollama"
check_websocket_proxy

echo ""
echo "=========================================="
echo "   ✅ 系統啟動完成！"
echo "=========================================="
echo ""
echo "📍 服務入口："
echo "   - 對外前端:   https://61.216.9.52:3030"
echo "   - 本機 API:    https://127.0.0.1:3030/health"
echo "   - Neo4j:       http://localhost:17474"
echo "   - Nginx:       https://localhost:3030"
echo "   - Ollama:      http://127.0.0.1:11434"
echo ""
echo "📝 日誌位置："
echo "   - docker compose logs -f web"
echo "   - docker compose logs -f celery_search_worker"
echo "   - docker compose logs -f celery_ingest_worker"
echo "   - docker compose logs -f nginx"
echo ""
echo "=========================================="
