# BROKER_CONNECTIVITY_VERIFICATION.md
# STATUS: CONDITIONAL — Account confirmed, API credentials INCOMPLETE
# Generated: 2026-09-23

---

## A. DERIV ACCOUNT STATUS

### Verified from screenshot

| Item | Value | Status |
|------|-------|--------|
| Account Type | cTrader | ✅ CONFIRMED |
| Mode | DEMO | ✅ CONFIRMED |
| Server | DerivSVG-Server | ✅ CONFIRMED |
| Login ID (cTrader) | 2565611 | ✅ CONFIRMED |
| Balance | 10,000.00 USD | ✅ CONFIRMED (Demo funds) |
| Account Owner | Nawaphon Koedbua | ✅ CONFIRMED |

---

## B. CREDENTIAL ANALYSIS

### Provided Credentials

| Credential | Type | Status | Action Required |
|------------|------|--------|-----------------|
| Deriv API Token (`pat_0a69f...`) | Deriv WebSocket API PAT | ✅ Received | Store in .env ONLY — revoke & regenerate after setup |
| "App ID" (`34tzoLtwQUNOLqSK0uLaj`) | ⚠️ Unknown type — NOT numeric App ID | ❓ Needs clarification | See note below |
| cTrader Client ID | NOT PROVIDED | ❌ MISSING | Required for cTrader Open API |
| cTrader Client Secret | NOT PROVIDED | ❌ MISSING | Required for cTrader Open API |
| cTrader Access Token | NOT PROVIDED | ❌ MISSING | Required — obtained via OAuth |

### ⚠️ IMPORTANT NOTE: Two separate API systems

#### System 1: Deriv WebSocket API
- URL: `wss://ws.binaryws.com/websockets/v3`
- Auth: Deriv API Token (`pat_...`) — PROVIDED ✅
- Used for: account info, general Deriv operations
- **NOT** used for cTrader order execution

#### System 2: cTrader Open API (Required for trading)
- URL: `demo.ctraderapi.com:5035` (TCP/Protobuf)
- Auth: OAuth2 — requires Client ID + Client Secret from Spotware Developer Hub
- Used for: symbol discovery, market data, order execution, positions
- **Status: CREDENTIALS MISSING** ❌

### What "34tzoLtwQUNOLqSK0uLaj" might be

Standard Deriv App IDs are **numeric** (e.g., `16929`, `34`).
`34tzoLtwQUNOLqSK0uLaj` is NOT a standard Deriv App ID format.

Possibilities:
1. OAuth Client ID from somewhere else (not Deriv)
2. Partial/incorrect value
3. A different credential type

**Status: UNVERIFIED — cannot use until clarified**

---

## C. WHAT IS NEEDED FOR cTRADER OPEN API

### Step 1: Register at Spotware Open API Portal
URL: https://openapi.ctrader.com/

Required:
- Create an Application
- Get **Client ID** (e.g., `1234_AbCdEf...`)
- Get **Client Secret**
- Set Redirect URI (can be `http://localhost:8080/callback` for local OAuth)

### Step 2: OAuth Flow to get Access Token
```
GET https://connect.spotware.com/apps/auth?
    client_id=YOUR_CLIENT_ID
    &redirect_uri=YOUR_REDIRECT_URI
    &scope=trading
    &response_type=code
```

Exchange code for token:
```
POST https://connect.spotware.com/apps/token
    client_id=YOUR_CLIENT_ID
    client_secret=YOUR_CLIENT_SECRET
    code=AUTH_CODE
    grant_type=authorization_code
```

This gives you an **Access Token** to use with cTrader Open API.

### Step 3: Verify Account Authorization
After getting Access Token, verify that account `2565611` (DerivSVG-Server) 
is accessible and authorized for API trading.

---

## D. cTRADER API TECHNICAL SPECS

| Item | Value |
|------|-------|
| Demo host | demo.ctraderapi.com |
| Live host | live.ctraderapi.com |
| Port | 5035 (TCP) |
| Protocol | Protobuf over TCP |
| SDK | ctrader-open-api (pip) |
| Rate limit (non-historical) | 50 requests/sec/connection |
| Rate limit (historical) | 5 requests/sec/connection |

---

## E. SYMBOL VERIFICATION STATUS

| Symbol | Expected cTrader Name | Status |
|--------|-----------------------|--------|
| XAUUSD | UNKNOWN | ❌ Must discover via API |
| EURUSD | UNKNOWN | ❌ Must discover via API |
| GBPUSD | UNKNOWN | ❌ Must discover via API |
| USDJPY | UNKNOWN | ❌ Must discover via API |

**DO NOT assume symbol names.** Must call `ProtoOASymbolsListReq` and search by name.

---

## F. DERIV API TOKEN SECURITY

### ⚠️ ACTION REQUIRED

The Deriv API token was shared in a chat message.
**Recommend: Revoke and regenerate immediately after initial setup.**

To revoke:
1. Go to https://app.deriv.com/account/api-token
2. Find the token and click Delete
3. Create new token with minimal required scopes
4. Update .env with new token

Token is stored ONLY in local `.env` file (gitignored, never committed).

---

## BROKER CONNECTIVITY SUMMARY

| Item | Status |
|------|--------|
| Deriv account existence | ✅ CONFIRMED |
| cTrader DEMO account | ✅ CONFIRMED (Login: 2565611) |
| Deriv WebSocket API token | ✅ RECEIVED (security rotation recommended) |
| cTrader Open API Client ID | ❌ NOT PROVIDED |
| cTrader Open API Client Secret | ❌ NOT PROVIDED |
| cTrader OAuth Access Token | ❌ NOT OBTAINED |
| Symbol discovery | ❌ NOT VERIFIED |
| Order execution (DEMO) | ❌ NOT VERIFIED |
| "App ID" 34tzoLtwQUNOLqSK0uLaj | ❓ UNCLEAR — format not matching |

**OVERALL BROKER STATUS: CONDITIONAL**
Account confirmed. cTrader Open API credentials must be obtained before Phase 6 (broker implementation).
Phase 0 HARD GATE: PARTIALLY PASSED — account exists, API credentials incomplete.
