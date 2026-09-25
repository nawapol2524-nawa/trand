"""
Unit and integration tests for Profit Acceleration Suite v1.3.0.
Verifies:
  1. High-Liquidity Institutional Session Filter (London / NY active, Asian blocked)
  2. Conviction-Weighted Dynamic Sizing (1.0% standard vs 1.5% high conviction + Level 1 Defense clamp)
  3. Convex Asymmetric Exit Phase 1 & 2: 1.5R Partial TP (50%) & Break-Even SL lock
  4. Convex Asymmetric Exit Phase 3: Trailing ATR Runner & ratchet protection (LONG & SHORT)
  5. Schema v1.3 persistence & migration verification
"""
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.ai.context import AIContextBuilder
from src.ai.schemas import AIContext, TradeProposal, ProposalDecision
from src.ai.validator import DeterministicGate
from src.brokers.ctrader_mcp import CTraderMCPBroker
from src.core.models import Bar, Direction, Signal, Timeframe
from src.core.risk import RiskConfig, RiskEngine
from src.core.version import SCHEMA_VERSION, SYSTEM_VERSION
from src.services.decision_trace import DecisionTraceService
from src.services.evidence import EvidenceCollector
from src.services.monitor import OperationalMonitor
from src.services.state_manager import BotRuntimeState, PositionState, StateManager
from src.app.runner import TradingBotRunner, SYMBOL_MAP


# ============================================================================
# MODULE 1: Institutional Session Filter Tests
# ============================================================================
class TestInstitutionalSessionFilter:
    def _create_mock_context(self, utc_time: datetime) -> AIContext:
        session = AIContextBuilder.determine_session(utc_time)
        return AIContext(
            symbol="EURUSD",
            timeframe=Timeframe.M5,
            price=1.1450,
            trend="BULLISH",
            rsi=52.0,
            ema={"EMA9": 1.1440, "EMA21": 1.1430},
            atr=0.0015,
            market_structure="BOS_LONG",
            volatility="NORMAL",
            session=session,
            news_state={"high_impact_soon": False, "minutes_to_next": 999},
            current_position={"open_positions": 0, "symbol_exposure": 0.0},
            account_risk_state={"daily_pnl_pct": 0.0, "kill_switch_active": False},
            recent_trade_state={"consecutive_losses": 0},
            scenario_state={"h1_regime": "BULLISH"},
            timestamp=utc_time,
        )

    def _create_approved_proposal(self, utc_time: datetime) -> TradeProposal:
        return TradeProposal(
            decision=ProposalDecision.APPROVE,
            direction=Direction.LONG,
            confidence=0.88,
            entry_context={"rsi": 52.0},
            invalidation="Below 1.1400",
            rationale="London institutional volume breakout",
            scenario="BREAKOUT",
            symbol="EURUSD",
            timestamp=utc_time,
            model_provider="mock",
            trace_id="trace_session_test",
        )

    def test_london_session_allowed(self):
        # 08:30 UTC is peak London session
        utc_t = datetime(2026, 9, 25, 8, 30, tzinfo=timezone.utc)
        ctx = self._create_mock_context(utc_t)
        prop = self._create_approved_proposal(utc_t)

        res = DeterministicGate.validate(prop, ctx, now=utc_t, enforce_session_filter=True)
        assert res.passed is True
        assert res.checks.get("session_active") is True

    def test_new_york_overlap_session_allowed(self):
        # 14:00 UTC is peak London/New York overlap session
        utc_t = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)
        ctx = self._create_mock_context(utc_t)
        prop = self._create_approved_proposal(utc_t)

        res = DeterministicGate.validate(prop, ctx, now=utc_t, enforce_session_filter=True)
        assert res.passed is True
        assert res.checks.get("session_active") is True

    def test_asian_off_hours_blocked_when_enforced(self):
        # 03:00 UTC is Asian off-hours
        utc_t = datetime(2026, 9, 25, 3, 0, tzinfo=timezone.utc)
        ctx = self._create_mock_context(utc_t)
        prop = self._create_approved_proposal(utc_t)

        res = DeterministicGate.validate(prop, ctx, now=utc_t, enforce_session_filter=True)
        assert res.passed is False
        assert res.decision == "REJECTED"
        assert "Institutional Session Filter" in res.reason
        assert res.checks.get("session_active") is False

    def test_asian_off_hours_bypassed_when_not_enforced(self):
        # When enforce_session_filter=False (default for unit tests/backtests), Asian trades pass
        utc_t = datetime(2026, 9, 25, 3, 0, tzinfo=timezone.utc)
        ctx = self._create_mock_context(utc_t)
        prop = self._create_approved_proposal(utc_t)

        res = DeterministicGate.validate(prop, ctx, now=utc_t, enforce_session_filter=False)
        assert res.passed is True
        assert res.checks.get("session_active") is True


