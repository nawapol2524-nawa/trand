# BROKER INTEGRATION ROOT-CAUSE AUDIT
**Date**: 2026-09-24T16:15:00+07:00 (09:15:00 UTC)  
**Investigation Targets**:
1. Railway Repeated Broker HTTP 404 & Graceful Shutdown
2. USDJPY `HTTP 400 Relative stop loss has invalid precision`

---

## 1. Executive Summary

A comprehensive forensic audit of real Railway DEMO runtime telemetry, cTrader Remote MCP tool contracts, and local execution pipelines was conducted.

### Key Findings:
1. **Issue #1 (HTTP 404 & Container Shutdown)**:
   - The repeated HTTP 404 errors observed between 08:55:22 and 08:57:16 UTC were generated exclusively by the **OLD container deployment (`4c70a120`)**.
   - Deployment `4c70a120` was built from an earlier commit prior to the HTTP 404 session recovery fix (`72eade6`). When its cTrader session expired, it raised an unhandled 404 on `get_positions` every 5-second cycle.
   - The **NEW deployment (`a3eaf0a0`)** started at 08:57:13 UTC, initialized cleanly (`Broker connected successfully in 527.30 ms`), reconciled state (`status: IN_SYNC`), and executed full market data/strategy cycles for EURUSD, GBPUSD, USDJPY, and XAUUSD with **zero 404 errors**.
   - The shutdown at 08:57:21 UTC was an orchestrated, normal **`SIGTERM` (signal 15)** sent by Railway to retire the superseded container `4c70a120` after the new container `a3eaf0a0` passed startup healthchecks. It was **NOT** an application crash or failure.

2. **Issue #2 (USDJPY `Relative stop loss has invalid precision`)**:
   - The rejection occurred during market order submission for USDJPY (`BUY`, volume 1.31 lots, relative SL 116, relative TP 231).
   - In `src/app/runner.py`, `SYMBOL_MAP["USDJPY"]["point_scale"]` was incorrectly configured as `1000`, based on the mistaken assumption that USDJPY's 3-digit price meant points were in pipettes ($10^3$).
   - The cTrader Remote MCP server / Open API contract requires all `relativeStopLoss` and `relativeTakeProfit` integer values to be in **fixed $10^{-5}$ scale (100,000 multiplier)** across all symbols, matching its internal price representation.
   - When `relativeStopLoss: 116` was passed, cTrader divided by $100,000$, computing an offset of $0.00116$ JPY (5 decimal places). Adding $0.00116$ to USDJPY display price ($xxx.xxx$) resulted in a 5-digit price, violating USDJPY's 3-decimal precision rule and triggering `HTTP 400 Relative stop loss has invalid precision`.
   - The correct offset for USDJPY requires rounding the calculated distance to the symbol's permitted decimal precision ($3$ digits) and multiplying by $100,000$ (e.g. $0.116 \times 100,000 = 11,600$), yielding an offset of exactly $0.116$ JPY that maintains 3-digit price validity.

---

## 2. Issue #1 — Broker 404 & Lifecycle Root Cause

### 2.1 Exact Failing Broker Query & Call Path
- **Failing Operation**: `get_positions` during startup and cyclic broker reconciliation.
- **Complete Call Path**:
  ```
  TradingBotRunner.execute_cycle() [src/app/runner.py:130]
    └── CTraderMCPBroker.get_positions() [src/brokers/ctrader_mcp.py:159]
          └── CTraderMCPBroker.call_tool("get_positions", {}) [src/brokers/ctrader_mcp.py:101]
                └── urllib.request.urlopen(req) [POST https://mcp.ctrader.com/trading/mcp]
                      └── cTrader Remote MCP Server
  ```
- **Failing Response**: `HTTP 404 Not Found` with JSON-RPC payload:
  `{"jsonrpc":"2.0","error":{"code":-32000,"message":"Session not found; re-initialize"},"id":null}`.

### 2.2 Why 404 Repeated Every 5 Seconds in Deployment `4c70a120`
- Deployment `4c70a120` ran code where `call_tool` only caught HTTP 400.
- When the cTrader MCP session expired, the server returned HTTP 404.
- Because 404 was not caught in that deployment, `call_tool` raised `urllib.error.HTTPError: HTTP Error 404: Not Found` directly to `runner.py:135`, which logged:
  `Broker query failed: HTTP Error 404: Not Found`.
