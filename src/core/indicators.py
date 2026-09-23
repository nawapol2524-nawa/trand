"""
Technical indicators — pure numpy, no pandas, no TA-lib, no broker imports.
SINGLE SOURCE OF TRUTH for backtest, paper, demo, and live.

All functions:
  - Accept numpy arrays
  - Return numpy arrays of the same length
  - Use NaN for positions where insufficient data exists
  - Do NOT look ahead
"""
from __future__ import annotations

import numpy as np


def ema(closes: np.ndarray, period: int) -> np.ndarray:
    """
    Exponential Moving Average.
    Alpha = 2 / (period + 1).
    First `period-1` values are NaN.
    Seed = SMA of first `period` bars.
    """
    if len(closes) == 0:
        return np.array([], dtype=float)

    result = np.full(len(closes), np.nan, dtype=float)
    if len(closes) < period:
        return result

    alpha = 2.0 / (period + 1.0)
    # Seed with SMA of first `period` values
    result[period - 1] = np.mean(closes[:period])
    for i in range(period, len(closes)):
        result[i] = closes[i] * alpha + result[i - 1] * (1.0 - alpha)
    return result


def rsi(closes: np.ndarray, period: int) -> np.ndarray:
    """
    Wilder's RSI.
    Alpha = 1 / period (Wilder smoothing).
    First `period` values are NaN (need period+1 bars for first RSI value
    because we need period differences starting from index 1).

    Result[period] is the first valid RSI value (index period, 0-based),
    meaning first `period` positions (indices 0..period-1) are NaN.
    """
    n = len(closes)
    result = np.full(n, np.nan, dtype=float)
    if n < period + 1:
        return result

    deltas = np.diff(closes)  # length n-1
    gains  = np.where(deltas > 0, deltas,  0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # First average gain/loss over first `period` deltas (indices 0..period-1)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    # First RSI at position `period` in closes (after `period` deltas)
    if avg_loss < 1e-14:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    # Wilder smoothing for subsequent values
    alpha = 1.0 / period
    for i in range(period + 1, n):
        avg_gain = alpha * gains[i - 1] + (1.0 - alpha) * avg_gain
        avg_loss = alpha * losses[i - 1] + (1.0 - alpha) * avg_loss
        if avg_loss < 1e-14:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - (100.0 / (1.0 + rs))

    return result


def atr(highs: np.ndarray, lows: np.ndarray,
        closes: np.ndarray, period: int) -> np.ndarray:
    """
    Wilder's Average True Range.
    TR = max(high-low, |high-prev_close|, |low-prev_close|)
    First `period` values are NaN.
    Seed = SMA of first `period` TRs (uses bars 1..period, needs prev_close = bar 0).
    """
    n = len(closes)
    result = np.full(n, np.nan, dtype=float)
    if n < period + 1:
        return result

    # True Range (length n-1, starts at index 1)
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )

    if len(tr) < period:
        return result

    # Seed: SMA of first `period` TRs → stored at closes index `period`
    result[period] = np.mean(tr[:period])

    alpha = 1.0 / period
    for i in range(period + 1, n):
        result[i] = alpha * tr[i - 1] + (1.0 - alpha) * result[i - 1]

    return result
