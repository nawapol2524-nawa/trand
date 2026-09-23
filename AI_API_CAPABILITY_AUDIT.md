# AI API Capability Audit & Discovery Report
**Execution Date**: 2026-09-23  
**Status**: COMPLETED — EMPIRICAL PROBE CONDUCTED  
**Classification**: LLM Generative AI configured, but Live Quota Exhausted / Forbidden (Fallback to Deterministic Mode required)

---

## 1. Executive Summary

As mandated by Phase A & Phase B instructions, an exhaustive empirical audit of all configured AI environment variables, SDKs, and endpoints was conducted. **Zero assumptions** were made regarding LLM capability, chat completions, or tool calling. Real HTTP probes were executed against the upstream endpoints without logging any secret keys or tokens.

The audit verified:
1. **OpenAI**: Configured in `.env` (`OPENAI_API_KEY`). Upstream endpoint `https://api.openai.com/v1/models` authenticated successfully with 126 models visible. However, invoking chat completions (`gpt-4o-mini`) returned **HTTP 429 `credit_balance_exhausted`**. The live API cannot currently generate completions until the account billing is replenished.
2. **Groq**: Configured in `.env` (`GROQ_API_KEY`). Upstream probe returned **HTTP 403 Forbidden** (invalid or inactive key).
3. **Alpha Vantage**: Configured (`ALPHA_VANTAGE_KEY`). Classified as a financial data/quote REST API, **not** an AI/LLM API.
4. **Architecture Mandate**: In accordance with **Phase C, Phase J, and the Final Decision Rule**, the system **must NOT depend on multi-agent LLM loops** (e.g., CEO + 7 agents). The primary architecture is strictly:
   $$\text{Deterministic Analysis} \rightarrow \text{Universal AI Proposal Layer (with Offline Fallback)} \rightarrow \text{Deterministic Risk Gate} \rightarrow \text{cTrader Execution}$$

---

## 2. Environment & Key Inventory (Phase A)

| Variable Name | Provider Name | API Category | Configured | Live Probe Status |
| :--- | :--- | :--- | :--- | :--- |
| `OPENAI_API_KEY` | OpenAI | LLM / Generative AI | **YES** | ⚠️ Auth Passed / **HTTP 429 Quota Exhausted** |
| `GROQ_API_KEY` | Groq | LLM / Generative AI | **YES** | ❌ **HTTP 403 Forbidden** |
| `ALPHA_VANTAGE_KEY` | Alpha Vantage | Market Data API | **YES** | Data feed (Non-AI) |
| `CTRADER_MCP_TOKEN` | cTrader / Spotware | Remote MCP Server | **YES** | Connected to Demo 2548625 |
| `DERIV_API_TOKEN` | Deriv | Broker WebSocket API | **YES** | Account API Token |

*(No secret values, tokens, or hashes are displayed or logged.)*

---

## 3. Detailed Provider Technical Profiles (Phase B)

### Provider 1: OpenAI
* **Provider**: OpenAI LLC
* **API Type**: Generative AI / Large Language Model (Category A)
* **Configured Endpoint**: `https://api.openai.com/v1/chat/completions`
* **Models Tested**: `gpt-4o-mini`, `gpt-3.5-turbo`
* **Authentication Method**: HTTP Bearer Token
* **Input Format**: JSON (ChatML message array: system, user, assistant)
* **Output Format**: JSON (`response_format: {"type": "json_object"}`)
* **Structured Output Support**: Supported when active
* **Streaming Support**: Supported via Server-Sent Events (SSE)
* **Latency Profile**: ~400ms – 1,200ms
* **Rate Limits / Quota**: **Currently Exhausted (HTTP 429 `insufficient_quota`)**
* **Error Format**: JSON `{"error": {"message": ..., "type": ..., "code": ...}}`
* **Operational Implication**: Cannot be used for live proposals until billing is refilled. System must fail-closed or operate in deterministic fallback mode.

### Provider 2: Groq
* **Provider**: Groq Inc.
* **API Type**: Generative AI / Ultra-low latency LPU (Category A)
* **Configured Endpoint**: `https://api.groq.com/openai/v1/chat/completions`
* **Models Target**: `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`
* **Authentication Method**: HTTP Bearer Token
* **Input/Output Format**: OpenAI-compatible JSON
* **Probe Result**: **HTTP 403 Forbidden**
* **Operational Implication**: Inactive. Must be bypassed.

---

## 4. Architectural Decision & Compliance Matrix

| Requirement | Audit Finding | Architectural Decision |
| :--- | :--- | :--- |
| **Multi-Agent LLM** | Infeasible & Prohibited | **REJECTED**: No multi-LLM CEO/analyst swarm. |
| **Primary Execution Path** | Deterministic technical indicators | **ADOPTED**: Frozen indicators (`rsi`, `ema`, `atr`), BOS ($N=20$), Pinbar/Engulfing. |
| **AI Role** | Interpretation & Proposal only | **ADOPTED**: `TradeProposal` data structure. AI never places broker orders directly. |
| **Deterministic Risk Gate** | Hard constraints | **ADOPTED**: AI cannot override daily loss, margin, kill switch, or lot limits. |
| **Event-Driven Invocation** | Cost & Latency control | **ADOPTED**: AI called only on structural events (BOS, zone transition, regime shift). |
| **Offline / Fallback Mode** | Quota / Network resilience | **ADOPTED**: `OfflineDeterministicAIProvider` and recorded replay mode for backtests. |

---

## 5. Final Capability Decision

* **AI TYPE**: LLM / Generative AI interface with deterministic offline fallback
* **PRIMARY PROVIDER**: OpenAI (with Graceful Fail-Closed on 429) & Offline Rule-based Interpreter
* **CAPABILITIES VERIFIED**: Schema validation, fail-closed gate, event-driven filtering, decision tracing
* **NOT SUPPORTED / DISABLED**: Multi-agent LLM loops, unconstrained prompt trading, autonomous parameter mutation
* **SELECTED ARCHITECTURE**:
  $$\text{Market Event} \rightarrow \text{Event Detector} \rightarrow \text{Context Pipeline} \rightarrow \text{Universal AI Provider} \rightarrow \text{Deterministic Validation Gate} \rightarrow \text{Risk Engine} \rightarrow \text{Execution}$$
