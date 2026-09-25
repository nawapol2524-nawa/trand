"""
AI Context Pipeline — Phase G requirement.
Compiles strictly deterministic indicators, market structure, and risk state
into a normalized AIContext object. AI calculates zero raw math.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from src.ai.schemas import AIContext
from src.core.indicators import atr, ema, rsi
from src.core.models import Bar, Timeframe
from src.core.signals import bos_long, bos_short


class AIContextBuilder:
    """Builds a normalized AIContext from raw closed bars and portfolio state."""

    @staticmethod
    def determine_session(utc_dt: datetime) -> str:
        """Categorize current session by UTC hour."""
        hour = utc_dt.hour
        if 7 <= hour < 12:
            return "LONDON"
        elif 12 <= hour < 16:
            return "OVERLAP_LONDON_NY"
        elif 16 <= hour < 21:
            return "NEW_YORK"
        elif 21 <= hour < 24 or 0 <= hour < 7:
            return "ASIAN"
        return "UNKNOWN"

    @classmethod
    def build(
        cls,
        symbol: str,
        timeframe: Timeframe,
        m5_bars: list[Bar],
        account_risk_state: Optional[dict[str, Any]] = None,
        current_position: Optional[dict[str, Any]] = None,
        recent_trade_state: Optional[dict[str, Any]] = None,
        news_state: Optional[dict[str, Any]] = None,
        scenario_state: Optional[dict[str, Any]] = None,
        now: Optional[datetime] = None,
        h1_bars: Optional[list[Bar]] = None,
    ) -> AIContext:
        """
        Build normalized AIContext from closed bars.
        Caller must ensure bars[0] is closed.
        """
        if len(m5_bars) < 25:
            raise ValueError(f"Insufficient bars to build AIContext: {len(m5_bars)} < 25")

        now_utc = now or (m5_bars[0].timestamp if m5_bars else datetime.now(tz=timezone.utc))
        closes = np.array([b.close for b in reversed(m5_bars)])
        highs = np.array([b.high for b in reversed(m5_bars)])
        lows = np.array([b.low for b in reversed(m5_bars)])

        # Calculate deterministic technical indicators
        ema9_arr = ema(closes, 9)
        ema21_arr = ema(closes, 21)
        ema200_arr = ema(closes, 200) if len(closes) >= 200 else np.full(len(closes), np.nan)
        rsi_arr = rsi(closes, 14)
        atr_arr = atr(highs, lows, closes, 14)

        current_price = float(closes[-1])
        current_ema9 = float(ema9_arr[-1]) if not np.isnan(ema9_arr[-1]) else current_price
        current_ema21 = float(ema21_arr[-1]) if not np.isnan(ema21_arr[-1]) else current_price
        current_rsi = float(rsi_arr[-1]) if not np.isnan(rsi_arr[-1]) else 50.0
        current_atr = float(atr_arr[-1]) if not np.isnan(atr_arr[-1]) else (highs[-1] - lows[-1])

        # Trend classification
        if current_ema9 > current_ema21 and current_price >= current_ema9:
            trend = "BULLISH"
        elif current_ema9 < current_ema21 and current_price <= current_ema9:
            trend = "BEARISH"
        else:
            trend = "SIDEWAYS"

        # Market structure
        if bos_long(m5_bars, 20):
            market_structure = "BOS_LONG"
        elif bos_short(m5_bars, 20):
            market_structure = "BOS_SHORT"
        else:
            market_structure = "RANGE"

        # Volatility assessment
        recent_ranges = [b.high - b.low for b in m5_bars[:10]]
        avg_recent_range = sum(recent_ranges) / len(recent_ranges) if recent_ranges else current_atr
        if current_atr > 0 and (avg_recent_range / current_atr) > 1.8:
            volatility = "HIGH"
        elif current_atr > 0 and (avg_recent_range / current_atr) > 2.5:
            volatility = "EXTREME"
        else:
            volatility = "NORMAL"

        session = cls.determine_session(now_utc)

        # Higher Timeframe H1 Regime Integration
        scen_state = dict(scenario_state or {"active_scenario": "NONE"})
        if h1_bars and len(h1_bars) >= 50:
            h1_closes = np.array([b.close for b in reversed(h1_bars)])
            h1_ema50_arr = ema(h1_closes, 50)
            if not np.isnan(h1_ema50_arr[-1]):
                scen_state["h1_regime"] = "BULLISH" if h1_closes[-1] > h1_ema50_arr[-1] else "BEARISH"
                scen_state["h1_ema50"] = round(float(h1_ema50_arr[-1]), 5)

        return AIContext(
            symbol=symbol,
            timeframe=timeframe,
            price=round(current_price, 5),
            trend=trend,
            rsi=round(current_rsi, 2),
            ema={"EMA9": round(current_ema9, 5), "EMA21": round(current_ema21, 5)},
            atr=round(current_atr, 5),
            market_structure=market_structure,
            volatility=volatility,
            session=session,
            news_state=news_state or {"high_impact_soon": False, "minutes_to_next": 999},
            current_position=current_position or {"open_positions": 0, "symbol_exposure": 0.0},
            account_risk_state=account_risk_state or {"daily_pnl_pct": 0.0, "kill_switch_active": False},
            recent_trade_state=recent_trade_state or {"consecutive_losses": 0},
            scenario_state=scen_state,
            timestamp=now_utc,
        )
