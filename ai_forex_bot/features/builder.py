"""
Institutional Multi-Timeframe Feature Builder
=============================================
Generates comprehensive quantitative and market features with strict causal isolation:
- All indicator calculations use completed bar series.
- Higher timeframe features (H1) are merged using strict backward alignment on completed bars.
- Zero future candle contamination.
"""

from typing import List, Dict, Optional
import numpy as np
import pandas as pd

from ai_forex_bot.market.indicators.technical import TechnicalIndicators
from ai_forex_bot.market.sessions.session import MarketSession
from ai_forex_bot.market.regime.classifier import RegimeClassifier, MarketRegime
from ai_forex_bot.news_ai.calendar import EconomicCalendarEngine
from ai_forex_bot.news_ai.sentiment import NewsContextEngine


class FeatureBuilder:
    def __init__(self):
        self.regime_classifier = RegimeClassifier()
        self.calendar_engine = EconomicCalendarEngine()
        self.news_engine = NewsContextEngine()

    def build_features(
        self,
        df_base: pd.DataFrame,
        df_h1: Optional[pd.DataFrame] = None,
        symbol: str = "frxEURUSD"
    ) -> pd.DataFrame:
        df = df_base.copy()
        df.sort_values("epoch", inplace=True)
        df.reset_index(drop=True, inplace=True)

        close = df["close"]
        high = df["high"]
        low = df["low"]
        open_ = df["open"]

        # 1. Returns & Realized Volatility
        df["ret_1"] = np.log(close / close.shift(1))
        df["ret_5"] = np.log(close / close.shift(5))
        df["ret_15"] = np.log(close / close.shift(15))
        df["realized_vol_20"] = df["ret_1"].rolling(20, min_periods=10).std()

        # 2. Moving Averages & Distances
        ema_20 = TechnicalIndicators.calculate_ema(close, 20)
        ema_50 = TechnicalIndicators.calculate_ema(close, 50)
        ema_200 = TechnicalIndicators.calculate_ema(close, 200)

        df["ema_20"] = ema_20
        df["ema_50"] = ema_50
        df["dist_ema_20"] = (close - ema_20) / (close + 1e-9)
        df["dist_ema_50"] = (close - ema_50) / (close + 1e-9)
        df["dist_ema_200"] = (close - ema_200) / (close + 1e-9)
        df["ema_spread_20_50"] = (ema_20 - ema_50) / (close + 1e-9)

        # 3. ATR and Bollinger
        atr_14 = TechnicalIndicators.calculate_atr(df, 14)
        df["atr_14"] = atr_14
        df["norm_atr_14"] = atr_14 / (close + 1e-9)

        upper_bb, mid_bb, lower_bb, bandwidth, pct_b = TechnicalIndicators.calculate_bollinger_bands(df, 20, 2.0)
        df["bb_bandwidth"] = bandwidth
        df["bb_pct_b"] = pct_b

        # 4. Momentum & Oscillators
        df["rsi_14"] = TechnicalIndicators.calculate_rsi(df, 14)
        macd_line, sig_line, macd_hist = TechnicalIndicators.calculate_macd(df, 12, 26, 9)
        df["macd_hist"] = macd_hist / (close + 1e-9)
        df["adx_14"] = TechnicalIndicators.calculate_adx(df, 14)

        # 5. Price Action & Candle Structure
        range_ = high - low + 1e-9
        df["candle_body_ratio"] = (close - open_).abs() / range_
        df["candle_upper_wick_ratio"] = (high - np.maximum(open_, close)) / range_
        df["candle_lower_wick_ratio"] = (np.minimum(open_, close) - low) / range_

        high_20, low_20, _ = TechnicalIndicators.calculate_donchian(df, 20)
        df["range_pos_20"] = (close - low_20) / (high_20 - low_20 + 1e-9)

        # 6. Market Regime Classification
        df["regime"] = self.regime_classifier.classify_series(df)
        # Numerical regime mapping
        regime_map = {
            MarketRegime.TREND_UP.value: 1,
            MarketRegime.TREND_DOWN.value: -1,
            MarketRegime.RANGE.value: 0,
            MarketRegime.HIGH_VOLATILITY.value: 2,
            MarketRegime.LOW_VOLATILITY.value: -2,
            MarketRegime.UNCERTAIN.value: 3
        }
        df["regime_code"] = df["regime"].map(regime_map).fillna(3).astype(int)

        # 7. Market Sessions
        df = MarketSession.add_session_features(df)

        # 8. Higher Timeframe Feature Merging (H1) with strict zero look-ahead
        if df_h1 is not None and len(df_h1) > 0:
            df_h1_feat = df_h1.copy().sort_values("epoch").reset_index(drop=True)
            h1_close = df_h1_feat["close"]
            h1_ema_50 = TechnicalIndicators.calculate_ema(h1_close, 50)
            df_h1_feat["h1_dist_ema_50"] = (h1_close - h1_ema_50) / (h1_close + 1e-9)
            df_h1_feat["h1_trend_bull"] = (h1_close > h1_ema_50).astype(int)

            # An H1 bar at epoch T finishes at epoch T + 3600.
            # Therefore, at base epoch t, the completed H1 bar is available only if t >= T + 3600.
            df_h1_feat["h1_available_epoch"] = df_h1_feat["epoch"] + 3600
            merge_cols = ["h1_available_epoch", "h1_dist_ema_50", "h1_trend_bull"]

            df = pd.merge_asof(
                df,
                df_h1_feat[merge_cols].sort_values("h1_available_epoch"),
                left_on="epoch",
                right_on="h1_available_epoch",
                direction="backward"
            )
            df.drop(columns=["h1_available_epoch"], inplace=True)
            df["h1_dist_ema_50"] = df["h1_dist_ema_50"].fillna(0.0)
            df["h1_trend_bull"] = df["h1_trend_bull"].fillna(0).astype(int)
        else:
            df["h1_dist_ema_50"] = 0.0
            df["h1_trend_bull"] = 0

        # 9. Economic & News Features
        currency = symbol[3:6] if symbol.startswith("frx") else "USD"
        df = self.calendar_engine.add_calendar_features(df, currency=currency)
        df = self.news_engine.add_news_features(df, currency=currency)

        # Drop warmup rows containing NaNs
        df.dropna(inplace=True)
        df.reset_index(drop=True, inplace=True)

        return df
