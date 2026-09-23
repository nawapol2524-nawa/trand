# Railway 24/7 Demo Deployment Runbook

**Objective**: Deploy the trading bot to Railway PaaS for continuous 24/7 autonomous DEMO execution on Deriv cTrader Demo account `2548625`.  
**Safety Status**: **DEMO ONLY**. Live trading is strictly locked and disabled.  
**Repository**: `https://github.com/nawapol2524-nawa/trand`  
**Deployment Model**: Headless containerized daemon supervised by Railway (`python -m src.app.main`).  

---

## Step-by-Step Deployment Instructions

### Step 1: Create Railway Project
1. Log in to [Railway](https://railway.app/).
2. Click **New Project** on the dashboard.
3. Select **Deploy from GitHub repo**.

### Step 2: Connect GitHub Repository
1. In the repository search list, select `nawapol2524-nawa/trand`.
2. Authorize Railway to access the repository if prompted.

### Step 3: Select Main Branch
1. Under deployment branch settings, confirm the target branch is `main`.
2. Automatic deployments on push to `main` should be enabled.

### Step 4: Configure Service Settings
1. In the Railway service settings, navigate to the **Settings** tab.
2. Confirm the build configuration:
   - **Builder**: `Dockerfile` (automatically detected via `railway.toml`).
   - **DockerfilePath**: `Dockerfile`.
3. Under **Deploy**:
   - **Start Command**: `python -m src.app.main` (defined in `railway.toml`).
   - **Restart Policy**: `Always` (or `On Failure` with max retries 10).
   - **Healthcheck Timeout**: `120` seconds.
   - **Healthcheck Path**: Leave empty (`""`) since this is a headless background daemon.

### Step 5: Configure Environment Variables
Navigate to the **Variables** tab for the service and add the following configuration keys (substituting your actual secret placeholders):

| Variable Key | Value / Placeholder | Note |
| :--- | :--- | :--- |
| `TRADING_MODE` | `DEMO` | Enforces Demo trading against cTrader |
| `LIVE_TRADING_ENABLED` | `false` | **MANDATORY SAFETY LOCK** |
| `CTRADER_MCP_URL` | `https://mcp.ctrader.com/trading/mcp` | Remote MCP endpoint |
| `CTRADER_MCP_TOKEN` | `Bearer <YOUR_CTRADER_DEMO_BEARER_TOKEN>` | Your active Deriv cTrader Demo MCP token |
| `GROQ_API_KEY` | `<YOUR_GROQ_API_KEY>` | (Optional) Primary AI advisory inference |
| `OPENAI_API_KEY` | `<YOUR_OPENAI_API_KEY>` | (Optional) Fallback AI advisory inference |
| `LOG_LEVEL` | `INFO` | JSON structured log verbosity |
| `STATE_DIR` | `/app/state` | Persistent state mount path |
| `LOG_DIR` | `/app/logs` | Persistent log mount path |

> [!CAUTION]
> **DO NOT** enter `LIVE_TRADING_ENABLED=true`. Live trading is strictly prohibited.

### Step 6: Configure Persistent Volume (Required for State Persistence)
1. On the service canvas, right-click or click **+ Add Volume**.
2. Mount the volume to:
   - **Mount Path**: `/app/state`
3. (Optional) Add a second volume for audit logs mounted to `/app/logs`.
4. This ensures that `bot_state.json` (daily starting balance, PnL, consecutive loss streak) survives container re-deployments and host restarts.

### Step 7: Deploy
1. Click **Deploy** or push a new commit to trigger the build.
2. Watch the **Build Logs** in Railway:
   - Base image: `python:3.11-slim`
   - Dependencies: installed via `pip install -r requirements.txt`
   - User: switched to unprivileged non-root `botuser`
   - Healthcheck: registered `python -m src.services.healthcheck`
   - Image build: SUCCESS

### Step 8: Verify Deployment Startup
Open the **Deploy Logs** tab and look for the structured JSON startup events:
```json
{"event": "BOT_STARTING", "trading_mode": "DEMO", "python": "3.11..."}
{"event": "RUNNER_START", "mode": "DEMO", "action": "Starting 24/7 cTrader Demo loop"}
```
Ensure there are no uncaught exceptions during initialization.

### Step 9: Verify Healthcheck Status
1. Check the service status indicator in the Railway Dashboard. It should turn green (**Healthy** / **Active**).
2. The internal healthcheck runs `python -m src.services.healthcheck` every 30 seconds:
   - Checks `state/health.json` existence and `alive: true`.
   - Verifies heartbeat freshness ($\le 60$ seconds).
   - Verifies broker connectivity.
   - Verifies consistency of `state/bot_state.json`.

### Step 10: Verify Broker Connection
In the deploy logs, confirm:
```
Initializing TradingBotRunner...
Broker connected successfully in ... ms
Account balance: $9999.85 | Equity: $9999.85
```
This confirms dynamic session negotiation with the Deriv cTrader Remote MCP server.

### Step 11: Verify Broker Reconciliation
Confirm initial startup reconciliation in the deploy logs:
```
Startup reconciliation complete: {'reconciliation_time': '...', 'broker_open_count': 0, 'local_open_count': 0, 'orphans_discovered': [], 'closed_detected': [], 'status': 'IN_SYNC'}
```
This guarantees that any pre-existing broker positions are discovered and no duplicate trades can be opened.

### Step 12: Verify DEMO Mode Enforcement
Verify in deploy logs that:
- `trading_mode: "DEMO"`
- Real money trading is inactive.
- If `TRADING_MODE=LIVE` is mistakenly configured without `LIVE_TRADING_ENABLED=true`, verify the log outputs:
  ```json
  {"event": "LIVE_BLOCKED", "reason": "TRADING_MODE=LIVE but LIVE_TRADING_ENABLED is not 'true'", "action": "Forcing PAPER mode for safety"}
  ```

### Step 13: Verify Process Survives Local MacBook Shutdown
1. Close all terminal windows on your local MacBook.
2. Put the MacBook to sleep or turn off Wi-Fi.
3. Access the Railway dashboard from another device or smartphone.
4. Verify that the service remains running and deploy logs continue emitting heartbeats every 5 seconds.

### Step 14: Verify Restart Recovery
1. In the Railway dashboard, click **Restart** on the service.
2. Observe the restart logs:
   - Container shuts down via graceful `SIGTERM`.
   - New container launches and mounts the persistent volume `/app/state`.
   - `StateManager` loads `bot_state.json` from the volume.
   - Broker reconciliation runs and confirms `IN_SYNC`.
   - Daily starting balance and consecutive loss counter are fully preserved.
