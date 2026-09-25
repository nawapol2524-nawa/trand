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
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
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
from src.core.version import SYSTEM_VERSION, get_git_commit_sha
from src.services.decision_trace import DecisionTraceService
from src.services.evidence import EvidenceCollector, EvidenceUploader, TradeRecord
from src.services.monitor import OperationalMonitor
from src.services.state_manager import PositionState, StateManager
from src.strategies import forex_trend_breakout, xau_mean_reversion

logger = logging.getLogger("TradingBot")

SYMBOL_MAP = {
    "EURUSD": {"id": 1, "lot_size": 100000.0, "scale": 100000.0, "digits": 5, "max_spread": 2.0},
    "GBPUSD": {"id": 2, "lot_size": 100000.0, "scale": 100000.0, "digits": 5, "max_spread": 2.5},
    "USDJPY": {"id": 4, "lot_size": 100000.0, "scale": 100000.0, "digits": 3, "max_spread": 2.5},
    "XAUUSD": {"id": 41, "lot_size": 100.0, "scale": 100000.0, "digits": 2, "max_spread": 50.0},
}


def _normalize_position_dict(p: Any) -> Dict[str, Any]:
    """Normalize position representation to Dict[str, Any] with canonical symbol mapping."""
    if isinstance(p, dict):
        d = dict(p)
    elif hasattr(p, "to_dict") and callable(p.to_dict):
        d = p.to_dict()
    elif is_dataclass(p):
        d = asdict(p)
    else:
        d = dict(p)

    raw_sym = str(d.get("symbol", ""))
    id_to_sym = {str(info["id"]): name for name, info in SYMBOL_MAP.items()}
    if raw_sym in id_to_sym:
        d["symbol"] = id_to_sym[raw_sym]
    return d


