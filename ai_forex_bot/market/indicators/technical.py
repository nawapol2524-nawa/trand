"""
Technical & Quantitative Indicators
===================================
Pure numerical implementations with zero external C dependencies.
All calculations are strictly causal (no future bars referenced).
"""

import numpy as np
import pandas as pd


class TechnicalIndicators:
    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["high"]
        low = df["low"]
        close_prev = df["close"].shift(1)
        
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period, min_periods=period).mean()

    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()

        rs = avg_gain / (avg_loss + 1e-9)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    @staticmethod
    def calculate_ema(series: pd.Series, span: int) -> pd.Series:
        return series.ewm(span=span, adjust=False).mean()

    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0):
        close = df["close"]
        sma = close.rolling(window=period, min_periods=period).mean()
        std = close.rolling(window=period, min_periods=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        bandwidth = (upper - lower) / (sma + 1e-9)
        pct_b = (close - lower) / (upper - lower + 1e-9)
        return upper, sma, lower, bandwidth, pct_b

    @staticmethod
    def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
        close = df["close"]
        fast_ema = close.ewm(span=fast, adjust=False).mean()
        slow_ema = close.ewm(span=slow, adjust=False).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["high"]
        low = df["low"]
        close_prev = df["close"].shift(1)

        tr = pd.concat([high - low, (high - close_prev).abs(), (low - close_prev).abs()], axis=1).max(axis=1)
        up_move = high.diff()
        down_move = -low.diff()

        pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        tr_smooth = pd.Series(tr).rolling(window=period, min_periods=period).sum()
        pos_di = 100.0 * (pd.Series(pos_dm).rolling(window=period, min_periods=period).sum() / (tr_smooth + 1e-9))
        neg_di = 100.0 * (pd.Series(neg_dm).rolling(window=period, min_periods=period).sum() / (tr_smooth + 1e-9))

        dx = 100.0 * (pos_di - neg_di).abs() / (pos_di + neg_di + 1e-9)
        adx = dx.rolling(window=period, min_periods=period).mean()
        return adx

    @staticmethod
    def calculate_donchian(df: pd.DataFrame, period: int = 20):
        high_n = df["high"].rolling(window=period, min_periods=period).max()
        low_n = df["low"].rolling(window=period, min_periods=period).min()
        mid = (high_n + low_n) / 2.0
        return high_n, low_n, mid
