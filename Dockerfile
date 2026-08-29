# Dockerfile - 知識庫系統

FROM python:3.12-slim

WORKDIR /app

# 安裝系統依賴（Neo4j client, OCR 等）
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# 複製 requirements 並安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式
COPY app/ ./app/
COPY src/ ./src/
COPY config/ ./config/
COPY data/ ./data/

# 建立必要目錄
RUN mkdir -p logs

# 環境變數
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# 預設指令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
