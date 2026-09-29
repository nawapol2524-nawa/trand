# AI Decision Architecture Audit Report

**Date**: 2026-09-27  
**Scope**: Full-system audit, refactoring, and verification of the Trading Decision Architecture.  
**Strategy Logic Status**: Unaltered (EMA 9/21/200, Wilder RSI, ATR 14, BOS N=20 preserved with zero parameter drift).  
**Overall Architectural Status**: **PASS**

---

## 1. Executive Summary & Target Architecture

The trading bot's decision pipeline has been audited and refactored from an inverted gatekeeper structure into an institutional-grade, multi-stage quantitative pipeline where non-deterministic AI acts strictly as an advisory/context enrichment layer, with absolute veto authority held by the Deterministic Risk & Execution Gate.

### Pipeline Comparison

```
Previous Architecture:
Market Data → Technical Signal → AI Gatekeeper (Veto/Approve) → Deterministic Gate → Broker Order

Target Institutional Architecture (Implemented):
Market Data
    │
    ▼
Technical Signal (M5 Pullback, BOS, Wilder RSI, EMAs)
    │
    ▼
ML / Quantitative Signal & Regime Evaluator
    │
    ▼
LLM Advisory & Context Layer (Groq / OpenAI — Advisory ONLY, Zero Final Authority)
    │
    ▼
Deterministic Risk & Execution Gate (Hard Veto over Spread, Slippage, News, Drawdown, Daily Loss, Circuit Breaker)
    │
    ▼
FINAL DECISION (BUY, SELL, HOLD, BLOCK)
    │
    ▼
Broker Execution Layer (Deriv / cTrader Fix API)
```

---

## 2. Core Architectural Invariants Established

1. **LLM Advisory Restriction**:
   - The LLM layer is strictly decoupled from broker execution. LLM output produces a `TradeProposal` advisory (`APPROVE`, `REJECT`, `HOLD`, `PASS`, `UNAVAILABLE`), never an executable order.
   - `llm_confidence` is explicitly segregated from `ml_probability`. `llm_confidence` is purely subjective advisory metadata and has zero mathematical authority to inflate position sizing or override risk boundaries.
2. **Deterministic Gate Absolute Veto**:
   - The Deterministic Gate evaluates hard capital-preservation constraints before order routing.
   - Hard blocks unconditionally override LLM approvals:
     - News blackout window active (`BLOCK_NEWS`)
     - Spread exceeds symbol threshold (`BLOCK_SPREAD`)
     - Slippage exceeds threshold (`BLOCK_SLIPPAGE`)
     - Account intraday drawdown limit breached (`BLOCK_DAILY_LOSS`)
     - Consecutive loss circuit breaker active (`BLOCK_CIRCUIT_BREAKER`)
     - Maximum concurrent or symbol exposure limit reached (`BLOCK_DUPLICATE`)
     - Stale market data or bar age (`BLOCK_STALE_SIGNAL`)
     - Out of approved trading sessions (`BLOCK_SESSION_OFF_HOURS`)
     - Emergency kill switch active (`BLOCK_KILL_SWITCH`)
3. **Explicit Failover Policy**:
   - Provider cascade: `Groq (Llama-3.3-70b)` → `OpenAI (GPT-4o-mini)` → Explicit `LLM_UNAVAILABLE` advisory state (or `DeterministicDecisionEngine` for offline backtesting).
   - In production live mode, if all LLM providers fail, the system records `ProposalDecision.UNAVAILABLE` with reason `LLM_UNAVAILABLE`, preventing silent unauthorized execution.
4. **Standardized Taxonomy Normalization**:
   - All gate and risk engine rejections produce canonical `BlockReason` codes (`BLOCK_*`).
   - `NormalizedBlockReason` provides bidirectional normalization with legacy error strings (`KILL_SWITCH_ACTIVE`, `CONSECUTIVE_LOSS_HALT`, `DAILY_LOSS_LIMIT`, `SPREAD_TOO_HIGH`, `SYMBOL_EXPOSURE_LIMIT`, `MAX_POSITIONS_REACHED`, `STALE_DATA`) ensuring 100% backward compatibility with existing tests and audit archives.

---

## 3. Files Modified & Summary of Changes

| File | Primary Changes |
| :--- | :--- |
| `src/ai/schemas.py` | Added `FinalDecision` (`BUY`, `SELL`, `HOLD`, `BLOCK`), canonical `BlockReason` taxonomy, `NormalizedBlockReason(str)` with alias mapping, `normalize_block_reason()`, and enriched `TradeProposal` with separated `llm_confidence`, `ml_probability`, `llm_decision`, `final_decision`, `block_reason`. |
| `src/ai/provider.py` | Renamed `OfflineDeterministicAIProvider` to `DeterministicDecisionEngine` (with legacy alias preserved), added `is_available()` methods, updated `GroqProvider` and `OpenAIProvider` to populate separated fields, enhanced `FailoverAIProvider` with explicit `LLM_UNAVAILABLE` state and provider tracking. |
| `src/ai/validator.py` | Refactored `DeterministicGate.validate` to enforce absolute veto over LLM approvals, return typed `final_decision` (`FinalDecision`) and canonical `block_reason` (`BlockReason`), evaluate spot spread and slippage before execution. |
| `src/core/risk.py` | Standardized `evaluate_order` block reasons to use `normalize_block_reason(...)`, maintained discrete frozen high-conviction tier sizing (1.5% vs base 1.0% strictly gated by H1 alignment and < 3 consecutive losses, with zero continuous LLM multiplier). |
| `src/app/runner.py` | Re-ordered pipeline: market data → technical signal → AI advisory proposal → spot spread pre-fetch → Deterministic Gate final authority check → log trace → risk sizing → execution. |
| `src/services/decision_trace.py` | Updated `log_decision` schema to persist `final_decision`, `block_reason`, `llm_confidence`, and `ml_probability` to immutable trace JSON lines. |
| `tests/unit/test_ai_decision_architecture.py` | Added 13 new unit tests covering Section 14 (Determinism), Section 15 (Provider Failover Cases A-D), Section 16 (Hard Veto & Risk Override Prevention), and Taxonomy Normalization. |

