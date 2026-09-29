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
    APPROVE     = "APPROVE"
    REJECT      = "REJECT"
    PASS        = "PASS"
    HOLD        = "HOLD"
    ADVISORY    = "ADVISORY"
    UNAVAILABLE = "UNAVAILABLE"


class FinalDecision(str, Enum):
    BUY   = "BUY"
    SELL  = "SELL"
    HOLD  = "HOLD"
    BLOCK = "BLOCK"


class BlockReason(str, Enum):
    BLOCK_NEWS              = "BLOCK_NEWS"
    BLOCK_SPREAD            = "BLOCK_SPREAD"
    BLOCK_SLIPPAGE          = "BLOCK_SLIPPAGE"
    BLOCK_DRAWDOWN          = "BLOCK_DRAWDOWN"
    BLOCK_DAILY_LOSS        = "BLOCK_DAILY_LOSS"
    BLOCK_CIRCUIT_BREAKER   = "BLOCK_CIRCUIT_BREAKER"
    BLOCK_REGIME            = "BLOCK_REGIME"
    BLOCK_SIGNAL            = "BLOCK_SIGNAL"
    BLOCK_CONFIDENCE        = "BLOCK_CONFIDENCE"
    BLOCK_EXECUTION         = "BLOCK_EXECUTION"
    BLOCK_DUPLICATE         = "BLOCK_DUPLICATE"
    BLOCK_STALE_SIGNAL      = "BLOCK_STALE_SIGNAL"
    BLOCK_INVALID_DATA      = "BLOCK_INVALID_DATA"
    BLOCK_MODEL_UNAVAILABLE = "BLOCK_MODEL_UNAVAILABLE"
    BLOCK_KILL_SWITCH       = "BLOCK_KILL_SWITCH"
    BLOCK_SESSION_OFF_HOURS = "BLOCK_SESSION_OFF_HOURS"


class NormalizedBlockReason(str):
    """
    Standardized block reason supporting canonical BLOCK_* taxonomy and legacy aliases.
    Normalizes reason codes across the entire architecture.
    """
    _ALIASES = {
        "BLOCK_KILL_SWITCH": {"KILL_SWITCH_ACTIVE", "BLOCK_KILL_SWITCH"},
        "BLOCK_CIRCUIT_BREAKER": {"CONSECUTIVE_LOSS_HALT", "BLOCK_CIRCUIT_BREAKER"},
        "BLOCK_DAILY_LOSS": {"DAILY_LOSS_LIMIT", "BLOCK_DAILY_LOSS"},
        "BLOCK_DRAWDOWN": {"MAX_DRAWDOWN", "BLOCK_DRAWDOWN"},
        "BLOCK_SPREAD": {"SPREAD_TOO_HIGH", "BLOCK_SPREAD"},
        "BLOCK_SLIPPAGE": {"SLIPPAGE_TOO_HIGH", "BLOCK_SLIPPAGE"},
        "BLOCK_DUPLICATE": {"MAX_POSITIONS_REACHED", "SYMBOL_EXPOSURE_LIMIT", "BLOCK_DUPLICATE"},
        "BLOCK_STALE_SIGNAL": {"STALE_DATA", "BLOCK_STALE_SIGNAL"},
        "BLOCK_NEWS": {"NEWS_BLACKOUT", "BLOCK_NEWS"},
        "BLOCK_EXECUTION": {"SIZING_REJECTED", "BLOCK_EXECUTION"},
        "BLOCK_SESSION_OFF_HOURS": {"SESSION_FILTER", "BLOCK_SESSION_OFF_HOURS"},
        "BLOCK_CONFIDENCE": {"INSUFFICIENT_CONFIDENCE", "BLOCK_CONFIDENCE"},
        "BLOCK_REGIME": {"COUNTER_TREND", "BLOCK_REGIME"},
        "BLOCK_SIGNAL": {"INVALID_SIGNAL", "BLOCK_SIGNAL"},
        "BLOCK_INVALID_DATA": {"SCHEMA_INVALID", "BLOCK_INVALID_DATA"},
        "BLOCK_MODEL_UNAVAILABLE": {"MODEL_UNAVAILABLE", "BLOCK_MODEL_UNAVAILABLE"},
    }

    def __eq__(self, other: Any) -> bool:
        other_str = other.value if hasattr(other, "value") else str(other)
        if str(self) == other_str:
            return True
        for aliases in self._ALIASES.values():
            if str(self) in aliases and other_str in aliases:
                return True
        return False

    def __hash__(self) -> int:
        return hash(str(self))


def normalize_block_reason(code: Optional[Any]) -> Optional[NormalizedBlockReason]:
    if code is None:
        return None
    val = code.value if hasattr(code, "value") else str(code)
    for canonical, aliases in NormalizedBlockReason._ALIASES.items():
        if val in aliases:
            return NormalizedBlockReason(canonical)
    return NormalizedBlockReason(val)


