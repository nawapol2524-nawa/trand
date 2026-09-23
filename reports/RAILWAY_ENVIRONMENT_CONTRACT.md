# Railway Environment Variable Specification Contract

**Target Platform**: Railway Cloud PaaS  
**Deployment Target**: 24/7 Autonomous Demo Trading Daemon  
**Repository**: `https://github.com/nawapol2524-nawa/trand`  
**Security Policy**: Zero hardcoded secrets. All variables are configured via Railway Project Service Variables.  

---

## 1. Environment Variable Contract Matrix

| Variable Name | Requirement | Sensitive / Secret? | Safe Default Behavior | Purpose & Description | DEMO Deployment Requirement |
| :--- | :---: | :---: | :--- | :--- | :--- |
| `TRADING_MODE` | **REQUIRED** | No | `DEMO` (in Docker) | Sets execution mode: `DEMO`, `PAPER`, or `LIVE`. | Must be set to `DEMO`. |
| `LIVE_TRADING_ENABLED` | **REQUIRED** | No | `false` | Critical safety dual-lock. If not `"true"`, `LIVE` mode is unconditionally blocked. | Must be set to `false`. |
| `CTRADER_MCP_URL` | **REQUIRED** | No | `https://mcp.ctrader.com/trading/mcp` | Remote MCP SSE endpoint for Spotware cTrader. | Set to `https://mcp.ctrader.com/trading/mcp`. |
| `CTRADER_MCP_TOKEN` | **REQUIRED** | **YES (SECRET)** | None (raises error if missing) | Bearer token authorizing access to Deriv cTrader Demo account. | Required. Must be pasted in Railway Variables as a secret. |
| `PRIMARY_AI_PROVIDER` | OPTIONAL | No | `groq` | Designates primary advisory LLM provider (`groq` or `openai`). | Optional. Defaults to `groq`. |
| `GROQ_API_KEY` | OPTIONAL | **YES (SECRET)** | Falls back to offline rules if omitted | API key for Groq Cloud ultra-fast inference. | Recommended for low-latency AI advisory. |
| `SECONDARY_AI_PROVIDER` | OPTIONAL | No | `openai` | Fallback advisory LLM provider. | Optional. Defaults to `openai`. |
| `OPENAI_API_KEY` | OPTIONAL | **YES (SECRET)** | Falls back to offline rules if omitted | API key for OpenAI GPT models. | Optional. Fallback provider. |
| `LOG_LEVEL` | OPTIONAL | No | `INFO` | Verbosity of stdout JSON logs (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | Recommended: `INFO`. |
| `LOG_DIR` | OPTIONAL | No | `/app/logs` (Docker) or `logs` | Directory path where append-only audit traces and logs are stored. | Recommended: `/app/logs`. |
| `STATE_DIR` | OPTIONAL | No | `/app/state` (Docker) or `state` | Mount path where `bot_state.json` and `health.json` are persisted. | Recommended: `/app/state` (mount Railway Volume here). |
| `CYCLE_INTERVAL` | OPTIONAL | No | `5.0` | Heartbeat & market data evaluation cycle interval in seconds. | Recommended: `5.0`. |
| `HEALTHCHECK_MAX_STALE_SECONDS` | OPTIONAL | No | `60.0` | Threshold in seconds before healthcheck flags stale heartbeat as unhealthy. | Recommended: `60.0`. |
| `HEALTHCHECK_MAX_DISCONNECT_SECONDS` | OPTIONAL | No | `180.0` | Maximum tolerable broker disconnect duration before healthcheck triggers container restart. | Recommended: `180.0`. |
| `RISK_PER_TRADE_PCT` | OPTIONAL | No | `0.01` (1.0%) | Hard position risk limit per trade. Enforced by RiskEngine. | Frozen at `0.01`. |
| `MAX_DAILY_LOSS_PCT` | OPTIONAL | No | `0.05` (5.0%) | Maximum cumulative daily loss before daily halt triggers. | Frozen at `0.05`. |
| `MAX_CONSECUTIVE_LOSSES` | OPTIONAL | No | `5` | Circuit breaker threshold for 1-hour cooling halt. | Frozen at `5`. |
| `MAX_OPEN_POSITIONS` | OPTIONAL | No | `3` | Portfolio-wide simultaneous open position limit. | Frozen at `3`. |
| `EMERGENCY_KILL_SWITCH` | OPTIONAL | No | `false` | Immediate circuit breaker. When `true`, stops all new orders instantly. | Keep `false` unless manual emergency shutdown is required. |

---

## 2. Minimal Railway Configuration Set

To start 24/7 DEMO trading on Railway, only **two** variables are strictly required to be provided by the user in the Railway Dashboard (all others have secure fail-safe defaults):

```bash
TRADING_MODE=DEMO
LIVE_TRADING_ENABLED=false
CTRADER_MCP_TOKEN=Bearer eyJ... # (Paste your valid Deriv Demo cTrader token)
```

Optional advisory AI enhancement:
```bash
GROQ_API_KEY=gsk_...
```

---

## 3. Strict Prohibitions
1. **NEVER** set `LIVE_TRADING_ENABLED=true` on this deployment.
2. **NEVER** commit `.env` into git or upload raw tokens into GitHub.
3. If `TRADING_MODE=LIVE` is accidentally configured without `LIVE_TRADING_ENABLED=true`, the bot logs `LIVE_BLOCKED` and safely forces `PAPER` mode.
