"""
Unit & Integration Tests for Architecture Upgrade v1.2.0:
  - Module 1: State Atomic Write Hardening & Schema Migration
  - Module 2: Pre-Trade Spread Guard & Slippage Calculation
  - Module 3: Multi-Level Defense (Levels 0-4)
  - Module 4: Higher Timeframe Regime Filter (Forex H1 context)
  - Module 5: Post-Trade Loss Reason Classifier
  - Module 6: Version Control & Git Lineage
"""
import concurrent.futures
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from src.ai.schemas import AIContext, ProposalDecision, TradeProposal
from src.ai.validator import DeterministicGate
from src.core.loss_classifier import LossReason, classify_loss_reason
from src.core.models import Bar, Direction, RiskDecision, Timeframe
from src.core.risk import RiskConfig, RiskEngine
from src.core.version import SCHEMA_VERSION, SYSTEM_VERSION, get_git_commit_sha, get_version_info
from src.services.decision_trace import DecisionTraceLogger
from src.services.monitor import OperationalMonitor
from src.services.state_manager import BotRuntimeState, PositionState, StateManager
from src.strategies import forex_trend_breakout


# ============================================================================
# MODULE 1: Atomic State & Schema Migration Tests
# ============================================================================
class TestStateHardeningAndMigration:
    def test_state_schema_migration_from_legacy(self, tmp_path):
        legacy_data = {
            "daily_starting_balance": 10000.0,
            "daily_pnl": -50.0,
            "consecutive_losses": 1,
            "open_positions": {
                "pos_123": {
                    "position_id": "pos_123",
                    "symbol": "EURUSD",
                    "direction": "LONG",
                    "volume_lots": 0.05,
                    "entry_price": 1.0850,
                }
            },
        }
        state_file = tmp_path / "bot_state.json"
        state_file.write_text(json.dumps(legacy_data), encoding="utf-8")

        mgr = StateManager(state_dir=str(tmp_path))
        assert mgr.state.schema_version == SCHEMA_VERSION
        assert "pos_123" in mgr.state.open_positions
        assert mgr.state.daily_starting_balance == 10000.0

    def test_state_concurrent_writes(self, tmp_path):
        state_file = tmp_path / "bot_state.json"
        mgr = StateManager(state_dir=str(tmp_path))

        def write_worker(idx: int):
            mgr.record_new_position(
                PositionState(
                    position_id=f"pos_{idx}",
                    symbol="EURUSD",
                    direction="LONG",
                    volume_lots=0.01 * idx,
                    entry_price=1.0800 + idx * 0.0001,
                )
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(write_worker, i) for i in range(1, 21)]
            concurrent.futures.wait(futures)

        assert state_file.exists()
        reloaded = StateManager(state_dir=str(tmp_path))
        assert len(reloaded.state.open_positions) == 20


# ============================================================================
# MODULE 2: Pre-Trade Spread Guard Tests
# ============================================================================
class TestSpreadGuard:
    def test_evaluate_spread_normal_and_wide(self):
        engine = RiskEngine()
        ok, reason = engine.evaluate_spread("EURUSD", 1.2, 2.0)
        assert ok is True

        ok, reason = engine.evaluate_spread("EURUSD", 3.5, 2.0)
        assert ok is False
        assert "exceeds allowed" in reason

    def test_evaluate_order_blocked_by_spread(self):
        engine = RiskEngine()
        now = datetime.now(tz=timezone.utc)
        decision = engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.0850,
            atr_val=0.0010,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=0.0,
            consecutive_losses=0,
            halt_until=None,
            open_positions=[],
            data_timestamp=now,
            now=now,
            current_spread_pips=4.2,
            max_spread_pips=2.0,
        )
        assert decision.approved is False
        assert decision.block_reason == "SPREAD_TOO_HIGH"


