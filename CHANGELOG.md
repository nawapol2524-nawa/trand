# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
