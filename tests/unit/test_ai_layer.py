"""
Unit tests for Universal AI Layer, Deterministic Gate, and Decision Traces (Phase R).
All external API calls are mocked — zero live network dependencies in test suite.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from src.ai.errors import (
    AuthError,
    NetworkError,
    Provider5xxError,
    RateLimit429Error,
    SchemaError,
    TimeoutError,
)
from src.ai.event_detector import EventDetector, MarketEventType
from src.ai.provider import MockAIProvider, OfflineDeterministicAIProvider
from src.ai.schemas import (
    AIContext,
    ProposalDecision,
    TradeProposal,
)
from src.ai.validator import DeterministicGate, ValidationResult
from src.core.models import Direction, Timeframe
from src.services.decision_trace import DecisionTraceLogger

UTC = timezone.utc


def make_test_context(
    price: float = 1.1425,
    trend: str = "BULLISH",
    rsi: float = 55.0,
    structure: str = "BOS_LONG",
    daily_loss: float = 0.0,
    kill_switch: bool = False,
    news_high_impact: bool = False,
    open_positions: int = 0,
) -> AIContext:
    return AIContext(
        symbol="EURUSD",
        timeframe=Timeframe.M5,
        price=price,
        trend=trend,
        rsi=rsi,
        ema={"EMA9": 1.1420, "EMA21": 1.1400},
        atr=0.0015,
        market_structure=structure,
        volatility="NORMAL",
        session="LONDON",
        news_state={"high_impact_soon": news_high_impact, "minutes_to_next": 120},
        current_position={"open_positions": open_positions, "symbol_exposure": 0.0},
        account_risk_state={"daily_pnl_pct": daily_loss, "kill_switch_active": kill_switch},
        recent_trade_state={"consecutive_losses": 0},
        scenario_state={"active_scenario": "BULLISH_CONTINUATION"},
        timestamp=datetime.now(tz=UTC),
    )


class TestUniversalAILayer:

    def test_offline_deterministic_provider_bullish_bos(self):
        ctx = make_test_context(structure="BOS_LONG", trend="BULLISH")
        provider = OfflineDeterministicAIProvider()
        prop = provider.analyze(ctx)

        assert prop.decision == ProposalDecision.APPROVE
        assert prop.direction == Direction.LONG
        assert prop.confidence >= 0.8
        assert prop.scenario == "BULLISH_CONTINUATION"

    def test_offline_deterministic_provider_news_blackout(self):
        ctx = make_test_context(news_high_impact=True)
        provider = OfflineDeterministicAIProvider()
        prop = provider.analyze(ctx)

        assert prop.decision == ProposalDecision.REJECT
        assert "news" in prop.rationale.lower()

    def test_mock_provider_error_simulation(self):
        # 429 Rate limit simulation
        provider_429 = MockAIProvider(exception_to_raise=RateLimit429Error("Quota exceeded"))
        ctx = make_test_context()
        with pytest.raises(RateLimit429Error):
            provider_429.analyze(ctx)

        # Timeout simulation
        provider_timeout = MockAIProvider(exception_to_raise=TimeoutError("Request timed out"))
        with pytest.raises(TimeoutError):
            provider_timeout.analyze(ctx)

        # 5xx error simulation
        provider_5xx = MockAIProvider(exception_to_raise=Provider5xxError("Server error"))
        with pytest.raises(Provider5xxError):
            provider_5xx.analyze(ctx)


class TestDeterministicGate:

    def test_gate_approves_valid_proposal(self):
        ctx = make_test_context(trend="BULLISH")
        prop = TradeProposal(
            decision=ProposalDecision.APPROVE,
            direction=Direction.LONG,
            symbol="EURUSD",
            confidence=0.85,
            entry_context=ctx.to_dict(),
            invalidation="Below 1.1400",
            rationale="Strong trend alignment",
            scenario="BULLISH_CONTINUATION",
            timestamp=datetime.now(tz=UTC),
            model_provider="mock",
            trace_id="test_tr_1",
        )
        res = DeterministicGate.validate(prop, ctx)
        assert res.passed is True
        assert res.decision == "APPROVED"

    def test_gate_rejects_counter_trend_without_reversal(self):
        ctx = make_test_context(trend="BEARISH")
        prop = TradeProposal(
            decision=ProposalDecision.APPROVE,
            direction=Direction.LONG,
            symbol="EURUSD",
            confidence=0.85,
            entry_context=ctx.to_dict(),
            invalidation="Below 1.1400",
            rationale="Trying to buy into downtrend",
            scenario="BULLISH_CONTINUATION",
            timestamp=datetime.now(tz=UTC),
            model_provider="mock",
            trace_id="test_tr_2",
        )
        res = DeterministicGate.validate(prop, ctx)
        assert res.passed is False
        assert "trend" in res.reason.lower()

    def test_gate_fail_closed_on_kill_switch(self):
        ctx = make_test_context(kill_switch=True)
        prop = TradeProposal(
            decision=ProposalDecision.APPROVE,
            direction=Direction.LONG,
            symbol="EURUSD",
            confidence=0.99,
            entry_context=ctx.to_dict(),
            invalidation="Below 1.1400",
            rationale="Valid signal",
            scenario="BULLISH_CONTINUATION",
            timestamp=datetime.now(tz=UTC),
            model_provider="mock",
            trace_id="test_tr_3",
        )
        res = DeterministicGate.validate(prop, ctx)
        assert res.passed is False
        assert "kill switch" in res.reason.lower()

    def test_gate_rejects_stale_proposal(self):
        ctx = make_test_context()
        stale_time = datetime.now(tz=UTC) - timedelta(seconds=120)  # 2 mins old
        prop = TradeProposal(
            decision=ProposalDecision.APPROVE,
            direction=Direction.LONG,
            symbol="EURUSD",
            confidence=0.90,
            entry_context=ctx.to_dict(),
            invalidation="Below 1.1400",
            rationale="Valid thesis",
            scenario="BULLISH_CONTINUATION",
            timestamp=stale_time,
            model_provider="mock",
            trace_id="test_tr_4",
        )
        res = DeterministicGate.validate(prop, ctx)
        assert res.passed is False
        assert "stale" in res.reason.lower()

    def test_gate_rejects_low_confidence(self):
        ctx = make_test_context()
        prop = TradeProposal(
            decision=ProposalDecision.APPROVE,
            direction=Direction.LONG,
            symbol="EURUSD",
            confidence=0.50,  # Below threshold 0.65
            entry_context=ctx.to_dict(),
            invalidation="Below 1.1400",
            rationale="Uncertain signal",
            scenario="BULLISH_CONTINUATION",
            timestamp=datetime.now(tz=UTC),
            model_provider="mock",
            trace_id="test_tr_5",
        )
        res = DeterministicGate.validate(prop, ctx)
        assert res.passed is False
        assert "confidence" in res.reason.lower()


class TestEventDetector:

    def test_event_detected_on_bos(self):
        detector = EventDetector(cooldown_seconds=60.0)
        ctx = make_test_context(structure="BOS_LONG")
        invoke, event = detector.should_invoke(ctx)

        assert invoke is True
        assert event is not None
        assert event.event_type == MarketEventType.BOS_OCCURRED

    def test_event_suppressed_by_cooldown(self):
        detector = EventDetector(cooldown_seconds=60.0)
        ctx = make_test_context(structure="BOS_LONG")
        now = datetime.now(tz=UTC)

        invoke1, _ = detector.should_invoke(ctx, now=now)
        assert invoke1 is True

        # Second call 10s later -> suppressed by cooldown
        invoke2, _ = detector.should_invoke(ctx, now=now + timedelta(seconds=10))
        assert invoke2 is False

    def test_event_suppressed_when_no_change(self):
        detector = EventDetector(cooldown_seconds=0.0)
        ctx = make_test_context(structure="RANGE", trend="SIDEWAYS")
        invoke, event = detector.should_invoke(ctx)
        assert invoke is False
        assert event is None


class TestDecisionTraceLogger:

    def test_decision_trace_creation_and_sanitization(self, tmp_path):
        logger = DecisionTraceLogger(log_dir=str(tmp_path))
        ctx = make_test_context()
        prop = TradeProposal(
            decision=ProposalDecision.APPROVE,
            direction=Direction.LONG,
            symbol="EURUSD",
            confidence=0.88,
            entry_context={"api_key": "SECRET123", "price": 1.1425},
            invalidation="Below 1.1400",
            rationale="Clear breakout",
            scenario="BULLISH_CONTINUATION",
            timestamp=datetime.now(tz=UTC),
            model_provider="test_provider",
            trace_id="tr_sanitized_001",
        )
        val = ValidationResult(passed=True, decision="APPROVED", reason="OK", checks={})

        record = logger.log_decision(
            trace_id=prop.trace_id,
            event_id="evt_001",
            provider="test_provider",
            model="test_model",
            context_summary={"token": "SECRET_TOKEN", "price": 1.1425},
            proposal=prop,
            validation_result=val,
        )

        assert record.trace_id == "tr_sanitized_001"
        # Verify sanitization of secret keys in logged trace
        assert record.context_summary.get("token") == "[REDACTED]"

        log_file = tmp_path / "decision_traces.jsonl"
        assert log_file.exists()
        content = log_file.read_text()
        assert "SECRET_TOKEN" not in content
        assert "[REDACTED]" in content
