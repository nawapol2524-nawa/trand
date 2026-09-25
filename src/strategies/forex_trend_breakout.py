"""
Forex Trend Breakout Strategy — STRATEGY_SPEC.md v1.0.0 FROZEN.
strategy_id = 'FOREX_TREND_BREAKOUT_V1'
Applies to: EURUSD, GBPUSD, USDJPY

Signal logic:
  LONG:
    Trend:  EMA9 > EMA21 AND close > EMA200 (on bars[0])
    BOS:    bars[0].high > max(bars[1..20].high)
    Confirm: bullish engulfing OR bullish pin bar on bars[0]

  SHORT:
    Trend:  EMA9 < EMA21 AND close < EMA200 (on bars[0])
    BOS:    bars[0].low  < min(bars[1..20].low)
    Confirm: bearish engulfing OR bearish pin bar on bars[0]

No broker imports. Uses only closed bars.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np

from src.core.indicators import atr, ema
from src.core.models import Bar, Direction, Signal
from src.core.signals import (
    bos_long,
    bos_short,
    is_bearish_engulfing,
    is_bearish_pinbar,
    is_bullish_engulfing,
    is_bullish_pinbar,
)

STRATEGY_ID = "FOREX_TREND_BREAKOUT_V1"

# Frozen parameters — DO NOT CHANGE after backtest begins
EMA_FAST_PERIOD = 9
EMA_MID_PERIOD  = 21
EMA_SLOW_PERIOD = 200
ATR_PERIOD      = 14
BOS_LOOKBACK_N  = 20

# Minimum bars needed: EMA200 seed + lookback
MIN_BARS = EMA_SLOW_PERIOD + BOS_LOOKBACK_N + 1


def evaluate(
    m5_bars: list[Bar],
    now: Optional[datetime] = None,
    h1_bars: Optional[list[Bar]] = None,
) -> Optional[Signal]:
    """
    Evaluate the Forex Trend Breakout strategy.

    Args:
        m5_bars: List of M5 bars, newest at index 0, all must be CLOSED.
                 Minimum length: EMA_SLOW_PERIOD + BOS_LOOKBACK_N + 1 = 221
        now:     Reference UTC time (defaults to datetime.now(utc))
        h1_bars: Optional list of H1 bars for Higher Timeframe Regime context.

    Returns:
        Signal with direction LONG or SHORT, or None if no signal.

    CRITICAL: Caller must ensure bars[0] is a CLOSED candle.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    if len(m5_bars) < MIN_BARS:
        return None

    # Build arrays (newest-first list → oldest-first array for indicators)
    closes = np.array([b.close for b in reversed(m5_bars)])
    highs  = np.array([b.high  for b in reversed(m5_bars)])
    lows   = np.array([b.low   for b in reversed(m5_bars)])

    # Compute indicators
    ema9_arr  = ema(closes, EMA_FAST_PERIOD)
    ema21_arr = ema(closes, EMA_MID_PERIOD)
    ema200_arr = ema(closes, EMA_SLOW_PERIOD)
    atr_arr   = atr(highs, lows, closes, ATR_PERIOD)

    ema9  = ema9_arr[-1]
    ema21 = ema21_arr[-1]
    ema200 = ema200_arr[-1]
    atr_val = atr_arr[-1]
    close  = closes[-1]

    # Check for NaN
    if any(np.isnan(v) for v in [ema9, ema21, ema200, atr_val]):
        return None

    bars = m5_bars  # newest at index 0

    # Higher Timeframe H1 Regime Context
    h1_regime = "NOT_PROVIDED"
    if h1_bars and len(h1_bars) >= 50:
        h1_closes = np.array([b.close for b in reversed(h1_bars)])
        h1_ema50_arr = ema(h1_closes, 50)
        if not np.isnan(h1_ema50_arr[-1]):
            h1_regime = "BULLISH" if h1_closes[-1] > h1_ema50_arr[-1] else "BEARISH"

    # ----------------------------------------------------------------
    # LONG conditions
    # ----------------------------------------------------------------
    trend_long = (ema9 > ema21) and (close > ema200)
    if trend_long and bos_long(bars, BOS_LOOKBACK_N):
        bullish_engulf = is_bullish_engulfing(bars)
        bullish_pin    = is_bullish_pinbar(bars[0])
        if bullish_engulf or bullish_pin:
            pattern = "bullish_engulfing" if bullish_engulf else "bullish_pinbar"
            bos_level = max(bars[i].high for i in range(1, BOS_LOOKBACK_N + 1))
            return Signal(
                symbol=bars[0].symbol,
                direction=Direction.LONG,
                strategy_id=STRATEGY_ID,
                timestamp=now,
                price=close,
                indicators={
                    "ema9":      round(ema9, 5),
                    "ema21":     round(ema21, 5),
                    "ema200":    round(ema200, 5),
                    "atr":       round(atr_val, 5),
                    "bos_level": round(bos_level, 5),
                    "pattern":   pattern,
                    "h1_regime": h1_regime,
                    "m5_timestamp": bars[0].timestamp.isoformat(),
                },
                reason={
                    "trend_condition": f"EMA9({ema9:.5f}) > EMA21({ema21:.5f}), close({close:.5f}) > EMA200({ema200:.5f})",
                    "bos_condition":   f"High broke {BOS_LOOKBACK_N}-bar high at {bos_level:.5f}",
                    "candle_pattern":  pattern,
                    "h1_regime":       h1_regime,
                },
            )

    # ----------------------------------------------------------------
    # SHORT conditions
    # ----------------------------------------------------------------
    trend_short = (ema9 < ema21) and (close < ema200)
    if trend_short and bos_short(bars, BOS_LOOKBACK_N):
        bearish_engulf = is_bearish_engulfing(bars)
        bearish_pin    = is_bearish_pinbar(bars[0])
        if bearish_engulf or bearish_pin:
            pattern = "bearish_engulfing" if bearish_engulf else "bearish_pinbar"
            bos_level = min(bars[i].low for i in range(1, BOS_LOOKBACK_N + 1))
            return Signal(
                symbol=bars[0].symbol,
                direction=Direction.SHORT,
                strategy_id=STRATEGY_ID,
                timestamp=now,
                price=close,
                indicators={
                    "ema9":      round(ema9, 5),
                    "ema21":     round(ema21, 5),
                    "ema200":    round(ema200, 5),
                    "atr":       round(atr_val, 5),
                    "bos_level": round(bos_level, 5),
                    "pattern":   pattern,
                    "h1_regime": h1_regime,
                    "m5_timestamp": bars[0].timestamp.isoformat(),
                },
                reason={
                    "trend_condition": f"EMA9({ema9:.5f}) < EMA21({ema21:.5f}), close({close:.5f}) < EMA200({ema200:.5f})",
                    "bos_condition":   f"Low broke {BOS_LOOKBACK_N}-bar low at {bos_level:.5f}",
                    "candle_pattern":  pattern,
                    "h1_regime":       h1_regime,
                },
            )

    return None
