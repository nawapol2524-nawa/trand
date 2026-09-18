# 24/7 AUTONOMOUS PRODUCTION HOST DEPLOYMENT GUIDE

**System**: AI Forex Autonomous Quantitative Trading System (`ai_forex_bot`)  
**Architecture**: Decoupled Production Services (Trading Engine, Continuous Retraining, Health Watchdog)  
**Security Standard**: Non-Root Containerization, Dual-Trigger Kill Switch, Secret Isolation  
**Default Mode**: `LIVE_TRADING = false` (Zero Financial Risk, Full High-Fidelity Paper Simulation)  

---

## 1. Host Prerequisites & System Requirements

### Recommended Hardware Specifications
- **Operating System**: Linux (Ubuntu 22.04 LTS / 24.04 LTS, Debian 12) or macOS Server
- **CPU**: 4 vCPUs or higher (optimized for multicore feature extraction and gradient boosting)
- **RAM**: 8 GB minimum (16 GB recommended for multi-pair retraining)
- **Storage**: 40 GB+ NVMe SSD (minimum 500 MB free space enforced by retraining preflight checks)
- **Network**: Stable low-latency connection (< 50ms to broker endpoints)

### Required Host Packages
```bash
# Update system repositories
sudo apt-get update && sudo apt-get upgrade -y

# Install Docker Engine, Docker Compose, Git, and Python
sudo apt-get install -y git curl ca-certificates python3 python3-pip python3-venv

# Install Docker (if not installed)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

---

## 2. Repository Setup & Directory Initialization

```bash
# 1. Clone repository to deployment directory
git clone https://github.com/your-org/ai_forex_bot.git /opt/ai_forex_bot
cd /opt/ai_forex_bot

# 2. Initialize required runtime directories
mkdir -p logs artifacts/models artifacts/state artifacts/experiments data/clean

# 3. Secure file permissions
chmod 750 /opt/ai_forex_bot
chmod 700 logs artifacts/state
```

---

## 3. Host Environment & Credential Configuration

> [!CAUTION]
> Never commit `.env` into git. The file `.env` is ignored by `.gitignore` and must be populated on the host machine only.

```bash
# 1. Copy production template
cp .env.example .env

# 2. Edit .env with host credentials
nano .env
```

### Environment Configuration Schema (`.env`)
```bash
# Broker Connectivity (Deriv WebSocket API)
DERIV_API_TOKEN=your_actual_deriv_api_token
DERIV_APP_ID=1089
ENABLE_DERIV=true

# Notification & Webhooks
LINE_CHANNEL_ACCESS_TOKEN=your_line_token
LINE_USER_ID=your_line_user_id

# System Governance (Keep false until paper validation criteria are met)
LIVE_TRADING=false
AUTO_PROMOTION=false
```

---

## 4. Deployment Option A: Docker Compose (Recommended)

Docker Compose runs the trading system as two decoupled, isolated container services with least-privilege security.

### 4.1 Build and Launch
```bash
# Build production images (multi-stage non-root appuser UID 1001)
docker compose build

# Start services in the background
docker compose up -d

# Verify container status
docker compose ps
```

### 4.2 Inspect Decoupled Container Logs
```bash
# Real-time shadow/paper trading telemetry
docker compose logs -f trading-bot

# Scheduled continuous retraining telemetry
docker compose logs -f training-worker
```

### 4.3 Container Healthcheck Probe
The `SystemHealthMonitor` provides an automated probe for container health:
```bash
docker exec -it ai_forex_trading_bot python3 -m ai_forex_bot.monitoring.health --probe
```

---

## 5. Deployment Option B: Native Host Daemon via Systemd

For bare-metal Linux VPS deployments, manage the supervisor with `systemd`.

### 5.1 Create Virtual Environment & Install Dependencies
```bash
python3 -m venv /opt/ai_forex_bot/venv
/opt/ai_forex_bot/venv/bin/pip install --upgrade pip
/opt/ai_forex_bot/venv/bin/pip install -r requirements.txt
```

### 5.2 Create Systemd Service File
```bash
sudo nano /etc/systemd/system/ai-forex-daemon.service
```

```ini
[Unit]
Description=AI Forex Autonomous 24/7 Production Daemon Supervisor
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=appuser
Group=appgroup
WorkingDirectory=/opt/ai_forex_bot
EnvironmentFile=/opt/ai_forex_bot/.env
ExecStart=/opt/ai_forex_bot/venv/bin/python3 scripts/run_production_daemon.py --symbol frxEURUSD --heartbeat-interval 60
Restart=always
RestartSec=10
KillSignal=SIGTERM
TimeoutStopSec=30
StandardOutput=append:/opt/ai_forex_bot/logs/daemon.log
StandardError=append:/opt/ai_forex_bot/logs/daemon_error.log

