# AI Forex Autonomous Trading System (AG 2.0 Institutional)

An enterprise-grade, leakage-free, multi-timeframe quantitative trading architecture built for institutional forex and gold markets.

## Current State: TRAINING-READY (Phase 1 Complete)
- **Zero Lookahead Guarantee:** Causal indicator and feature computation verified with automated test suites.
- **Cost-Aware Labeling:** Triple-barrier target generation factoring in spread, commissions, and slippage.
- **Layered Architecture:** Independent Data, Feature, Regime, AI, Meta-Decision, Risk, and Execution modules.
- **Zero Secrets Committed:** Environment variables strictly isolated.

## Quick Start
```bash
# 1. Inspect environment variables
python3 cli.py inspect-env

# 2. Run data leakage audit
python3 cli.py run-leakage-audit

# 3. Train model on EUR/USD M15
python3 cli.py train --symbol frxEURUSD --timeframe M15

# 4. Run walk-forward validation
python3 cli.py walk-forward --symbol frxEURUSD --timeframe M15 --splits 3

# 5. Run full test suite
python3 -m unittest discover -s tests -p "test_*.py"
```
