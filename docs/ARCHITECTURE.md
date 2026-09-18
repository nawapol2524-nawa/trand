# Institutional Architecture — AI Forex Autonomous Trading System

## 1. Core Design Principles

The system is strictly partitioned into single-responsibility decoupled layers:
```text
                  REAL HISTORICAL DATA
                           │
                           ▼
                  DATA VALIDATION
                           │
                           ▼
                TIMESTAMP ALIGNMENT (UTC)
                           │
                           ▼
                  FEATURE ENGINE
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
       MARKET FEATURES             NEWS FEATURES
              │                         │
              └────────────┬────────────┘
                           ▼
                    REGIME ENGINE
                           │
                           ▼
                     LABEL ENGINE (Cost-Aware)
                           │
                           ▼
                 LEAKAGE AUDIT
                           │
                           ▼
             TRAIN / VALIDATE / TEST (Temporal)
                           │
                           ▼
                    AI TRAINING (Layered Models)
                           │
                           ▼
                 PROBABILITY CALIBRATION
                           │
                           ▼
                   WALK-FORWARD VALIDATION
                           │
                           ▼
                     EVALUATION (Classification & PnL Metrics)
                           │
                           ▼
                  MODEL REGISTRY (Versioned Artifacts)
                           │
                           ▼
                    TRAINING-READY
```

And in future deployment, the exact same inference pipeline feeds:
```text
TRAINED MODEL → LIVE DATA → FEATURES → REGIME → NEWS → AI → DECISION → RISK → EXECUTION → BROKER → POSITION → AUDIT
```

## 2. Layer Responsibilities & Isolation Invariants

1. **AI Isolation:** The AI models NEVER interact with the broker API, credentials, or order dispatch directly. They output pure probability distributions and confidence metrics.
2. **Decision Engine:** Translates model outputs and environmental contexts into trade intents (`BUY`, `SELL`, `HOLD`, `NO_TRADE`).
3. **Risk Engine:** Acts as an absolute veto gatekeeper. Every proposed order is evaluated against daily loss limits, maximum drawdown, position concentration, and current spread.
4. **Execution Engine:** Manages order lifecycles through a deterministic Finite State Machine (FSM) with reconciliation against the broker.
5. **No Look-Ahead Guarantee:** Feature engineering strictly consumes data available strictly prior to the current decision epoch.
