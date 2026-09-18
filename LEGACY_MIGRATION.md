# Legacy Migration & Isolation Audit

## 1. Migration Protocol

All historical files and previous experiments have been safely sequestered in:
`/Users/nawaphonkoedbua/Desktop/TradingBot_Workspace.zip` (Sep 18, 2026 archive)

## 2. Reusable vs. Quarantined Modules

| Legacy Module | Status | Migration Action |
| :--- | :--- | :--- |
| `main_forex.py` | **QUARANTINED** | Deconstructed into modular packages (`execution/`, `risk/`, `strategy/`, `news_ai/`). Monolithic file is retired. |
| `backtest_engine.py` | **REFACTORED** | Ported into `ai_forex_bot/backtest/` with strict alignment to the live execution FSM and cost models. |
| `capital_vault.py` | **REFACTORED** | Ported into `ai_forex_bot/risk/capital_vault.py` as an institutional treasury sweep sub-module. |
| `data/historical/*.parquet` | **PRESERVED** | Extracted and verified bit-for-bit into `data/market/raw/` with matching SHA-256 hashes. |
| `.env` | **MIGRATED** | Preserved securely; `.env.example` created without secret exposure. |

## 3. Ambiguities & Resolution Log

- **AMBIGUITY 1: Spread Units on Gold vs Forex**
  - *Legacy Issue:* A global spread limit of 1.8 pips caused severe blocking on Gold (where spread is expressed in points/dollars).
  - *Resolution:* Per-symbol spread configuration (`configs/symbols.yaml`) specifying exact acceptable spreads per instrument.
- **AMBIGUITY 2: Daily Reset Latches**
  - *Legacy Issue:* Daily kill switch was previously evaluated only on trade closures, creating sticky latches on zero-trade days.
  - *Resolution:* Calendar timeline date boundary listener evaluating UTC midnight transition on every market tick.
