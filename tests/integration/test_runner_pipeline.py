"""
Integration tests for TradingBotRunner Runtime Pipeline Wiring.
Verifies the complete execution pipeline:
Market Data -> Strategy -> AI Advisory -> Deterministic Gate -> Risk Engine -> Broker Execution -> State Update -> Reconciliation -> Monitoring -> Decision Trace.
"""
import asyncio
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.ai.provider import OfflineDeterministicAIProvider
from src.ai.schemas import AIContext, ProposalDecision, TradeProposal
from src.ai.validator import DeterministicGate, ValidationResult
from src.app.runner import SYMBOL_MAP, TradingBotRunner
from src.brokers.ctrader_mcp import CTraderMCPBroker
from src.core.models import Bar, Direction, Signal, Timeframe
from src.core.risk import RiskConfig, RiskDecision, RiskEngine
from src.services.decision_trace import DecisionTraceService
from src.services.monitor import OperationalMonitor
from src.services.state_manager import StateManager


@pytest.fixture
def temp_dirs():
    state_d = tempfile.mkdtemp()
    log_d = tempfile.mkdtemp()
    yield state_d, log_d
    shutil.rmtree(state_d, ignore_errors=True)
    shutil.rmtree(log_d, ignore_errors=True)


def generate_synthetic_trendbars(symbol_id: int, count: int = 250, base_price: int = 114250, now_dt: datetime = None):
    if now_dt is None:
        now_dt = datetime.now(tz=timezone.utc)
    bars = []
    # 5-minute intervals going backward from previous closed candle
    latest_open = int(now_dt.timestamp() // 300) * 300 - 300
    for i in range(count):
        t_epoch = latest_open - ((count - 1 - i) * 300)
        p = base_price + (i % 20) * 5
        bars.append({
            "timestamp": t_epoch * 1000,
            "open": p,
            "high": p + 15,
            "low": p - 10,
            "close": p + 5,
            "volume": 350,
        })
    return bars


def test_1_execute_cycle_reaches_strategy_path(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    broker.get_trendbars.return_value = generate_synthetic_trendbars(1, count=250)

    state_mgr = StateManager(state_dir=state_d)
    monitor = OperationalMonitor(state_dir=state_d)
    trace = DecisionTraceService(log_dir=log_d)
    runner = TradingBotRunner(
        broker=broker,
        state_manager=state_mgr,
        monitor=monitor,
        trace_service=trace,
    )

    asyncio.run(runner.execute_cycle())
    assert broker.get_trendbars.called
    assert broker.get_trendbars.call_args[1]["symbol_id"] in [1, 2, 4, 41]


def test_2_no_signal_no_order(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    # Synthetic flat bars will not trigger breakout or RSI cross
    broker.get_trendbars.return_value = generate_synthetic_trendbars(1, count=250, base_price=110000)

    runner = TradingBotRunner(
        broker=broker,
        state_manager=StateManager(state_dir=state_d),
        monitor=OperationalMonitor(state_dir=state_d),
        trace_service=DecisionTraceService(log_dir=log_d),
    )

    asyncio.run(runner.execute_cycle())
    assert not broker.create_market_order.called


def test_3_strategy_signal_to_ai_path(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    broker.get_trendbars.return_value = generate_synthetic_trendbars(1, count=250)

    mock_ai = MagicMock(spec=OfflineDeterministicAIProvider)
    mock_ai.name = "MockAI"
    mock_ai.analyze.return_value = TradeProposal(
        decision=ProposalDecision.PASS,
        direction=Direction.FLAT,
        confidence=0.5,
        entry_context={"rsi": 50.0},
        invalidation="None",
        rationale="Pass",
        scenario="NO_TRADE",
        symbol="EURUSD",
        timestamp=datetime.now(tz=timezone.utc),
        model_provider="mock",
        trace_id="trace_test_3",
    )

    runner = TradingBotRunner(
        broker=broker,
        state_manager=StateManager(state_dir=state_d),
        monitor=OperationalMonitor(state_dir=state_d),
        trace_service=DecisionTraceService(log_dir=log_d),
        ai_provider=mock_ai,
    )

    dummy_signal = Signal(
        symbol="EURUSD",
        direction=Direction.LONG,
        strategy_id="FOREX_TREND_BREAKOUT_V1",
        timestamp=datetime.now(tz=timezone.utc),
        price=1.1450,
        indicators={"atr": 0.0015},
    )
    with patch("src.strategies.forex_trend_breakout.evaluate", side_effect=lambda bars, now=None: dummy_signal if bars and bars[0].symbol == "EURUSD" else None):
        asyncio.run(runner.execute_cycle())

    assert mock_ai.analyze.called
    assert mock_ai.analyze.call_args[0][0].symbol == "EURUSD"


def test_4_ai_reject_no_order(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    broker.get_trendbars.return_value = generate_synthetic_trendbars(1, count=250)

    mock_ai = MagicMock(spec=OfflineDeterministicAIProvider)
    mock_ai.name = "MockAI"
    mock_ai.analyze.return_value = TradeProposal(
        decision=ProposalDecision.REJECT,
        direction=Direction.FLAT,
        confidence=0.8,
        entry_context={"rsi": 50.0},
        invalidation="Invalidated by structure",
        rationale="AI advises rejection",
        scenario="BREAKOUT_FAILURE",
        symbol="EURUSD",
        timestamp=datetime.now(tz=timezone.utc),
        model_provider="mock",
        trace_id="trace_test_4",
    )

    runner = TradingBotRunner(
        broker=broker,
        state_manager=StateManager(state_dir=state_d),
        monitor=OperationalMonitor(state_dir=state_d),
        trace_service=DecisionTraceService(log_dir=log_d),
        ai_provider=mock_ai,
    )

    dummy_signal = Signal(
        symbol="EURUSD",
        direction=Direction.LONG,
        strategy_id="FOREX_TREND_BREAKOUT_V1",
        timestamp=datetime.now(tz=timezone.utc),
        price=1.1450,
        indicators={"atr": 0.0015},
    )
    with patch("src.strategies.forex_trend_breakout.evaluate", return_value=dummy_signal):
        asyncio.run(runner.execute_cycle())

    assert not broker.create_market_order.called


def test_5_gate_reject_no_order(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    broker.get_trendbars.return_value = generate_synthetic_trendbars(1, count=250)

    mock_ai = MagicMock(spec=OfflineDeterministicAIProvider)
    mock_ai.name = "MockAI"
    # AI proposes SHORT when strategy proposed LONG -> Gate mismatch
    mock_ai.analyze.return_value = TradeProposal(
        decision=ProposalDecision.APPROVE,
        direction=Direction.SHORT,
        confidence=0.9,
        entry_context={"rsi": 50.0},
        invalidation="EMA cross",
        rationale="Counter trend attempt",
        scenario="REVERSAL",
        symbol="EURUSD",
        timestamp=datetime.now(tz=timezone.utc),
        model_provider="mock",
        trace_id="trace_test_5",
    )

    runner = TradingBotRunner(
        broker=broker,
        state_manager=StateManager(state_dir=state_d),
        monitor=OperationalMonitor(state_dir=state_d),
        trace_service=DecisionTraceService(log_dir=log_d),
        ai_provider=mock_ai,
    )

    dummy_signal = Signal(
        symbol="EURUSD",
        direction=Direction.LONG,
        strategy_id="FOREX_TREND_BREAKOUT_V1",
        timestamp=datetime.now(tz=timezone.utc),
        price=1.1450,
        indicators={"atr": 0.0015},
    )
    with patch("src.strategies.forex_trend_breakout.evaluate", return_value=dummy_signal):
        asyncio.run(runner.execute_cycle())

    assert not broker.create_market_order.called


def test_6_risk_reject_no_order(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    # Account equity is 0 -> risk reject
    broker.get_balance.return_value = {"balance": 0.0, "equity": 0.0}
    broker.get_trendbars.return_value = generate_synthetic_trendbars(1, count=250)

    mock_ai = MagicMock(spec=OfflineDeterministicAIProvider)
    mock_ai.name = "MockAI"
    mock_ai.analyze.return_value = TradeProposal(
        decision=ProposalDecision.APPROVE,
        direction=Direction.LONG,
        confidence=0.9,
        entry_context={"rsi": 50.0},
        invalidation="Below EMA200",
        rationale="Strong trend continuation",
        scenario="BULLISH_CONTINUATION",
        symbol="EURUSD",
        timestamp=datetime.now(tz=timezone.utc),
        model_provider="mock",
        trace_id="trace_test_6",
    )

    runner = TradingBotRunner(
        broker=broker,
        state_manager=StateManager(state_dir=state_d),
        monitor=OperationalMonitor(state_dir=state_d),
        trace_service=DecisionTraceService(log_dir=log_d),
        ai_provider=mock_ai,
    )

    dummy_signal = Signal(
        symbol="EURUSD",
        direction=Direction.LONG,
        strategy_id="FOREX_TREND_BREAKOUT_V1",
        timestamp=datetime.now(tz=timezone.utc),
        price=1.1450,
        indicators={"atr": 0.0015},
    )
    with patch("src.strategies.forex_trend_breakout.evaluate", return_value=dummy_signal):
        asyncio.run(runner.execute_cycle())

    assert not broker.create_market_order.called


def test_7_approved_signal_broker_execution_path(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    broker.get_trendbars.return_value = generate_synthetic_trendbars(1, count=250)
    broker.create_market_order.return_value = {"orderId": "ORD_123", "status": "FILLED"}

    mock_ai = MagicMock(spec=OfflineDeterministicAIProvider)
    mock_ai.name = "MockAI"
    mock_ai.analyze.return_value = TradeProposal(
        decision=ProposalDecision.APPROVE,
        direction=Direction.LONG,
        confidence=0.85,
        entry_context={"rsi": 50.0},
        invalidation="Below EMA200",
        rationale="Confirmed bullish breakout",
        scenario="BREAKOUT",
        symbol="EURUSD",
        timestamp=datetime.now(tz=timezone.utc),
        model_provider="mock",
        trace_id="trace_test_7",
    )

    runner = TradingBotRunner(
        broker=broker,
        state_manager=StateManager(state_dir=state_d),
        monitor=OperationalMonitor(state_dir=state_d),
        trace_service=DecisionTraceService(log_dir=log_d),
        ai_provider=mock_ai,
    )

    dummy_signal = Signal(
        symbol="EURUSD",
        direction=Direction.LONG,
        strategy_id="FOREX_TREND_BREAKOUT_V1",
        timestamp=datetime.now(tz=timezone.utc),
        price=1.1450,
        indicators={"atr": 0.0015},
    )
    with patch("src.strategies.forex_trend_breakout.evaluate", side_effect=lambda bars, now=None: dummy_signal if bars and bars[0].symbol == "EURUSD" else None):
        asyncio.run(runner.execute_cycle())

    assert broker.create_market_order.called
    call_kwargs = broker.create_market_order.call_args[1]
    assert call_kwargs["symbol_id"] == 1
    assert call_kwargs["trade_side"] == "BUY"
    assert call_kwargs["volume"] > 0
    assert call_kwargs["relative_sl"] > 0
    assert call_kwargs["relative_tp"] > 0


def test_8_broker_failure_safe_state(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    broker.get_trendbars.return_value = generate_synthetic_trendbars(1, count=250)
    broker.create_market_order.side_effect = ConnectionError("cTrader MCP execution timeout")

    mock_ai = MagicMock(spec=OfflineDeterministicAIProvider)
    mock_ai.name = "MockAI"
    mock_ai.analyze.return_value = TradeProposal(
        decision=ProposalDecision.APPROVE,
        direction=Direction.LONG,
        confidence=0.9,
        entry_context={"rsi": 50.0},
        invalidation="Below EMA",
        rationale="Approved",
        scenario="BULLISH_CONTINUATION",
        symbol="EURUSD",
        timestamp=datetime.now(tz=timezone.utc),
        model_provider="mock",
        trace_id="trace_test_8",
    )

    runner = TradingBotRunner(
        broker=broker,
        state_manager=StateManager(state_dir=state_d),
        monitor=OperationalMonitor(state_dir=state_d),
        trace_service=DecisionTraceService(log_dir=log_d),
        ai_provider=mock_ai,
    )

    dummy_signal = Signal(
        symbol="EURUSD",
        direction=Direction.LONG,
        strategy_id="FOREX_TREND_BREAKOUT_V1",
        timestamp=datetime.now(tz=timezone.utc),
        price=1.1450,
        indicators={"atr": 0.0015},
    )
    with patch("src.strategies.forex_trend_breakout.evaluate", return_value=dummy_signal):
        asyncio.run(runner.execute_cycle())

    assert len(runner.state_mgr.state.open_positions) == 0


def test_9_duplicate_cycle_protection(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    bars = generate_synthetic_trendbars(1, count=250)
    broker.get_trendbars.return_value = bars

    runner = TradingBotRunner(
        broker=broker,
        state_manager=StateManager(state_dir=state_d),
        monitor=OperationalMonitor(state_dir=state_d),
        trace_service=DecisionTraceService(log_dir=log_d),
    )

    eval_count = 0

    def mock_eval(*args, **kwargs):
        nonlocal eval_count
        eval_count += 1
        return None

    with patch("src.strategies.forex_trend_breakout.evaluate", side_effect=mock_eval):
        asyncio.run(runner.execute_cycle())
        first_count = eval_count
        asyncio.run(runner.execute_cycle())
        second_count = eval_count

    assert first_count >= 1
    assert second_count == first_count


def test_10_restart_reconciliation(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    broker.get_positions.return_value = [
        {
            "positionId": 99901,
            "symbolId": 1,
            "tradeSide": "BUY",
            "volume": 100000,
            "entryPrice": 1.1450,
        }
    ]

    state_mgr = StateManager(state_dir=state_d)
    runner = TradingBotRunner(
        broker=broker,
        state_manager=state_mgr,
        monitor=OperationalMonitor(state_dir=state_d),
    )

    asyncio.run(runner.initialize())
    assert "99901" in state_mgr.state.open_positions
    assert state_mgr.state.open_positions["99901"]["symbol"] == "1"


def test_11_daily_utc_reset(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10500.0, "equity": 10500.0}

    state_mgr = StateManager(state_dir=state_d)
    state_mgr.state.last_reset_date = "2026-09-22"
    state_mgr.state.daily_pnl = 500.0
    state_mgr.state.daily_starting_balance = 10000.0
    state_mgr.save_state()

    runner = TradingBotRunner(
        broker=broker,
        state_manager=state_mgr,
        monitor=OperationalMonitor(state_dir=state_d),
    )

    asyncio.run(runner.execute_cycle())
    today_utc = datetime.now(tz=timezone.utc).date().isoformat()
    assert state_mgr.state.last_reset_date == today_utc
    assert state_mgr.state.daily_pnl == 0.0
    assert state_mgr.state.daily_starting_balance == 10500.0


def test_12_kill_switch_active(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}

    runner = TradingBotRunner(
        broker=broker,
        state_manager=StateManager(state_dir=state_d),
        monitor=OperationalMonitor(state_dir=state_d),
    )

    with patch.dict(os.environ, {"EMERGENCY_KILL_SWITCH": "true"}):
        asyncio.run(runner.execute_cycle())

    assert not broker.get_trendbars.called
    assert not broker.create_market_order.called


def test_13_stale_market_data_rejection(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    # Old bars from 1 hour ago
    old_time = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    broker.get_trendbars.return_value = generate_synthetic_trendbars(1, count=250, now_dt=old_time)

    mock_ai = MagicMock(spec=OfflineDeterministicAIProvider)
    mock_ai.name = "MockAI"
    mock_ai.analyze.return_value = TradeProposal(
        decision=ProposalDecision.APPROVE,
        direction=Direction.LONG,
        confidence=0.9,
        entry_context={"rsi": 50.0},
        invalidation="Below EMA",
        rationale="Approved",
        scenario="BULLISH_CONTINUATION",
        symbol="EURUSD",
        timestamp=datetime.now(tz=timezone.utc),
        model_provider="mock",
        trace_id="trace_test_13",
    )

    runner = TradingBotRunner(
        broker=broker,
        state_manager=StateManager(state_dir=state_d),
        monitor=OperationalMonitor(state_dir=state_d),
        trace_service=DecisionTraceService(log_dir=log_d),
        ai_provider=mock_ai,
    )

    dummy_signal = Signal(
        symbol="EURUSD",
        direction=Direction.LONG,
        strategy_id="FOREX_TREND_BREAKOUT_V1",
        timestamp=datetime.now(tz=timezone.utc),
        price=1.1450,
        indicators={"atr": 0.0015},
    )
    with patch("src.strategies.forex_trend_breakout.evaluate", return_value=dummy_signal):
        asyncio.run(runner.execute_cycle())

    # Blocked by RiskEngine STALE_DATA check
    assert not broker.create_market_order.called


def test_14_decision_trace_emitted(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    broker.get_trendbars.return_value = generate_synthetic_trendbars(1, count=250)

    mock_ai = MagicMock(spec=OfflineDeterministicAIProvider)
    mock_ai.name = "MockAI"
    mock_ai.analyze.return_value = TradeProposal(
        decision=ProposalDecision.REJECT,
        direction=Direction.FLAT,
        confidence=0.9,
        entry_context={"rsi": 50.0},
        invalidation="Structure break",
        rationale="Rejected",
        scenario="NO_TRADE",
        symbol="EURUSD",
        timestamp=datetime.now(tz=timezone.utc),
        model_provider="mock",
        trace_id="trace_test_14",
    )

    trace = DecisionTraceService(log_dir=log_d)
    runner = TradingBotRunner(
        broker=broker,
        state_manager=StateManager(state_dir=state_d),
        monitor=OperationalMonitor(state_dir=state_d),
        trace_service=trace,
        ai_provider=mock_ai,
    )

    dummy_signal = Signal(
        symbol="EURUSD",
        direction=Direction.LONG,
        strategy_id="FOREX_TREND_BREAKOUT_V1",
        timestamp=datetime.now(tz=timezone.utc),
        price=1.1450,
        indicators={"atr": 0.0015},
    )
    with patch("src.strategies.forex_trend_breakout.evaluate", return_value=dummy_signal):
        asyncio.run(runner.execute_cycle())

    trace_file = os.path.join(log_d, "decision_traces.jsonl")
    assert os.path.exists(trace_file)
    with open(trace_file, "r") as f:
        lines = f.readlines()
    assert len(lines) >= 1
    assert "EURUSD" in lines[0]


def test_15_health_heartbeat_advances(temp_dirs):
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = []
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    broker.get_trendbars.return_value = []

    monitor = OperationalMonitor(state_dir=state_d)
    runner = TradingBotRunner(
        broker=broker,
        state_manager=StateManager(state_dir=state_d),
        monitor=monitor,
    )

    asyncio.run(runner.execute_cycle())
    health_file = os.path.join(state_d, "health.json")
    assert os.path.exists(health_file)
    with open(health_file, "r") as f:
        content = f.read()
    assert '"alive": true' in content
    assert '"broker_connected": true' in content


def test_16_regression_open_positions_dict_serialization(temp_dirs):
    """
    Regression test for:
    Unhandled error in execution cycle: 'dict' object has no attribute 'to_dict'

    When an existing open position is tracked in state_manager (e.g. from prior
    order or broker startup discovery), each item in state.open_positions is a dict.
    When a new signal (e.g. GBPUSD) is evaluated and approved by AI + Gate,
    passing open_positions to RiskEngine must NOT invoke .to_dict() on the dicts.
    """
    state_d, log_d = temp_dirs
    broker = MagicMock(spec=CTraderMCPBroker)
    broker.get_positions.return_value = [
        {"positionId": "PID1001", "symbolId": 1, "tradeSide": "BUY", "volume": 100000, "entryPrice": 1.1000}
    ]
    broker.get_balance.return_value = {"balance": 10000.0, "equity": 10000.0}
    broker.get_trendbars.return_value = generate_synthetic_trendbars(2, count=250)
    broker.create_market_order.return_value = {"orderId": "ORD_GBP_001", "status": "FILLED"}

    state_mgr = StateManager(state_dir=state_d)
    # Pre-populate state with an existing open position as dict
    state_mgr.state.open_positions = {
        "PID1001": {
            "position_id": "PID1001",
            "symbol": "EURUSD",
            "direction": "BUY",
            "volume_lots": 0.05,
            "entry_price": 1.1000,
            "sl_price": 1.0950,
            "tp_price": 1.1100,
            "open_time": "2026-09-25T10:00:00+00:00",
            "status": "OPEN",
        }
    }

    mock_ai = MagicMock(spec=OfflineDeterministicAIProvider)
    mock_ai.name = "MockAI"
    mock_ai.analyze.return_value = TradeProposal(
        decision=ProposalDecision.APPROVE,
        direction=Direction.SHORT,
        confidence=0.90,
        entry_context={"rsi": 65.0},
        invalidation="Above EMA200",
        rationale="Strong breakdown confirmed",
        scenario="BEARISH_BREAKDOWN",
        symbol="GBPUSD",
        timestamp=datetime.now(tz=timezone.utc),
        model_provider="mock",
        trace_id="trace_regression_16",
    )

    runner = TradingBotRunner(
        broker=broker,
        state_manager=state_mgr,
        monitor=OperationalMonitor(state_dir=state_d),
        trace_service=DecisionTraceService(log_dir=log_d),
        ai_provider=mock_ai,
    )

    dummy_signal = Signal(
        symbol="GBPUSD",
        direction=Direction.SHORT,
        strategy_id="FOREX_TREND_BREAKOUT_V1",
        timestamp=datetime.now(tz=timezone.utc),
        price=1.3245,
        indicators={"atr": 0.0020},
    )

    with patch("src.strategies.forex_trend_breakout.evaluate", return_value=dummy_signal):
        asyncio.run(runner.execute_cycle())

    # Verify broker order was successfully submitted without throwing 'dict' object has no attribute 'to_dict'
    assert broker.create_market_order.called
    call_args = broker.create_market_order.call_args[1]
    assert call_args["symbol_id"] == 2
    assert call_args["trade_side"] == "SELL"
