"""
Deterministic Gate & TradeProposal Validation — Phase E requirement.
AI output is strictly validated against hard mathematical, risk, and schema constraints.
AI has ZERO authority to override risk limits, kill switches, or stale data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from src.ai.schemas import AIContext, BlockReason, FinalDecision, ProposalDecision, TradeProposal
from src.core.models import Direction


@dataclass
class ValidationResult:
    passed:         bool
    decision:       str                       # 'APPROVED', 'REJECTED', 'BLOCK'
    reason:         str
    checks:         dict[str, bool]
    final_decision: FinalDecision = FinalDecision.BLOCK
    block_reason:   Optional[BlockReason] = None
    repaired:       bool = False
    repair_count:   int = 0


class DeterministicGate:
    """
    Independent gatekeeper enforcing deterministic safety over all AI proposals.
    Rules:
      1. Schema integrity & completeness
      2. Data freshness (rejection if stale > MAX_STALENESS_SECONDS)
      3. Strategy trend alignment (cannot propose counter-trend unless explicit reversal)
      4. Risk limits (kill switch, daily loss, max positions, circuit breakers)
      5. Execution limits (news blackout, spread, slippage, session)
      6. Absolute veto over LLM: LLM can NEVER override any hard safety check.
    """

    MAX_STALENESS_SECONDS: float = 60.0
    MIN_CONFIDENCE_THRESHOLD: float = 0.65
    MAX_REPAIR_ATTEMPTS: int = 2

    @classmethod
    def validate(
        cls,
        proposal: TradeProposal,
        context: AIContext,
        max_daily_loss_pct: float = 0.05,
        max_open_positions: int = 3,
        now: Optional[datetime] = None,
        enforce_session_filter: bool = False,
        current_spread_pips: Optional[float] = None,
        max_spread_pips: Optional[float] = None,
        slippage_pips: Optional[float] = None,
        max_slippage_pips: Optional[float] = None,
        require_llm_advisory: bool = False,
    ) -> ValidationResult:
        now_utc = now or datetime.now(tz=timezone.utc)
        checks: dict[str, bool] = {}

        # 1. Schema & completeness check
        has_symbol = bool(proposal.symbol and proposal.symbol == context.symbol)
        has_rationale = bool(
            (proposal.rationale and len(proposal.rationale.strip()) > 3)
            or (proposal.reasons and len(proposal.reasons) > 0)
        )
        has_invalidation = bool(
            (proposal.invalidation and len(proposal.invalidation.strip()) > 3)
            or (proposal.invalidation_conditions and len(proposal.invalidation_conditions) > 0)
        )
        valid_confidence = 0.0 <= proposal.confidence <= 1.0

        checks["schema_complete"] = has_symbol and has_rationale and has_invalidation and valid_confidence
        if not checks["schema_complete"]:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                final_decision=FinalDecision.BLOCK,
                block_reason=BlockReason.BLOCK_INVALID_DATA,
                reason="Schema validation failed: missing symbol, rationale, invalidation, or invalid confidence",
                checks=checks,
            )

        # 2. Freshness check
        age_seconds = (now_utc - proposal.timestamp).total_seconds()
        checks["data_fresh"] = age_seconds <= cls.MAX_STALENESS_SECONDS
        if not checks["data_fresh"]:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                final_decision=FinalDecision.BLOCK,
                block_reason=BlockReason.BLOCK_STALE_SIGNAL,
                reason=f"Stale proposal: age is {age_seconds:.1f}s (max allowed {cls.MAX_STALENESS_SECONDS}s)",
                checks=checks,
            )

        # 3. Kill Switch & Risk State Check (AI CANNOT OVERRIDE)
        risk_state = context.account_risk_state
        kill_switch = risk_state.get("kill_switch_active", False)
        daily_loss = risk_state.get("daily_pnl_pct", 0.0)

        checks["kill_switch_clear"] = not kill_switch
        if not checks["kill_switch_clear"]:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                final_decision=FinalDecision.BLOCK,
                block_reason=BlockReason.BLOCK_KILL_SWITCH,
                reason="HARD GATE: Emergency kill switch is active",
                checks=checks,
            )

        checks["daily_loss_within_limit"] = daily_loss > -max_daily_loss_pct
        if not checks["daily_loss_within_limit"]:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                final_decision=FinalDecision.BLOCK,
                block_reason=BlockReason.BLOCK_DAILY_LOSS,
                reason=f"HARD GATE: Daily loss limit reached ({daily_loss:.2%} <= -{max_daily_loss_pct:.2%})",
                checks=checks,
            )

        # 3.1 Circuit Breaker / Consecutive Loss Check
        consec_losses = context.recent_trade_state.get("consecutive_losses", 0) if context.recent_trade_state else 0
        circuit_active = context.recent_trade_state.get("circuit_breaker_active", False) if context.recent_trade_state else False
        checks["circuit_breaker_clear"] = not circuit_active and consec_losses < 5
        if not checks["circuit_breaker_clear"]:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                final_decision=FinalDecision.BLOCK,
                block_reason=BlockReason.BLOCK_CIRCUIT_BREAKER,
                reason=f"HARD GATE: Circuit breaker active ({consec_losses} consecutive losses)",
                checks=checks,
            )

        # 3.2 Position limit / Duplicate Check
        open_pos_count = context.current_position.get("open_positions", 0)
        checks["position_limit_ok"] = open_pos_count < max_open_positions
        if proposal.decision == ProposalDecision.APPROVE and not checks["position_limit_ok"]:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                final_decision=FinalDecision.BLOCK,
                block_reason=BlockReason.BLOCK_DUPLICATE,
                reason=f"HARD GATE: Max open positions limit reached ({open_pos_count}/{max_open_positions})",
                checks=checks,
            )

        # 4. News Blackout Check (AI CANNOT OVERRIDE)
        news_high_impact = context.news_state.get("high_impact_soon", False)
        checks["news_window_clear"] = not news_high_impact
        if not checks["news_window_clear"]:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                final_decision=FinalDecision.BLOCK,
                block_reason=BlockReason.BLOCK_NEWS,
                reason="HARD GATE: News blackout window active (high-impact event)",
                checks=checks,
            )

        # 4.1 Pre-trade Spread Guard
        if current_spread_pips is not None and max_spread_pips is not None:
            spread_ok = current_spread_pips <= max_spread_pips
            checks["spread_within_limit"] = spread_ok
            if not spread_ok:
                return ValidationResult(
                    passed=False,
                    decision="REJECTED",
                    final_decision=FinalDecision.BLOCK,
                    block_reason=BlockReason.BLOCK_SPREAD,
                    reason=f"HARD GATE: Current spread {current_spread_pips:.2f} pips exceeds allowed {max_spread_pips:.2f} pips for {context.symbol}",
                    checks=checks,
                )
        else:
            checks["spread_within_limit"] = True

        # 4.2 Slippage Guard
        if slippage_pips is not None and max_slippage_pips is not None:
            slippage_ok = slippage_pips <= max_slippage_pips
            checks["slippage_within_limit"] = slippage_ok
            if not slippage_ok:
                return ValidationResult(
                    passed=False,
                    decision="REJECTED",
                    final_decision=FinalDecision.BLOCK,
                    block_reason=BlockReason.BLOCK_SLIPPAGE,
                    reason=f"HARD GATE: Slippage {slippage_pips:.2f} pips exceeds maximum {max_slippage_pips:.2f} pips",
                    checks=checks,
                )
        else:
            checks["slippage_within_limit"] = True

        # 4.3 Institutional Session Filter Check
        session = getattr(context, "session", "UNKNOWN").upper()
        allowed_sessions = ("LONDON", "OVERLAP_LONDON_NY", "OVERLAP", "NEW_YORK")
        checks["session_active"] = session in allowed_sessions if enforce_session_filter else True
        if enforce_session_filter and not (session in allowed_sessions):
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                final_decision=FinalDecision.BLOCK,
                block_reason=BlockReason.BLOCK_SESSION_OFF_HOURS,
                reason=f"Institutional Session Filter: Session '{session}' is off-hours. Active windows: London (07:00-12:00 UTC) & New York (12:00-21:00 UTC)",
                checks=checks,
            )

        # 4.4 Provider Availability Policy Check
        if proposal.decision == ProposalDecision.UNAVAILABLE:
            if require_llm_advisory:
                return ValidationResult(
                    passed=False,
                    decision="REJECTED",
                    final_decision=FinalDecision.BLOCK,
                    block_reason=BlockReason.BLOCK_MODEL_UNAVAILABLE,
                    reason="HARD GATE: Mandatory LLM advisory layer is unavailable",
                    checks=checks,
                )
            else:
                checks["llm_advisory_available"] = False
        else:
            checks["llm_advisory_available"] = True

        # 4.5 Proposal Decision Check (Advisory veto)
        if proposal.decision in (ProposalDecision.REJECT, ProposalDecision.HOLD, ProposalDecision.PASS):
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                final_decision=FinalDecision.BLOCK,
                block_reason=BlockReason.BLOCK_CONFIDENCE,
                reason=f"Proposal decision is {proposal.decision.value}: {proposal.rationale}",
                checks=checks,
            )

        # 5. Confidence Threshold Check (Level 2 Restricted Mode: 0.80 threshold if consecutive_losses >= 3)
        req_confidence = 0.80 if consec_losses >= 3 else cls.MIN_CONFIDENCE_THRESHOLD
        checks["confidence_sufficient"] = (
            proposal.decision != ProposalDecision.APPROVE or proposal.confidence >= req_confidence
        )
        if not checks["confidence_sufficient"]:
            level_str = " (Level 2 Restricted Mode)" if consec_losses >= 3 else ""
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                final_decision=FinalDecision.BLOCK,
                block_reason=BlockReason.BLOCK_CONFIDENCE,
                reason=f"Insufficient AI confidence: {proposal.confidence:.2f} < {req_confidence:.2f}{level_str}",
                checks=checks,
            )

        # 6. Direction & Trend Alignment Check (M5 & H1 Regime)
        h1_regime = context.scenario_state.get("h1_regime") if context.scenario_state else None
        valid_long_scenarios = ("REVERSAL", "BREAKOUT", "BULLISH_BREAKOUT", "REVERSAL_CONFIRMED")
        valid_short_scenarios = ("REVERSAL", "BREAKDOWN", "BEARISH_BREAKDOWN", "REVERSAL_CONFIRMED")

        if proposal.decision == ProposalDecision.APPROVE:
            if h1_regime == "BEARISH" and proposal.direction == Direction.LONG and proposal.scenario not in valid_long_scenarios:
                checks["h1_regime_alignment"] = False
                return ValidationResult(
                    passed=False,
                    decision="REJECTED",
                    final_decision=FinalDecision.BLOCK,
                    block_reason=BlockReason.BLOCK_REGIME,
                    reason="Proposal LONG contradicts BEARISH H1 regime without confirmed REVERSAL scenario",
                    checks=checks,
                )
            elif h1_regime == "BULLISH" and proposal.direction == Direction.SHORT and proposal.scenario not in valid_short_scenarios:
                checks["h1_regime_alignment"] = False
                return ValidationResult(
                    passed=False,
                    decision="REJECTED",
                    final_decision=FinalDecision.BLOCK,
                    block_reason=BlockReason.BLOCK_REGIME,
                    reason="Proposal SHORT contradicts BULLISH H1 regime without confirmed REVERSAL scenario",
                    checks=checks,
                )
            else:
                checks["h1_regime_alignment"] = True

            if proposal.direction == Direction.LONG and context.trend == "BEARISH" and proposal.scenario != "REVERSAL":
                checks["trend_alignment"] = False
                return ValidationResult(
                    passed=False,
                    decision="REJECTED",
                    final_decision=FinalDecision.BLOCK,
                    block_reason=BlockReason.BLOCK_REGIME,
                    reason="Proposal LONG contradicts BEARISH trend without confirmed REVERSAL scenario",
                    checks=checks,
                )
            elif proposal.direction == Direction.SHORT and context.trend == "BULLISH" and proposal.scenario != "REVERSAL":
                checks["trend_alignment"] = False
                return ValidationResult(
                    passed=False,
                    decision="REJECTED",
                    final_decision=FinalDecision.BLOCK,
                    block_reason=BlockReason.BLOCK_REGIME,
                    reason="Proposal SHORT contradicts BULLISH trend without confirmed REVERSAL scenario",
                    checks=checks,
                )
            else:
                checks["trend_alignment"] = True
        else:
            checks["h1_regime_alignment"] = True
            checks["trend_alignment"] = True

        all_passed = all(checks.values())
        if all_passed:
            exec_dir = FinalDecision.BUY if proposal.direction == Direction.LONG else FinalDecision.SELL
            return ValidationResult(
                passed=True,
                decision="APPROVED",
                final_decision=exec_dir,
                block_reason=None,
                reason="All deterministic gate checks passed",
                checks=checks,
            )
        else:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                final_decision=FinalDecision.BLOCK,
                block_reason=BlockReason.BLOCK_SIGNAL,
                reason="Gate check failed",
                checks=checks,
            )
