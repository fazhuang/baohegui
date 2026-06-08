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
COPY backend/pyproject.toml .
RUN pip install --no-cache-dir .

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
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制已安装的 Python 包
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制代码
COPY backend/app ./app

# 复制规则文件
COPY rules ./rules

# spaCy 中文模型（运行时下载，忽略失败）
RUN python -m spacy download zh_core_web_sm 2>/dev/null || echo "spaCy模型跳过"

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')" || exit 1

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
