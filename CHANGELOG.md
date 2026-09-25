# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.3.0] - 2026-09-25

### Profit Acceleration Suite (Quantitative Triad)

This release implements the approved **Profit Acceleration Suite (v1.3.0)**, boosting bot profit expectancy and convex equity growth without altering base strategy indicators or exceeding risk limits:

### Added
- **Pillar 1: Institutional High-Liquidity Session Filter**
  - Restricts new position entries to London (`07:00–11:30 UTC`) and New York / Overlap (`12:30–16:30 UTC`) high-volume sessions.
  - Off-hours / Asian session trades are rejected by `DeterministicGate.validate()` (`session_active=False`) when `ENFORCE_SESSION_FILTER=true`, filtering out low-liquidity false breakouts and wide spreads.
  - Active positions continue to be monitored, protected, and trailed 24/7.
- **Pillar 2: Conviction-Weighted Dynamic Sizing**
  - Standard Conviction trades (AI Confidence 65%–84%): Base 1.0% equity risk per trade.
  - High Conviction A+ setups (AI Confidence >= 85% + H1 regime alignment + < 3 consecutive losses): Scale risk up to 1.5% equity per trade (+50% profit acceleration).
  - Risk is automatically clamped by Multi-Level Defense (e.g. Level 1 halves position size to 0.75% during >= 2.5% intraday drawdown).
- **Pillar 3: Convex Asymmetric Exit Engine**
  - **Phase 1 (Partial Take Profit):** When price advances to $+1.5R$, automatically closes 50% position volume via cTrader MCP `close_position()`, locking in cash profits.
  - **Phase 2 (Break-Even Lock):** Immediately amends Stop Loss to `entry_price` via cTrader MCP `amend_position()`, turning the remaining 50% volume into a completely risk-free runner ($0 risk).
  - **Phase 3 (Trailing ATR Runner):** Trails the remaining 50% volume using $1.5 \times \text{ATR}$ with a monotonic upward ratchet rule (never moving backwards).
- **Schema & Persistence Upgrade (v1.3)**
  - Updated `SCHEMA_VERSION = "1.3"` and `SYSTEM_VERSION = "1.3.0"`.
  - Added tracking fields to `PositionState`: `original_volume`, `partial_tp_hit`, `break_even_set`, `trailing_stop_active`, `highest_favorable_price`, `atr_at_entry`, `sl_distance`.
  - Added runtime event emissions: `PARTIAL_TP_EXECUTED` and `TRAILING_STOP_UPDATED`.
- **Comprehensive Test Suite**
  - Added 14 comprehensive tests in `tests/unit/test_profit_acceleration.py`.
  - Achieved 100% test pass rate across 138 total tests (124 existing + 14 new).

---

## [1.2.0] - 2026-09-25

### Architecture Upgrade & Risk Hardening Release

This release introduces institutional-grade defensive controls, thread-safe atomic persistence, higher-timeframe regime alignment, post-trade loss classification, and complete Git lineage traceability across all orders, audit traces, and telemetry.

### Added
- **Module 1: Atomic State & Schema Migration**
  - Thread-safe state persistence using `threading.Lock()` and unique per-write temporary files (`bot_state_{uuid}.tmp`).
  - Added `schema_version = "1.2"` to `BotRuntimeState` with automated backward-compatible migration for legacy states.
- **Module 2: Pre-Trade Spread Guard & Slippage Guard**
  - Added per-symbol `max_spread_pips` configuration (`EURUSD`: 2.0, `GBPUSD`: 2.5, `USDJPY`: 2.5, `XAUUSD`: 50.0).
  - Pre-trade spread validation in `RiskEngine.evaluate_spread()` and `RiskEngine.evaluate_order()`, automatically blocking trade execution if live spread exceeds threshold (`SPREAD_TOO_HIGH`).
  - Execution slippage tracking in points/pips recorded on every filled market order.
- **Module 3: Multi-Level Defense Mode (Levels 0–4)**
  - **Level 0 (Normal):** Standard 1.0% risk per trade sizing.
  - **Level 1 (Defensive):** Triggers when intraday drawdown reaches >= 2.5%, automatically halving allocated position size (0.5% risk) to preserve equity.
  - **Level 2 (Restricted):** Triggers upon 3 consecutive losses, elevating required AI proposal confidence threshold from 65% to 80% in `DeterministicGate`.
  - **Level 3 (Halt):** Enforces 1-hour cooling halt upon 5 consecutive losses or 5% maximum daily loss limit breach.
  - **Level 4 (Emergency):** Emergency kill switch gate preventing all executions when active.
- **Module 4: Higher Timeframe Regime Filter for Forex**
  - Injected H1 trendbars (up to 70 bars) for Forex pairs (`EURUSD`, `GBPUSD`, `USDJPY`) to compute H1 EMA50 trend bias (`BULLISH` vs `BEARISH`).
  - Integrated H1 regime into `AIContext` and `DeterministicGate` to prevent trading counter to higher timeframe momentum unless an explicit structural breakout/reversal scenario is confirmed.
- **Module 5: Post-Trade Loss Reason Classifier**
  - Created `src/core/loss_classifier.py` categorizing trade losses into root causes:
    - `SPREAD_COST`: Fast exit dominated by spread friction.
    - `NEWS_EVENT`: Loss occurring during or near high-impact macroeconomic news volatility.
    - `SLIPPAGE_IMPACT`: Execution slippage significantly impacting entry/exit price.
    - `REGIME_REVERSAL`: Higher timeframe regime reversal contrary to trade direction.
    - `NORMAL_STRATEGY_LOSS`: Standard strategy stop loss hit under normal market conditions.
  - Tagged loss reasons in `StateManager.record_closed_position` and persistent closed trade ledger history.
- **Module 6: Version Control & Git Lineage**
  - Created `src/core/version.py` establishing `SYSTEM_VERSION = "1.2.0"` and `SCHEMA_VERSION = "1.2"`.
  - Automated Git SHA discovery from Railway environment variables (`RAILWAY_GIT_COMMIT_SHA`) and local git CLI.
  - Broker order comment tagging: `Bot_{symbol}_v1.2.0_{git_sha}`.
  - Embedded system version and Git SHA into `health.json`, `decision_traces.jsonl`, and `TradeRecord`.
- **Module 7: Verification & Test Suite**
  - Added 14 unit and integration tests in `tests/unit/test_version_and_guards.py`.
  - Achieved 100% test pass rate across 124 total tests.

### Strategy Integrity Guarantees
- Strategy baseline logic (indicator periods, BOS lookback N=20, candlestick pattern definitions) remains completely frozen and unmodified.
- Baseline 1.0% risk formula and 5.0% daily maximum loss limit remain intact.
- Timeframe remains strictly Fixed M5.
- `TRADING_MODE` defaults to `DEMO` / `PAPER` with `LIVE_TRADING_ENABLED=false` safety lock.
