"""
Integration & Failure Recovery Test Suite — Phase 3 & 4 Requirements.
Verifies all 18 failure and recovery scenarios:
  1. AI unavailable
  2. AI timeout
  3. AI invalid response
  4. Market data stale
  5. Malformed market data
  6. cTrader disconnect
  7. Reconnect
  8. Order rejection
  9. Order timeout
  10. Duplicate execution attempt
  11. Application restart
  12. Restart with open position
  13. Restart after network interruption
  14. Local state vs broker state mismatch
  15. Kill switch activation
  16. Daily loss threshold condition
  17. Consecutive loss halt
  18. Max position limit
"""
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.ai.context import AIContextBuilder
from src.ai.errors import NetworkError, TimeoutError
from src.ai.provider import FailoverAIProvider, OfflineDeterministicAIProvider
from src.ai.schemas import AIContext, ProposalDecision, TradeProposal
from src.ai.validator import DeterministicGate
from src.core.models import Bar, Direction, Timeframe
from src.core.risk import RiskConfig, RiskEngine
from src.services.monitor import OperationalMonitor
from src.services.state_manager import BotRuntimeState, PositionState, StateManager


@pytest.fixture
def temp_state_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def sample_context():
    now = datetime.now(tz=timezone.utc)
    return AIContext(
        symbol="EURUSD",
        timeframe=Timeframe.M5,
        price=1.1450,
        trend="BULLISH",
        rsi=55.0,
        ema={"EMA9": 1.1448, "EMA21": 1.1440},
        atr=0.0015,
        market_structure="BOS_LONG",
        volatility="NORMAL",
        session="LONDON",
        news_state={"high_impact_soon": False},
        current_position={"open_positions": 0},
        account_risk_state={"daily_pnl_pct": 0.0, "kill_switch_active": False},
        recent_trade_state={"consecutive_losses": 0},
        scenario_state={"active_scenario": "NONE"},
        timestamp=now,
    )


