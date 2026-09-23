"""
Event-Driven AI Invocation Detector — Phase F requirement.
Prevents per-tick AI invocation churn.
AI is invoked ONLY when a meaningful market or structural event occurs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from src.ai.schemas import AIContext
from src.core.models import Bar


class MarketEventType(str, Enum):
    BOS_OCCURRED            = "BOS_OCCURRED"
    REGIME_CHANGE           = "REGIME_CHANGE"
    VOLATILITY_SPIKE        = "VOLATILITY_SPIKE"
    SESSION_TRANSITION      = "SESSION_TRANSITION"
    POSITION_CLOSED         = "POSITION_CLOSED"
    ORDER_REJECTED          = "ORDER_REJECTED"
    MONITORED_ZONE_REACHED  = "MONITORED_ZONE_REACHED"
    SCHEDULED_REVIEW        = "SCHEDULED_REVIEW"


@dataclass
class MarketEvent:
    event_type: MarketEventType
    symbol:     str
    timestamp:  datetime
    details:    dict


class EventDetector:
    """
    Evaluates market changes to determine if an AI invocation is warranted.
    If no meaningful event has occurred, AI invocation is suppressed.
    """

    def __init__(self, cooldown_seconds: float = 60.0):
        self.cooldown_seconds = cooldown_seconds
        self._last_invocation_time: dict[str, datetime] = {}
        self._last_session: dict[str, str] = {}
        self._last_trend: dict[str, str] = {}

    def should_invoke(
        self,
        context: AIContext,
        now: Optional[datetime] = None,
        force_review: bool = False,
    ) -> tuple[bool, Optional[MarketEvent]]:
        """
        Check if an event justifies calling the AI layer.
        Returns: (should_invoke: bool, event: Optional[MarketEvent])
        """
        now_utc = now or datetime.now(tz=timezone.utc)
        sym = context.symbol

        # 1. Respect cooldown to prevent invocation spam
        last_time = self._last_invocation_time.get(sym)
        if last_time:
            elapsed = (now_utc - last_time).total_seconds()
            if elapsed < self.cooldown_seconds and not force_review:
                return False, None

        # 2. Check for Break of Structure (BOS)
        if context.market_structure in ("BOS_LONG", "BOS_SHORT"):
            event = MarketEvent(
                event_type=MarketEventType.BOS_OCCURRED,
                symbol=sym,
                timestamp=now_utc,
                details={"structure": context.market_structure, "price": context.price},
            )
            self._record_invocation(sym, now_utc, context)
            return True, event

        # 3. Check for Regime/Trend Change
        prev_trend = self._last_trend.get(sym)
        if prev_trend and prev_trend != context.trend:
            event = MarketEvent(
                event_type=MarketEventType.REGIME_CHANGE,
                symbol=sym,
                timestamp=now_utc,
                details={"prev_trend": prev_trend, "new_trend": context.trend},
            )
            self._record_invocation(sym, now_utc, context)
            return True, event

        # 4. Check for Volatility Spike
        if context.volatility in ("HIGH", "EXTREME"):
            event = MarketEvent(
                event_type=MarketEventType.VOLATILITY_SPIKE,
                symbol=sym,
                timestamp=now_utc,
                details={"volatility": context.volatility, "atr": context.atr},
            )
            self._record_invocation(sym, now_utc, context)
            return True, event

        # 5. Check for Session Transition
        prev_session = self._last_session.get(sym)
        if prev_session and prev_session != context.session:
            event = MarketEvent(
                event_type=MarketEventType.SESSION_TRANSITION,
                symbol=sym,
                timestamp=now_utc,
                details={"prev_session": prev_session, "new_session": context.session},
            )
            self._record_invocation(sym, now_utc, context)
            return True, event

        # 6. Forced or Scheduled Review
        if force_review:
            event = MarketEvent(
                event_type=MarketEventType.SCHEDULED_REVIEW,
                symbol=sym,
                timestamp=now_utc,
                details={"reason": "forced_or_scheduled"},
            )
            self._record_invocation(sym, now_utc, context)
            return True, event

        # Default: no meaningful event -> do not invoke AI
        self._last_trend[sym] = context.trend
        self._last_session[sym] = context.session
        return False, None

    def _record_invocation(self, symbol: str, now: datetime, context: AIContext) -> None:
        self._last_invocation_time[symbol] = now
        self._last_trend[symbol] = context.trend
        self._last_session[symbol] = context.session