# ============================================================================
# MODULE 2: Conviction-Weighted Dynamic Sizing Tests
# ============================================================================
class TestConvictionWeightedDynamicSizing:
    def setup_method(self):
        self.risk_engine = RiskEngine(RiskConfig(
            max_risk_per_trade_pct=0.010,
            base_risk_pct=0.010,
            high_conviction_risk_pct=0.015,
            high_conviction_threshold=0.85,
        ))

    def test_standard_conviction_sizing(self):
        # Standard trade: Confidence 0.70 -> base risk 1.0% ($100 on $10,000 equity)
        now_utc = datetime.now(tz=timezone.utc)
        dec = self.risk_engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.1400,
            atr_val=0.0015,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=0.0,
            consecutive_losses=0,
            halt_until=None,
            open_positions=[],
            data_timestamp=now_utc,
            now=now_utc,
            confidence=0.70,
            h1_aligned=True,
        )
        assert dec.approved is True
        assert dec.defense_level == 0
        # sl_dist = 0.0015 * 1.5 = 0.00225; lots = 100 / (0.00225 * 100000) = 0.444 -> 0.44 lots
        assert 0.40 <= dec.adjusted_volume <= 0.46
        assert "High Conviction Tier" not in dec.reason

    def test_high_conviction_a_plus_sizing(self):
        # High Conviction A+: Confidence 0.90 + H1 aligned + streak 0 -> risk 1.5% ($150 on $10,000 equity)
        now_utc = datetime.now(tz=timezone.utc)
        dec = self.risk_engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.1400,
            atr_val=0.0015,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=0.0,
            consecutive_losses=0,
            halt_until=None,
            open_positions=[],
            data_timestamp=now_utc,
            now=now_utc,
            confidence=0.90,
            h1_aligned=True,
        )
        assert dec.approved is True
        assert dec.defense_level == 0
        # sl_dist = 0.00225; lots = 150 / (0.00225 * 100000) = 0.666 -> 0.66 lots (1.5x of 0.44)
        assert 0.60 <= dec.adjusted_volume <= 0.70
        assert "High Conviction Tier (Confidence 90%): risk 1.5%" in dec.reason

    def test_high_conviction_reverts_if_not_h1_aligned(self):
        # Confidence 0.90 but H1 NOT aligned -> falls back to base 1.0%
        now_utc = datetime.now(tz=timezone.utc)
        dec = self.risk_engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.1400,
            atr_val=0.0015,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=0.0,
            consecutive_losses=0,
            halt_until=None,
            open_positions=[],
            data_timestamp=now_utc,
            now=now_utc,
            confidence=0.90,
            h1_aligned=False,
        )
        assert dec.approved is True
        assert 0.40 <= dec.adjusted_volume <= 0.46
        assert "High Conviction Tier" not in dec.reason

    def test_high_conviction_reverts_if_streak_losses(self):
        # Confidence 0.92, H1 aligned, but consecutive_losses = 3 -> restricted, no boost
        now_utc = datetime.now(tz=timezone.utc)
        dec = self.risk_engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.1400,
            atr_val=0.0015,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=0.0,
            consecutive_losses=3,
            halt_until=None,
            open_positions=[],
            data_timestamp=now_utc,
            now=now_utc,
            confidence=0.92,
            h1_aligned=True,
        )
        assert dec.approved is True
        assert dec.defense_level == 2
        assert 0.40 <= dec.adjusted_volume <= 0.46
        assert "High Conviction Tier" not in dec.reason

    def test_defensive_level_1_clamps_high_conviction(self):
        # Drawdown 2.5% triggers Level 1 Defensive: cuts position size by half!
        now_utc = datetime.now(tz=timezone.utc)
        dec = self.risk_engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.1400,
            atr_val=0.0015,
            equity=9750.0,
            daily_starting_balance=10000.0,
            daily_pnl=-250.0, # -2.5% daily drawdown
            consecutive_losses=1,
            halt_until=None,
            open_positions=[],
            data_timestamp=now_utc,
            now=now_utc,
            confidence=0.90,
            h1_aligned=True,
        )
        assert dec.approved is True
        assert dec.defense_level == 1
        # High conviction was ~0.66 lots, halved to ~0.33 lots
        assert 0.30 <= dec.adjusted_volume <= 0.36
        assert "Level 1 Defensive Mode" in dec.reason and "volume halved" in dec.reason