class TradingBotRunner:
    def __init__(
        self,
        broker: Optional[CTraderMCPBroker] = None,
        risk_engine: Optional[RiskEngine] = None,
        state_manager: Optional[StateManager] = None,
        monitor: Optional[OperationalMonitor] = None,
        ai_provider: Optional[Any] = None,
        trace_service: Optional[DecisionTraceService] = None,
        evidence_collector: Optional[EvidenceCollector] = None,
        evidence_uploader: Optional[EvidenceUploader] = None,
    ):
        self.broker = broker or CTraderMCPBroker()
        self.risk_engine = risk_engine or RiskEngine()
        self.state_mgr = state_manager or StateManager()
        self.monitor = monitor or OperationalMonitor()
        self.ai_provider = ai_provider or FailoverAIProvider()
        self.trace_service = trace_service or DecisionTraceService()
        self.evidence_collector = evidence_collector or EvidenceCollector(
            base_dir=str(Path(self.state_mgr.state_dir) / "evidence")
        )
        self.evidence_uploader = evidence_uploader or EvidenceUploader(
            collector=self.evidence_collector
        )

        self.detectors: Dict[str, EventDetector] = {
            sym: EventDetector(cooldown_seconds=300.0) for sym in SYMBOL_MAP
        }
        self.last_evaluated_bar_ts: Dict[str, datetime] = {}
        self._shutdown_event: Optional[asyncio.Event] = None
        self._uploader_task: Optional[asyncio.Task] = None

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
        self.evidence_collector.record_runtime_event("BOT_INITIALIZING", status="IN_PROGRESS")
        t0 = time.perf_counter()
        try:
            self.broker.connect()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.info("Broker connected successfully in %.2f ms", elapsed_ms)
        except Exception as e:
            logger.error("Failed to connect to broker: %s", e)
            self.evidence_collector.record_runtime_event(
                "BROKER_CONNECT_FAILED",
                status="FAILED",
                error_message=str(e),
            )
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
        self.evidence_collector.record_runtime_event(
            "BROKER_CONNECTED",
            status="SUCCESS",
            payload={"latency_ms": elapsed_ms, "balance": balance, "equity": equity},
        )

        # Update starting balance if not set
        if self.state_mgr.state.daily_starting_balance <= 0:
            self.state_mgr.state.daily_starting_balance = balance
            self.state_mgr.save_state()

        broker_positions = self.broker.get_positions()
        recon = self.state_mgr.reconcile_with_broker(broker_positions)
        logger.info("Startup reconciliation complete: %s", recon)
        self.evidence_collector.record_reconciliation(recon)
        self.evidence_collector.record_runtime_event(
            "RECONCILIATION",
            status=recon.get("status", "IN_SYNC"),
            reconciliation_state=recon.get("status", "IN_SYNC"),
            payload=recon,
        )

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
        self.evidence_collector.record_health(asdict(self.monitor.telemetry))
        self.evidence_collector.record_runtime_event("BOT_INITIALIZED", status="SUCCESS")

    def manage_open_positions(
        self,
        broker_positions: list[dict[str, Any]],
        now: Optional[datetime] = None,
    ) -> None:
        """
        Convex Asymmetric Exit Engine:
          1. 1.5R Partial Take Profit (Close 50% volume)
          2. Break-Even Stop Loss protection (Risk-Free)
          3. Trailing ATR runner on remaining 50% volume
        """
        now_utc = now or datetime.now(tz=timezone.utc)
        open_positions_dict = self.state_mgr.state.open_positions
        if not open_positions_dict:
            return

        symbol_ids = [info["id"] for info in SYMBOL_MAP.values()]
        spots_by_id: dict[int, dict[str, Any]] = {}
        try:
            spot_list = self.broker.get_spot_prices(symbol_ids)
            if isinstance(spot_list, list):
                spots_by_id = {s.get("symbolId"): s for s in spot_list if isinstance(s, dict)}
        except Exception as e:
            logger.debug("Failed to fetch spot prices for position management: %s", e)

        id_to_sym = {str(info["id"]): name for name, info in SYMBOL_MAP.items()}

        for pos_id, pos_data in list(open_positions_dict.items()):
            raw_sym = pos_data.get("symbol")
            canonical_sym = id_to_sym.get(str(raw_sym), str(raw_sym))
            sym_info = SYMBOL_MAP.get(canonical_sym)
            if not sym_info:
                continue

            sym_id = sym_info["id"]
            scale = sym_info.get("scale", 100000.0)
            lot_size = sym_info.get("lot_size", 100000.0)
            digits = sym_info.get("digits", 5)

            spot = spots_by_id.get(sym_id)
            if not spot:
                continue
            bid_raw = spot.get("bid")
            ask_raw = spot.get("ask")
            if bid_raw is None or ask_raw is None:
                continue

            bid = float(bid_raw)
            ask = float(ask_raw)
            if bid > 10.0 and canonical_sym in ("EURUSD", "GBPUSD"):
                bid /= scale
            if ask > 10.0 and canonical_sym in ("EURUSD", "GBPUSD"):
                ask /= scale
            if bid > 100.0 and canonical_sym == "USDJPY":
                bid /= scale
            if ask > 100.0 and canonical_sym == "USDJPY":
                ask /= scale
            if bid > 10000.0 and canonical_sym == "XAUUSD":
                bid /= scale
            if ask > 10000.0 and canonical_sym == "XAUUSD":
                ask /= scale

            direction = str(pos_data.get("direction", "")).upper()
            is_long = direction in ("LONG", "BUY")
            entry_price = float(pos_data.get("entry_price", 0.0))
            if entry_price <= 0.0:
                continue

            current_price = bid if is_long else ask
            sl_distance = float(pos_data.get("sl_distance", 0.0))
            if sl_distance <= 0.0:
                sl_price = float(pos_data.get("sl_price", 0.0))
                if sl_price > 0.0:
                    sl_distance = abs(entry_price - sl_price)
                else:
                    sl_distance = entry_price * 0.002

            original_volume = float(pos_data.get("original_volume") or pos_data.get("volume_lots", 0.01))
            current_volume = float(pos_data.get("volume_lots", original_volume))
            partial_tp_hit = bool(pos_data.get("partial_tp_hit", False))
            trailing_active = bool(pos_data.get("trailing_stop_active", False))
            highest_favorable = float(pos_data.get("highest_favorable_price") or entry_price)
            atr_val = float(pos_data.get("atr_at_entry") or (sl_distance / 1.5))

            try:
                pid_arg: Any = int(pos_id)
            except (ValueError, TypeError):
                pid_arg = pos_id

            # 1. Partial TP Check (+1.5R)
            r_multiple = ((current_price - entry_price) / sl_distance) if is_long else ((entry_price - current_price) / sl_distance)

            if not partial_tp_hit and r_multiple >= 1.5:
                half_lots = max(0.01, round(original_volume * 0.5, 2))
                half_mcp_volume = int(round(half_lots * lot_size * 100))

                logger.info(
                    "Executing 1.5R Partial TP for %s pos_id=%s (R=%.2f, half_lots=%.2f)",
                    canonical_sym, pos_id, r_multiple, half_lots
                )
                if hasattr(self.broker, "close_position") and callable(self.broker.close_position):
                    try:
                        self.broker.close_position(pid_arg, volume=half_mcp_volume)
                    except Exception as e:
                        logger.error("Failed to execute partial close on broker for pos %s: %s", pos_id, e)

                be_sl = round(entry_price, digits)
                if hasattr(self.broker, "amend_position") and callable(self.broker.amend_position):
                    try:
                        self.broker.amend_position(pid_arg, stop_loss=be_sl)
                    except Exception as e:
                        logger.error("Failed to amend SL to Break-Even for pos %s: %s", pos_id, e)

                pos_data["partial_tp_hit"] = True
                pos_data["break_even_set"] = True
                pos_data["trailing_stop_active"] = True
                pos_data["sl_price"] = be_sl
                pos_data["volume_lots"] = max(0.01, round(current_volume - half_lots, 2))
                pos_data["highest_favorable_price"] = current_price
                self.state_mgr.save_state()

                self.evidence_collector.record_runtime_event(
                    "PARTIAL_TP_EXECUTED",
                    symbol=canonical_sym,
                    position_id=str(pos_id),
                    status="EXECUTED",
                    payload={
                        "r_multiple": round(r_multiple, 2),
                        "closed_volume_lots": half_lots,
                        "remaining_volume_lots": pos_data["volume_lots"],
                        "break_even_sl": be_sl,
                        "spot_price": current_price,
                    },
                )

            # 2. Trailing ATR Stop Check (for runner)
            elif trailing_active:
                trail_distance = atr_val * 1.5
                current_sl = float(pos_data.get("sl_price", entry_price))

                if is_long:
                    if current_price > highest_favorable:
                        highest_favorable = current_price
                        pos_data["highest_favorable_price"] = highest_favorable

                    new_sl = round(highest_favorable - trail_distance, digits)
                    if new_sl > current_sl and new_sl >= entry_price:
                        logger.info(
                            "Ratchet Trailing SL up for LONG %s pos_id=%s: %.5f -> %.5f",
                            canonical_sym, pos_id, current_sl, new_sl
                        )
                        if hasattr(self.broker, "amend_position") and callable(self.broker.amend_position):
                            try:
                                self.broker.amend_position(pid_arg, stop_loss=new_sl)
                            except Exception as e:
                                logger.error("Failed to amend trailing SL for pos %s: %s", pos_id, e)

                        pos_data["sl_price"] = new_sl
                        self.state_mgr.save_state()
                        self.evidence_collector.record_runtime_event(
                            "TRAILING_STOP_UPDATED",
                            symbol=canonical_sym,
                            position_id=str(pos_id),
                            status="AMENDED",
                            payload={
                                "new_sl": new_sl,
                                "previous_sl": current_sl,
                                "highest_price": highest_favorable,
                                "atr": atr_val,
                            },
                        )
                else: # SHORT
                    if highest_favorable <= 0.0 or current_price < highest_favorable:
                        highest_favorable = current_price
                        pos_data["highest_favorable_price"] = highest_favorable

                    new_sl = round(highest_favorable + trail_distance, digits)
                    if (current_sl <= 0.0 or new_sl < current_sl) and new_sl <= entry_price:
                        logger.info(
                            "Ratchet Trailing SL down for SHORT %s pos_id=%s: %.5f -> %.5f",
                            canonical_sym, pos_id, current_sl, new_sl
                        )
                        if hasattr(self.broker, "amend_position") and callable(self.broker.amend_position):
                            try:
                                self.broker.amend_position(pid_arg, stop_loss=new_sl)
                            except Exception as e:
                                logger.error("Failed to amend trailing SL for pos %s: %s", pos_id, e)

                        pos_data["sl_price"] = new_sl
                        self.state_mgr.save_state()
                        self.evidence_collector.record_runtime_event(
                            "TRAILING_STOP_UPDATED",
                            symbol=canonical_sym,
                            position_id=str(pos_id),
                            status="AMENDED",
                            payload={
                                "new_sl": new_sl,
                                "previous_sl": current_sl,
                                "lowest_price": highest_favorable,
                                "atr": atr_val,
                            },
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
            self.evidence_collector.record_reconciliation(recon)
            for cid in recon.get("closed_detected", []):
                self.evidence_collector.record_runtime_event(
                    event_type="POSITION_CLOSED",
                    position_id=str(cid),
                    status="CLOSED",
                    reason="RECONCILIATION_EXTERNAL_CLOSE",
                )
                self.evidence_collector.update_trade_exit(
                    position_id=str(cid),
                    exit_price=0.0,
                    exit_time=now_utc.isoformat(),
                    close_reason="CLOSED_EXTERNAL",
                    gross_pnl=0.0,
                    net_pnl=0.0,
                )
            for oid in recon.get("orphans_discovered", []):
                self.evidence_collector.record_runtime_event(
                    event_type="ORPHAN_POSITION_DISCOVERED",
                    position_id=str(oid),
                    status="DISCOVERED",
                )
        except Exception as e:
            logger.error("Broker query failed: %s", e)
            broker_connected = False
            latency_ms = 0.0
            self.monitor.record_exception()
            self.evidence_collector.record_runtime_event(
                "BROKER_DISCONNECTED",
                status="FAILED",
                error_message=str(e),
            )

        # 1.1 Convex Asymmetric Exit Engine: Manage open positions (Partial TP & Trailing Stop)
        if broker_connected and self.state_mgr.state.open_positions:
            try:
                self.manage_open_positions(broker_positions, now=now_utc)
            except Exception as e:
                logger.error("Error managing open positions: %s", e)

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
            if did_reset and prev_reset_str:
                self.evidence_collector.generate_daily_summary(prev_reset_str[:10])
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

        id_to_sym = {str(info["id"]): name for name, info in SYMBOL_MAP.items()}
        open_symbols = set(self.state_mgr.state.open_positions.keys())
        for p in self.state_mgr.state.open_positions.values():
            sym = p.get("symbol") if isinstance(p, dict) else getattr(p, "symbol", None)
            if sym:
                open_symbols.add(str(sym))
                if str(sym) in id_to_sym:
                    open_symbols.add(id_to_sym[str(sym)])

        total_open = len(self.state_mgr.state.open_positions)

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
                if symbol == "XAUUSD":
                    continue

            if symbol == "XAUUSD" and len(h1_bars) < 51:
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
                "h1_bars": len(h1_bars),
                "latest_closed_bar": m5_bars[0].timestamp.isoformat(),
            }))
            self.evidence_collector.record_runtime_event(
                "MARKET_DATA",
                symbol=symbol,
                status="ACQUIRED",
                payload={
                    "m5_bars": len(m5_bars),
                    "h1_bars": len(h1_bars),
                    "latest_closed_bar": m5_bars[0].timestamp.isoformat(),
                },
            )

            # 3.2 Strategy Signal Generation
            sig: Optional[Signal] = None
            if symbol == "XAUUSD":
                sig = xau_mean_reversion.evaluate(m5_bars, h1_bars, now=now_utc)
            else:
                try:
                    sig = forex_trend_breakout.evaluate(m5_bars, now=now_utc, h1_bars=h1_bars)
                except TypeError:
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
            self.evidence_collector.record_runtime_event(
                "STRATEGY_SIGNAL",
                symbol=symbol,
                direction=sig.direction.value,
                strategy_version=sig.strategy_id,
                status="SIGNAL_GENERATED",
                payload={
                    "price": sig.price,
                    "indicators": sig.indicators,
                },
            )

            # 3.3 AI Advisory Layer
            try:
                ctx = AIContextBuilder.build(
                    symbol=symbol,
                    timeframe=Timeframe.M5,
                    m5_bars=m5_bars,
                    h1_bars=h1_bars,
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
            self.evidence_collector.record_runtime_event(
                "AI_DECISION",
                symbol=symbol,
                direction=proposal.direction.value,
                status="PROPOSAL_GENERATED",
                payload={
                    "decision": proposal.decision.value,
                    "confidence": proposal.confidence,
                    "scenario": proposal.scenario if isinstance(proposal.scenario, str) else getattr(proposal.scenario, "value", str(proposal.scenario)),
                },
            )

            # 3.4 Deterministic Gatekeeper
            enforce_session = os.environ.get("ENFORCE_SESSION_FILTER", "true").lower() == "true"
            val_res = DeterministicGate.validate(
                proposal=proposal,
                context=ctx,
                max_daily_loss_pct=self.risk_engine.config.max_daily_loss_pct,
                max_open_positions=self.risk_engine.config.max_open_positions,
                now=now_utc,
                enforce_session_filter=enforce_session,
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
                dec_rec = self.trace_service.log_decision(
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
                self.evidence_collector.record_decision(asdict(dec_rec))
                self.evidence_collector.record_runtime_event(
                    "DETERMINISTIC_GATE",
                    symbol=symbol,
                    status="REJECTED",
                    reason=reject_reason,
                )
                continue

            logger.info(json.dumps({
                "event": "GATE",
                "symbol": symbol,
                "status": "APPROVED",
                "reason": val_res.reason,
            }))
            self.evidence_collector.record_runtime_event(
                "DETERMINISTIC_GATE",
                symbol=symbol,
                status="APPROVED",
                reason=val_res.reason,
            )

            # 3.5 Risk Engine Evaluation & Pre-Trade Spread Guard
            current_spread_pips: Optional[float] = None
            try:
                spot_prices = self.broker.get_spot_prices([sym_info["id"]])
                if spot_prices and isinstance(spot_prices, list):
                    spot = spot_prices[0]
                    bid = spot.get("bid")
                    ask = spot.get("ask")
                    if bid is not None and ask is not None:
                        spread_raw = float(ask) - float(bid)
                        if spread_raw > 1.0 and symbol in ("EURUSD", "GBPUSD"):
                            spread_raw = spread_raw / scale
                        elif spread_raw > 10.0 and symbol == "USDJPY":
                            spread_raw = spread_raw / scale
                        elif spread_raw > 100.0 and symbol == "XAUUSD":
                            spread_raw = spread_raw / scale

                        if symbol in ("EURUSD", "GBPUSD"):
                            current_spread_pips = spread_raw / 0.0001
                        elif symbol in ("USDJPY", "XAUUSD"):
                            current_spread_pips = spread_raw / 0.01
            except Exception as e:
                logger.debug("Failed to query live spot prices for %s spread check: %s", symbol, e)

            atr_val = ctx.atr
            # Determine H1 alignment for dynamic sizing boost
            h1_regime = ctx.scenario_state.get("h1_regime") or sig.indicators.get("h1_regime")
            if not h1_regime and symbol == "XAUUSD":
                h1_regime = "BULLISH" if "bullish" in sig.reason.get("h1_bias", "").lower() else "BEARISH"
            h1_aligned = (
                (sig.direction == Direction.LONG and h1_regime in ("BULLISH", "UP", "TREND_UP"))
                or (sig.direction == Direction.SHORT and h1_regime in ("BEARISH", "DOWN", "TREND_DOWN"))
            )

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
                open_positions=[_normalize_position_dict(p) for p in self.state_mgr.state.open_positions.values()],
                data_timestamp=candle_close_time(m5_bars[0].timestamp, Timeframe.M5),
                now=now_utc,
                lot_size_units=sym_info.get("lot_size", 100000.0),
                current_spread_pips=current_spread_pips,
                max_spread_pips=sym_info.get("max_spread"),
                confidence=proposal.confidence if proposal else None,
                h1_aligned=h1_aligned,
            )

            if not risk_decision.approved:
                logger.info(json.dumps({
                    "event": "RISK",
                    "symbol": symbol,
                    "status": "REJECTED",
                    "reason": risk_decision.reason,
                    "block_reason": risk_decision.block_reason,
                    "defense_level": risk_decision.defense_level,
                }))
                dec_rec = self.trace_service.log_decision(
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
                        "defense_level": risk_decision.defense_level,
                    },
                    execution_result={"status": "REJECTED_BY_RISK", "reason": risk_decision.reason},
                )
                self.evidence_collector.record_decision(asdict(dec_rec))
                self.evidence_collector.record_runtime_event(
                    "RISK_DECISION",
                    symbol=symbol,
                    status="REJECTED",
                    reason=risk_decision.reason,
                    payload={
                        "block_reason": risk_decision.block_reason,
                        "defense_level": risk_decision.defense_level,
                    },
                )
                continue

            logger.info(json.dumps({
                "event": "RISK",
                "symbol": symbol,
                "status": "APPROVED",
                "allocated_volume": risk_decision.adjusted_volume,
                "defense_level": risk_decision.defense_level,
            }))
            self.evidence_collector.record_runtime_event(
                "RISK_DECISION",
                symbol=symbol,
                status="APPROVED",
                payload={
                    "allocated_volume": risk_decision.adjusted_volume,
                    "defense_level": risk_decision.defense_level,
                },
            )

            # 3.6 Broker Order Submission (cTrader Remote MCP)
            lots = risk_decision.adjusted_volume
            lot_size = sym_info.get("lot_size", 100000.0)
            # Volume in 1/100 base-asset units: volume = lots * lotSize * 100
            mcp_volume = int(round(lots * lot_size * 100))

            sl_dist = max(atr_val * self.risk_engine.config.atr_multiplier_sl, 1e-5)
            tp_dist = sl_dist * self.risk_engine.config.rr_ratio

            digits = sym_info.get("digits", 5)
            sl_dist_rounded = round(sl_dist, digits)
            tp_dist_rounded = round(tp_dist, digits)
            # In cTrader MCP, relative SL/TP are in 10^-5 scale (fixed 100,000 points multiplier)
            relative_sl = max(1, int(round(sl_dist_rounded * 100000)))
            relative_tp = max(1, int(round(tp_dist_rounded * 100000)))

            trade_side = "BUY" if sig.direction == Direction.LONG else "SELL"
            trace_id = str(uuid.uuid4())
            git_sha = get_git_commit_sha()[:7]
            order_comment = f"Bot_{symbol}_v{SYSTEM_VERSION}_{git_sha}"

            order_result: dict[str, Any] = {}
            try:
                order_result = self.broker.create_market_order(
                    symbol_id=sym_info["id"],
                    trade_side=trade_side,
                    volume=mcp_volume,
                    relative_sl=relative_sl,
                    relative_tp=relative_tp,
                    comment=order_comment,
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

            fill_price = float(order_result.get("executionPrice", order_result.get("order", {}).get("executionPrice", sig.price)))
            slippage = abs(fill_price - sig.price)
            if symbol in ("EURUSD", "GBPUSD"):
                slippage_pips = round(slippage / 0.0001, 2)
            elif symbol in ("USDJPY", "XAUUSD"):
                slippage_pips = round(slippage / 0.01, 2)
            else:
                slippage_pips = 0.0
            order_result["slippage_pips"] = slippage_pips

            # 3.7 Decision Trace Logging
            dec_rec = self.trace_service.log_decision(
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
                    "defense_level": risk_decision.defense_level,
                },
                execution_result=order_result,
            )
            self.evidence_collector.record_decision(asdict(dec_rec))

            order_id = str(order_result.get("orderId", order_result.get("order", {}).get("orderId", "")))
            position_id = str(order_result.get("positionId", order_result.get("position", {}).get("positionId", "")))

            self.evidence_collector.record_runtime_event(
                event_type="ORDER_SUBMITTED",
                symbol=symbol,
                direction=sig.direction.value,
                strategy_version=f"{sig.strategy_id}_v{SYSTEM_VERSION}",
                bot_git_sha=get_git_commit_sha(),
                order_id=order_id or None,
                position_id=position_id or None,
                trade_id=trace_id,
                status="SUBMITTED" if order_result.get("status") != "FAILED" else "FAILED",
                payload={
                    "trade_side": trade_side,
                    "volume_lots": lots,
                    "mcp_volume": mcp_volume,
                    "relative_sl_points": relative_sl,
                    "relative_tp_points": relative_tp,
                    "slippage_pips": slippage_pips,
                    "result": order_result,
                },
            )

            trade_rec = TradeRecord(
                trade_id=trace_id,
                symbol=symbol,
                direction=sig.direction.value,
                signal_time_utc=sig.timestamp.isoformat() if hasattr(sig, "timestamp") and sig.timestamp else now_utc.isoformat(),
                order_time_utc=now_utc.isoformat(),
                entry_time_utc=now_utc.isoformat(),
                entry_price=fill_price,
                volume=lots,
                stop_loss=round(sig.price - (sl_dist if sig.direction == Direction.LONG else -sl_dist), digits),
                take_profit=round(sig.price + (tp_dist if sig.direction == Direction.LONG else -tp_dist), digits),
                risk_amount=risk_decision.risk_amount if hasattr(risk_decision, "risk_amount") else None,
                order_id=order_id or None,
                position_id=position_id or None,
                strategy_version=f"{sig.strategy_id}_v{SYSTEM_VERSION}",
                bot_git_sha=get_git_commit_sha(),
                ai_decision=proposal.decision.value if proposal else None,
                ai_confidence=proposal.confidence if proposal else None,
                gate_result=val_res.reason if val_res else None,
                risk_result=risk_decision.reason if risk_decision else None,
                source="BOT_EVENT",
            )
            self.evidence_collector.record_trade(trade_rec)

            # Record active position state locally for Asymmetric Exit Engine tracking
            if position_id and position_id not in ("", "None") and order_result.get("status") != "FAILED":
                sl_target = round(sig.price - (sl_dist if sig.direction == Direction.LONG else -sl_dist), digits)
                tp_target = round(sig.price + (tp_dist if sig.direction == Direction.LONG else -tp_dist), digits)
                pos_state = PositionState(
                    position_id=position_id,
                    symbol=symbol,
                    direction=sig.direction.value,
                    volume_lots=lots,
                    entry_price=fill_price,
                    sl_price=sl_target,
                    tp_price=tp_target,
                    open_time=now_utc.isoformat(),
                    status="OPEN",
                    original_volume=lots,
                    partial_tp_hit=False,
                    break_even_set=False,
                    trailing_stop_active=False,
                    highest_favorable_price=fill_price,
                    atr_at_entry=atr_val,
                    sl_distance=sl_dist,
                )
                self.state_mgr.record_new_position(pos_state)

            # 3.8 State Update & Reconciliation
            try:
                updated_positions = self.broker.get_positions()
                self.state_mgr.reconcile_with_broker(updated_positions, now=now_utc)
            except Exception as e:
                logger.error("Post-order position reconciliation error: %s", e)

        # Update monitor telemetry with Google Drive uploader metrics
        self.monitor.telemetry.metadata["google_drive"] = self.evidence_uploader.get_telemetry()
        self.evidence_collector.record_health(asdict(self.monitor.telemetry))

    async def run_forever(self, cycle_interval_seconds: float = 5.0) -> None:
        """Main 24/7 autonomous loop."""
        await self.initialize()
        logger.info("TradingBotRunner 24/7 loop started (interval: %.1fs)", cycle_interval_seconds)

        self._uploader_task = asyncio.create_task(self.evidence_uploader.start())

        try:
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
        finally:
            logger.info("TradingBotRunner shutting down gracefully...")
            self.evidence_uploader.stop()
            if self._uploader_task:
                try:
                    await asyncio.wait_for(self._uploader_task, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
            self.evidence_collector.generate_daily_summary()
            self.evidence_collector.record_runtime_event("BOT_SHUTDOWN", status="SUCCESS")
            self.monitor.shutdown()

    def stop(self) -> None:
        self.shutdown_event.set()
        self.evidence_uploader.stop()
