"""
Meta-Decision Engine
====================
Translates AI model probabilities and multi-source contexts into trading decisions:
- Combines Model A (Regime), Model B (Directional Probabilities), and Model C (News Context).
- Enforces strict confidence thresholds.
- Capable of issuing NO_TRADE without treating it as a system failure.
- Decoupled from broker ordering (emits pure DecisionPayload).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional
import numpy as np


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"


@dataclass
class DecisionPayload:
    symbol: str
    epoch: int
    direction: Direction
    confidence: float
    probability_buy: float
    probability_sell: float
    probability_hold: float
    regime: str
    news_policy: str
    reason: str


class MetaDecisionEngine:
    def __init__(self, confidence_threshold: float = 0.55):
        self.confidence_threshold = confidence_threshold

    def evaluate(
        self,
        symbol: str,
        epoch: int,
        probabilities: np.ndarray,  # [p_hold, p_buy, p_sell]
        regime: str,
        news_policy: str,
        is_news_blackout: bool = False
    ) -> DecisionPayload:
        p_hold = float(probabilities[0])
        p_buy = float(probabilities[1])
        p_sell = float(probabilities[2])

        # 1. Economic blackout check
        if is_news_blackout or news_policy == "BLACKOUT":
            return DecisionPayload(
                symbol=symbol,
                epoch=epoch,
                direction=Direction.NO_TRADE,
                confidence=0.0,
                probability_buy=p_buy,
                probability_sell=p_sell,
                probability_hold=p_hold,
                regime=regime,
                news_policy=news_policy,
                reason="High-impact news blackout window active."
            )

        # 2. Extreme volatility regime check (applies to fiat forex, synthetic indices are designed for volatility)
        if not symbol.startswith("R_") and regime in {"HIGH_VOLATILITY", "UNCERTAIN"}:
            return DecisionPayload(
                symbol=symbol,
                epoch=epoch,
                direction=Direction.NO_TRADE,
                confidence=0.0,
                probability_buy=p_buy,
                probability_sell=p_sell,
                probability_hold=p_hold,
                regime=regime,
                news_policy=news_policy,
                reason=f"Adverse market regime: {regime}"
            )

        # 3. Model direction conviction check
        if p_buy > p_sell and p_buy >= self.confidence_threshold:
            return DecisionPayload(
                symbol=symbol,
                epoch=epoch,
                direction=Direction.BUY,
                confidence=p_buy,
                probability_buy=p_buy,
                probability_sell=p_sell,
                probability_hold=p_hold,
                regime=regime,
                news_policy=news_policy,
                reason=f"Bullish conviction above threshold ({p_buy:.2f} >= {self.confidence_threshold:.2f})"
            )
        elif p_sell > p_buy and p_sell >= self.confidence_threshold:
            return DecisionPayload(
                symbol=symbol,
                epoch=epoch,
                direction=Direction.SELL,
                confidence=p_sell,
                probability_buy=p_buy,
                probability_sell=p_sell,
                probability_hold=p_hold,
                regime=regime,
                news_policy=news_policy,
                reason=f"Bearish conviction above threshold ({p_sell:.2f} >= {self.confidence_threshold:.2f})"
            )
        else:
            return DecisionPayload(
                symbol=symbol,
                epoch=epoch,
                direction=Direction.HOLD,
                confidence=p_hold,
                probability_buy=p_buy,
                probability_sell=p_sell,
                probability_hold=p_hold,
                regime=regime,
                news_policy=news_policy,
                reason="Model conviction below confidence threshold."
            )
