# Project Inventory — AI Forex Autonomous Trading System

**Audit Timestamp:** 2026-09-18T14:55:00+07:00  
**Repository Baseline:** Clean-room institutional reconstruction from Gate 1 Parquet datasets  

---

## 1. Existing Architecture & Directory Layout

The workspace has transitioned from an unversioned monolithic script (`main_forex.py` ~1,992 lines) to a clean, institutional layered modular system:

```text
TradingBot_Workspace/
├── ai_forex_bot/               # Core institutional Python package
│   ├── config/                 # System & trading configurations
│   ├── data/                   # Data ingestion, schemas, and validation
│   ├── market/                 # Market regime, technical indicators, sessions
│   ├── features/               # Multi-timeframe leak-free feature engineering
│   ├── labels/                 # Cost-aware triple barrier / horizon labeling
│   ├── ai/                     # BaseModel, training, evaluation, registry
│   ├── news_ai/                # Economic calendar & news NLP contextualization
│   ├── strategy/               # Quant & AI hybrid strategy decision engines
│   ├── decision/               # Meta-decision signal filter (AI + Market + News)
│   ├── risk/                   # Independent Risk Engine & Capital Impairment Guard
│   ├── portfolio/              # Cross-currency exposure & correlation matrix
│   ├── execution/              # Broker execution abstraction & order FSM
│   ├── backtest/               # Cost-aware backtesting with slippage/swap/spread
│   ├── monitoring/             # System health, telemetry, and kill switch
│   └── reporting/              # Institutional metrics, performance, and risk
├── data/                       # Parquet data lake (raw, clean, features, labels)
├── configs/                    # Declarative YAML configs (symbols, models, risk)
├── artifacts/                  # Saved models, encoders, and calibration objects
├── reports/                    # Audit reports, leakage audits, data quality reports
├── scripts/                    # Command-line workflows (train, evaluate, etc.)
├── docs/                       # Complete engineering documentation
└── tests/                      # Unit, integration, regression, and leakage tests
```

---

## 2. Dependencies

| Package | Version Baseline | Role |
| :--- | :--- | :--- |
| `numpy` | `>=1.26.4` | High-performance numerical computations |
| `pandas` | `>=2.2.0` | Time series manipulation and tabular datasets |
| `pyarrow` | `>=16.0.0` | High-speed Parquet serialization and column storage |
| `scikit-learn` | `>=1.4.2` | Machine learning algorithms, scalers, and probability calibration |
| `scipy` | `>=1.13.1` | Statistical distributions and hypothesis testing |
| `joblib` | `>=1.4.0` | Threaded serialization and pipeline persistence |
| `pyyaml` | `>=6.0` | Human-readable configuration management |
| `requests` | `>=2.31.0` | HTTP client for economic calendar and news scraping |
| `websockets` | `>=12.0` | Real-time WebSocket streaming for broker connectivity |
| `python-dotenv`| `>=1.0.0` | Secure environment variable injection |

---

## 3. Component Categorization

### A. Reusable Components (from verified legacy audits)
1. **Deriv WebSocket Protocol:** WebSocket request framing and ping/pong keepalive logic.
2. **Approved Gate 1 Historical Parquet Files:**
   - `frxXAUUSD_M1_20250918_20260918.parquet` (`f88e1b52...`)
   - `frxEURUSD_M1_20250918_20260918.parquet` (`e8d8f44f...`)
   - `frxGBPUSD_M1_20250918_20260918.parquet` (`3f3aa830...`)
   - `frxUSDJPY_M1_20250918_20260918.parquet` (`8ff85947...`)
3. **Daily Reset & Kill Switch Logic:** Transitioning UTC midnight boundary unlatch mechanism verified in Gate 3 audit.
4. **Per-Symbol Spread Gate:** Distinct thresholds per instrument avoiding catastrophic single-parameter slippage.

### B. Obsolete Components (Quarantined)
1. **Monolithic `main_forex.py`:** Mixed GUI, trading, scraping, order execution, and LLM calls in one 2,000-line script.
2. **Hard-coded thresholds:** Fixed PIP values embedded in control loops rather than externalized in YAML.
3. **Uncalibrated AI Scoring:** Naive sentiment prompting where LLM was granted raw BUY/SELL decision power without feature grounding.

### C. Risky Components (Remediated by Architecture)
1. **Look-Ahead Bias in Legacy Indicator Loops:** Previous indicators calculated rolling statistics across whole series without strict `.shift(1)` bar-close guarantees.
2. **Fee Drag Unawareness:** Legacy signals ignored realistic spread and commission, generating 29x fee-to-edge drag on small targets.

### D. Missing Components (Implemented in Current Reconstruction)
1. Layered AI Model Hierarchy (Regime + Directional + News Impact + Decision Filter).
2. Automated Leakage Audit Test Suite (shifted feature, target contamination, train/test split leakage).
3. Walk-Forward Rolling Evaluation Engine.
4. Systematic Model Registry with experiment versioning.
5. Calibrated Probabilities (Platt / Isotonic) with Brier scoring.