---

## 4. Provider Failover Verification (Sections 14 & 15)

| Case | Scenario | Expected Behavior | Audit Verification |
| :--- | :--- | :--- | :--- |
| **Case A** | Groq available | Primary provider executes request; returns proposal with `provider="groq"`. | Verified by `test_case_a_primary_groq_success` |
| **Case B** | Groq down (429/5xx), OpenAI available | Seamless fallback to OpenAI; returns proposal with `provider="openai"`, logs failover. | Verified by `test_case_b_groq_down_openai_fallback` |
| **Case C** | Both Groq and OpenAI down | Explicit `LLM_UNAVAILABLE` advisory state returned; `decision=UNAVAILABLE`, `provider="none"`. | Verified by `test_case_c_both_llms_down_explicit_unavailable` |
| **Case D** | No API keys configured | Graceful initialization without crash; `is_available()=False`, returns `LLM_UNAVAILABLE`. | Verified by `test_case_d_no_api_keys_handled_gracefully` |

---

## 5. Hard Veto & Risk Override Verification (Section 16)

| Hard Gate | Trigger Condition | LLM Input | Gate Output | Block Reason |
| :--- | :--- | :--- | :--- | :--- |
| **News Blackout** | High-impact news within 30m window | APPROVE (confidence=0.99) | `FinalDecision.BLOCK` | `BlockReason.BLOCK_NEWS` |
| **Spread Guard** | EURUSD spread 3.8 pips > 2.5 max | APPROVE (confidence=0.99) | `FinalDecision.BLOCK` | `BlockReason.BLOCK_SPREAD` |
| **Daily Loss Limit** | Account daily PnL -6.0% <= -5.0% | APPROVE (confidence=0.99) | `FinalDecision.BLOCK` | `BlockReason.BLOCK_DAILY_LOSS` |
| **Circuit Breaker** | 5 consecutive losses halt active | APPROVE (confidence=0.99) | `FinalDecision.BLOCK` | `BlockReason.BLOCK_CIRCUIT_BREAKER` |
| **LLM Rejection** | LLM Advisory returns REJECT | REJECT (confidence=0.35) | `FinalDecision.BLOCK` | `BlockReason.BLOCK_CONFIDENCE` |
| **Determinism** | Identical inputs submitted 5x | Same context | Identical output 5x | N/A (100% reproducible) |

---

## 6. Full Test Suite Execution Summary

```
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.3.4, pluggy-1.5.0
rootdir: /Users/nawaphonkoedbua/Desktop/TradingBot_Workspace
configfile: pyproject.toml
collected 151 items

tests/integration/test_demo_e2e_recovery.py ....................         [ 13%]
tests/integration/test_runner_pipeline.py ..................             [ 25%]
tests/unit/test_ai_decision_architecture.py .............                [ 33%]
tests/unit/test_ai_layer.py ........................                     [ 49%]
tests/unit/test_ai_resilience.py ........                                [ 54%]
tests/unit/test_ai_validation.py ............                            [ 62%]
tests/unit/test_ctrader_broker.py ..............                          [ 72%]
tests/unit/test_evidence_archive.py .....                                 [ 75%]
tests/unit/test_fix_protocol.py .............                             [ 84%]
tests/unit/test_profit_acceleration.py .........                          [ 90%]
tests/unit/test_runner.py ...                                            [ 92%]
tests/unit/test_version_and_guards.py ............                       [100%]

======================== 151 passed, 2 warnings in 5.59s =======================
```

- **Total Tests**: 151
- **Passed**: 151 (100%)
- **Failed**: 0
- **Regression**: 0

---

## 7. Residual Risks & Production Mitigations

1. **Broker Spread Spikes during Roll-Over (21:00 - 22:00 UTC)**:
   - *Mitigation*: Spread is dynamically measured via live tick subscription immediately before the Deterministic Gate; trades exceeding symbol pip thresholds are blocked with `BLOCK_SPREAD`.
2. **LLM Latency Outliers**:
   - *Mitigation*: Hard 4.0-second timeout enforced with `urllib` socket timeout. Failover kicks in instantly without blocking the runner main loop.
3. **Session Timing Drift**:
   - *Mitigation*: UTC clock synchronization verified on startup; all gate operations strictly use timezone-aware `datetime.now(tz=timezone.utc)`.

---

## 8. Final Sign-Off

The trading decision architecture meets all production-grade institutional requirements:
- Deterministic safety is sovereign.
- LLM advisory output cannot override mathematical or capital risk boundaries.
- All 151 tests pass with complete taxonomy normalization.

**Final Status**: **PASS (PRODUCTION READY)**
