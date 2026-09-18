# ==============================================================================
# Multi-Stage Production Dockerfile for AI Forex Autonomous Trading System
# Security Standard: Gate 25 (Non-Root Execution, Minimal Attack Surface)
# ==============================================================================

# --- Stage 1: Build & Dependency Resolution ---
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install/deps -r requirements.txt


# --- Stage 2: Hardened Runtime Container ---
FROM python:3.11-slim AS runtime

LABEL maintainer="Quant Dev Team" \
      version="2.0.0-institutional" \
      description="Autonomous AI Forex Trading & Continuous Training System"

# Install OpenMP runtime required by HistGradientBoosting / LightGBM
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built dependencies from builder
COPY --from=builder /install/deps /usr/local

# Security & Execution Environment Invariants
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    LIVE_TRADING=false \
    AUTO_PROMOTION=false

# Create unprivileged application user & group
RUN groupadd -r appgroup -g 1001 && \
    useradd -r -u 1001 -g appgroup -m -d /app -s /sbin/nologin appuser

WORKDIR /app

# Initialize directory structure with unprivileged ownership
RUN mkdir -p /app/logs \
             /app/artifacts/models \
             /app/artifacts/experiments \
             /app/data/clean \
             /app/configs && \
    chown -R appuser:appgroup /app

# Copy application source code with non-root ownership
COPY --chown=appuser:appgroup ai_forex_bot/ /app/ai_forex_bot/
COPY --chown=appuser:appgroup configs/ /app/configs/
COPY --chown=appuser:appgroup scripts/ /app/scripts/

# Switch to unprivileged runtime user
USER appuser

# Default Entrypoint (Can be overridden by docker-compose)
CMD ["python3", "scripts/run_shadow_engine.py", "--symbol", "frxEURUSD", "--max-ticks", "0"]
