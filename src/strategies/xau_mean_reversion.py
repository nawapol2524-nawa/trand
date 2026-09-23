"""
XAU Mean Reversion Strategy — STRATEGY_SPEC.md v1.0.0 FROZEN.
strategy_id = 'XAU_MEAN_REVERSION_V1'

Signal logic:
  LONG:  RSI(14) crosses above 37 on M5 AND H1 close > H1 EMA(50)
  SHORT: RSI(14) crosses below 63 on M5 AND H1 close < H1 EMA(50)
  FLAT:  no condition met

No broker imports. Uses only closed bars.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np

from src.core.indicators import ema, rsi
from src.core.models import Bar, Direction, Signal, Timeframe
from src.core.signals import xau_rsi_cross_long, xau_rsi_cross_short

STRATEGY_ID = "XAU_MEAN_REVERSION_V1"

# Frozen parameters — DO NOT CHANGE after backtest begins
RSI_PERIOD   = 14
RSI_OVERSOLD = 37.0
RSI_OVERBOUGHT = 63.0
EMA_PERIOD   = 50


def evaluate(
    m5_bars: list[Bar],
    h1_bars: list[Bar],
    now: Optional[datetime] = None,
) -> Optional[Signal]:
    """
    Evaluate the XAU mean reversion strategy.

    Args:
        m5_bars: List of M5 bars, newest at index 0, all must be CLOSED.
                 Minimum length: RSI_PERIOD + 2 = 16
        h1_bars: List of H1 bars, newest at index 0, all must be CLOSED.
                 Minimum length: EMA_PERIOD + 1 = 51
        now:     Reference UTC time (defaults to datetime.now(utc))

    Returns:
        Signal with direction LONG or SHORT, or None if no signal.

    CRITICAL: Caller must ensure bars[0] is a CLOSED candle.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    # Need at least RSI_PERIOD+2 M5 bars for a crossover (prev + current RSI)
    min_m5 = RSI_PERIOD + 2
    min_h1 = EMA_PERIOD + 1

    if len(m5_bars) < min_m5:
        return None
    if len(h1_bars) < min_h1:
        return None

    # Build numpy arrays from bars (newest-first list → oldest-first array)
    m5_closes = np.array([b.close for b in reversed(m5_bars)])
    h1_closes = np.array([b.close for b in reversed(h1_bars)])

    # Compute indicators
    rsi_arr  = rsi(m5_closes, RSI_PERIOD)
    ema50_h1 = ema(h1_closes, EMA_PERIOD)

    # Last two valid RSI values (indices -1 and -2 of rsi_arr)
    rsi_current = rsi_arr[-1]
    rsi_prev    = rsi_arr[-2]
    ema50_val   = ema50_h1[-1]
    h1_close    = h1_closes[-1]   # most recent closed H1 bar close

    # Check for NaN
    if any(np.isnan(v) for v in [rsi_current, rsi_prev, ema50_val]):
        return None

    m5_close = m5_closes[-1]
    m5_ts    = m5_bars[0].timestamp  # most recent closed M5 bar open time

    indicators = {
        "rsi_current": round(rsi_current, 4),
        "rsi_prev":    round(rsi_prev, 4),
        "ema50_h1":    round(ema50_val, 5),
        "h1_close":    round(h1_close, 5),
        "m5_close":    round(m5_close, 5),
        "m5_timestamp": m5_ts.isoformat(),
    }

    # LONG signal
    if (xau_rsi_cross_long([rsi_prev, rsi_current], RSI_OVERSOLD)
            and h1_close > ema50_val):
        return Signal(
            symbol=m5_bars[0].symbol,
            direction=Direction.LONG,
            strategy_id=STRATEGY_ID,
            timestamp=now,
            price=m5_close,
            indicators=indicators,
            reason={
                "entry_condition": f"RSI crossed above {RSI_OVERSOLD}",
                "h1_bias": "bullish (close > EMA50)",
                "rsi_cross": f"{rsi_prev:.2f} → {rsi_current:.2f}",
            },
        )

    # SHORT signal
    if (xau_rsi_cross_short([rsi_prev, rsi_current], RSI_OVERBOUGHT)
            and h1_close < ema50_val):
        return Signal(
            symbol=m5_bars[0].symbol,
            direction=Direction.SHORT,
            strategy_id=STRATEGY_ID,
            timestamp=now,
            price=m5_close,
            indicators=indicators,
            reason={
                "entry_condition": f"RSI crossed below {RSI_OVERBOUGHT}",
                "h1_bias": "bearish (close < EMA50)",
                "rsi_cross": f"{rsi_prev:.2f} → {rsi_current:.2f}",
            },
        )

    return None
