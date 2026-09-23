"""
Trading Bot Core Runner — Orchestrates 24/7 Demo execution lifecycle.
Wires: Market Data -> Strategy -> AI Layer -> Gate -> Risk Engine -> Broker -> Reconciliation -> Monitor.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.ai.context import AIContextBuilder
from src.ai.event_detector import EventDetector
from src.ai.provider import FailoverAIProvider, OfflineDeterministicAIProvider
from src.ai.schemas import ProposalDecision
from src.ai.validator import DeterministicGate
from src.brokers.ctrader_mcp import CTraderMCPBroker
from src.core.clock import candle_close_time, is_candle_closed
from src.core.models import Bar, Direction, Signal, Timeframe
from src.core.risk import RiskConfig, RiskEngine
from src.services.decision_trace import DecisionTraceService
from src.services.monitor import OperationalMonitor
from src.services.state_manager import PositionState, StateManager
from src.strategies import forex_trend_breakout, xau_mean_reversion

logger = logging.getLogger("TradingBot")

SYMBOL_MAP = {
    "EURUSD": {"id": 1, "lot_size": 100000.0, "scale": 100000.0, "point_scale": 100000},
    "GBPUSD": {"id": 2, "lot_size": 100000.0, "scale": 100000.0, "point_scale": 100000},
    "USDJPY": {"id": 4, "lot_size": 100000.0, "scale": 100000.0, "point_scale": 1000},
    "XAUUSD": {"id": 41, "lot_size": 100.0, "scale": 100000.0, "point_scale": 100},
}


class TradingBotRunner:
    def __init__(
        self,
        broker: Optional[CTraderMCPBroker] = None,
        risk_engine: Optional[RiskEngine] = None,
        state_manager: Optional[StateManager] = None,
        monitor: Optional[OperationalMonitor] = None,
        ai_provider: Optional[Any] = None,
        trace_service: Optional[DecisionTraceService] = None,
    ):
        self.broker = broker or CTraderMCPBroker()
        self.risk_engine = risk_engine or RiskEngine()
        self.state_mgr = state_manager or StateManager()
        self.monitor = monitor or OperationalMonitor()
        self.ai_provider = ai_provider or FailoverAIProvider()
        self.trace_service = trace_service or DecisionTraceService()

        self.detectors: Dict[str, EventDetector] = {
            sym: EventDetector(cooldown_seconds=300.0) for sym in SYMBOL_MAP
        }
        self.last_evaluated_bar_ts: Dict[str, datetime] = {}
        self._shutdown_event: Optional[asyncio.Event] = None

    @property
    def shutdown_event(self) -> asyncio.Event:
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()
        return self._shutdown_event

    @shutdown_event.setter
    def shutdown_event(self, val: asyncio.Event) -> None:
        self._shutdown_event = val

    async def initialize(self) -> None:
        """Connect to broker, verify account, and reconcile initial state."""
        logger.info("Initializing TradingBotRunner...")
        t0 = time.perf_counter()
        try:
            self.broker.connect()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.info("Broker connected successfully in %.2f ms", elapsed_ms)
        except Exception as e:
            logger.error("Failed to connect to broker: %s", e)
            self.monitor.record_heartbeat(
                broker_connected=False,
                open_positions=0,
                daily_pnl=self.state_mgr.state.daily_pnl,
                daily_pnl_pct=0.0,
                consecutive_losses=self.state_mgr.state.consecutive_losses,
                kill_switch_active=self.risk_engine.is_kill_switch_active(),
                ai_status="UNKNOWN",
            )
            raise

        # Fetch balance and reconcile open positions
        bal = self.broker.get_balance()
        balance = bal["balance"]
        equity = bal["equity"]
        logger.info("Account balance: $%.2f | Equity: $%.2f", balance, equity)

        # Update starting balance if not set
        if self.state_mgr.state.daily_starting_balance <= 0:
            self.state_mgr.state.daily_starting_balance = balance
            self.state_mgr.save_state()

        broker_positions = self.broker.get_positions()
        recon = self.state_mgr.reconcile_with_broker(broker_positions)
        logger.info("Startup reconciliation complete: %s", recon)

        # Update initial monitor telemetry
        self.monitor.record_heartbeat(
            broker_connected=True,
            open_positions=len(self.state_mgr.state.open_positions),
            daily_pnl=self.state_mgr.state.daily_pnl,
            daily_pnl_pct=self.state_mgr.state.daily_pnl / balance if balance > 0 else 0.0,
            consecutive_losses=self.state_mgr.state.consecutive_losses,
            kill_switch_active=self.risk_engine.is_kill_switch_active(),
            ai_status="HEALTHY",
            broker_latency_ms=elapsed_ms,
        )

    async def execute_cycle(self) -> None:
        """Execute a single evaluation, risk verification, and monitoring cycle."""
        now_utc = datetime.now(tz=timezone.utc)
        prev_reset_str = self.state_mgr.state.last_reset_date

        # 1. Broker state sync & reconciliation
        t0 = time.perf_counter()
        try:
            broker_positions = self.broker.get_positions()
            latency_ms = (time.perf_counter() - t0) * 1000.0
            recon = self.state_mgr.reconcile_with_broker(broker_positions, now=now_utc)
            broker_connected = True
        except Exception as e:
            logger.error("Broker query failed: %s", e)
            broker_connected = False
            latency_ms = 0.0
            self.monitor.record_exception()

        # 2. Account balance & risk state
        bal_info = self.broker.get_balance() if broker_connected else {"balance": 10000.0, "equity": 10000.0}
        equity = bal_info["equity"]
        balance = bal_info["balance"]

        # Check UTC midnight daily reset
        prev_reset_date = datetime.fromisoformat(prev_reset_str).date() if prev_reset_str else None
        did_reset, new_date, new_bal = self.risk_engine.check_daily_reset(
            current_time=now_utc,
            last_reset_date=prev_reset_date,
            current_balance=balance,
        )
        if did_reset or self.state_mgr.state.daily_starting_balance <= 0.0:
            self.state_mgr.state.last_reset_date = new_date.isoformat()
            self.state_mgr.state.daily_starting_balance = new_bal
            self.state_mgr.state.daily_pnl = 0.0
            self.state_mgr.save_state()

        daily_starting_bal = self.state_mgr.state.daily_starting_balance
        daily_pnl = self.state_mgr.state.daily_pnl
        consecutive_losses = self.state_mgr.state.consecutive_losses
        halt_until = datetime.fromisoformat(self.state_mgr.state.halt_until) if self.state_mgr.state.halt_until else None
        kill_switch = self.risk_engine.is_kill_switch_active()

        # Update monitor telemetry
        self.monitor.record_heartbeat(
            broker_connected=broker_connected,
            open_positions=len(self.state_mgr.state.open_positions),
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl / daily_starting_bal if daily_starting_bal > 0 else 0.0,
            consecutive_losses=consecutive_losses,
            kill_switch_active=kill_switch,
            ai_status="HEALTHY",
            broker_latency_ms=latency_ms,
        )

        if not broker_connected or kill_switch:
            if kill_switch:
                logger.warning(json.dumps({"event": "RISK_GATE", "status": "KILL_SWITCH_ACTIVE"}))
            return

        # Check consecutive loss halt or daily loss limit
        is_halted = halt_until is not None and now_utc < halt_until
        daily_loss_breached = (
            (daily_pnl / daily_starting_bal) <= -self.risk_engine.config.max_daily_loss_pct
            if daily_starting_bal > 0
            else False
        )
        if is_halted:
            logger.info("Cycle halted until %s (consecutive losses: %d)", halt_until, consecutive_losses)
            return
        if daily_loss_breached:
            logger.warning("Cycle halted: daily loss limit breached (%.2f%%)", (daily_pnl / daily_starting_bal) * 100)
            return

        open_symbols = set(self.state_mgr.state.open_positions.keys())
        total_open = len(open_symbols)

        if total_open >= self.risk_engine.config.max_open_positions:
            logger.info("Max open positions reached (%d/%d). Skipping new evaluations.",
                        total_open, self.risk_engine.config.max_open_positions)
            return

        # 3. Symbol Evaluation Loop (Forex & Metals)
        for symbol, sym_info in SYMBOL_MAP.items():
            if symbol in open_symbols:
                logger.debug("Symbol %s already has open position. Skipping.", symbol)
                continue
            if len(self.state_mgr.state.open_positions) >= self.risk_engine.config.max_open_positions:
                break

            # 3.1 Market Data Acquisition
            try:
                raw_m5 = self.broker.get_trendbars(
                    symbol_id=sym_info["id"],
                    period="M_5",
                    count=250,
                )
            except Exception as e:
                logger.error("Failed to fetch M5 trendbars for %s: %s", symbol, e)
                continue

            scale = sym_info.get("scale", 100000.0)
            m5_bars: list[Bar] = []
            for b in raw_m5:
                try:
                    open_f = b["open"] / scale
                    high_f = b["high"] / scale
                    low_f = b["low"] / scale
                    close_f = b["close"] / scale
                    ts = datetime.fromtimestamp(b["timestamp"] / 1000.0, tz=timezone.utc)
                    # Enforce closed-candle policy
                    if is_candle_closed(ts, Timeframe.M5, now=now_utc):
                        m5_bars.append(Bar(
                            symbol=symbol,
                            timeframe=Timeframe.M5,
                            timestamp=ts,
                            open=open_f,
                            high=max(high_f, open_f, close_f),
                            low=min(low_f, open_f, close_f),
                            close=close_f,
                            volume=float(b.get("volume", 0)),
                        ))
                except Exception as ex:
                    logger.debug("Skipping malformed bar for %s: %s", symbol, ex)

            # Deduplicate & sort newest at index 0
            m5_bars = sorted({b.timestamp: b for b in m5_bars}.values(), key=lambda b: b.timestamp, reverse=True)

            # Duplicate-cycle protection: avoid re-evaluating the identical closed bar
            if m5_bars and self.last_evaluated_bar_ts.get(symbol) == m5_bars[0].timestamp:
                logger.debug("Candle %s for %s already evaluated. Skipping.", m5_bars[0].timestamp, symbol)
                continue

            min_m5 = 16 if symbol == "XAUUSD" else 221
            if len(m5_bars) < min_m5:
                logger.info(json.dumps({
                    "event": "MARKET_DATA",
                    "symbol": symbol,
                    "status": "INSUFFICIENT_BARS",
                    "count": len(m5_bars),
                    "required": min_m5,
                }))
                continue

            h1_bars: list[Bar] = []
            if symbol == "XAUUSD":
                try:
                    raw_h1 = self.broker.get_trendbars(
                        symbol_id=sym_info["id"],
                        period="H_1",
                        count=70,
                    )
                    for b in raw_h1:
                        try:
                            open_f = b["open"] / scale
                            high_f = b["high"] / scale
                            low_f = b["low"] / scale
                            close_f = b["close"] / scale
                            ts = datetime.fromtimestamp(b["timestamp"] / 1000.0, tz=timezone.utc)
                            if is_candle_closed(ts, Timeframe.H1, now=now_utc):
                                h1_bars.append(Bar(
                                    symbol=symbol,
                                    timeframe=Timeframe.H1,
                                    timestamp=ts,
                                    open=open_f,
                                    high=max(high_f, open_f, close_f),
                                    low=min(low_f, open_f, close_f),
                                    close=close_f,
                                    volume=float(b.get("volume", 0)),
                                ))
                        except Exception:
                            pass
                    h1_bars = sorted({b.timestamp: b for b in h1_bars}.values(), key=lambda b: b.timestamp, reverse=True)
                except Exception as e:
                    logger.error("Failed to fetch H1 trendbars for %s: %s", symbol, e)
                    continue

                if len(h1_bars) < 51:
                    logger.info(json.dumps({
                        "event": "MARKET_DATA",
                        "symbol": symbol,
                        "status": "INSUFFICIENT_H1_BARS",
                        "count": len(h1_bars),
                        "required": 51,
                    }))
                    continue

            # Mark this closed bar timestamp as evaluated
            self.last_evaluated_bar_ts[symbol] = m5_bars[0].timestamp

            logger.info(json.dumps({
                "event": "MARKET_DATA",
                "symbol": symbol,
                "status": "ACQUIRED",
                "m5_bars": len(m5_bars),
                "h1_bars": len(h1_bars) if symbol == "XAUUSD" else 0,
                "latest_closed_bar": m5_bars[0].timestamp.isoformat(),
            }))

            # 3.2 Strategy Signal Generation
            sig: Optional[Signal] = None
            if symbol == "XAUUSD":
                sig = xau_mean_reversion.evaluate(m5_bars, h1_bars, now=now_utc)
            else:
                sig = forex_trend_breakout.evaluate(m5_bars, now=now_utc)

            if sig is None:
                logger.info(json.dumps({
                    "event": "STRATEGY",
                    "symbol": symbol,
                    "status": "NO_TRADE",
                    "reason": "NO_SIGNAL",
                    "bar_timestamp": m5_bars[0].timestamp.isoformat(),
                }))
                continue

            logger.info(json.dumps({
                "event": "STRATEGY",
                "symbol": symbol,
                "status": "SIGNAL_GENERATED",
                "direction": sig.direction.value,
                "strategy_id": sig.strategy_id,
                "price": sig.price,
                "indicators": sig.indicators,
            }))

            # 3.3 AI Advisory Layer
            try:
                ctx = AIContextBuilder.build(
                    symbol=symbol,
                    timeframe=Timeframe.M5,
                    m5_bars=m5_bars,
                    account_risk_state={
                        "daily_pnl_pct": round(daily_pnl / daily_starting_bal, 4) if daily_starting_bal > 0 else 0.0,
                        "kill_switch_active": kill_switch,
                    },
                    current_position={
                        "open_positions": len(self.state_mgr.state.open_positions),
                        "symbol_exposure": len(self.state_mgr.state.open_positions) / self.risk_engine.config.max_open_positions,
                    },
                    recent_trade_state={"consecutive_losses": consecutive_losses},
                    now=now_utc,
                )
            except Exception as e:
                logger.error("Failed to build AI context for %s: %s", symbol, e)
                continue

            should_invoke, event = self.detectors[symbol].should_invoke(ctx, now=now_utc, force_review=True)
            if not should_invoke:
                logger.info(json.dumps({
                    "event": "AI",
                    "symbol": symbol,
                    "status": "SUPPRESSED",
                    "reason": "COOLDOWN_ACTIVE",
                }))
                continue

            try:
                proposal = self.ai_provider.analyze(ctx)
            except Exception as e:
                logger.error("AI provider failure for %s: %s", symbol, e)
                fallback = OfflineDeterministicAIProvider()
                proposal = fallback.analyze(ctx)

            logger.info(json.dumps({
                "event": "AI",
                "symbol": symbol,
                "status": "PROPOSAL_GENERATED",
                "decision": proposal.decision.value,
                "direction": proposal.direction.value,
                "confidence": proposal.confidence,
                "scenario": proposal.scenario if isinstance(proposal.scenario, str) else getattr(proposal.scenario, "value", str(proposal.scenario)),
            }))

            # 3.4 Deterministic Gatekeeper
            val_res = DeterministicGate.validate(
                proposal=proposal,
                context=ctx,
                max_daily_loss_pct=self.risk_engine.config.max_daily_loss_pct,
                max_open_positions=self.risk_engine.config.max_open_positions,
                now=now_utc,
            )

            gate_approved = (
                val_res.passed
                and proposal.decision == ProposalDecision.APPROVE
                and proposal.direction == sig.direction
            )

            if not gate_approved:
                reject_reason = (
                    val_res.reason
                    if not val_res.passed
                    else f"Proposal decision={proposal.decision.value} or direction={proposal.direction.value} mismatches strategy={sig.direction.value}"
                )
                logger.info(json.dumps({
                    "event": "GATE",
                    "symbol": symbol,
                    "status": "REJECTED",
                    "reason": reject_reason,
                }))
                self.trace_service.log_decision(
                    trace_id=str(uuid.uuid4()),
                    event_id=event.event_type.value if event else "STRATEGY_SIGNAL",
                    provider=getattr(self.ai_provider, "name", "AIProvider"),
                    model=getattr(self.ai_provider, "model", "default"),
                    context_summary=ctx.to_dict(),
                    proposal=proposal,
                    validation_result=val_res,
                    risk_result={"approved": False, "reason": "Gate rejected"},
                    execution_result={"status": "REJECTED_BY_GATE", "reason": reject_reason},
                )
                continue

            logger.info(json.dumps({
                "event": "GATE",
                "symbol": symbol,
                "status": "APPROVED",
                "reason": val_res.reason,
            }))

            # 3.5 Risk Engine Evaluation
            atr_val = ctx.atr
            risk_decision = self.risk_engine.evaluate_order(
                symbol=symbol,
                direction=sig.direction,
                entry_price=sig.price,
                atr_val=atr_val,
                equity=equity,
                daily_starting_balance=daily_starting_bal,
                daily_pnl=daily_pnl,
                consecutive_losses=consecutive_losses,
                halt_until=halt_until,
                open_positions=[p.to_dict() for p in self.state_mgr.state.open_positions.values()],
                data_timestamp=candle_close_time(m5_bars[0].timestamp, Timeframe.M5),
                now=now_utc,
                lot_size_units=sym_info.get("lot_size", 100000.0),
            )

            if not risk_decision.approved:
                logger.info(json.dumps({
                    "event": "RISK",
                    "symbol": symbol,
                    "status": "REJECTED",
                    "reason": risk_decision.reason,
                    "block_reason": risk_decision.block_reason,
                }))
                self.trace_service.log_decision(
                    trace_id=str(uuid.uuid4()),
                    event_id=event.event_type.value if event else "STRATEGY_SIGNAL",
                    provider=getattr(self.ai_provider, "name", "AIProvider"),
                    model=getattr(self.ai_provider, "model", "default"),
                    context_summary=ctx.to_dict(),
                    proposal=proposal,
                    validation_result=val_res,
                    risk_result={
                        "approved": False,
                        "reason": risk_decision.reason,
                        "block_reason": risk_decision.block_reason,
                    },
                    execution_result={"status": "REJECTED_BY_RISK", "reason": risk_decision.reason},
                )
                continue

            logger.info(json.dumps({
                "event": "RISK",
                "symbol": symbol,
                "status": "APPROVED",
                "allocated_volume": risk_decision.adjusted_volume,
            }))

            # 3.6 Broker Order Submission (cTrader Remote MCP)
            lots = risk_decision.adjusted_volume
            lot_size = sym_info.get("lot_size", 100000.0)
            # Volume in 1/100 base-asset units: volume = lots * lotSize * 100
            mcp_volume = int(round(lots * lot_size * 100))

            sl_dist = max(atr_val * self.risk_engine.config.atr_multiplier_sl, 1e-5)
            tp_dist = sl_dist * self.risk_engine.config.rr_ratio

            point_scale = sym_info.get("point_scale", 100000)
            relative_sl = max(1, int(round(sl_dist * point_scale)))
            relative_tp = max(1, int(round(tp_dist * point_scale)))

            trade_side = "BUY" if sig.direction == Direction.LONG else "SELL"
            trace_id = str(uuid.uuid4())

            order_result: dict[str, Any] = {}
            try:
                order_result = self.broker.create_market_order(
                    symbol_id=sym_info["id"],
                    trade_side=trade_side,
                    volume=mcp_volume,
                    relative_sl=relative_sl,
                    relative_tp=relative_tp,
                    comment=f"Bot_{symbol}_{sig.strategy_id}",
                    label="trading-bot-m5",
                )
                logger.info(json.dumps({
                    "event": "EXECUTION",
                    "symbol": symbol,
                    "status": "ORDER_SUBMITTED",
                    "trade_side": trade_side,
                    "volume_lots": lots,
                    "mcp_volume": mcp_volume,
                    "relative_sl_points": relative_sl,
                    "relative_tp_points": relative_tp,
                    "result": order_result,
                }))
            except Exception as e:
                logger.error("Order submission failed for %s: %s", symbol, e)
                order_result = {"status": "FAILED", "error": str(e)}

            # 3.7 Decision Trace Logging
            self.trace_service.log_decision(
                trace_id=trace_id,
                event_id=event.event_type.value if event else "STRATEGY_SIGNAL",
                provider=getattr(self.ai_provider, "name", "AIProvider"),
                model=getattr(self.ai_provider, "model", "default"),
                context_summary=ctx.to_dict(),
                proposal=proposal,
                validation_result=val_res,
                risk_result={
                    "approved": True,
                    "adjusted_volume": lots,
                    "reason": risk_decision.reason,
                },
                execution_result=order_result,
            )

            # 3.8 State Update & Reconciliation
            try:
                updated_positions = self.broker.get_positions()
                self.state_mgr.reconcile_with_broker(updated_positions, now=now_utc)
            except Exception as e:
                logger.error("Post-order position reconciliation error: %s", e)

    async def run_forever(self, cycle_interval_seconds: float = 5.0) -> None:
        """Main 24/7 autonomous loop."""
        await self.initialize()
        logger.info("TradingBotRunner 24/7 loop started (interval: %.1fs)", cycle_interval_seconds)

        while not self.shutdown_event.is_set():
            try:
                await self.execute_cycle()
            except Exception as e:
                logger.error("Unhandled error in execution cycle: %s", e)
                self.monitor.record_exception()

            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=cycle_interval_seconds)
            except asyncio.TimeoutError:
                pass

        logger.info("TradingBotRunner shutting down gracefully...")
        self.monitor.shutdown()

    def stop(self) -> None:
        self.shutdown_event.set()
