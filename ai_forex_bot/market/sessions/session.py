"""
Market Sessions Classification
==============================
Classifies UTC timestamps into institutional forex trading sessions:
- Asian (Tokyo/Sydney): 00:00 - 08:00 UTC
- London: 07:00 - 16:00 UTC
- New York: 12:00 - 21:00 UTC
- London / NY Overlap: 12:00 - 16:00 UTC (Peak institutional liquidity)
"""

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
