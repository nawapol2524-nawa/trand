"""
Multi-Timeframe Market Resampler
================================
Resamples 1-minute OHLC bars into M5, M15, H1, H4, and D1 bars deterministically.
Maintains UTC epoch alignment at the start of each bar.
"""

from typing import Dict
import pandas as pd
import numpy as np


TIMEFRAME_SECONDS: Dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400
}


class Resampler:
    @staticmethod
    def resample(df_m1: pd.DataFrame, target_timeframe: str) -> pd.DataFrame:
        if target_timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"Unsupported target timeframe: {target_timeframe}. Supported: {list(TIMEFRAME_SECONDS.keys())}")
        
        interval_secs = TIMEFRAME_SECONDS[target_timeframe]
        if interval_secs == 60:
            return df_m1.copy()

        df = df_m1.copy()
        # Compute bar start epoch
        df["bar_epoch"] = (df["epoch"] // interval_secs) * interval_secs

        # Aggregation
        agg_rules = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last"
        }
        if "volume" in df.columns:
            agg_rules["volume"] = "sum"

        resampled = df.groupby("bar_epoch", as_index=False).agg(agg_rules)
        resampled.rename(columns={"bar_epoch": "epoch"}, inplace=True)
        resampled.sort_values("epoch", inplace=True)
        resampled.reset_index(drop=True, inplace=True)
        
        return resampled
