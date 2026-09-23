# System Architecture Specification
**System**: Deriv cTrader Quantitative Trading Bot  
**Target Instruments**: XAUUSD, EURUSD, GBPUSD, USDJPY  
**Target Runtime**: Python 3.11+ / Docker Linux Production  

---

## 1. High-Level Architecture Overview

The system is structured as a decoupled, multi-tier quantitative trading engine:

```
[ Market Data Feed ]
        │  (cTrader Remote MCP / Historical Data)
        ▼
[ Core Data & Time Tier ]
        │  src/core/models.py, clock.py (Closed Candles Only, UTC)
        ▼
[ Deterministic Feature Tier ]
        │  src/core/indicators.py (Wilder RSI, EMA, ATR)
        │  src/core/signals.py (BOS N=20, Pinbar, Engulfing)
        ▼
[ Scenario & Strategy Tier ]
        │  src/core/scenarios.py (Scenario Book Lifecycle)
        │  src/strategies/xau_mean_reversion.py
        │  src/strategies/forex_trend_breakout.py
        ▼
[ Event Detector & Universal AI Tier ]
        │  src/ai/event_detector.py (Filters non-events)
        │  src/ai/context.py (Normalized Context Pipeline)
        │  src/ai/provider.py (OpenAI / Offline Deterministic Provider)
        ▼
[ Deterministic Gatekeeper ]
        │  src/ai/validator.py (Fail-closed schema, freshness, trend validation)
        ▼
[ Risk Management Tier ]
        │  src/core/risk.py (Hard limits: 1% risk, 5% daily loss, kill switch)
        ▼
[ Broker Execution Tier ]
        │  src/brokers/ (cTrader Remote MCP / Spotware Client)
```

---

## 2. Key Architectural Guarantees
1. **No Lookahead Bias**: Indicators and strategies consume exclusively closed bars.
2. **Single Source of Truth**: Math calculations are implemented once in `src/core/indicators.py` and reused across backtest, paper, and live.
3. **AI Is Advisory Only**: AI outputs a `TradeProposal`. It cannot submit orders, mutate risk parameters, or override safety stops.
4. **Independent Risk Guardian**: The Risk Engine has absolute veto power over every signal and proposal.
5. **Deterministic Replay**: Every decision logs an immutable record with a unique `trace_id` in `logs/decision_traces.jsonl`.