# ============================================================================
# MODULE 3: Multi-Level Defense Mode Tests
# ============================================================================
class TestMultiLevelDefense:
    def test_defense_level_0_normal(self):
        engine = RiskEngine()
        now = datetime.now(tz=timezone.utc)
        decision = engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.0850,
            atr_val=0.0010,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=0.0,
            consecutive_losses=0,
            halt_until=None,
            open_positions=[],
            data_timestamp=now,
            now=now,
        )
        assert decision.approved is True
        assert decision.defense_level == 0

    def test_defense_level_1_defensive_drawdown_halving(self):
        engine = RiskEngine()
        now = datetime.now(tz=timezone.utc)
        # Daily loss is -2.6% (exceeds 2.5% defensive threshold)
        decision = engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.0850,
            atr_val=0.0010,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=-260.0,
            consecutive_losses=1,
            halt_until=None,
            open_positions=[],
            data_timestamp=now,
            now=now,
        )
        assert decision.approved is True
        assert decision.defense_level == 1
        assert "Level 1 Defensive Mode" in decision.reason

    def test_defense_level_2_restricted_confidence_gate(self):
        engine = RiskEngine()
        now = datetime.now(tz=timezone.utc)
        decision = engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.0850,
            atr_val=0.0010,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=0.0,
            consecutive_losses=3,
            halt_until=None,
            open_positions=[],
            data_timestamp=now,
            now=now,
        )
        assert decision.approved is True
        assert decision.defense_level == 2

        # Test DeterministicGate enforces 0.80 threshold
        ctx = AIContext(
            symbol="EURUSD",
            timeframe=Timeframe.M5,
            price=1.0850,
            trend="BULLISH",
            rsi=50.0,
            ema={"EMA9": 1.0850, "EMA21": 1.0840},
            atr=0.0010,
            market_structure="BOS_LONG",
            volatility="NORMAL",
            session="LONDON",
            news_state={"high_impact_soon": False},
            current_position={"open_positions": 0},
            account_risk_state={"daily_pnl_pct": 0.0, "kill_switch_active": False},
            recent_trade_state={"consecutive_losses": 3},
            scenario_state={"active_scenario": "NONE"},
            timestamp=now,
        )
        # Confidence 0.70 should be rejected in Level 2 (requires 0.80)
        prop_70 = TradeProposal(
            symbol="EURUSD",
            decision=ProposalDecision.APPROVE,
            direction=Direction.LONG,
            confidence=0.70,
            entry_context={},
            rationale="Good setup but streak=3",
            invalidation="Below low",
            scenario="BULLISH_CONTINUATION",
            timestamp=now,
            model_provider="test",
            trace_id="t1",
        )
        res_70 = DeterministicGate.validate(prop_70, ctx, now=now)
        assert res_70.passed is False
        assert "Level 2 Restricted Mode" in res_70.reason

        # Confidence 0.82 should pass
        prop_82 = TradeProposal(
            symbol="EURUSD",
            decision=ProposalDecision.APPROVE,
            direction=Direction.LONG,
            confidence=0.82,
            entry_context={},
            rationale="High quality setup",
            invalidation="Below low",
            scenario="BULLISH_CONTINUATION",
            timestamp=now,
            model_provider="test",
            trace_id="t2",
        )
        res_82 = DeterministicGate.validate(prop_82, ctx, now=now)
        assert res_82.passed is True

    def test_defense_level_3_halt_and_level_4_emergency(self):
        engine = RiskEngine()
        now = datetime.now(tz=timezone.utc)
        halt_time = now + timedelta(minutes=30)
        # Level 3 Halt
        dec_halt = engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.0850,
            atr_val=0.0010,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=0.0,
            consecutive_losses=5,
            halt_until=halt_time,
            open_positions=[],
            data_timestamp=now,
            now=now,
        )
        assert dec_halt.approved is False
        assert dec_halt.defense_level == 3
        assert dec_halt.block_reason == "CONSECUTIVE_LOSS_HALT"

        # Level 4 Emergency
        engine.config.emergency_kill_switch = True
        dec_kill = engine.evaluate_order(
            symbol="EURUSD",
            direction=Direction.LONG,
            entry_price=1.0850,
            atr_val=0.0010,
            equity=10000.0,
            daily_starting_balance=10000.0,
            daily_pnl=0.0,
            consecutive_losses=0,
            halt_until=None,
            open_positions=[],
            data_timestamp=now,
            now=now,
        )
        assert dec_kill.approved is False
        assert dec_kill.defense_level == 4
        assert dec_kill.block_reason == "KILL_SWITCH_ACTIVE"


