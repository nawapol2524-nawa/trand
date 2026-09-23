# Decision Trace Specification (v1.0.0)
**Purpose**: Full auditability, regulatory compliance, and deterministic historical replay for all AI decisions.

---

## 1. Core Principles
1. **Append-Only & Tamper-Evident**: Every AI invocation emits exactly one JSON record to `logs/decision_traces.jsonl`.
2. **Deterministic Replay**: Given an identical `context_summary`, the recorded proposal can be re-evaluated offline without contacting any live AI endpoint.
3. **Zero Secret Leakage**: Sanitizers strictly filter all keys containing `key`, `token`, `secret`, `password`, or `auth`.

---

## 2. Record Schema

```json
{
  "trace_id": "trace_a1b2c3d4e5f6",
  "timestamp": "2026-09-23T11:20:00.000000+00:00",
  "event_id": "evt_bos_long_001",
  "provider": "openai/gpt-4o-mini",
  "model": "gpt-4o-mini",
  "input_schema_version": "1.0",
  "output_schema_version": "1.0",
  "context_summary": {
    "symbol": "EURUSD",
    "timeframe": "M5",
    "price": 1.14250,
    "trend": "BULLISH",
    "rsi": 54.2,
    "market_structure": "BOS_LONG"
  },
  "proposal": {
    "decision": "APPROVE",
    "direction": "LONG",
    "confidence": 0.85,
    "invalidation": "Close below 1.13900",
    "rationale": "Bullish structure continuation after BOS",
    "scenario": "BULLISH_CONTINUATION"
  },
  "validation_result": {
    "passed": true,
    "decision": "APPROVED",
    "reason": "All deterministic gate checks passed",
    "checks": {
      "schema_complete": true,
      "data_fresh": true,
      "kill_switch_clear": true,
      "daily_loss_within_limit": true,
      "position_limit_ok": true,
      "news_window_clear": true,
      "confidence_sufficient": true,
      "trend_alignment": true
    }
  },
  "risk_result": {
    "approved": true,
    "adjusted_volume": 0.01,
    "sl_price": 1.13900,
    "tp_price": 1.14800
  },
  "execution_result": {
    "status": "FILLED",
    "broker_order_id": "ord_998877",
    "fill_price": 1.14252
  }
}
```

---

## 3. Storage & Retention
* File format: JSON Lines (`.jsonl`)
* Rotation policy: daily or 50MB per chunk
* Replay tooling: `src/services/decision_trace.py` loads records sequentially for simulation tests.
