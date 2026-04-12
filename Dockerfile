FROM python:3.11-slim

WORKDIR /app

# 安裝系統依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 先複製 pyproject.toml 以利 Docker layer cache
COPY pyproject.toml .
COPY src/ ./src/

RUN pip install --no-cache-dir -e .

COPY . .

EXPOSE 8000 8501
