"""
Signal evaluation functions — frozen per STRATEGY_SPEC.md v1.0.0.
No broker imports. No mutation of Bar objects.
All functions operate on CLOSED bars only — caller is responsible for enforcement.
"""
from __future__ import annotations

from typing import Optional

from src.core.models import Bar


# ---------------------------------------------------------------------------
# XAU — RSI crossover signals
# ---------------------------------------------------------------------------

def xau_rsi_cross_long(rsi_values: list[float],
                       oversold: float = 37.0) -> bool:
    """
    RSI crossed above oversold threshold.
    Requires at least 2 values: [prev, current]
    LONG signal: prev < oversold AND current >= oversold
    """
    if len(rsi_values) < 2:
        return False
    prev, current = rsi_values[-2], rsi_values[-1]
    if prev != prev or current != current:  # NaN check
        return False
    return prev < oversold <= current


def xau_rsi_cross_short(rsi_values: list[float],
                        overbought: float = 63.0) -> bool:
    """
    RSI crossed below overbought threshold.
    SHORT signal: prev > overbought AND current <= overbought
    """
    if len(rsi_values) < 2:
        return False
    prev, current = rsi_values[-2], rsi_values[-1]
    if prev != prev or current != current:  # NaN check
        return False
    return prev > overbought >= current


# ---------------------------------------------------------------------------
# FOREX — Break of Structure (BOS)  N=20 (STRATEGY_SPEC frozen)
# ---------------------------------------------------------------------------

def bos_long(bars: list[Bar], n: int = 20) -> bool:
    """
    BOS LONG: bars[0].high > max(bars[1..n].high)
    bars[0] = most recently CLOSED bar.
    bars[1..n] = N bars before bars[0].
    Requires len(bars) >= n + 1.
    Returns False if insufficient data.
    """
    if len(bars) < n + 1:
        return False
    signal_high = bars[0].high
    lookback_highs = [bars[i].high for i in range(1, n + 1)]
    return signal_high > max(lookback_highs)


def bos_short(bars: list[Bar], n: int = 20) -> bool:
    """
    BOS SHORT: bars[0].low < min(bars[1..n].low)
    """
    if len(bars) < n + 1:
        return False
    signal_low = bars[0].low
    lookback_lows = [bars[i].low for i in range(1, n + 1)]
    return signal_low < min(lookback_lows)


# ---------------------------------------------------------------------------
# Candlestick patterns — frozen thresholds from STRATEGY_SPEC.md v1.0.0
# PIN_BAR_WICK_RATIO = 2.0
# PIN_BAR_OPPOSITE_MAX = 0.25
# ---------------------------------------------------------------------------

def is_bullish_engulfing(bars: list[Bar]) -> bool:
    """
    Bullish engulfing pattern.
    Requires bars[0] (signal) and bars[1] (previous).
    Frozen definition:
      bars[0].close > bars[0].open
      bars[0].open <= bars[1].close
      bars[0].close >= bars[1].open
      bars[0].body_size > 0
    """
    if len(bars) < 2:
        return False
    b0, b1 = bars[0], bars[1]
    if b0.body_size < 1e-10:
        return False
    return (
        b0.close > b0.open and           # bullish candle
        b0.open <= b1.close and           # opens at or below prev close
        b0.close >= b1.open               # closes at or above prev open
    )


def is_bearish_engulfing(bars: list[Bar]) -> bool:
    """
    Bearish engulfing pattern.
    Frozen definition:
      bars[0].close < bars[0].open
      bars[0].open >= bars[1].close
      bars[0].close <= bars[1].open
      bars[0].body_size > 0
    """
    if len(bars) < 2:
        return False
    b0, b1 = bars[0], bars[1]
    if b0.body_size < 1e-10:
        return False
    return (
        b0.close < b0.open and
        b0.open >= b1.close and
        b0.close <= b1.open
    )


def is_bullish_pinbar(bar: Bar,
                      wick_ratio: float = 2.0,
                      opp_max_pct: float = 0.25) -> bool:
    """
    Bullish pin bar — frozen thresholds from STRATEGY_SPEC.md:
      lower_wick >= wick_ratio * body_size   (default 2.0x)
      upper_wick <= opp_max_pct * total_range (default 25%)
      body_size > 0
      total_range > 0
    """
    body = bar.body_size
    rng  = bar.total_range
    if body < 1e-10 or rng < 1e-10:
        return False
    return (
        bar.close > bar.open and                      # bullish candle
        bar.lower_wick >= wick_ratio * body and        # long lower wick
        bar.upper_wick <= opp_max_pct * rng            # short upper wick
    )


def is_bearish_pinbar(bar: Bar,
                      wick_ratio: float = 2.0,
                      opp_max_pct: float = 0.25) -> bool:
    """
    Bearish pin bar — frozen thresholds from STRATEGY_SPEC.md:
      upper_wick >= wick_ratio * body_size
      lower_wick <= opp_max_pct * total_range
      body_size > 0
      total_range > 0
    """
    body = bar.body_size
    rng  = bar.total_range
    if body < 1e-10 or rng < 1e-10:
        return False
    return (
        bar.close < bar.open and
        bar.upper_wick >= wick_ratio * body and
        bar.lower_wick <= opp_max_pct * rng
    )
