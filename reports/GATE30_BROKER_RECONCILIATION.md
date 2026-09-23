# GATE 30 — Broker Execution-Path Reconciliation Report
**Date**: 2026-09-23  
**Status**: VERIFIED & RECONCILED (DEMO ENVIRONMENT ONLY)  
**Broker Host**: `mcp.ctrader.com/trading/mcp` (Deriv cTrader)  

---

## 1. Authoritative Production Execution Pipeline

```
[ Market Data ] 
       │  cTrader Remote MCP (get_spot_prices / get_trendbars)
       ▼
[ Closed Candle Normalization ]
       │  src/core/clock.py (strictly closed bars, monotonic UTC)
       ▼
[ Feature Calculation & Pattern Recognition ]
       │  src/core/indicators.py (Wilder RSI, EMA, ATR)
       │  src/core/signals.py (BOS N=20, Pinbar, Engulfing)
       ▼
[ Forward-Looking Scenario Book ]
       │  src/core/scenarios.py (State machine: PLANNED -> ACTIVE -> COMPLETED)
       ▼
[ Event-Driven Invocation Filter ]
       │  src/ai/event_detector.py (Filters 99% of ticks; invokes only on BOS/Regime)
       ▼
[ Normalized Context Pipeline ]
       │  src/ai/context.py (Compiles compact numeric JSON; zero LLM raw math)
       ▼
[ Universal AI Proposal Layer ]
       │  src/ai/provider.py (Failover: Groq -> OpenAI -> OfflineDeterministicAIProvider)
       ▼
[ Deterministic Gatekeeper (FAIL-CLOSED) ]
       │  src/ai/validator.py (Strict schema, staleness <60s, trend & news check)
       ▼
[ Deterministic Risk Guardian ]
       │  src/core/risk.py (1% equity risk, 5% daily loss limit, kill switch)
       ▼
[ Execution Adapter ]
       │  src/brokers/ctrader_mcp.py (create_market_order, amend, close)
       ▼
[ Broker State Reconciliation ]
          src/brokers/ctrader_mcp.py (Authoritative get_positions & get_balance)
```

---

## 2. Broker Symbol Specification & Sizing Rules

| Instrument | Symbol ID | Class | Lot Size | 0.01 Lot Volume Units | Digits / Scale | Verified Live Quotes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **EURUSD** | `1` | Forex | 100,000 | `100,000` | 5 (`/ 100,000`) | Bid `1.14269` / Ask `1.14280` |
| **GBPUSD** | `2` | Forex | 100,000 | `100,000` | 5 (`/ 100,000`) | Bid `1.33151` / Ask `1.33163` |
| **USDJPY** | `4` | Forex | 100,000 | `100,000` | 5 (`/ 100,000`) | Bid `157.630` / Ask `157.645` |
| **XAUUSD** | `41` | Metals| 100 | `100` | 5 (`/ 100,000`) | Bid `4338.25` / Ask `4338.43` |

> **Critical Sizing Rule**: Volume in cTrader MCP is expressed in $1/100$ base-asset units:
> $$\text{Volume} = \text{Lots} \times \text{LotSize} \times 100$$
> Reusing Forex `10,000,000` for XAUUSD results in a catastrophic $1000\times$ oversized position. Sizing logic strictly branches on asset class.

---

## 3. Empirical Demo Order Lifecycle Verification

A live, automated end-to-end execution test was performed on Deriv cTrader Demo Account `2548625`:

| Step | Operation | Parameters / Request | Broker Response | Evidence / ID |
| :--- | :--- | :--- | :--- | :--- |
| **1** | Handshake | `initialize` (protocol 2024-11-05) | `200 OK` | Session: `eb01d55e-...` |
| **2** | Pre-check | `get_positions` | `0 open positions` | Account Clean |
| **3** | Submit Order | `create_order` (0.01 lot EURUSD BUY) | `ORDER_ACCEPTED` | **Order ID: `44624448`** |
| **4** | Discovery | `get_positions` | `1 position active` | **Position ID: `139550911`**, Entry: `1.14268` |
| **5** | Amend SL | `amend_position` (SL $\rightarrow$ 1.14118) | `ORDER_REPLACED` | New SL Confirmed |
| **6** | Close Order | `close_position` (vol 100,000) | `ORDER_CANCELLED` | Remaining Vol: `0` |
| **7** | Reconcile | `get_positions` | `0 open positions` | Reconciliation Confirmed |

---

## 4. Restart & Recovery Architecture

* **Zero Trust in Local Cache**: Upon process startup, the bot queries `get_positions` and `get_balance` directly from the broker.
* **No Phantom Orders**: Any discrepancy between internal memory and broker API is reconciled immediately by adopting broker state as authoritative truth.
