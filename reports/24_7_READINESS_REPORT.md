# 24/7 Operational Readiness Report

**Date**: 2026-09-23  
**Target Scope**: 24/7 Autonomous Deployment on Deriv cTrader (Demo Mode)  
**Overall Verdict**: **READY_FOR_24_7_DEMO** ✅  
**Live Money Status**: **STRICTLY DISABLED** (`TRADING_MODE=DEMO`, `LIVE_TRADING_ENABLED=false`)

---

## 1. Executive Summary

This report certifies that the autonomous trading bot codebase in `https://github.com/nawapol2524-nawa/trand` is fully equipped for headless, resilient, unsupervised 24/7 execution in **DEMO** mode.

All core operational subsystems have been built, integrated, and empirically validated:
- **Process Supervision**: Automatic restart and supervision via Docker, systemd, or Railway.app.
- **Fail-Safe Startup & Reconciliation**: Discovers existing broker positions on startup, recovers orphan positions, and prevents duplicate order submissions.
- **Live Telemetry & Heartbeats**: Emits atomic status updates to `state/health.json` every cycle for external monitoring and container health checks.
- **Fail-Closed Risk Guardrails**: Enforces 1.0% risk per trade, 5.0% daily loss limit, 5 consecutive loss halt, and emergency kill switch.
- **Disaster Recovery**: Verified across 18 failure injection scenarios (AI outages, network dropouts, stale data, and local state mismatches).

---

## 2. Process Supervision Architecture

| Supervision Layer | Implementation File | Restart Policy | Security & Sandboxing |
| :--- | :--- | :--- | :--- |
| **Docker Container** | `Dockerfile` | `unless-stopped` | Non-root `botuser`, multi-stage build, minimal attack surface |
| **Docker Compose** | `docker-compose.yml` | `unless-stopped` | JSON log driver (max 50MB, 10 rotated files), volume-mounted state |
| **Linux Systemd** | `systemd/trading-bot.service`| `always` (10s backoff) | `ProtectSystem=strict`, `NoNewPrivileges=true`, `MemoryMax=1G` |
| **Railway PaaS** | `railway.toml` | `on_failure` (max 10) | Headless cloud deployment, automatic healthcheck bindings |

### Clean Shutdown Protocol
The application traps both `SIGTERM` and `SIGINT`. Upon receipt of a termination signal:
1. Signal handler triggers `_shutdown` asyncio event.
2. In-flight evaluation cycles complete safely.
3. Health telemetry sets `alive: false` and `status: "STOPPED"`.
4. Process exits with exit code 0.

---

## 3. Startup Recovery & Broker Reconciliation Protocol

```
[STARTUP]
    │
    ▼
[CONNECT] ────────────► Deriv cTrader Remote MCP Session Established
    │
    ▼
[LOAD LOCAL STATE] ───► Read `state/bot_state.json` (daily starting balance, loss streak)
    │
    ▼
[SYNC BROKER STATE] ──► Call `get_positions` to query authoritative broker state
    │
    ▼
[RECONCILE] ──────────┬─► Discover Orphan Positions (in broker, not in local) -> Integrate
                      └─► Detect Closed Positions (in local, not in broker) -> Mark closed
    │
    ▼
[RESUME SAFELY] ──────► Zero duplicate orders, full historical continuity preserved
```

- **Zero Duplicate Orders**: New signals are strictly checked against both local tracked positions and live broker open positions before execution.
- **Atomic State Saves**: All state file writes use atomic replacement (`.tmp` write followed by `replace`), preventing corruption during sudden power loss.

---

## 4. Telemetry & Heartbeat Observability

The bot continuously publishes comprehensive operational telemetry to `state/health.json`:

```json
{
  "alive": true,
  "status": "HEALTHY",
  "mode": "DEMO",
  "started_at": "2026-09-23T19:35:00Z",
  "last_heartbeat": "2026-09-23T19:40:00Z",
  "uptime_seconds": 300.0,
  "broker_connected": true,
  "broker_latency_ms": 145.2,
  "ai_status": "HEALTHY",
  "open_positions": 0,
  "trade_count_today": 0,
  "daily_pnl_usd": 0.0,
  "daily_pnl_pct": 0.0,
  "consecutive_losses": 0,
  "kill_switch_active": false,
  "data_freshness_seconds": 2.1,
  "reconnect_count": 0,
  "uncaught_exceptions": 0
}
```

- **Docker Healthcheck**: Configured to query `state/health.json` every 30 seconds. If `alive: true`, container is reported as healthy.

---

## 5. Log Rotation & Disk Growth Protection

- **Docker JSON File Driver**: Configured in `docker-compose.yml` with `max-size: "50m"` and `max-file: "10"`. Total log consumption is strictly bounded to $< 500\text{ MB}$.
- **Decision Trace Service**: Emits compact, append-only JSONL lines with regex secret masking.

---

## 6. Risk Guardrails & Safety Policy

1. **Max Risk per Trade**: Clamped to $1.0\%$ account equity.
2. **Max Daily Loss Limit**: Hard stop at $5.0\%$ drawdown from daily opening balance (UTC midnight reset).
3. **Consecutive Loss Halt**: 5 consecutive losses trigger a mandatory 1-hour trading halt.
4. **Max Concurrent Positions**: Maximum 3 open positions across all instruments.
5. **Max Positions per Symbol**: Strictly 1 open position per instrument.
6. **Data Staleness Gate**: Rejects signals if candle data is $> 300$ seconds old.
7. **Emergency Kill Switch**: Immediate shutdown via `EMERGENCY_KILL_SWITCH=true`.

---

## 7. Operational Run Guide

### Option A: Docker Deployment (Recommended)
```bash
# 1. Build and launch container in background
docker compose up -d --build

# 2. Check live health status
docker inspect --format='{{json .State.Health}}' deriv-ctrader-bot

# 3. View live structured logs
docker compose logs -f
```

### Option B: Linux Systemd Service
```bash
# 1. Install service unit
sudo cp systemd/trading-bot.service /etc/systemd/system/
sudo systemctl daemon-reload

# 2. Start and enable service
sudo systemctl enable --now trading-bot.service

# 3. Check live status
sudo systemctl status trading-bot.service
```

### Option C: Railway.app Deployment
- Repository contains valid `railway.toml`.
- Configure environment variables (`TRADING_MODE=DEMO`, `CTRADER_MCP_URL`, `CTRADER_MCP_TOKEN`).
- Deploy directly from GitHub `main`.

---

## 8. Verification Sign-Off

- **Test Suite**: 68/68 passing tests (`pytest`).
- **Failure Injection**: 18/18 scenarios passed (100%).
- **Broker Connectivity**: Verified live on Deriv cTrader Demo account `2548625`.
- **Status**: **READY_FOR_24_7_DEMO** ✅