[Install]
WantedBy=multi-user.target
```

### 5.3 Enable and Start Service
```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-forex-daemon
sudo systemctl start ai-forex-daemon

# Check real-time service status
sudo systemctl status ai-forex-daemon
```

---

## 6. Health Monitoring & Observability

### 6.1 Inspect Heartbeat Status
The supervisor writes a structured JSON heartbeat every 60 seconds to `logs/heartbeat.json`:
```bash
cat logs/heartbeat.json | python3 -m json.tool
```

Sample Heartbeat Payload:
```json
{
  "timestamp": "2026-09-18T12:57:56.270096+00:00",
  "uptime_seconds": 3600.0,
  "overall_status": "HEALTHY",
  "governance": {
    "live_trading": false,
    "auto_promotion": false
  },
  "system_resources": {
    "pid": 73962,
    "memory_rss_mb": 81.06,
    "free_disk_mb": 21040.16
  },
  "trading_state": {
    "champion_model_id": "candidate_b_frxEURUSD_M15",
    "open_positions_count": 0,
    "today_pnl_usd": 0.0,
    "risk_engine_status": "NORMAL",
    "kill_switch_active": false
  }
}
```

### 6.2 Health Probe Command
```bash
python3 -m ai_forex_bot.monitoring.health --probe --max-stale 120
# Returns 0 if healthy, 1 if unhealthy or stale
```

---

## 7. Emergency Kill-Switch & Position Recovery

### 7.1 Activating Emergency Kill-Switch
If anomalous market volatility, network degradation, or unexpected behavior occurs:

**Option 1: File-based Flag (Instant, works from any process or shell)**
```bash
touch /opt/ai_forex_bot/KILL_SWITCH
```
*The supervisor detects the flag within 1 second, rejects all pending signals, persists open portfolio state, and executes a safe shutdown.*

**Option 2: Programmatic / CLI Trigger**
```bash
python3 -c "from ai_forex_bot.risk.kill_switch import EmergencyKillSwitch; EmergencyKillSwitch().activate_kill_switch('MANUAL_OPERATOR_OVERRIDE')"
```

### 7.2 Clearing Kill-Switch & Resuming Operation
```bash
rm -f /opt/ai_forex_bot/KILL_SWITCH
python3 -c "from ai_forex_bot.risk.kill_switch import EmergencyKillSwitch; EmergencyKillSwitch().reset_kill_switch('RESUMED_AFTER_AUDIT')"
```

### 7.3 Crash Recovery & Portfolio Reconciliation
When the daemon starts up with `--restore-state` (enabled by default):
1. `StateRecoveryManager` reads `artifacts/state/portfolio_state.json`.
2. Restores open positions, account balance, and processed order keys into `PaperBroker`.
3. Runs `broker.reconcile()` to audit margin and equity balance integrity.
4. Prevents duplicate order placement for past bars.

---

## 8. Safe Protocol for Transitioning to Live Trading

> [!WARNING]
> Live trading involves capital risk. Do not enable live trading until the system has achieved at least 30 consecutive days of shadow/paper validation matching backtest expectations.

### Verification Checklist Before Live Activation:
- [ ] Minimum 30 days of clean shadow trading logs in `logs/shadow_signals.jsonl`.
- [ ] Paper broker reconciliation shows zero discrepancies over 500+ simulated trades.
- [ ] All 61 unit and integration tests pass cleanly (`python3 -m unittest discover tests`).
- [ ] Security scanner reports 0 secret leaks (`python3 scripts/security_scan.py`).
- [ ] Emergency Kill-Switch tested and operational on host.

### Activation Protocol:
1. In host `.env`:
   ```bash
   LIVE_TRADING=true
   ```
2. Restart daemon or Docker containers:
   ```bash
   docker compose restart
   ```
3. Monitor `logs/heartbeat.json` to confirm broker connection and live status.
