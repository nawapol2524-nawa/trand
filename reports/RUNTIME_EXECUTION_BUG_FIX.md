# Runtime Execution Bug Fix Report
**Deployment ID:** `5e0dee93-82da-40bb-9d79-02b2555f7d2d`  
**Date:** 2026-09-25  
**Error:** `Unhandled error in execution cycle: 'dict' object has no attribute 'to_dict'`

---

## 1. Executive Summary

During live DEMO execution on Railway (Deployment `5e0dee93-82da-40bb-9d79-02b2555f7d2d`), the bot encountered an unhandled exception immediately after Deterministic Gate approval:
```text
GBPUSD
MARKET_DATA ACQUIRED
→ STRATEGY SIGNAL_GENERATED
→ AI PROPOSAL_GENERATED / APPROVE
→ GATE APPROVED
→ ERROR: "Unhandled error in execution cycle: 'dict' object has no attribute 'to_dict'"
```

This bug prevented execution from reaching Risk Engine evaluation, broker order placement (`broker.create_market_order`), and post-trade state reconciliation.

The root cause was identified, isolated with an exact regression test, and fixed cleanly without modifying any strategy logic, risk models, AI policies, or trading parameters.

---

## 2. Root Cause Analysis

### 2.1 Code Location
- **File:** `src/app/runner.py`
- **Line:** 559 (prior to patch)
- **Call site:**
  ```python
  risk_decision = self.risk_engine.evaluate_order(
      symbol=symbol,
      direction=sig.direction,
      entry_price=sig.price,
      atr_val=atr_val,
      equity=equity,
      daily_starting_balance=daily_starting_bal,
      daily_pnl=daily_pnl,
      consecutive_losses=consecutive_losses,
      halt_until=halt_until,
      open_positions=[p.to_dict() for p in self.state_mgr.state.open_positions.values()],
      data_timestamp=candle_close_time(m5_bars[0].timestamp, Timeframe.M5),
      now=now_utc,
      lot_size_units=sym_info.get("lot_size", 100000.0),
  )
  ```

### 2.2 Mechanism of Failure
1. In `src/services/state_manager.py`, `BotRuntimeState.open_positions` is defined as `Dict[str, Dict[str, Any]]`.
2. When the bot connects to the broker or performs startup reconciliation (`reconcile_with_broker`), active positions returned from the broker MCP or loaded from `bot_state.json` are stored directly as standard Python dictionaries (`dict`).
3. Calling `.to_dict()` on a Python `dict` raises `AttributeError: 'dict' object has no attribute 'to_dict'`.
4. In earlier pipeline tests, `state_mgr.state.open_positions` happened to be empty (`{}`), so the list comprehension had 0 items and never evaluated `p.to_dict()`. The moment the demo account had at least one tracked or orphan open position, the iteration attempted `p.to_dict()`, causing an unhandled crash during the execution cycle.

---

## 3. Engineering Fix

### 3.1 `src/app/runner.py`
1. Added helper function `_normalize_position_dict(p: Any) -> Dict[str, Any]`:
   - Checks if `p` is `dict`, has `to_dict()`, or is a dataclass via `is_dataclass(p)`.
   - Normalizes numeric broker `symbolId` values (e.g. `"2"` for GBPUSD) to canonical symbol strings (`GBPUSD`), ensuring risk exposure calculations evaluate properly.
2. Replaced `[p.to_dict() for p in ...]` with `[_normalize_position_dict(p) for p in self.state_mgr.state.open_positions.values()]`.
3. Hardened `open_symbols` calculation to resolve both position IDs and mapped symbol names from existing open positions.

### 3.2 `src/services/decision_trace.py`
Defensively hardened line 68 so `proposal` accepts `dict`, objects with `to_dict()`, or dataclasses without raising `AttributeError`.

---

## 4. Regression Test & Verification

1. **Regression Test Added:**
   `tests/integration/test_runner_pipeline.py::test_16_regression_open_positions_dict_serialization`
   - Setup: Injects open position as a Python `dict` into `state_mgr.state.open_positions`.
   - Execution: Triggers `runner.execute_cycle()` with valid signal + AI approval + Gate approval.
   - Result on unpatched code: **FAILED** with `AttributeError: 'dict' object has no attribute 'to_dict'`.
   - Result on patched code: **PASSED** — pipeline progresses to `broker.create_market_order` and completes cycle.

2. **Full Test Suite:**
   - 110 passed out of 110 tests (including 16 integration runner pipeline tests).
   - Zero syntax/compilation errors (`python3 -m compileall -q src tests`).

---

## 5. Constraint Compliance Verification

- **Strategy Parameters / Logic:** Unchanged (0 changes to indicators, BOS, periods, or signals).
- **Risk Model:** Unchanged (0 changes to risk formulas, daily loss limits, or exposure limits).
- **AI Policy:** Unchanged (0 changes to prompts, scenarios, or confidence gates).
- **Deterministic Gate:** Unchanged (preserves strict validation and fail-closed design).
- **Trading Mode:** `DEMO` only; `LIVE_TRADING_ENABLED=false` strictly enforced.
