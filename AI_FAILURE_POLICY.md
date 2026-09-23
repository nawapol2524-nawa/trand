# AI Failure & Latency Policy
**Version**: 1.0.0 (Phase L & Phase M Standard)  
**Status**: APPROVED

---

## 1. Explicit Error Taxonomy

The AI layer strictly categorizes errors into 10 distinct classes:

| Error Type | Code | Cause | Immediate Action | Max Retries |
| :--- | :--- | :--- | :--- | :--- |
| **`NetworkError`** | `NETWORK_ERROR` | DNS failure, socket disconnect | Fail closed (no new trade) | 2 (backoff 0.5s) |
| **`TimeoutError`** | `TIMEOUT` | Request latency > `AI_TIMEOUT_SECONDS` | Fail closed (no new trade) | 1 |
| **`RateLimit429Error`**| `429_RATE_LIMIT`| Quota or rate limit exceeded | Backoff & fall back to offline mode | 0 (No spam) |
| **`Provider5xxError`** | `5XX_PROVIDER_ERROR`| OpenAI/Groq internal outage | Bounded retry with exponential backoff | 2 |
| **`AuthError`** | `AUTH_ERROR` | Invalid or revoked API key | Permanent shutdown of AI calls; alert | 0 |
| **`InvalidResponseError`**| `INVALID_RESPONSE`| Empty or non-JSON body | Fail closed | 1 |
| **`SchemaError`** | `SCHEMA_ERROR` | Missing required fields | Enter repair loop (max 2), else reject | 2 |
| **`ModelError`** | `MODEL_ERROR` | Model refused or errored | Fail closed | 0 |
| **`StaleResponseError`** | `STALE_RESPONSE` | Age > `MAX_STALENESS_SECONDS` (60s) | Reject proposal | 0 |
| **`UnknownError`** | `UNKNOWN_ERROR` | Unclassified runtime error | Fail closed | 0 |

---

## 2. Latency Policy & Timeout Constraints

* **`AI_TIMEOUT_SECONDS`**: **5.0 seconds** (Hard ceiling).
* **Emergency Independence**: If an AI call hangs or times out, it is aborted immediately. **AI is never permitted to block emergency position management, stop-loss execution, or the kill switch.**
* **Existing Positions**: Managed entirely by deterministic code (`src/core/risk.py`). Position trailing stops and margin closeouts do not await AI.

---

## 3. Repair Loop Protocol

If an LLM response is valid JSON but violates the `TradeProposal` schema:
1. Attempt 1: Re-prompt the provider with the specific schema error message.
2. Attempt 2: Final re-prompt.
3. If still invalid after 2 attempts: **FAIL CLOSED**. The trade is aborted.
4. Non-LLM providers (classifiers, offline rules) bypass the repair loop entirely and reject immediately.
