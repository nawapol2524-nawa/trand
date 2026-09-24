# Multi-stage build — Python 3.11, non-root, Linux production
FROM python:3.11-slim AS base

# Security: non-root user
RUN groupadd -r botuser && useradd -r -g botuser botuser

# Minimal system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies layer (cached separately from source)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Application source
COPY src/ ./src/
COPY configs/ ./configs/
COPY STRATEGY_SPEC.md .

# Persistent directories
RUN mkdir -p /app/logs /app/state && \
    chmod 777 /app/logs /app/state && \
    chown -R botuser:botuser /app

USER botuser

# Safety defaults — DEMO mode, LIVE requires explicit dual opt-in
ENV TRADING_MODE=DEMO
ENV LIVE_TRADING_ENABLED=false
ENV LOG_LEVEL=INFO
ENV TZ=UTC
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -m src.services.healthcheck

ENTRYPOINT ["python", "-m", "src.app.main"]
