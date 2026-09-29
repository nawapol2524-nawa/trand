# Trading Bot — STRATEGY_SPEC.md
# STATUS: FROZEN — DO NOT MODIFY AFTER BACKTEST BEGINS
# Version: 1.0.0
# Frozen: 2026-09-23

## CRITICAL RULE
Once backtest begins, these parameters are FROZEN.
Do NOT change thresholds to improve win rate, PnL, or drawdown.
Do NOT cherry-pick periods. Do NOT remove losing trades.

---

## SYMBOL SET

| Symbol | Timeframe (Primary) | Higher TF | Strategy |
|--------|---------------------|-----------|----------|
| XAUUSD | M5 | H1 | XAU Mean Reversion (RSI + EMA) |
| EURUSD | M5 | H1 | Forex Trend Pullback (EMA Trend + Confirmation) |
| GBPUSD | M5 | H1 | Forex Trend Pullback (EMA Trend + Confirmation) |
| USDJPY | M5 | H1 | Forex Trend Pullback (EMA Trend + Confirmation) |

NOTE: Actual Deriv cTrader symbol names must be verified in Phase 1 (SYMBOL_SPECIFICATION.md).
Do not assume "XAUUSD" is the exact symbol name on Deriv cTrader.

---

## STRATEGY A — XAU MEAN REVERSION (XAUUSD)

### Timeframes
- Signal: M5
- Filter: H1

### Indicators
| Indicator | Period | Applied to |
|-----------|--------|------------|
| RSI | 14 | M5 close |
| EMA | 50 | H1 close |

### Signal Rules — LONG
1. Current M5 candle: RSI crossed above 37 (previous bar RSI < 37, current bar RSI >= 37)
2. H1 bias: last CLOSED H1 bar close > H1 EMA(50)
3. Signal uses CLOSED candles only — never the forming bar

### Signal Rules — SHORT
1. Current M5 candle: RSI crossed below 63 (previous bar RSI > 63, current bar RSI <= 63)
2. H1 bias: last CLOSED H1 bar close < H1 EMA(50)
3. Signal uses CLOSED candles only — never the forming bar

### Frozen Parameters
```
RSI_PERIOD = 14
RSI_OVERSOLD = 37
RSI_OVERBOUGHT = 63
EMA_PERIOD = 50
EMA_TIMEFRAME = H1
SIGNAL_TIMEFRAME = M5
```

---

## STRATEGY B — FOREX TREND PULLBACK (EURUSD / GBPUSD / USDJPY)
*Optimized for "Steady Profit & Capital Preservation" (High Win Rate / Pullback Style)*

### Timeframes
- Signal: M5
- Context: H1

### Indicators
| Indicator | Period | Applied to |
|-----------|--------|------------|
| EMA_FAST | 9 | M5 close |
| EMA_MID | 21 | M5 close |
| EMA_SLOW | 200 | M5 close |
| ATR | 14 | M5 (high, low, close) |

### Trend Condition
**LONG bias:**
- EMA_FAST(9) > EMA_MID(21) on last CLOSED M5 bar
- Close of last CLOSED M5 bar > EMA_SLOW(200)

**SHORT bias:**
- EMA_FAST(9) < EMA_MID(21) on last CLOSED M5 bar
- Close of last CLOSED M5 bar < EMA_SLOW(200)

### Unblocked Entry Architecture (BOS Removed)
To eliminate entry blockages and capture high-probability pullback continuation:
- **BOS (Break of Structure) requirement is completely removed**.
- Minimum required closed bars is reduced to **201** (`EMA_SLOW(200) + 1`).
- Confirmation relies purely on dynamic candle reversal patterns (Engulfing or Pin Bar) aligned with macro EMA trend.

### Target Risk-to-Reward & Exit Rules
- **Target R:R**: 1:1.2 (Default `rr_ratio = 1.2`)
- **SL Distance**: 2.5x ATR (clamped to minimum pip floor)
- **TP Distance**: 3.0x ATR ($3.0 / 2.5 = 1.2$ R:R)
- **Break-Even Enforcement (+1.0R)**: When floating profit reaches $+1.0R$ ($\text{distance} = \text{SL distance}$), the Stop Loss is immediately amended to the Entry Price (100% Risk-Free trade).

### Candlestick Confirmation — FROZEN DEFINITIONS

Signal candle = bars[0] (the most recently CLOSED bar that triggered BOS)

#### Bullish Engulfing
```
bars[0].close > bars[0].open                          # bullish candle
bars[0].open <= bars[1].close                          # opens at or below prev close
bars[0].close >= bars[1].open                          # closes at or above prev open
bars[0].body_size > 0                                  # has a real body
body_size = abs(close - open)
```

