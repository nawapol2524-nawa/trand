"""
Market Regime Classification Engine
===================================
Classifies current market condition into institutional regimes:
- TREND_UP: ADX > threshold and Fast EMA > Slow EMA and Price > EMA
- TREND_DOWN: ADX > threshold and Fast EMA < Slow EMA and Price < EMA
- RANGE: ADX <= threshold and Bollinger Bandwidth is moderate
- HIGH_VOLATILITY: ATR > 1.5 * Rolling ATR(50)
- LOW_VOLATILITY: ATR < 0.6 * Rolling ATR(50)
- UNCERTAIN: Conflicting momentum/trend signals
"""

from enum import Enum
import pandas as pd
import numpy as np


class MarketRegime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    UNCERTAIN = "UNCERTAIN"


class RegimeClassifier:
    def __init__(self, adx_trend_threshold: float = 25.0, vol_high_multiplier: float = 1.5, vol_low_multiplier: float = 0.6):
        self.adx_trend_threshold = adx_trend_threshold
        self.vol_high_multiplier = vol_high_multiplier
        self.vol_low_multiplier = vol_low_multiplier

    def classify_series(self, df: pd.DataFrame) -> pd.Series:
        """
        Classifies regime row-by-row on completed bars.
        Expects df to contain columns: adx_14, ema_20, ema_50, close, atr_14.
        """
        regimes = pd.Series(MarketRegime.UNCERTAIN.value, index=df.index)
        
        if "atr_14" in df.columns:
            atr_baseline = df["atr_14"].rolling(50, min_periods=20).mean()
            is_high_vol = df["atr_14"] > (atr_baseline * self.vol_high_multiplier)
            is_low_vol = df["atr_14"] < (atr_baseline * self.vol_low_multiplier)
        else:
            is_high_vol = pd.Series(False, index=df.index)
            is_low_vol = pd.Series(False, index=df.index)

        adx = df.get("adx_14", pd.Series(20.0, index=df.index))
        ema_fast = df.get("ema_20", df["close"])
        ema_slow = df.get("ema_50", df["close"])
        close = df["close"]

        # Vectorized classification
        is_trending = adx >= self.adx_trend_threshold
        is_uptrend = is_trending & (ema_fast > ema_slow) & (close > ema_fast)
        is_downtrend = is_trending & (ema_fast < ema_slow) & (close < ema_fast)
        is_range = (~is_trending) & (~is_high_vol)

        regimes[is_range] = MarketRegime.RANGE.value
        regimes[is_uptrend] = MarketRegime.TREND_UP.value
        regimes[is_downtrend] = MarketRegime.TREND_DOWN.value
        regimes[is_high_vol] = MarketRegime.HIGH_VOLATILITY.value
        regimes[is_low_vol & is_range] = MarketRegime.LOW_VOLATILITY.value

        return regimes
