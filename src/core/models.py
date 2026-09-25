"""
Core data models for the Deriv cTrader Trading Bot.
Single source of truth — shared by backtest, paper, demo, and live.
No broker imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Timeframe(str, Enum):
    M1  = "M1"
    M5  = "M5"
    M15 = "M15"
    H1  = "H1"
    H4  = "H4"
    D1  = "D1"


class Direction(str, Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    FLAT  = "FLAT"


class TradingMode(str, Enum):
    PAPER = "PAPER"
    DEMO  = "DEMO"
    LIVE  = "LIVE"


class OrderStatus(str, Enum):
    PENDING   = "PENDING"
    FILLED    = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED  = "REJECTED"
    PARTIAL   = "PARTIAL"


# ---------------------------------------------------------------------------
# Bar — OHLCV candle
# ---------------------------------------------------------------------------

@dataclass
class Bar:
    """
    A single OHLCV candle.
    timestamp = candle OPEN time (UTC, timezone-aware).
    All price fields are floats in the instrument's quote currency.
    """
    symbol:    str
    timeframe: Timeframe
    timestamp: datetime   # candle OPEN time, must be UTC-aware
    open:      float
    high:      float
    low:       float
    close:     float
    volume:    float

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("Bar.timestamp must be timezone-aware (UTC)")
        if self.high < self.low:
            raise ValueError(f"Bar.high ({self.high}) < Bar.low ({self.low})")
        if self.high < self.open - 1e-10 or self.high < self.close - 1e-10:
            raise ValueError("Bar.high must be >= open and close")
        if self.low > self.open + 1e-10 or self.low > self.close + 1e-10:
            raise ValueError("Bar.low must be <= open and close")
        if self.volume < 0:
            raise ValueError("Bar.volume must be >= 0")

    # Derived properties — no mutation
    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def total_range(self) -> float:
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def is_doji(self) -> bool:
        return self.body_size < 1e-10


# ---------------------------------------------------------------------------
# Signal — strategy output
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """
    Output from a strategy evaluation.
    direction=FLAT means no trade.
    All broker/execution logic is downstream.
    """
    symbol:      str
    direction:   Direction
    strategy_id: str
    timestamp:   datetime          # UTC, time signal was generated
    price:       float             # reference price at signal time
    indicators:  dict[str, Any] = field(default_factory=dict)
    reason:      dict[str, Any] = field(default_factory=dict)
    news_clear:  bool = False      # set by NewsFilter gate
    risk_approved: bool = False    # set by RiskEngine gate


# ---------------------------------------------------------------------------
# Order / Execution
# ---------------------------------------------------------------------------

@dataclass
class OrderRequest:
    """
    Requested trade parameters — passed to broker layer.
    Strategies never create these directly; RiskEngine does after approval.
    """
    symbol:           str
    direction:        Direction
    volume:           float
    sl_price:         Optional[float] = None
    tp_price:         Optional[float] = None
    comment:          str = ""
    strategy_id:      str = ""
    signal_timestamp: Optional[datetime] = None


@dataclass
class OrderResult:
    """
    Actual broker response after order submission.
    Never infer success from absence of error — always check status.
    """
    order_id:         Optional[str]
    status:           OrderStatus
    symbol:           str
    direction:        Direction
    volume_requested: float
    volume_filled:    float = 0.0
    fill_price:       Optional[float] = None
    error_code:       Optional[str] = None
    error_message:    Optional[str] = None
    broker_timestamp: Optional[datetime] = None


@dataclass
class Position:
    """
    An open position as reported by the broker.
    Broker state is authoritative — never trust local state alone.
    """
    position_id:   str
    symbol:        str
    direction:     Direction
    volume:        float
    entry_price:   float
    sl_price:      Optional[float] = None
    tp_price:      Optional[float] = None
    open_time:     Optional[datetime] = None
    strategy_id:   str = ""
    unrealized_pnl: float = 0.0


# ---------------------------------------------------------------------------
# Risk decision
# ---------------------------------------------------------------------------

@dataclass
class RiskDecision:
    """
    Output from RiskEngine.evaluate().
    approved=False means no order must be submitted.
    """
    approved:        bool
    reason:          str
    adjusted_volume: float = 0.0
    block_reason:    Optional[str] = None
    defense_level:   int = 0
