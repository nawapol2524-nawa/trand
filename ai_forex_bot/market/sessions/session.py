"""
Market Sessions Classification
==============================
Classifies UTC timestamps into institutional forex trading sessions:
- Asian (Tokyo/Sydney): 00:00 - 08:00 UTC
- London: 07:00 - 16:00 UTC
- New York: 12:00 - 21:00 UTC
- London / NY Overlap: 12:00 - 16:00 UTC (Peak institutional liquidity)
"""

from datetime import datetime, timezone
from typing import Optional, List
import pandas as pd


class MarketSession:
    @staticmethod
    def add_session_features(df: pd.DataFrame) -> pd.DataFrame:
        ts = pd.to_datetime(df["epoch"], unit="s", utc=True)
        hour = ts.dt.hour
        dow = ts.dt.dayofweek

        df["is_asian_session"] = ((hour >= 0) & (hour < 8)).astype(int)
        df["is_london_session"] = ((hour >= 7) & (hour < 16)).astype(int)
        df["is_ny_session"] = ((hour >= 12) & (hour < 21)).astype(int)
        df["is_london_ny_overlap"] = ((hour >= 12) & (hour < 16)).astype(int)
        df["day_of_week"] = dow
        df["hour_of_day"] = hour
        return df


class MarketScheduleManager:
    """
    Manages global market open/close schedules and auto-routes active trading symbols:
    - Forex & Commodities: Active Sunday 21:00 UTC to Friday 21:00 UTC.
    - Synthetic Indices: Active 24/7/365 (constant liquidity, weekend safe).
    """

    @staticmethod
    def is_forex_market_open(dt: Optional[datetime] = None) -> bool:
        if dt is None:
            dt = datetime.now(timezone.utc)
        weekday = dt.weekday()  # Monday = 0, Friday = 4, Saturday = 5, Sunday = 6
        hour = dt.hour
        # Closes Friday at 21:00 UTC
        if weekday == 4 and hour >= 21:
            return False
        # Closed all day Saturday
        if weekday == 5:
            return False
        # Re-opens Sunday at 21:00 UTC
        if weekday == 6 and hour < 21:
            return False
        return True

    @staticmethod
    def get_auto_symbols(dt: Optional[datetime] = None) -> List[str]:
        """
        Dynamically returns optimal active symbols based on market schedule:
        - Weekdays (Forex open): ['frxEURUSD', 'frxGBPUSD', 'frxXAUUSD', 'R_75']
        - Weekends (Forex closed): ['R_75', 'R_25', 'R_10']
        """
        if MarketScheduleManager.is_forex_market_open(dt):
            return ["frxEURUSD", "frxGBPUSD", "frxXAUUSD", "R_75"]
        else:
            return ["R_75", "R_25", "R_10"]

