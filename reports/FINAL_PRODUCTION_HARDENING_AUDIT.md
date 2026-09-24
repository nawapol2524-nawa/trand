# FINAL PRODUCTION HARDENING AUDIT
**Date**: 2026-09-24  
**Commit Range**: HEAD  
**Environment**: Railway (DEMO Mode) / local simulation  

## 1. Broker 404 Root-Cause & Defect Fix
**Symptom**: Railway runtime reported `Broker query failed: HTTP Error 404: Not Found`.
**Investigation**:
- Traced the `CTraderMCPBroker` execution path through `runner.py -> execute_cycle -> get_positions -> call_tool`.
- Wrote diagnostic scripts against `https://mcp.ctrader.com/trading/mcp`.
- **Root Cause Verified**: When a session expires or is manually invalidated, the cTrader remote MCP server responds with HTTP 404 (`{"error":{"code":-32000,"message":"Session not found; re-initialize"}}`). The existing adapter only caught HTTP 400 for session reconnections.
- **Fix Applied**: Updated `src/brokers/ctrader_mcp.py` to handle both `400` and `404` errors in `call_tool`. If a 404 occurs, the adapter now transparently calls `connect()` and retries the tool call once. Also added a `_retry` flag to prevent infinite loops if the session cannot be re-established.

## 2. MCP Interface Consistency Audit
Audited `src/brokers/ctrader_mcp.py`:
- `get_balance`: Calls `get_balance`, cleanly unpacks factor via `moneyDigits`.
- `get_positions`: Calls `get_positions`, returns `positions` list.
- `get_spot_prices`: Calls `get_spot_prices` with `{"symbolId": [...]}`.
- `get_trendbars`: Calls `get_trendbars` with `{"symbolId": ..., "period": ..., "count": ..., "fromTimestamp": ..., "toTimestamp": ...}`.
All mappings were tested manually and matched the remote MCP schema perfectly.

## 3. Broker Error Handling / Resilience
- The `CTraderMCPBroker` handles timeouts gracefully (fail-closed, caught by `runner.py`'s general `Exception` handler which marks `broker_connected = False`).
- The 404 / 400 session expiration cases are now handled with automatic reconnection.
- Missing `.env` variables cleanly throw `ValueError`.

## 4. Full Runtime Pipeline Audit
- Re-ran the end-to-end `TradingBotRunner` execution cycle.
- **Result**: `execute_cycle()` runs cleanly. Pipeline successfully acquires market data (M5 and H1 bars), passes it to strategy evaluation, and correctly handles `NO_TRADE` when there's no signal.
- The state sync and reconciliation process (`IN_SYNC`) runs at startup without error.

## 5. 60-Cycle Soak Verification
- Simulated 60 cycles (5 seconds each) locally.
- Confirmed loop stability and correct market data logging (`{"event": "MARKET_DATA", "status": "ACQUIRED"}`).
- Process responds cleanly to SIGTERM (`{"event": "SHUTDOWN_SIGNAL", "signal": 15}`).

## 6. Full Test Suite Safety
- Ran `pytest tests/`: **89/89 tests passed**.
- Confirmed no secrets were hardcoded. All sensitive data strictly comes from environment variables (`.env`).
- `TRADING_MODE` is enforced as `DEMO` and `LIVE_TRADING_ENABLED=false` via Docker/Railway config defaults.

## Conclusion
The defect has been resolved. The runtime is hardened, fully traceable against the original `STRATEGY_SPEC.md`, and prepared for 24/7 soak testing in the Railway environment.

**STATUS**: PASS - DEPLOYMENT READY
