"""
AI Decision Architecture Comprehensive Test Suite
Validates Sections 14 (Determinism), 15 (Provider Consistency), 16 (Hard Veto & Risk Override Prevention),
and canonical Taxonomy Normalization according to institutional production trading standards.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest

from src.ai.provider import (
    DeterministicDecisionEngine,
    FailoverAIProvider,
    GroqProvider,
    OpenAIProvider,
)
from src.ai.schemas import (
    AIContext,
    BlockReason,
    FinalDecision,
    NormalizedBlockReason,
    ProposalDecision,
    TradeProposal,
    normalize_block_reason,
)
from src.ai.validator import DeterministicGate, ValidationResult
from src.core.models import Direction, Signal, Timeframe
from src.core.risk import RiskConfig, RiskEngine


def make_test_context(
    symbol: str = "EURUSD",
    price: float = 1.1450,
    trend: str = "BULLISH",
    rsi: float = 58.0,
    high_impact_news: bool = False,
    open_positions: int = 0,
    daily_pnl_pct: float = 0.0,
    consecutive_losses: int = 0,
    session: str = "LONDON",
    market_structure: str = "BOS_LONG",
    timestamp: datetime = None,
) -> AIContext:
    return AIContext(
        symbol=symbol,
        timeframe=Timeframe.M5,
        price=price,
        trend=trend,
        rsi=rsi,
        ema={"EMA9": 1.1440, "EMA21": 1.1420, "EMA200": 1.1380},
        atr=0.0015,
        market_structure=market_structure,
        volatility="NORMAL",
        session=session,
        news_state={"high_impact_soon": high_impact_news, "minutes_to_next": 10 if high_impact_news else 180},
        current_position={"open_positions": open_positions, "symbol_exposure": 0.0},
        account_risk_state={"balance": 10000.0, "daily_pnl_pct": daily_pnl_pct},
        recent_trade_state={"consecutive_losses": consecutive_losses},
        scenario_state={"active_scenario": "BULLISH_CONTINUATION", "h1_regime": "BULLISH"},
        timestamp=timestamp or datetime.now(tz=timezone.utc),
    )


# ============================================================================
# SECTION 14: DETERMINISM TESTS
# ============================================================================
class TestArchitectureDeterminism:
    """Verifies that non-LLM decision components are 100% deterministic."""

    def test_deterministic_decision_engine_reproducibility(self):
        engine = DeterministicDecisionEngine()
        context = make_test_context(
            timestamp=datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)
        )

        proposals = [engine.analyze(context) for _ in range(5)]
        first = proposals[0]

        for p in proposals[1:]:
            assert p.decision == first.decision
            assert p.confidence == first.confidence
            assert p.llm_confidence == first.llm_confidence
            assert p.direction == first.direction
            assert p.regime == first.regime
            assert p.reasons == first.reasons
            assert p.provider == first.provider

    def test_deterministic_gate_reproducibility(self):
        context = make_test_context(
            timestamp=datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)
        )
        proposal = TradeProposal(
            symbol="EURUSD",
            direction=Direction.LONG,
            decision=ProposalDecision.APPROVE,
            confidence=0.85,
            llm_confidence=0.85,
            reasons=["Strong momentum"],
            invalidation="Drop below EMA200",
            invalidation_conditions=["Drop below EMA200"],
        )

        results = [
            DeterministicGate.validate(
                proposal=proposal,
                context=context,
                current_spread_pips=1.2,
                max_spread_pips=2.5,
            )
            for _ in range(5)
        ]
        first = results[0]

        for r in results[1:]:
            assert r.passed == first.passed
            assert r.final_decision == first.final_decision
            assert r.block_reason == first.block_reason
            assert r.reason == first.reason


# ============================================================================
# SECTION 15: PROVIDER FAILOVER CONSISTENCY (CASES A - D)
# ============================================================================
class TestProviderFailoverConsistency:
    """Verifies failover behavior across Cases A, B, C, and D."""

    def test_case_a_primary_groq_success(self):
        mock_groq = MagicMock()
        mock_groq.provider_name = "groq"
        mock_groq.analyze.return_value = TradeProposal(
            symbol="EURUSD",
            direction=Direction.LONG,
            decision=ProposalDecision.APPROVE,
            confidence=0.88,
            provider="groq",
        )

        mock_openai = MagicMock()
        mock_openai.provider_name = "openai"

        failover = FailoverAIProvider(primary=mock_groq, secondary=mock_openai)
        context = make_test_context()

        proposal = failover.analyze(context)
        assert proposal.decision == ProposalDecision.APPROVE
        assert proposal.provider == "groq"
        assert failover.last_used_provider == "groq"
        mock_groq.analyze.assert_called_once()
        mock_openai.analyze.assert_not_called()

    def test_case_b_groq_down_openai_fallback(self):
        mock_groq = MagicMock()
        mock_groq.provider_name = "groq"
        mock_groq.analyze.side_effect = RuntimeError("Groq rate limit exceeded 429")

        mock_openai = MagicMock()
        mock_openai.provider_name = "openai"
        mock_openai.analyze.return_value = TradeProposal(
            symbol="EURUSD",
            direction=Direction.LONG,
            decision=ProposalDecision.APPROVE,
            confidence=0.82,
            provider="openai",
        )

        failover = FailoverAIProvider(primary=mock_groq, secondary=mock_openai)
        context = make_test_context()

        proposal = failover.analyze(context)
        assert proposal.decision == ProposalDecision.APPROVE
        assert proposal.provider == "openai"
        assert failover.last_used_provider == "openai"
        mock_groq.analyze.assert_called_once()
        mock_openai.analyze.assert_called_once()

    def test_case_c_both_llms_down_explicit_unavailable(self):
        mock_groq = MagicMock()
        mock_groq.provider_name = "groq"
        mock_groq.analyze.side_effect = RuntimeError("Groq connection timeout")

        mock_openai = MagicMock()
        mock_openai.provider_name = "openai"
        mock_openai.analyze.side_effect = RuntimeError("OpenAI quota exceeded")

        failover = FailoverAIProvider(
            primary=mock_groq,
            secondary=mock_openai,
            allow_offline_fallback=False, # Disable offline fallback to test explicit LLM_UNAVAILABLE
        )
        context = make_test_context()

        proposal = failover.analyze(context)
        assert proposal.decision == ProposalDecision.UNAVAILABLE
        assert proposal.provider == "none"
        assert "LLM_UNAVAILABLE" in proposal.reasons[0]
        assert failover.last_used_provider == "none"

    def test_case_d_no_api_keys_handled_gracefully(self):
        with patch.dict("os.environ", {}, clear=True):
            groq = GroqProvider(api_key="")
            openai = OpenAIProvider(api_key="")
            assert not groq.is_available()
            assert not openai.is_available()

            failover = FailoverAIProvider(
                primary=groq,
                secondary=openai,
                allow_offline_fallback=False,
            )
            context = make_test_context()

            proposal = failover.analyze(context)
            assert proposal.decision == ProposalDecision.UNAVAILABLE
            assert proposal.provider == "none"


# ============================================================================
# SECTION 16: HARD VETO & RISK OVERRIDE PREVENTION TESTS
# ============================================================================
class TestHardRiskVetoEnforcement:
    """Verifies that LLM approval CANNOT override any hard deterministic gate."""

    @pytest.fixture
    def setup_context(self):
        now_utc = datetime.now(tz=timezone.utc)
        context = make_test_context(timestamp=now_utc)
        # LLM approves with ultra-high conviction
        llm_approved_proposal = TradeProposal(
            symbol="EURUSD",
            direction=Direction.LONG,
            decision=ProposalDecision.APPROVE,
            confidence=0.99,
            llm_confidence=0.99,
            ml_probability=0.85,
            provider="groq",
            reasons=["Ultra-strong bullish pattern confirmed by LLM advisory"],
            invalidation="Drop below EMA200",
            invalidation_conditions=["Drop below EMA200"],
        )
        return context, llm_approved_proposal

    def test_veto_llm_approved_but_high_impact_news(self, setup_context):
        context, proposal = setup_context
        # High impact news in context
        context.news_state["high_impact_soon"] = True

        res = DeterministicGate.validate(
            proposal=proposal,
            context=context,
            current_spread_pips=1.2,
            max_spread_pips=2.5,
        )
        assert res.passed is False
        assert res.final_decision == FinalDecision.BLOCK
        assert res.block_reason == BlockReason.BLOCK_NEWS
        assert "News blackout" in res.reason

    def test_veto_llm_approved_but_spread_too_high(self, setup_context):
        context, proposal = setup_context

        res = DeterministicGate.validate(
            proposal=proposal,
            context=context,
            current_spread_pips=3.8, # Exceeds max 2.5
            max_spread_pips=2.5,
        )
        assert res.passed is False
        assert res.final_decision == FinalDecision.BLOCK
        assert res.block_reason == BlockReason.BLOCK_SPREAD
        assert "exceeds allowed" in res.reason

    def test_veto_llm_approved_but_daily_loss_limit(self, setup_context):
        context, proposal = setup_context
        risk_engine = RiskEngine(RiskConfig(max_daily_loss_pct=0.05))
        now_utc = datetime.now(tz=timezone.utc)

        # Evaluate risk directly under 6% daily loss
        risk_dec = risk_engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.1450,
            atr_val=0.0015,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=-600.0, # -6% drawdown > 5% limit
            consecutive_losses=1,
            halt_until=None,
            open_positions=[],
            data_timestamp=now_utc,
            now=now_utc,
            confidence=proposal.confidence,
        )
        assert risk_dec.approved is False
        assert risk_dec.block_reason == BlockReason.BLOCK_DAILY_LOSS

    def test_veto_llm_approved_but_circuit_breaker_active(self, setup_context):
        context, proposal = setup_context
        risk_engine = RiskEngine()
        now_utc = datetime.now(tz=timezone.utc)
        halt_until = now_utc + timedelta(minutes=45)

        risk_dec = risk_engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.1450,
            atr_val=0.0015,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=-100.0,
            consecutive_losses=5,
            halt_until=halt_until,
            open_positions=[],
            data_timestamp=now_utc,
            now=now_utc,
            confidence=proposal.confidence,
        )
        assert risk_dec.approved is False
        assert risk_dec.block_reason == BlockReason.BLOCK_CIRCUIT_BREAKER

    def test_llm_rejection_blocks_trade(self):
        context = make_test_context()
        proposal = TradeProposal(
            symbol="EURUSD",
            direction=Direction.LONG,
            decision=ProposalDecision.REJECT,
            confidence=0.35,
            reasons=["Adverse market regime detected by LLM advisory"],
            invalidation="Adverse regime invalidates setup",
            invalidation_conditions=["Adverse regime invalidates setup"],
        )
        res = DeterministicGate.validate(
            proposal=proposal,
            context=context,
            current_spread_pips=1.0,
            max_spread_pips=2.5,
        )
        assert res.passed is False
        assert res.final_decision == FinalDecision.BLOCK
        assert res.block_reason == BlockReason.BLOCK_CONFIDENCE


# ============================================================================
# SECTION: FIELD SEPARATION AND TAXONOMY NORMALIZATION
# ============================================================================
class TestFieldSeparationAndTaxonomy:
    """Verifies data model purity: llm_confidence != ml_probability and NormalizedBlockReason."""

    def test_field_separation_contract(self):
        proposal = TradeProposal(
            symbol="EURUSD",
            direction=Direction.LONG,
            decision=ProposalDecision.APPROVE,
            confidence=0.80,
            llm_confidence=0.78,
            ml_probability=0.88,
            ml_model_version="xgboost_regime_v2.1",
            provider="groq",
            model="llama-3.3-70b-versatile",
            model_version="2026.03",
            prompt_version="prompt_m5_v3.2",
        )
        # Verify strict distinction
        assert proposal.llm_confidence != proposal.ml_probability
        assert proposal.ml_probability == 0.88
        assert proposal.ml_model_version == "xgboost_regime_v2.1"
        assert proposal.confidence == 0.80

    def test_normalized_block_reason_aliases(self):
        norm = normalize_block_reason(BlockReason.BLOCK_KILL_SWITCH)
        assert isinstance(norm, NormalizedBlockReason)
        assert norm == "KILL_SWITCH_ACTIVE"
        assert norm == BlockReason.BLOCK_KILL_SWITCH
        assert "KILL_SWITCH_ACTIVE" == norm

        norm_spread = normalize_block_reason("SPREAD_TOO_HIGH")
        assert norm_spread == BlockReason.BLOCK_SPREAD
        assert norm_spread == "SPREAD_TOO_HIGH"
