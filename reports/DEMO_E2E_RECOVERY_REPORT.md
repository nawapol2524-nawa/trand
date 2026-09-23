# Demo E2E & Failure Recovery Verification Report

**Date**: 2026-09-23 12:45:53 UTC  
**Target Environment**: Deriv cTrader Remote MCP (Demo Account `2548625`)  
**Overall Status**: **PASS** ✅

---

## 1. Live Broker Verification Summary

- **Broker Endpoint**: `https://mcp.ctrader.com/trading/mcp`
- **Connection Status**: CONNECTED ✅
- **Account Balance**: `$9999.85 USD`
- **Account Equity**: `$9999.85 USD`
- **Open Positions**: `0`

---

## 2. 18 Failure Injection & Recovery Test Results

| ID | Scenario | Expected Behavior | Actual Behavior | Result |
| :--- | :--- | :--- | :--- | :---: |
| 1 | **AI unavailable** | Failover to OfflineDeterministicAIProvider without crash | Handled by offline_rules (decision=APPROVE) | **PASS** |
| 2 | **AI timeout** | Graceful fallback to offline rules | Handled by offline_rules | **PASS** |
| 3 | **AI invalid response** | DeterministicGate rejects schema violation | Rejected: Schema validation failed: missing symbol, rationale, invalidation, or invalid confidence | **PASS** |
| 4 | **Market data stale** | RiskEngine blocks stale data | Blocked with reason: STALE_DATA | **PASS** |
| 5 | **Malformed market data** | Validation error on High < Low | ValueError raised, fail-closed | **PASS** |
| 6 | **cTrader disconnect** | Telemetry reports DEGRADED_BROKER_DISCONNECTED | Status: DEGRADED_BROKER_DISCONNECTED | **PASS** |
| 7 | **Reconnect** | Reconnect metric incremented | Reconnect count: 1 | **PASS** |
| 8 | **Order rejection** | Rejected order does not enter local state | Open positions: 0 | **PASS** |
| 9 | **Order timeout** | Reconciliation safely verifies broker truth | Reconciliation status: IN_SYNC | **PASS** |
| 10 | **Duplicate execution attempt** | Blocked by SYMBOL_EXPOSURE_LIMIT | Blocked: SYMBOL_EXPOSURE_LIMIT | **PASS** |
| 11 | **Application restart** | State safely reloaded from disk | Recovered daily starting balance: $9500.00 | **PASS** |
| 12 | **Restart with open position** | Broker position discovered and tracked without duplication | Discovered position: ['12345'] | **PASS** |
| 13 | **Restart after network interruption** | Syncs properly once network is restored | Broker open count synced to 1 | **PASS** |
| 14 | **Local state vs broker state mismatch** | Detects external closure and moves to history | Closed detected: ['P1'] | **PASS** |
| 15 | **Kill switch activation** | Immediately halts all new orders | Blocked: KILL_SWITCH_ACTIVE | **PASS** |
| 16 | **Daily loss threshold condition** | Blocks new orders when daily loss >= 5% | Blocked: DAILY_LOSS_LIMIT | **PASS** |
| 17 | **Consecutive loss halt** | Halts trading after 5 consecutive losses | Blocked: CONSECUTIVE_LOSS_HALT | **PASS** |
| 18 | **Max position limit** | Blocks new orders when 3 positions are open | Blocked: MAX_POSITIONS_REACHED | **PASS** |

---

## 3. Operational Guarantees

1. **Fail-Closed Policy**: Any uncertainty, malformed data, or network failure causes zero new orders to be created.
2. **Broker as Single Source of Truth**: On restart and every cycle, open positions are synced directly with the broker.
3. **Zero Orphan Residue**: Untracked broker positions are auto-discovered and integrated into local risk accounting.
4. **Immutability of Frozen Rules**: AI has zero authority to alter risk limits or override kill switches.