- `runner.py` then marked `broker_connected = False` and bypassed the rest of the cycle.
- 5 seconds later, the runner called `get_positions` again with the same expired session ID, reproducing the exact 404.

### 2.3 Container Transition & Shutdown Evidence
From Railway runtime logs:
- `15:57:11` (`4c70a120`): `Broker query failed: HTTP Error 404: Not Found` (Old container)
- `15:57:13` (`a3eaf0a0`): `event: BOT_STARTING` (New container initialized)
- `15:57:14` (`a3eaf0a0`): `Broker connected successfully in 527.30 ms`
- `15:57:14` (`a3eaf0a0`): `Account balance: $9590.89 | Equity: $9590.89`
- `15:57:14` (`a3eaf0a0`): `Startup reconciliation complete: ... status: 'IN_SYNC'`
- `15:57:15` (`a3eaf0a0`): Market data and strategy evaluation for EURUSD & GBPUSD executed cleanly.
- `15:57:16` (`a3eaf0a0`): Market data and strategy evaluation for USDJPY executed cleanly.
- `15:57:16` (`4c70a120`): `Broker query failed: HTTP Error 404: Not Found` (Final tick of old container before Railway cut it off).
- `15:57:17` (`a3eaf0a0`): Market data and strategy evaluation for XAUUSD executed cleanly.
- `15:57:20` (`4c70a120`): `event: SHUTDOWN_SIGNAL ts: 2026-09-24T08:57:20.296560+00:00 signal: 15`
- `15:57:21` (`4c70a120`): `TradingBotRunner shutting down gracefully...`
- `15:57:21` (`4c70a120`): `event: BOT_STOPPED ts: 2026-09-24T08:57:21.596928+00:00 mode: DEMO`
- `15:57:22` (`4c70a120`): `Stopping Container`

**Shutdown Cause**: Railway orchestrator sent `SIGTERM` (signal 15) to terminate the old container once the new container (`a3eaf0a0`) became healthy.

---

## 3. Issue #2 — USDJPY Invalid Stop Precision Root Cause

### 3.1 Data Transformation Chain
1. **Strategy Evaluation**:
   USDJPY M5 generated a signal with ATR `0.077`.
2. **RiskEngine Evaluation**:
   - `sl_dist = 0.077 * 1.5 = 0.1155` JPY (display price distance).
   - `tp_dist = 0.1155 * 2.0 = 0.231` JPY.
   - Position sizing allocated `1.31` lots based on USDJPY quote currency calculations.
3. **Runner Order Submission Scaling (Defective Implementation)**:
   ```python
   point_scale = sym_info.get("point_scale", 100000) # USDJPY had point_scale: 1000
   relative_sl = max(1, int(round(sl_dist * point_scale))) # int(round(0.1155 * 1000)) = 116
   relative_tp = max(1, int(round(tp_dist * point_scale))) # int(round(0.231 * 1000)) = 231
   ```
4. **Broker Request Sent**:
   ```json
   {
     "symbolId": 4,
     "orderType": "MARKET",
     "tradeSide": "BUY",
     "volume": 13100000,
     "relativeStopLoss": 116,
     "relativeTakeProfit": 231
   }
   ```

### 3.2 Broker Rejection Mechanism
- **cTrader Server MCP Contract**:
  cTrader Open API represents all prices in scaled integer format ($10^5$, 5 decimal places).
  `relativeStopLoss` is interpreted by cTrader MCP as an integer offset scaled by $10^{-5}$:
  $$\Delta \text{Price} = \frac{\text{relativeStopLoss}}{100,000}$$
  $$\text{With relativeStopLoss} = 116 \implies \Delta \text{Price} = \frac{116}{100,000} = 0.00116$$
- For USDJPY, prices have a maximum precision of **3 decimals** (tick size $0.001$).
- When cTrader applied the offset to entry price (e.g. $158.601$):
  $$\text{StopPrice} = 158.601 - 0.00116 = 158.59984$$
- The resulting price $158.59984$ contains **5 decimal places**, violating the symbol's 3-digit precision rule.
- cTrader immediately rejected the order:
  `HTTP 400 Relative stop loss has invalid precision`.

### 3.3 Scope of Defect across Symbols
- **GBPUSD / EURUSD (`digits: 5`)**:
  `point_scale = 100000` produced offsets with 5 decimals, which matched the symbol's 5-digit precision and succeeded (as proven by trade `PID140062611`).
