# Gate 30 Data Audit Report

**Date**: 2026-09-23  
**Status**: VERIFIED & PASS ✅  
**Source**: Deriv cTrader Remote MCP (`https://mcp.ctrader.com/trading/mcp`)  
**Account**: `2548625` (Demo)  
**Historical Directory**: `data/historical/`

---

## 1. Executive Summary

This data audit validates the completeness, integrity, monotonicity, and validity of historical trendbars downloaded via the cTrader Remote MCP protocol for the frozen backtesting pipeline.

All 8 datasets (M5 and H1 across EURUSD, GBPUSD, USDJPY, and XAUUSD) have undergone strict verification:
- **Total Historical Bars**: 3,572 bars (2,380 M5 bars + 1,192 H1 bars)
- **Monotonicity**: 100% strictly increasing timestamps (zero out-of-order candles)
- **OHLC Consistency**: 100% valid candles ($High \ge \max(Open, Close)$ and $Low \le \min(Open, Close)$)
- **Numerical Integrity**: Zero `NaN`, zero `Inf`, zero negative/zero prices
- **Volume Integrity**: Valid tick volume across all candles (zero missing volumes)
- **Market Closure Conformance**: Gaps correspond strictly to weekend trading breaks and daily 21:00 UTC broker rollover/maintenance windows.

---

## 2. Dataset Inventory & Integrity Check

| Instrument | Timeframe | Bar Count | Start Timestamp (UTC) | End Timestamp (UTC) | File Size (Bytes) | SHA-256 Hash | Integrity Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **EURUSD** | `H1` | 298 | 2026-09-06T21:00:00Z | 2026-09-23T06:00:00Z | 56,209 | `c6a7016a3462923666891a80c13cd5aa0496ff5d12968f9a539fa6d1f166489e` | **PASS** ✅ |
| **EURUSD** | `M5` | 595 | 2026-09-21T04:10:00Z | 2026-09-23T06:00:00Z | 111,564 | `515c0f9f10de1791b86a83af2fd82c03e2c2ee513fec2fb7fbbcfff5215f8d9b` | **PASS** ✅ |
| **GBPUSD** | `H1` | 298 | 2026-09-06T21:00:00Z | 2026-09-23T06:00:00Z | 56,230 | `4fb76106357ae7e994f9d59061983c54df8a86c460f72c97686d26e6b2007dac` | **PASS** ✅ |
| **GBPUSD** | `M5` | 595 | 2026-09-21T04:10:00Z | 2026-09-23T06:00:00Z | 111,615 | `c4e223ba085abe88b390855a829a12ad25bd9a689776789f166c480e15168497` | **PASS** ✅ |
| **USDJPY** | `H1` | 298 | 2026-09-06T21:00:00Z | 2026-09-23T06:00:00Z | 56,390 | `9f51072b5989f766a28ad8f81862ca142d6ec5d7212a6f66f0a27bdc48b77a51` | **PASS** ✅ |
| **USDJPY** | `M5` | 595 | 2026-09-21T04:10:00Z | 2026-09-23T06:00:00Z | 111,865 | `f2a9a61d953bbc093451133898c456a316cbf348f67f0ae8e3a71fe3613a5281` | **PASS** ✅ |
| **XAUUSD** | `H1` | 298 | 2026-09-04T05:00:00Z | 2026-09-23T06:00:00Z | 56,489 | `48b10fcd28c0dc669646f242d5fac82b2cb7b4da7643d6701b9de88379b2f339` | **PASS** ✅ |
| **XAUUSD** | `M5` | 595 | 2026-09-21T02:20:00Z | 2026-09-23T06:00:00Z | 112,156 | `7ad0a14aaf300987a7bc2255106d9ab8f38f0b5c08f559d6a33d54d3b8c38304` | **PASS** ✅ |

---

## 3. Detailed Data Integrity Verification

### 3.1 OHLC Boundary & Non-Negativity Checks
Every candle was evaluated against:
1. $High \ge \max(Open, Close)$
2. $Low \le \min(Open, Close)$
3. $High \ge Low$
4. $Open > 0, High > 0, Low > 0, Close > 0$
5. $\text{not } \text{isnan}(x) \text{ and not } \text{isinf}(x)$

**Result**: 0 violations across 3,572 bars ($0.00\%$ failure rate).

### 3.2 Monotonicity & Timestamp Continuity
Each time series was tested for strict monotonicity:
$$t_{i+1} > t_i \quad \forall i \in [0, N-2]$$
**Result**: 100% strictly increasing timestamps across all files.

### 3.3 Gap Analysis
* **H1 Series**:
  - Identified 2 major weekend gaps (Friday 20:00 UTC to Sunday 21:00 UTC on 2026-09-11 and 2026-09-18).
  - Normal market holiday/weekend behavior; no unexplained data dropouts.
* **M5 Series**:
  - Continuous 5-minute intervals during active market hours.
  - Minor daily rollover gap at 20:55 to 21:10 UTC (daily broker maintenance), standard for cTrader forex feeds.
* **XAUUSD (Gold)**:
  - Daily 1-hour session break (21:00 to 22:00 UTC) as per global precious metals exchange trading calendar.

### 3.4 Volume Statistics

| Symbol & TF | Min Volume | Max Volume | Mean Volume | Zero Volume Bars |
| :--- | :--- | :--- | :--- | :--- |
| `EURUSD_H1` | 259 | 20,462 | 5,600.39 | 0 |
| `EURUSD_M5` | 5 | 1,527 | 430.19 | 0 |
| `GBPUSD_H1` | 488 | 22,216 | 8,103.88 | 0 |
| `GBPUSD_M5` | 1 | 1,695 | 633.83 | 0 |
| `USDJPY_H1` | 589 | 24,195 | 11,168.57 | 0 |
| `USDJPY_M5` | 19 | 2,241 | 865.67 | 0 |
| `XAUUSD_H1` | 8 | 35,042 | 21,192.20 | 0 |
| `XAUUSD_M5` | 386 | 2,704 | 1,640.21 | 0 |

---

## 4. Sufficiency for Frozen Strategies

1. **Forex Trend Breakout (EURUSD, GBPUSD, USDJPY)**:
   - Required lookback: $EMA(200) + BOS(20) + 1 = 221$ bars.
   - Available M5 bars: 595 bars.
   - Status: **SUFFICIENT** (374 bars available for signal generation and trade simulation).

2. **XAU Mean Reversion (XAUUSD)**:
   - Required lookback: $RSI(14) + 2 = 16$ M5 bars; $EMA(50) + 1 = 51$ H1 bars.
   - Available M5 bars: 595 bars. Available H1 bars: 298 bars.
   - Status: **SUFFICIENT** (full multi-day confluence window).

---

## 5. Audit Verdict

**DATA AUDIT VERDICT**: **PASS** ✅  
The historical trendbar dataset meets all standards for determinism, chronological integrity, and mathematical validity. Ready for frozen backtest execution.
