"""
Post-Trade Loss Reason Classifier — Module 5.
Categorizes trade losses into actionable root causes:
  - SPREAD_COST: Trade exited at loss where spread represented a major fraction of stop loss or quick exit
  - NEWS_EVENT: Exit coincided with high-impact economic news volatility
  - SLIPPAGE_IMPACT: Execution slippage significantly worsened exit price
  - REGIME_REVERSAL: Higher timeframe trend reversed against the trade
  - NORMAL_STRATEGY_LOSS: Standard strategy stop loss hit under normal market conditions
"""
from __future__ import annotations

from typing import Optional


class LossReason:
    PROFIT = "PROFIT"
    SPREAD_COST = "SPREAD_COST"
    NEWS_EVENT = "NEWS_EVENT"
    SLIPPAGE_IMPACT = "SLIPPAGE_IMPACT"
    REGIME_REVERSAL = "REGIME_REVERSAL"
    NORMAL_STRATEGY_LOSS = "NORMAL_STRATEGY_LOSS"


def classify_loss_reason(
    realized_pnl: float,
    slippage_pips: float = 0.0,
    max_slippage_threshold: float = 3.0,
    duration_seconds: float = 0.0,
    news_active: bool = False,
    regime_reversed: bool = False,
    spread_pips: float = 0.0,
    sl_distance_pips: Optional[float] = None,
) -> str:
    """
    Classifies the primary root cause for a closed position's loss.
    """
    if realized_pnl >= 0:
        return LossReason.PROFIT

    # 1. High impact news event took place
    if news_active:
        return LossReason.NEWS_EVENT

    # 2. Execution slippage significantly impacted the exit price
    if slippage_pips >= max_slippage_threshold:
        return LossReason.SLIPPAGE_IMPACT

    # 3. Higher timeframe (e.g. H1) trend reversed against position direction
    if regime_reversed:
        return LossReason.REGIME_REVERSAL

    # 4. Spread friction dominated the loss (quick exit where spread >= 35% of SL distance)
    if (
        duration_seconds > 0
        and duration_seconds < 180
        and sl_distance_pips is not None
        and sl_distance_pips > 0
        and (spread_pips / sl_distance_pips) >= 0.35
    ):
        return LossReason.SPREAD_COST

    # 5. Otherwise standard strategy stop loss
    return LossReason.NORMAL_STRATEGY_LOSS
