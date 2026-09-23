"""
Unit tests for core data models.
Tests: Bar validation, properties, Signal, RiskDecision
"""
import pytest
from datetime import datetime, timezone

from src.core.models import (
    Bar, Direction, OrderRequest, OrderStatus, Position,
    RiskDecision, Signal, Timeframe, TradingMode,
)

UTC = timezone.utc


class TestBar:
    def _make_bar(self, o=1900.0, h=1910.0, l=1895.0, c=1905.0):
        return Bar(
            symbol="XAUUSD",
            timeframe=Timeframe.M5,
            timestamp=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
            open=o, high=h, low=l, close=c, volume=1000.0,
        )

    def test_valid_bar_creates(self):
        b = self._make_bar()
        assert b.symbol == "XAUUSD"

    def test_naive_timestamp_raises(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            Bar("X", Timeframe.M5, datetime(2024, 1, 1), 1, 2, 0.5, 1.5, 10)

    def test_high_less_than_low_raises(self):
        with pytest.raises(ValueError, match="high"):
            self._make_bar(h=1890.0, l=1895.0)

    def test_high_less_than_open_raises(self):
        with pytest.raises(ValueError, match="high"):
            self._make_bar(o=1915.0, h=1910.0)

    def test_low_greater_than_close_raises(self):
        with pytest.raises(ValueError, match="low"):
            self._make_bar(c=1890.0, l=1895.0)

    def test_body_size(self):
        b = self._make_bar(o=1900.0, c=1905.0)
        assert abs(b.body_size - 5.0) < 1e-9

    def test_total_range(self):
        b = self._make_bar(h=1910.0, l=1895.0)
        assert abs(b.total_range - 15.0) < 1e-9

    def test_upper_wick(self):
        # open=1900, close=1905, high=1910 → upper wick = 1910-1905 = 5
        b = self._make_bar(o=1900.0, h=1910.0, l=1895.0, c=1905.0)
        assert abs(b.upper_wick - 5.0) < 1e-9

    def test_lower_wick(self):
        # open=1900, close=1905, low=1895 → lower wick = 1900-1895 = 5
        b = self._make_bar(o=1900.0, h=1910.0, l=1895.0, c=1905.0)
        assert abs(b.lower_wick - 5.0) < 1e-9

    def test_is_bullish(self):
        assert self._make_bar(o=1900.0, c=1905.0).is_bullish is True
        assert self._make_bar(o=1905.0, c=1900.0).is_bullish is False

    def test_is_bearish(self):
        assert self._make_bar(o=1905.0, c=1900.0).is_bearish is True

    def test_is_doji(self):
        b = Bar("X", Timeframe.M5, datetime(2024,1,1,tzinfo=UTC),
                1900.0, 1905.0, 1895.0, 1900.0, 0)
        assert b.is_doji is True


class TestRiskDecision:
    def test_approved(self):
        r = RiskDecision(approved=True, reason="OK", adjusted_volume=0.01)
        assert r.approved is True

    def test_blocked(self):
        r = RiskDecision(approved=False, reason="DAILY_LOSS", block_reason="DAILY_LOSS_LIMIT")
        assert r.approved is False
        assert r.block_reason == "DAILY_LOSS_LIMIT"