@dataclass
class TradeProposal:
    """
    Normalized AI Output Schema.
    AI output represents an analytical opinion / proposal, NOT an execution order.
    Now enriched with explicit separation of ML probability vs LLM qualitative confidence.
    """
    decision:                ProposalDecision
    direction:               Direction
    symbol:                  str
    confidence:              float = 0.0          # 0.0 to 1.0 (alias to llm_confidence)
    entry_context:           dict[str, Any] = field(default_factory=dict)
    invalidation:            str = ""             # primary market invalidation description
    rationale:               str = ""             # primary qualitative thesis
    scenario:                str = "RANGE"        # active scenario (e.g. BULLISH_CONTINUATION)
    timestamp:               datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    model_provider:          str = "unknown"      # e.g., 'openai/gpt-4o-mini', 'offline_rules'
    trace_id:                str = ""             # unique trace ID for audit and replay
    raw_response:            Optional[str] = None

    # Enhanced Architecture Fields (Auditable / Separated ML & LLM)
    llm_decision:            str = "NEUTRAL"
    llm_confidence:          float = 0.0
    ml_probability:          Optional[float] = None
    ml_model_version:        Optional[str] = None
    regime:                  str = "UNKNOWN"
    volatility_state:        str = "NORMAL"
    news_risk:               str = "LOW"
    technical_signal:        Optional[dict[str, Any]] = None
    reasons:                 list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    provider:                str = ""
    model:                   str = ""
    model_version:           str = "1.0"
    prompt_version:          str = "1.0"
    final_decision:          Optional[str] = None
    block_reason:            Optional[str] = None

    def __post_init__(self) -> None:
        if self.confidence > 0.0 and self.llm_confidence == 0.0:
            self.llm_confidence = self.confidence
        elif self.llm_confidence > 0.0 and self.confidence == 0.0:
            self.confidence = self.llm_confidence

        if self.rationale and not self.reasons:
            self.reasons = [self.rationale]
        elif self.reasons and not self.rationale:
            self.rationale = "; ".join(self.reasons)

        if self.invalidation and not self.invalidation_conditions:
            self.invalidation_conditions = [self.invalidation]
        elif self.invalidation_conditions and not self.invalidation:
            self.invalidation = "; ".join(self.invalidation_conditions)

        if not self.provider and self.model_provider:
            self.provider = self.model_provider
        elif not self.model_provider and self.provider:
            self.model_provider = self.provider

        if self.llm_decision == "NEUTRAL" and isinstance(self.decision, ProposalDecision):
            self.llm_decision = self.decision.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision":                self.decision.value if isinstance(self.decision, ProposalDecision) else str(self.decision),
            "direction":               self.direction.value if isinstance(self.direction, Direction) else str(self.direction),
            "symbol":                  self.symbol,
            "confidence":              self.confidence,
            "llm_confidence":          self.llm_confidence,
            "llm_decision":            self.llm_decision,
            "ml_probability":          self.ml_probability,
            "ml_model_version":        self.ml_model_version,
            "regime":                  self.regime,
            "volatility_state":        self.volatility_state,
            "news_risk":               self.news_risk,
            "technical_signal":        self.technical_signal,
            "reasons":                 self.reasons,
            "invalidation_conditions": self.invalidation_conditions,
            "entry_context":           self.entry_context,
            "invalidation":            self.invalidation,
            "rationale":               self.rationale,
            "scenario":                self.scenario,
            "timestamp":               self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else str(self.timestamp),
            "model_provider":          self.model_provider,
            "provider":                self.provider,
            "model":                   self.model,
            "model_version":           self.model_version,
            "prompt_version":          self.prompt_version,
            "trace_id":                self.trace_id,
            "final_decision":          self.final_decision,
            "block_reason":            self.block_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradeProposal:
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif not isinstance(ts, datetime):
            ts = datetime.now(tz=timezone.utc)

        raw_decision = data.get("decision", "PASS")
        try:
            decision = ProposalDecision(raw_decision)
        except ValueError:
            decision = ProposalDecision.PASS

        raw_direction = data.get("direction", "FLAT")
        try:
            direction = Direction(raw_direction)
        except ValueError:
            direction = Direction.FLAT

        confidence = float(data.get("confidence", data.get("llm_confidence", 0.0)))
        llm_conf = float(data.get("llm_confidence", confidence))

        reasons = list(data.get("reasons", []))
        rationale = str(data.get("rationale", ""))
        if not reasons and rationale:
            reasons = [rationale]

        inval_conds = list(data.get("invalidation_conditions", []))
        invalidation = str(data.get("invalidation", ""))
        if not inval_conds and invalidation:
            inval_conds = [invalidation]

        return cls(
            decision=decision,
            direction=direction,
            symbol=str(data.get("symbol", "")),
            confidence=confidence,
            llm_confidence=llm_conf,
            llm_decision=str(data.get("llm_decision", raw_decision)),
            ml_probability=data.get("ml_probability"),
            ml_model_version=data.get("ml_model_version"),
            regime=str(data.get("regime", "UNKNOWN")),
            volatility_state=str(data.get("volatility_state", "NORMAL")),
            news_risk=str(data.get("news_risk", "LOW")),
            technical_signal=data.get("technical_signal"),
            reasons=reasons,
            invalidation_conditions=inval_conds,
            entry_context=dict(data.get("entry_context", {})),
            invalidation=invalidation,
            rationale=rationale,
            scenario=str(data.get("scenario", "RANGE")),
            timestamp=ts,
            model_provider=str(data.get("model_provider", data.get("provider", "unknown"))),
            provider=str(data.get("provider", data.get("model_provider", "unknown"))),
            model=str(data.get("model", "")),
            model_version=str(data.get("model_version", "1.0")),
            prompt_version=str(data.get("prompt_version", "1.0")),
            trace_id=str(data.get("trace_id", "")),
            raw_response=data.get("raw_response"),
            final_decision=data.get("final_decision"),
            block_reason=data.get("block_reason"),
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