# ============================================================================
# MODULE 3: Convex Asymmetric Exit Engine (Partial TP & Break-Even)
# ============================================================================
class TestConvexAsymmetricExitEngine:
    def test_partial_tp_and_break_even_long(self, tmp_path):
        state_mgr = StateManager(state_dir=str(tmp_path / "state"))
        evidence = EvidenceCollector(base_dir=str(tmp_path / "evidence"))
        monitor = OperationalMonitor(state_dir=str(tmp_path / "monitor"))
        trace = DecisionTraceService(log_dir=str(tmp_path / "trace"))

        broker = MagicMock(spec=CTraderMCPBroker)
        runner = TradingBotRunner(
            broker=broker,
            state_manager=state_mgr,
            monitor=monitor,
            trace_service=trace,
            evidence_collector=evidence,
        )

        # Create an open LONG position: entry 1.1400, SL dist 0.0020 (SL 1.1380), volume 0.04 lots
        pos_id = "1001"
        pos = PositionState(
            position_id=pos_id,
            symbol="EURUSD",
            direction="LONG",
            volume_lots=0.04,
            entry_price=1.1400,
            sl_price=1.1380,
            original_volume=0.04,
            sl_distance=0.0020,
            atr_at_entry=0.00133,
            highest_favorable_price=1.1400,
            partial_tp_hit=False,
            break_even_set=False,
            trailing_stop_active=False,
        )
        state_mgr.record_new_position(pos)

        # Price advances to 1.1432 (Gain: 0.0032 = 1.6R >= 1.5R)
        broker.get_spot_prices.return_value = [{"symbolId": 1, "bid": 1.1432, "ask": 1.1433}]
        broker_positions = [{"positionId": 1001, "symbolId": 1, "tradeSide": "BUY", "volume": 400000}]

        now_utc = datetime.now(tz=timezone.utc)
        runner.manage_open_positions(broker_positions, now=now_utc)

        # Check broker calls:
        # 1. Partial close 50% volume (0.02 lots * 100000 * 100 = 200,000 MCP units)
        assert broker.close_position.called
        close_kwargs = broker.close_position.call_args[1]
        assert close_kwargs["volume"] == 200000

        # 2. Amend SL to Break-Even (entry_price 1.1400)
        assert broker.amend_position.called
        amend_kwargs = broker.amend_position.call_args[1]
        assert amend_kwargs["stop_loss"] == 1.1400

        # 3. Check updated local state
        updated_pos = state_mgr.state.open_positions[pos_id]
        assert updated_pos["partial_tp_hit"] is True
        assert updated_pos["break_even_set"] is True
        assert updated_pos["trailing_stop_active"] is True
        assert updated_pos["sl_price"] == 1.1400
        assert updated_pos["volume_lots"] == 0.02
        assert updated_pos["highest_favorable_price"] == 1.1432

    def test_trailing_atr_runner_ratchet_long(self, tmp_path):
        state_mgr = StateManager(state_dir=str(tmp_path / "state"))
        evidence = EvidenceCollector(base_dir=str(tmp_path / "evidence"))
        monitor = OperationalMonitor(state_dir=str(tmp_path / "monitor"))
        trace = DecisionTraceService(log_dir=str(tmp_path / "trace"))

        broker = MagicMock(spec=CTraderMCPBroker)
        runner = TradingBotRunner(
            broker=broker,
            state_manager=state_mgr,
            monitor=monitor,
            trace_service=trace,
            evidence_collector=evidence,
        )

        pos_id = "1002"
        # Position already hit Partial TP, now running trailing stop
        # Entry: 1.1400, ATR: 0.0010, Trail Dist: 0.0015, current SL: 1.1400 (Break-Even)
        pos = PositionState(
            position_id=pos_id,
            symbol="EURUSD",
            direction="LONG",
            volume_lots=0.02,
            entry_price=1.1400,
            sl_price=1.1400,
            original_volume=0.04,
            sl_distance=0.0020,
            atr_at_entry=0.0010,
            highest_favorable_price=1.1432,
            partial_tp_hit=True,
            break_even_set=True,
            trailing_stop_active=True,
        )
        state_mgr.record_new_position(pos)

        # Price advances higher to 1.1460:
        # highest_favorable becomes 1.1460. New SL = 1.1460 - 0.0015 = 1.1445 (> 1.1400)
        broker.get_spot_prices.return_value = [{"symbolId": 1, "bid": 1.1460, "ask": 1.1461}]
        broker_positions = [{"positionId": 1002, "symbolId": 1, "tradeSide": "BUY", "volume": 200000}]

        now_utc = datetime.now(tz=timezone.utc)
        runner.manage_open_positions(broker_positions, now=now_utc)

        # Verify amend_position called with ratchet stop loss 1.1445
        assert broker.amend_position.called
        assert broker.amend_position.call_args[1]["stop_loss"] == 1.1445
        assert state_mgr.state.open_positions[pos_id]["sl_price"] == 1.1445

        # Now simulate price pullback to 1.1450:
        # Trailing SL MUST NOT ratchet backwards! It must stay at 1.1445
        broker.amend_position.reset_mock()
        broker.get_spot_prices.return_value = [{"symbolId": 1, "bid": 1.1450, "ask": 1.1451}]
        runner.manage_open_positions(broker_positions, now=now_utc)

        assert not broker.amend_position.called
        assert state_mgr.state.open_positions[pos_id]["sl_price"] == 1.1445

    def test_partial_tp_and_trailing_runner_short(self, tmp_path):
        state_mgr = StateManager(state_dir=str(tmp_path / "state"))
        evidence = EvidenceCollector(base_dir=str(tmp_path / "evidence"))
        monitor = OperationalMonitor(state_dir=str(tmp_path / "monitor"))
        trace = DecisionTraceService(log_dir=str(tmp_path / "trace"))

        broker = MagicMock(spec=CTraderMCPBroker)
        runner = TradingBotRunner(
            broker=broker,
            state_manager=state_mgr,
            monitor=monitor,
            trace_service=trace,
            evidence_collector=evidence,
        )

        pos_id = "2001"
        # SHORT position: entry 1.1500, SL 1.1520 (sl_distance 0.0020), volume 0.04 lots
        pos = PositionState(
            position_id=pos_id,
            symbol="EURUSD",
            direction="SHORT",
            volume_lots=0.04,
            entry_price=1.1500,
            sl_price=1.1520,
            original_volume=0.04,
            sl_distance=0.0020,
            atr_at_entry=0.0010,
            highest_favorable_price=1.1500,
            partial_tp_hit=False,
            break_even_set=False,
            trailing_stop_active=False,
        )
        state_mgr.record_new_position(pos)

        # Price drops to 1.1468 (Gain: 1.1500 - 1.1468 = 0.0032 = 1.6R >= 1.5R)
        broker.get_spot_prices.return_value = [{"symbolId": 1, "bid": 1.1467, "ask": 1.1468}]
        broker_positions = [{"positionId": 2001, "symbolId": 1, "tradeSide": "SELL", "volume": 400000}]

        now_utc = datetime.now(tz=timezone.utc)
        runner.manage_open_positions(broker_positions, now=now_utc)

        # Check Partial TP close 50%
        assert broker.close_position.called
        assert broker.close_position.call_args[1]["volume"] == 200000

        # Check Break-Even amend
        assert broker.amend_position.called
        assert broker.amend_position.call_args[1]["stop_loss"] == 1.1500
        assert state_mgr.state.open_positions[pos_id]["trailing_stop_active"] is True

        # Now simulate further drop to 1.1440:
        # Trail dist = 0.0010 * 1.5 = 0.0015. New SL = 1.1440 + 0.0015 = 1.1455 (< 1.1500)
        broker.amend_position.reset_mock()
        broker.get_spot_prices.return_value = [{"symbolId": 1, "bid": 1.1439, "ask": 1.1440}]
        runner.manage_open_positions(broker_positions, now=now_utc)

        assert broker.amend_position.called
        assert broker.amend_position.call_args[1]["stop_loss"] == 1.1455
        assert state_mgr.state.open_positions[pos_id]["sl_price"] == 1.1455


