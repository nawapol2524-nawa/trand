"""
Normalized Data Schemas for the Universal AI Layer.
Decouples Strategies and Risk Engines from specific AI providers.
AI output is strictly a PROPOSAL — never a broker order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from src.core.models import Direction, Timeframe


class ProposalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT  = "REJECT"
    PASS    = "PASS"


@dataclass
class TradeProposal:
    """
    Normalized AI Output Schema.
    AI output represents an analytical opinion / proposal, NOT an execution order.
    """
    decision:       ProposalDecision
    direction:      Direction
    symbol:         str
    confidence:     float            # 0.0 to 1.0
    entry_context:  dict[str, Any]   # verified market parameters at evaluation
    invalidation:   str              # explicit market condition that invalidates thesis
    rationale:      str              # reasoned explanation
    scenario:       str              # name of active scenario (e.g. BULLISH_CONTINUATION)
    timestamp:      datetime         # UTC generation time
    model_provider: str              # e.g., 'openai/gpt-4o-mini', 'offline_rules'
    trace_id:       str              # unique trace ID for audit and replay
    raw_response:   Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision":       self.decision.value,
            "direction":      self.direction.value,
            "symbol":         self.symbol,
            "confidence":     self.confidence,
            "entry_context":  self.entry_context,
            "invalidation":   self.invalidation,
            "rationale":      self.rationale,
            "scenario":       self.scenario,
            "timestamp":      self.timestamp.isoformat(),
            "model_provider": self.model_provider,
            "trace_id":       self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradeProposal:
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif not isinstance(ts, datetime):
            ts = datetime.now(tz=timezone.utc)
            
        return cls(
            decision=ProposalDecision(data["decision"]),
            direction=Direction(data["direction"]),
            symbol=str(data["symbol"]),
            confidence=float(data.get("confidence", 0.0)),
            entry_context=dict(data.get("entry_context", {})),
            invalidation=str(data.get("invalidation", "")),
            rationale=str(data.get("rationale", "")),
            scenario=str(data.get("scenario", "RANGE")),
            timestamp=ts,
            model_provider=str(data.get("model_provider", "unknown")),
            trace_id=str(data.get("trace_id", "")),
            raw_response=data.get("raw_response"),
        )


@dataclass
class AIContext:
    """
    Normalized Context Pipeline Schema — Phase G requirement.
    All mathematical indicators, lots, and risk metrics are pre-calculated by deterministic Python.
    AI only receives consolidated context for interpretation.
    """
    symbol:             str
    timeframe:          Timeframe
    price:              float
    trend:              str               # 'BULLISH', 'BEARISH', 'SIDEWAYS'
    rsi:                float
    ema:                dict[str, float]  # e.g., {'EMA9': 1.1425, 'EMA21': 1.1420}
    atr:                float
    market_structure:   str               # 'BOS_LONG', 'BOS_SHORT', 'RANGE', 'SWING'
    volatility:         str               # 'NORMAL', 'HIGH', 'EXTREME'
    session:            str               # 'LONDON', 'NEW_YORK', 'ASIAN', 'OVERLAP'
    news_state:         dict[str, Any]    # {'high_impact_soon': False, 'minutes_to_next': 120}
    current_position:   dict[str, Any]    # {'open_positions': 0, 'symbol_exposure': 0.0}
    account_risk_state: dict[str, Any]    # {'balance': 10000.0, 'daily_pnl_pct': 0.0}
    recent_trade_state: dict[str, Any]    # {'consecutive_losses': 0}
    scenario_state:     dict[str, Any]    # {'active_scenario': 'BULLISH_CONTINUATION'}
    timestamp:          datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol":             self.symbol,
            "timeframe":          self.timeframe.value,
            "price":              self.price,
            "trend":              self.trend,
            "rsi":                self.rsi,
            "ema":                self.ema,
            "atr":                self.atr,
            "market_structure":   self.market_structure,
            "volatility":         self.volatility,
            "session":            self.session,
            "news_state":         self.news_state,
            "current_position":   self.current_position,
            "account_risk_state": self.account_risk_state,
            "recent_trade_state": self.recent_trade_state,
            "scenario_state":     self.scenario_state,
            "timestamp":          self.timestamp.isoformat(),
        }


@dataclass
class ProviderCapabilities:
    is_llm:                   bool
    supports_structured_output: bool
    supports_chat:            bool
    supports_streaming:       bool
    token_limits:             int
    default_timeout:          float
    api_category:             str  # 'LLM', 'ML_INFERENCE', 'OFFLINE_RULES', 'PREDICTION'


@dataclass
class HealthCheckResult:
    is_healthy: bool
    latency_ms: float
    message:    str
    code:       str = "OK"