- **USDJPY (`digits: 3`)**:
  `point_scale = 1000` produced fractional offsets at the 5th decimal place, failing broker validation.
- **XAUUSD (`digits: 2`)**:
  `point_scale = 100` would produce $1050 \div 100,000 = 0.0105$ (4 decimal places), which would also fail Gold's 2-digit precision rule.

### 3.4 Volume Contract Verification
- `lots = 1.31`.
- For Forex, 1 lot = 100,000 base asset units.
- MCP specification specifies volume in 1/100 base-asset units:
  $$\text{mcp\_volume} = 1.31 \times 100,000 \times 100 = 13,100,000$$
- `mcp_volume = 13100000` is **100% compliant** with the broker contract.

---

## 4. Evidence Classification

| Evidence Type | Item | Classification | Description |
| :--- | :--- | :--- | :--- |
| **Railway Runtime** | Deploy `4c70a120` repeated 404s | **Level A** | Real Railway log entries showing 404 every 5 seconds on old deployment. |
| **Railway Runtime** | Deploy `a3eaf0a0` clean start | **Level A** | Real Railway log showing successful connection, `IN_SYNC`, and 4 symbol evaluations. |
| **Railway Runtime** | Signal 15 shutdown | **Level A** | Real Railway log showing SIGTERM to `4c70a120` from container orchestrator. |
| **Railway Runtime** | USDJPY 400 rejection | **Level A** | Real Railway log showing `relative_sl_points: 116` rejected for invalid precision. |
| **Broker Contract** | `create_order` inputSchema | **Level A** | Live schema fetched directly from `https://mcp.ctrader.com/trading/mcp`. |
| **Integration Test**| 404 reconnect recovery | **Level B** | Tested against live cTrader MCP server with simulated corrupted session. |
| **Unit Test** | Symbol precision scaling | **Level B** | `tests/unit/test_broker_precision.py` verifying exact rounding per symbol digits. |
| **Static Code** | `SYMBOL_MAP` & `runner.py` | **Level C** | Code audit verifying where `point_scale` was introduced and used. |

---

## 5. What Is Proven vs. What Is Not Proven

### Proven:
1. Proven that repeated 404s belonged to the retired deployment `4c70a120` that lacked 404 handling.
2. Proven that the shutdown at 08:57:21 was Railway terminating `4c70a120` via SIGTERM after `a3eaf0a0` took over.
3. Proven that cTrader Remote MCP interprets `relativeStopLoss` in $10^{-5}$ scale across all symbols.
4. Proven that passing `relative_sl_points: 116` on USDJPY generates a 5-digit price that cTrader rejects for invalid precision.
5. Proven that `mcp_volume: 13100000` matches the broker volume contract.

### Not Proven:
- It is not proven that cTrader MCP session will never encounter an unrecoverable server-side outage; however, single-retry session recovery on 400/404 is verified.

---

## 6. Minimal Corrective Action Implemented

1. **Symbol Digits & Fixed $10^5$ Multiplier in `src/app/runner.py`**:
   Configured explicit `digits` per symbol (`EURUSD: 5`, `GBPUSD: 5`, `USDJPY: 3`, `XAUUSD: 2`).
   Rounded `sl_dist` and `tp_dist` to the symbol's permitted decimal digits before multiplying by fixed $100,000$ points multiplier:
   ```python
   digits = sym_info.get("digits", 5)
   sl_dist_rounded = round(sl_dist, digits)
   tp_dist_rounded = round(tp_dist, digits)
   relative_sl = max(1, int(round(sl_dist_rounded * 100000)))
   relative_tp = max(1, int(round(tp_dist_rounded * 100000)))
   ```
2. **Explicit Session Recovery Logging in `src/brokers/ctrader_mcp.py`**:
   Added `logger.warning(...)` when 400/404 triggers a transparent re-authentication attempt.
3. **Comprehensive Regression Tests**:
   Added `tests/unit/test_broker_precision.py` covering precision scaling for all 4 symbols, volume conversion contracts, and 404 single-retry limits.

---

## 7. Confirmation of Strategy / Risk / AI Freeze

- `STRATEGY_SPEC.md`: **0 changes**
- Strategy logic & parameters: **0 changes**
- AI Advisory & Deterministic Gate: **0 changes**
- RiskEngine & Position Sizing formulas: **0 changes**
- `LIVE_TRADING_ENABLED`: **`false`**