# ============================================================================
# MODULE 4: Schema v1.3 Persistence & Version Lineage Tests
# ============================================================================
class TestSchemaVersionAndLineage:
    def test_schema_and_system_version_constants(self):
        assert SYSTEM_VERSION == "1.3.0"
        assert SCHEMA_VERSION == "1.3"

    def test_state_schema_migration_to_v1_3(self, tmp_path):
        state_file = tmp_path / "bot_state.json"
        # Write legacy v1.2 state file
        legacy_data = {
            "schema_version": "1.2",
            "last_reset_date": "2026-09-25",
            "daily_starting_balance": 10000.0,
            "daily_pnl": 50.0,
            "consecutive_losses": 0,
            "open_positions": {
                "3001": {
                    "position_id": "3001",
                    "symbol": "XAUUSD",
                    "direction": "LONG",
                    "volume_lots": 0.05,
                    "entry_price": 2650.0,
                }
            },
        }
        state_file.write_text(json.dumps(legacy_data), encoding="utf-8")

        sm = StateManager(state_dir=str(tmp_path))
        # Verify auto-migration to schema 1.3
        assert sm.state.schema_version == "1.3"
        persisted = json.loads(state_file.read_text(encoding="utf-8"))
        assert persisted["schema_version"] == "1.3"