#### Bullish Pin Bar
```
bars[0].close > bars[0].open                          # bullish candle
lower_wick = min(open, close) - low
body_size = abs(close - open)
total_range = high - low
upper_wick = high - max(open, close)

FROZEN THRESHOLDS:
lower_wick >= 2.0 * body_size                         # lower wick >= 2x body
upper_wick <= 0.25 * total_range                      # upper wick <= 25% of range
body_size > 0                                          # has real body
total_range > 0                                        # candle has range
```

#### Bearish Engulfing
```
bars[0].close < bars[0].open                          # bearish candle
bars[0].open >= bars[1].close                          # opens at or above prev close
bars[0].close <= bars[1].open                          # closes at or below prev open
bars[0].body_size > 0
```

#### Bearish Pin Bar
```
bars[0].close < bars[0].open                          # bearish candle
upper_wick = high - max(open, close)
body_size = abs(close - open)
total_range = high - low
lower_wick = min(open, close) - low

FROZEN THRESHOLDS:
upper_wick >= 2.0 * body_size                         # upper wick >= 2x body
lower_wick <= 0.25 * total_range                      # lower wick <= 25% of range
body_size > 0
total_range > 0
```

### Full LONG Signal Sequence
1. Trend: EMA9 > EMA21 AND close > EMA200 (on bars[0])
2. Confirmation: bars[0] is Bullish Engulfing OR Bullish Pin Bar
3. All conditions evaluated on CLOSED bars only (minimum 201 bars)

### Full SHORT Signal Sequence
1. Trend: EMA9 < EMA21 AND close < EMA200 (on bars[0])
2. Confirmation: bars[0] is Bearish Engulfing OR Bearish Pin Bar
3. All conditions evaluated on CLOSED bars only (minimum 201 bars)

### Optimized Strategy Parameters
```
EMA_FAST_PERIOD = 9
EMA_MID_PERIOD = 21
EMA_SLOW_PERIOD = 200
ATR_PERIOD = 14
MIN_BARS = 201
TARGET_RR_RATIO = 1.2
BREAK_EVEN_TRIGGER_R = 1.0
PIN_BAR_WICK_RATIO = 2.0       # wick must be >= 2x body
PIN_BAR_OPPOSITE_MAX = 0.25    # opposite wick <= 25% of range
SIGNAL_TIMEFRAME = M5
```

---

## CLOSED CANDLE RULE (APPLIES TO BOTH STRATEGIES)

```
RULE: No signal evaluation on the forming (incomplete) candle.
bars[0] = the candle that JUST closed (timestamp is fully in the past)
bars[0] timestamp + timeframe_seconds <= current_utc_time
```

This must be enforced in the data engine, not just in the strategy.

---

## EXIT RULES

Exit rules are delegated to the Risk Engine (RISK_MODEL.md).
Strategies emit entry signals only.
Risk Engine determines:
- SL placement (ATR-based or fixed, see RISK_MODEL.md)
- TP placement
- Position sizing
- Exit on risk breach

---

## BACKTEST / LIVE PARITY

CRITICAL: The following must be bitwise identical between backtest and live:
- RSI calculation function
- EMA calculation function
- ATR calculation function
- BOS evaluation function
- Candlestick pattern functions
- Closed candle detection
- Timestamp normalization

Single source of truth: `src/core/indicators.py` and `src/core/signals.py`
Both backtest engine and live trading MUST import from these files.
No duplicate implementations permitted.

---

## INTEGRATION WITH SCENARIO ENGINE & UNIVERSAL AI LAYER

```
ARCHITECTURE:
Deterministic Strategy Signals / Structure
          ↓
Scenario Engine (src/core/scenarios.py)
          ↓
Event Detector (src/ai/event_detector.py)
          ↓
Universal AI Proposal Layer (src/ai/)
          ↓
Deterministic Gate (src/ai/validator.py)
          ↓
Deterministic Risk Engine (src/core/risk.py)
```

1. **Deterministic Signals**: Strategies evaluate market data and emit technical signals based strictly on frozen rules.
2. **Scenario Book Alignment**: The Scenario Engine tracks active scenarios (e.g. `BULLISH_CONTINUATION`). AI can propose scenario updates, but activations/invalidations are validated deterministically.
3. **AI as Proposal**: When triggered by meaningful events (BOS, monitored zone entry), the Universal AI Layer generates a `TradeProposal`.
4. **Veto & Gate**: If AI proposal conflicts with frozen strategy direction or risk limits, the deterministic gate REJECTS the trade (Fail-Closed). AI cannot force a trade.

---

## VERSION HISTORY

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-09-23 | Initial frozen spec |
| 1.1.0 | 2026-09-23 | Added Scenario Engine and Universal AI Proposal Layer integration |
| 1.2.0 | 2026-09-28 | Tuning: BOS_LOOKBACK_N 20→40, ATR multiplier 1.5x→2.5x, added min SL floor, added cooldown filter |
