# ─── v7ai-fast Dockerfile (optimized) ────────────────────
# 多阶段构建：uv 管理依赖 → 生产运行时
# 优化：去掉 build-essential（用 psycopg2-binary）+ 国内源
# ─────────────────────────────────────────────────────────────

# ── Stage 1: Build ──────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 先复制依赖文件，利用 Docker 缓存层
COPY pyproject.toml uv.lock* ./

# 安装 Python 依赖（psycopg2-binary 无需编译，跳过 build-essential）
RUN uv sync --frozen --no-dev --no-editable

# ── Stage 2: Runtime ────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# 最小运行时依赖（db 客户端、健康检查用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制虚拟环境
COPY --from=builder /app/.venv /app/.venv

# 复制应用代码
COPY . .

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 18081

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn main:app --host 0.0.0.0 --port 18081"]
