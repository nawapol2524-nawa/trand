# Symbol Specification & Verification Report
**Date**: 2026-09-23  
**Status**: VERIFIED AGAINST LIVE DERIV CTRADER ENDPOINT  
**Connection**: cTrader Remote MCP Server (`https://mcp.ctrader.com/trading/mcp`)  

---

## 1. Verified Target Symbols

| Target Instrument | Deriv cTrader Symbol ID | Symbol Name | Live Verified Bid / Ask | Description | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **EURUSD** | `1` | `EURUSD` | `1.14269 / 1.14280` | Euro vs US Dollar | **VERIFIED** ✅ |
| **GBPUSD** | `2` | `GBPUSD` | `1.33151 / 1.33163` | British Pound vs US Dollar | **VERIFIED** ✅ |
| **USDJPY** | `4` | `USDJPY` | `157.630 / 157.645` | US Dollar vs Japanese Yen | **VERIFIED** ✅ |
| **XAUUSD** | `41` | `XAUUSD` | `4338.25 / 4338.43` | Gold vs US Dollar | **VERIFIED** ✅ |

---

## 2. Price Scaling & Precision Rules

cTrader Open API and MCP express spot prices in scaled integer format.
* **EURUSD, GBPUSD, USDJPY, XAUUSD**: Divide integer price by `100,000.0` ($10^5$) to obtain floating price.
* Example:
  $$\text{Raw EURUSD Bid} = 114269 \longrightarrow 1.14269$$
  $$\text{Raw XAUUSD Bid} = 433825000 \longrightarrow 4338.25$$

---

## 3. Account Verification Summary

* **Account ID**: `2548625` (Demo)
* **Balance**: `10,000.00 USD` (1,000,000 cents with `moneyDigits=2`)
* **Equity**: `10,000.00 USD`
* **Free Margin**: `10,000.00 USD`
* **Broker Host**: `mcp.ctrader.com/trading/mcp`
* **Session Protocol**: JSON-RPC 2.0 with Server-Sent Events (SSE)
