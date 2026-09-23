"""
Deterministic Gate & TradeProposal Validation — Phase E requirement.
AI output is strictly validated against hard mathematical, risk, and schema constraints.
AI has ZERO authority to override risk limits, kill switches, or stale data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from src.ai.schemas import AIContext, ProposalDecision, TradeProposal
from src.core.models import Direction


@dataclass
class ValidationResult:
    passed:       bool
    decision:     str              # 'APPROVED', 'REJECTED'
    reason:       str
    checks:       dict[str, bool]
    repaired:     bool = False
    repair_count: int = 0


class DeterministicGate:
    """
    Independent gatekeeper enforcing deterministic safety over all AI proposals.
    Rules:
      1. Schema integrity & completeness
      2. Data freshness (rejection if stale > MAX_STALENESS_SECONDS)
      3. Strategy trend alignment (cannot propose counter-trend unless explicit reversal)
      4. Risk limits (kill switch, daily loss, max positions)
      5. Fail-closed guarantee
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
    ) -> ValidationResult:
        now_utc = now or datetime.now(tz=timezone.utc)
        checks: dict[str, bool] = {}

        # 1. Schema & completeness check
        has_symbol = bool(proposal.symbol and proposal.symbol == context.symbol)
        has_rationale = bool(proposal.rationale and len(proposal.rationale.strip()) > 5)
        has_invalidation = bool(proposal.invalidation and len(proposal.invalidation.strip()) > 3)
        valid_confidence = 0.0 <= proposal.confidence <= 1.0

        checks["schema_complete"] = has_symbol and has_rationale and has_invalidation and valid_confidence
        if not checks["schema_complete"]:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
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
                reason="HARD GATE: Emergency kill switch is active",
                checks=checks,
            )

        checks["daily_loss_within_limit"] = daily_loss > -max_daily_loss_pct
        if not checks["daily_loss_within_limit"]:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                reason=f"HARD GATE: Daily loss limit reached ({daily_loss:.2%} <= -{max_daily_loss_pct:.2%})",
                checks=checks,
            )

        open_pos_count = context.current_position.get("open_positions", 0)
        checks["position_limit_ok"] = open_pos_count < max_open_positions
        if proposal.decision == ProposalDecision.APPROVE and not checks["position_limit_ok"]:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                reason=f"HARD GATE: Max open positions limit reached ({open_pos_count}/{max_open_positions})",
                checks=checks,
            )

        # 4. News Blackout Check
        news_high_impact = context.news_state.get("high_impact_soon", False)
        checks["news_window_clear"] = not news_high_impact
        if proposal.decision == ProposalDecision.APPROVE and not checks["news_window_clear"]:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                reason="HARD GATE: News blackout window active",
                checks=checks,
            )

        # 5. Confidence Threshold Check
        checks["confidence_sufficient"] = (
            proposal.decision != ProposalDecision.APPROVE or proposal.confidence >= cls.MIN_CONFIDENCE_THRESHOLD
        )
        if not checks["confidence_sufficient"]:
            return ValidationResult(
                passed=False,
                decision="REJECTED",
                reason=f"Insufficient AI confidence: {proposal.confidence:.2f} < {cls.MIN_CONFIDENCE_THRESHOLD:.2f}",
                checks=checks,
            )

        # 6. Direction & Trend Alignment Check
        if proposal.decision == ProposalDecision.APPROVE:
            if proposal.direction == Direction.LONG and context.trend == "BEARISH" and proposal.scenario != "REVERSAL":
                checks["trend_alignment"] = False
                return ValidationResult(
                    passed=False,
                    decision="REJECTED",
                    reason="Proposal LONG contradicts BEARISH trend without confirmed REVERSAL scenario",
                    checks=checks,
                )
            elif proposal.direction == Direction.SHORT and context.trend == "BULLISH" and proposal.scenario != "REVERSAL":
                checks["trend_alignment"] = False
                return ValidationResult(
                    passed=False,
                    decision="REJECTED",
                    reason="Proposal SHORT contradicts BULLISH trend without confirmed REVERSAL scenario",
                    checks=checks,
                )
            else:
                checks["trend_alignment"] = True
        else:
            checks["trend_alignment"] = True

        all_passed = all(checks.values())
        return ValidationResult(
            passed=all_passed,
            decision="APPROVED" if all_passed else "REJECTED",
            reason="All deterministic gate checks passed" if all_passed else "Gate check failed",
            checks=checks,
        )
