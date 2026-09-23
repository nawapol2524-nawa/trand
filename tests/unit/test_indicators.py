"""
Unit tests for indicators — RSI, EMA, ATR.
Tests: output shape, NaN positions, known values, no look-ahead.
"""
import math
import pytest
import numpy as np

from src.core.indicators import ema, rsi, atr


class TestEMA:
    def test_output_length_equals_input(self):
        closes = np.random.uniform(100, 200, 100)
        result = ema(closes, 20)
        assert len(result) == len(closes)

    def test_first_period_minus_1_are_nan(self):
        closes = np.ones(50) * 100.0
        result = ema(closes, 10)
        # First 9 (period-1) should be NaN
        assert np.all(np.isnan(result[:9]))
        assert not np.isnan(result[9])

    def test_ema_of_constant_equals_constant(self):
        closes = np.ones(100) * 1500.0
        result = ema(closes, 50)
        # All non-NaN values should equal 1500
        valid = result[~np.isnan(result)]
        assert np.allclose(valid, 1500.0, atol=1e-6)

    def test_empty_input(self):
        result = ema(np.array([]), 10)
        assert len(result) == 0

    def test_insufficient_data_all_nan(self):
        result = ema(np.ones(5), 10)
        assert np.all(np.isnan(result))

    def test_seed_equals_sma(self):
        """EMA seed at index period-1 should equal SMA of first period bars."""
        closes = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        period = 5
        result = ema(closes, period)
        expected_seed = np.mean(closes[:period])  # SMA of first 5
        assert abs(result[period - 1] - expected_seed) < 1e-9


class TestRSI:
    def test_output_length_equals_input(self):
        closes = np.random.uniform(100, 200, 100)
        result = rsi(closes, 14)
        assert len(result) == len(closes)

    def test_first_period_values_are_nan(self):
        """First `period` indices should be NaN."""
        closes = np.random.uniform(100, 200, 50)
        result = rsi(closes, 14)
        assert np.all(np.isnan(result[:14]))
        assert not np.isnan(result[14])

    def test_rsi_bounds(self):
        """All valid RSI values must be in [0, 100]."""
        closes = np.random.uniform(100, 200, 200)
        result = rsi(closes, 14)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0.0)
        assert np.all(valid <= 100.0)

    def test_monotone_rising_gives_high_rsi(self):
        closes = np.linspace(100, 200, 100)
        result = rsi(closes, 14)
        valid = result[~np.isnan(result)]
        assert np.all(valid > 80.0), f"Expected RSI>80 for rising series, got min={valid.min():.2f}"

    def test_monotone_falling_gives_low_rsi(self):
        closes = np.linspace(200, 100, 100)
        result = rsi(closes, 14)
        valid = result[~np.isnan(result)]
        assert np.all(valid < 20.0), f"Expected RSI<20 for falling series, got max={valid.max():.2f}"

    def test_insufficient_data_all_nan(self):
        result = rsi(np.ones(5), 14)
        assert np.all(np.isnan(result))


class TestATR:
    def _make_ohlc(self, n=100, base=1900.0, spread=10.0):
        closes = np.random.uniform(base - spread, base + spread, n)
        highs  = closes + np.random.uniform(0, spread, n)
        lows   = closes - np.random.uniform(0, spread, n)
        return highs, lows, closes

    def test_output_length_equals_input(self):
        h, l, c = self._make_ohlc()
        result = atr(h, l, c, 14)
        assert len(result) == len(c)

    def test_first_period_values_are_nan(self):
        h, l, c = self._make_ohlc(100)
        result = atr(h, l, c, 14)
        assert np.all(np.isnan(result[:14]))
        assert not np.isnan(result[14])

    def test_atr_positive(self):
        h, l, c = self._make_ohlc(100)
        result = atr(h, l, c, 14)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0.0)

    def test_zero_range_gives_zero_atr(self):
        """Flat market: H=L=C → ATR should be 0."""
        n = 50
        c = np.ones(n) * 1900.0
        h = c.copy()
        l = c.copy()
        result = atr(h, l, c, 14)
        valid = result[~np.isnan(result)]
        assert np.allclose(valid, 0.0, atol=1e-9)
