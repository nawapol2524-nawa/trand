# Multi-stage build — Python 3.11, non-root, Linux production
FROM python:3.11-slim AS base

# Security: non-root user
RUN groupadd -r botuser && useradd -r -g botuser botuser

# Minimal system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
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
    chown -R botuser:botuser /app

USER botuser

# Safety defaults — PAPER mode, LIVE requires explicit opt-in
ENV TRADING_MODE=PAPER
ENV LIVE_TRADING_ENABLED=false
ENV LOG_LEVEL=INFO
ENV TZ=UTC
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import json,sys,pathlib; \
        hf=pathlib.Path('/app/state/health.json'); \
        d=json.loads(hf.read_text()) if hf.exists() else {}; \
        sys.exit(0 if d.get('alive') else 1)"

ENTRYPOINT ["python", "-m", "src.app.main"]