# ============================================================================
# MODULE 4: Higher Timeframe Regime Filter Tests
# ============================================================================
class TestHigherTimeframeRegime:
    def test_forex_h1_regime_filtering(self):
        now = datetime.now(tz=timezone.utc)
        # Create 60 H1 bars with rising trend (BULLISH regime)
        h1_bars = []
        for i in range(60):
            ts = now - timedelta(hours=60 - i)
            p = 1.0500 + i * 0.0010
            h1_bars.append(
                Bar("EURUSD", Timeframe.H1, ts, p, p + 0.0005, p - 0.0005, p + 0.0002, 1000.0)
            )
        h1_bars = sorted(h1_bars, key=lambda b: b.timestamp, reverse=True)

        # Create dummy M5 bars
        m5_bars = []
        for i in range(250):
            ts = now - timedelta(minutes=5 * (250 - i))
            p = 1.1000 + (i % 5) * 0.0001
            m5_bars.append(
                Bar("EURUSD", Timeframe.M5, ts, p, p + 0.0003, p - 0.0003, p + 0.0001, 500.0)
            )
        m5_bars = sorted(m5_bars, key=lambda b: b.timestamp, reverse=True)

        sig = forex_trend_breakout.evaluate(m5_bars, now=now, h1_bars=h1_bars)
        # Check gate against contrary H1 regime
        ctx_bearish_h1 = AIContext(
            symbol="EURUSD",
            timeframe=Timeframe.M5,
            price=1.0850,
            trend="BULLISH",
            rsi=50.0,
            ema={"EMA9": 1.0850, "EMA21": 1.0840},
            atr=0.0010,
            market_structure="BOS_LONG",
            volatility="NORMAL",
            session="LONDON",
            news_state={"high_impact_soon": False},
            current_position={"open_positions": 0},
            account_risk_state={"daily_pnl_pct": 0.0, "kill_switch_active": False},
            recent_trade_state={"consecutive_losses": 0},
            scenario_state={"h1_regime": "BEARISH"},
            timestamp=now,
        )
        prop_long = TradeProposal(
            symbol="EURUSD",
            decision=ProposalDecision.APPROVE,
            direction=Direction.LONG,
            confidence=0.85,
            entry_context={},
            rationale="M5 Bullish breakout",
            invalidation="Below low",
            scenario="BULLISH_CONTINUATION",
            timestamp=now,
            model_provider="test",
            trace_id="t3",
        )
        # Should be rejected because H1 regime is BEARISH and scenario is not REVERSAL
        val_res = DeterministicGate.validate(prop_long, ctx_bearish_h1, now=now)
        assert val_res.passed is False
        assert "contradicts BEARISH H1 regime" in val_res.reason


# ============================================================================
# MODULE 5: Post-Trade Loss Reason Classifier Tests
# ============================================================================
class TestLossReasonClassifier:
    def test_classify_loss_reasons(self):
        # Profit
        assert classify_loss_reason(realized_pnl=50.0) == LossReason.PROFIT

        # News event
        assert classify_loss_reason(realized_pnl=-50.0, news_active=True) == LossReason.NEWS_EVENT

        # Slippage impact
        assert classify_loss_reason(realized_pnl=-50.0, slippage_pips=4.5, max_slippage_threshold=3.0) == LossReason.SLIPPAGE_IMPACT

        # Regime reversal
        assert classify_loss_reason(realized_pnl=-50.0, regime_reversed=True) == LossReason.REGIME_REVERSAL

        # Spread cost (fast exit dominated by spread)
        assert classify_loss_reason(
            realized_pnl=-20.0,
            duration_seconds=60,
            spread_pips=2.0,
            sl_distance_pips=4.0,  # 2.0 / 4.0 = 50% >= 35%
        ) == LossReason.SPREAD_COST

        # Normal strategy loss
        assert classify_loss_reason(
            realized_pnl=-50.0,
            duration_seconds=1200,
            spread_pips=1.0,
            sl_distance_pips=15.0,
        ) == LossReason.NORMAL_STRATEGY_LOSS

    def test_state_manager_records_loss_reason(self, tmp_path):
        mgr = StateManager(state_dir=str(tmp_path))
        mgr.record_new_position(
            PositionState("pos_test", "EURUSD", "LONG", 0.05, 1.0850)
        )
        mgr.record_closed_position(
            position_id="pos_test",
            close_price=1.0830,
            realized_pnl=-100.0,
            loss_reason=LossReason.SPREAD_COST,
        )
        closed = mgr.state.closed_positions_history[-1]
        assert closed["loss_reason"] == LossReason.SPREAD_COST
        assert mgr.state.consecutive_losses == 1


# ============================================================================
# MODULE 6: Version Control & Git Lineage Tests
# ============================================================================
class TestVersionControlAndLineage:
    def test_version_constants(self):
        assert SYSTEM_VERSION == "1.3.0"
        assert SCHEMA_VERSION == "1.3"
        v_info = get_version_info()
        assert v_info["system_version"] == "1.3.0"
        assert len(v_info["git_commit"]) > 0

    def test_monitor_telemetry_includes_version(self, tmp_path):
        mon = OperationalMonitor(state_dir=str(tmp_path))
        mon.record_heartbeat(
            broker_connected=True,
            open_positions=0,
            daily_pnl=0.0,
            daily_pnl_pct=0.0,
            consecutive_losses=0,
            kill_switch_active=False,
        )
        health_file = tmp_path / "health.json"
        data = json.loads(health_file.read_text(encoding="utf-8"))
        assert data["system_version"] == "v1.3.0"
        assert "git_commit" in data

    def test_decision_trace_includes_version(self, tmp_path):
        logger = DecisionTraceLogger(log_dir=str(tmp_path))
        rec = logger.log_decision(
            trace_id="test_trace",
            event_id="TEST_EVENT",
            provider="TestProvider",
            model="test-model",
            context_summary={"test": True},
        )
        assert rec.system_version == SYSTEM_VERSION
        assert rec.git_commit is not None
        log_file = tmp_path / "decision_traces.jsonl"
        assert log_file.exists()
        line = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert line["system_version"] == "1.3.0"