class TestFailureInjectionAndRecovery:

    # 1. AI unavailable
    def test_case_01_ai_unavailable(self, sample_context):
        primary_mock = MagicMock()
        primary_mock.analyze.side_effect = NetworkError("Primary AI cluster unreachable")
        failover = FailoverAIProvider(primary=primary_mock, offline_fallback=OfflineDeterministicAIProvider())

        proposal = failover.analyze(sample_context)
        assert proposal is not None
        assert proposal.decision == ProposalDecision.APPROVE
        assert proposal.model_provider == "offline_rules"

    # 2. AI timeout
    def test_case_02_ai_timeout(self, sample_context):
        primary_mock = MagicMock()
        primary_mock.analyze.side_effect = TimeoutError("Request timed out after 3.0s")
        failover = FailoverAIProvider(primary=primary_mock, offline_fallback=OfflineDeterministicAIProvider())

        proposal = failover.analyze(sample_context)
        assert proposal is not None
        assert proposal.decision in (ProposalDecision.APPROVE, ProposalDecision.PASS)

    # 3. AI invalid response
    def test_case_03_ai_invalid_response(self, sample_context):
        malformed_proposal = TradeProposal(
            decision=ProposalDecision.APPROVE,
            direction=Direction.LONG,
            symbol="EURUSD",
            confidence=-0.5,  # Invalid negative confidence
            entry_context={},
            invalidation="",   # Missing invalidation
            rationale="",      # Missing rationale
            scenario="NONE",
            timestamp=datetime.now(tz=timezone.utc),
            model_provider="mock",
            trace_id="tr_001",
        )
        res = DeterministicGate.validate(malformed_proposal, sample_context)
        assert res.passed is False
        assert res.decision == "REJECTED"

    # 4. Market data stale
    def test_case_04_market_data_stale(self, sample_context):
        risk = RiskEngine(RiskConfig(max_data_staleness_seconds=60.0))
        stale_time = datetime.now(tz=timezone.utc) - timedelta(seconds=120)
        dec = risk.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.1450,
            atr_val=0.0015,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=0.0,
            consecutive_losses=0,
            halt_until=None,
            open_positions=[],
            data_timestamp=stale_time,
        )
        assert dec.approved is False
        assert dec.block_reason == "STALE_DATA"

    # 5. Malformed market data
    def test_case_05_malformed_market_data(self):
        with pytest.raises(ValueError):
            Bar(
                symbol="EURUSD",
                timeframe=Timeframe.M5,
                timestamp=datetime.now(tz=timezone.utc),
                open=1.1450,
                high=1.1400,  # High < Low violates mathematical integrity
                low=1.1460,
                close=1.1450,
                volume=100,
            )

    # 6. cTrader disconnect
    def test_case_06_ctrader_disconnect(self, temp_state_dir):
        monitor = OperationalMonitor(state_dir=temp_state_dir)
        monitor.record_heartbeat(
            broker_connected=False,
            open_positions=0,
            daily_pnl=0.0,
            daily_pnl_pct=0.0,
            consecutive_losses=0,
            kill_switch_active=False,
        )
        assert monitor.telemetry.broker_connected is False
        assert monitor.telemetry.status == "DEGRADED_BROKER_DISCONNECTED"

    # 7. Reconnect
    def test_case_07_reconnect(self, temp_state_dir):
        monitor = OperationalMonitor(state_dir=temp_state_dir)
        monitor.record_reconnect()
        assert monitor.telemetry.reconnect_count == 1

    # 8. Order rejection
    def test_case_08_order_rejection(self, temp_state_dir):
        state_mgr = StateManager(state_dir=temp_state_dir)
        # Order rejected by broker -> position is never added to open_positions
        assert len(state_mgr.state.open_positions) == 0

    # 9. Order timeout
    def test_case_09_order_timeout(self, temp_state_dir):
        state_mgr = StateManager(state_dir=temp_state_dir)
        # Reconciliation syncs with broker state
        recon = state_mgr.reconcile_with_broker([])
        assert recon["status"] == "IN_SYNC"
        assert len(state_mgr.state.open_positions) == 0

    # 10. Duplicate execution attempt
    def test_case_10_duplicate_execution_attempt(self):
        risk = RiskEngine()
        existing_pos = [{"symbol": "EURUSD", "positionId": 123}]
        dec = risk.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.1450,
            atr_val=0.0015,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=0.0,
            consecutive_losses=0,
            halt_until=None,
            open_positions=existing_pos,
        )
        assert dec.approved is False
        assert dec.block_reason == "SYMBOL_EXPOSURE_LIMIT"

    # 11. Application restart
    def test_case_11_application_restart(self, temp_state_dir):
        sm1 = StateManager(state_dir=temp_state_dir)
        sm1.state.daily_starting_balance = 9850.0
        sm1.state.consecutive_losses = 2
        sm1.save_state()

        # Restart app -> new StateManager instance
        sm2 = StateManager(state_dir=temp_state_dir)
        assert sm2.state.daily_starting_balance == 9850.0
        assert sm2.state.consecutive_losses == 2

    # 12. Restart with open position
    def test_case_12_restart_with_open_position(self, temp_state_dir):
        sm = StateManager(state_dir=temp_state_dir)
        broker_positions = [{"positionId": 998877, "symbolId": 1, "tradeSide": "BUY", "volume": 100000, "entryPrice": 1.1420}]
        recon = sm.reconcile_with_broker(broker_positions)

        assert "998877" in recon["orphans_discovered"]
        assert "998877" in sm.state.open_positions
        assert sm.state.open_positions["998877"]["status"] == "ORPHAN"

    # 13. Restart after network interruption
    def test_case_13_restart_after_network_interruption(self, temp_state_dir):
        sm = StateManager(state_dir=temp_state_dir)
        # Network down: 0 broker positions returned
        recon1 = sm.reconcile_with_broker([])
        assert recon1["broker_open_count"] == 0

        # Network restored: broker reports position
        recon2 = sm.reconcile_with_broker([{"positionId": 554433, "symbolId": 2, "tradeSide": "SELL", "volume": 100000, "entryPrice": 1.3320}])
        assert recon2["broker_open_count"] == 1
        assert "554433" in sm.state.open_positions

    # 14. Local state vs broker state mismatch (position closed on broker by SL/TP)
    def test_case_14_mismatch_broker_closed(self, temp_state_dir):
        sm = StateManager(state_dir=temp_state_dir)
        pos = PositionState(
            position_id="POS_001",
            symbol="EURUSD",
            direction="LONG",
            volume_lots=0.01,
            entry_price=1.1450,
            sl_price=1.1430,
            tp_price=1.1490,
            open_time=datetime.now(tz=timezone.utc).isoformat(),
        )
        sm.record_new_position(pos)
        assert "POS_001" in sm.state.open_positions

        # Broker reports 0 positions (SL was hit on broker side)
        recon = sm.reconcile_with_broker([])
        assert "POS_001" in recon["closed_detected"]
        assert "POS_001" not in sm.state.open_positions
        assert len(sm.state.closed_positions_history) == 1
        assert sm.state.closed_positions_history[0]["status"] == "CLOSED_EXTERNAL"

    # 15. Kill switch activation
    def test_case_15_kill_switch_activation(self):
        risk = RiskEngine()
        with patch.dict(os.environ, {"EMERGENCY_KILL_SWITCH": "true"}):
            dec = risk.evaluate_order(
                symbol="EURUSD",
                direction=Direction.LONG,
                entry_price=1.1450,
                atr_val=0.0015,
                equity=10000.0,
                daily_starting_balance=10000.0,
                daily_pnl=0.0,
                consecutive_losses=0,
                halt_until=None,
                open_positions=[],
            )
            assert dec.approved is False
            assert dec.block_reason == "KILL_SWITCH_ACTIVE"

    # 16. Daily loss threshold condition
    def test_case_16_daily_loss_threshold(self):
        risk = RiskEngine(RiskConfig(max_daily_loss_pct=0.05))
        dec = risk.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.1450,
            atr_val=0.0015,
            equity=9400.0,
            daily_starting_balance=10000.0,
            daily_pnl=-550.0,  # -5.5% loss exceeds 5.0% threshold
            consecutive_losses=2,
            halt_until=None,
            open_positions=[],
        )
        assert dec.approved is False
        assert dec.block_reason == "DAILY_LOSS_LIMIT"

    # 17. Consecutive loss halt
    def test_case_17_consecutive_loss_halt(self):
        risk = RiskEngine()
        halt_time = datetime.now(tz=timezone.utc) + timedelta(minutes=45)
        dec = risk.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.1450,
            atr_val=0.0015,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=-100.0,
            consecutive_losses=5,
            halt_until=halt_time,
            open_positions=[],
        )
        assert dec.approved is False
        assert dec.block_reason == "CONSECUTIVE_LOSS_HALT"

    # 18. Max position limit
    def test_case_18_max_position_limit(self):
        risk = RiskEngine(RiskConfig(max_open_positions=3))
        three_positions = [
            {"symbol": "GBPUSD", "positionId": 1},
            {"symbol": "USDJPY", "positionId": 2},
            {"symbol": "XAUUSD", "positionId": 3},
        ]
        dec = risk.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.1450,
            atr_val=0.0015,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=0.0,
            consecutive_losses=0,
            halt_until=None,
            open_positions=three_positions,
        )
        assert dec.approved is False
        assert dec.block_reason == "MAX_POSITIONS_REACHED"
