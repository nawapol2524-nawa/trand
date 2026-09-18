# AI & Machine Learning Architecture

## 1. Multi-Layer AI Model Hierarchy
The system explicitly avoids monolithic end-to-end "black box" models. Instead, predictions are layered:

```text
┌──────────────────────────────────────────────────────────────┐
│                       INPUT FEATURES                         │
└──────────────────────────────┬───────────────────────────────┘
                               │
       ┌───────────────────────┼───────────────────────┐
       ▼                       ▼                       ▼
┌──────────────┐       ┌──────────────┐        ┌──────────────┐
│   MODEL A    │       │   MODEL B    │        │   MODEL C    │
│Market Regime │       │ Directional  │        │ News & Event │
│ Classifier   │       │ Probabilities│        │   Context    │
└──────┬───────┘       └──────┬───────┘        └──────┬───────┘
       │                      │                       │
       └──────────────────────┼───────────────────────┘
                              ▼
               ┌──────────────────────────────┐
               │    META-DECISION ENGINE      │
               │ (Probability Calibration &   │
               │     Threshold Gating)        │
               └──────────────┬───────────────┘
                              ▼
               ┌──────────────────────────────┐
               │        TRADING SIGNAL        │
               │   (BUY / SELL / HOLD /       │
               │          NO_TRADE)           │
               └──────────────────────────────┘
```

### Model A: Market Regime Classifier
- **Role:** Identifies structural market phases (`TREND_UP`, `TREND_DOWN`, `RANGE`, `HIGH_VOLATILITY`, `LOW_VOLATILITY`, `UNCERTAIN`).
- **Implementation:** Rule-based ADX / Dual EMA / Rolling Volatility baseline, with extensible interface for Unsupervised Gaussian Mixture Models or Hidden Markov Models.

### Model B: Directional / Horizon Prediction Model
- **Role:** Generates posterior probability distribution over future cost-aware outcomes: $[P(\text{HOLD}), P(\text{BUY}), P(\text{SELL})]$.
- **Implementations:** `HistGradientBoostingModel`, `RandomForestModel`, `LogisticRegressionModel`.

### Model C: News & Event Impact Engine
- **Role:** Tracks macroeconomic calendar releases (forecast vs actual surprises) and causal news sentiment.
- **Guardrail:** Pre-event blackout windows and post-event stabilization periods automatically suppress trade generation.

### Model D: Meta-Decision Filter
- **Role:** Blends Model A, B, and C outputs. High model probability cannot trigger orders if regime is `HIGH_VOLATILITY` or economic policy is `BLACKOUT`.
- Emits `NO_TRADE` gracefully when conditions fail risk gates.
