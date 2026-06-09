# ═══════════════════════════════════════════════════════════════
# Stage 1: Build — 安装依赖
# ═══════════════════════════════════════════════════════════════
FROM python:3.13-slim AS builder

WORKDIR /build

# 系统依赖（WeasyPrint + spaCy 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0t64 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖描述文件
COPY requirements-railway.txt .
RUN pip install --no-cache-dir -r requirements-railway.txt

# ═══════════════════════════════════════════════════════════════
# Stage 2: Runtime — 精简运行环境
# ═══════════════════════════════════════════════════════════════
FROM python:3.13-slim

WORKDIR /app

# 系统依赖（运行时必需）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0t64 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制已安装的 Python 包
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制代码
COPY app ./app
COPY api ./api

# 复制规则文件
COPY rules ./rules

EXPOSE 8000

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
