"""
High-Fidelity Simulated Paper Broker
====================================
Institutional Execution Simulation Standard for Gate 23
Implements realistic trading dynamics:
- Market Orders with dynamic slippage (0.2–0.5 pips) and session-aware spread.
- Stop Loss (SL), Take Profit (TP), and Time-Based Exit (4 bars / 60 minutes).
- Commission ($6.00/lot), Rollover Swap, and Margin Accounting.
- Duplicate Order Prevention & Position Reconciliation.
- Strictly operates in simulation mode (LIVE_TRADING = false).
"""

import uuid
import math
import random
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timezone

from ai_forex_bot.execution.broker_base import BaseBroker
from ai_forex_bot.config.settings import settings, SymbolConfig
from ai_forex_bot.market.sessions.session import MarketSession


class PaperBroker(BaseBroker):
    def __init__(
        self,
        initial_balance: float = 1000.0,
        leverage: float = 100.0,
        time_exit_bars: int = 4,
        random_seed: Optional[int] = None,
        partial_tp_pips: Optional[float] = None,
        buffer_pips: float = 1.0
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.equity = initial_balance
        self.free_margin = initial_balance
        self.used_margin = 0.0
        self.leverage = leverage
        self.time_exit_bars = time_exit_bars
        self.partial_tp_pips = partial_tp_pips
        self.buffer_pips = buffer_pips

        self.rng = random.Random(random_seed) if random_seed is not None else random.Random()
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.closed_trades: List[Dict[str, Any]] = []
        self.quotes: Dict[str, Dict[str, Any]] = {}
        self.order_history: List[Dict[str, Any]] = []
        self._processed_order_keys: Set[str] = set()

        self.connected = False
        self.last_bar_epoch: Optional[int] = None

    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self):
        self.connected = False

    def health_check(self) -> Dict[str, Any]:
        return {
            "status": "HEALTHY",
            "connected": self.connected,
            "broker": "PaperBroker",
            "open_positions": len(self.positions),
            "closed_trades": len(self.closed_trades),
            "equity": round(self.equity, 2),
            "balance": round(self.balance, 2)
        }

    def _get_dynamic_spread_pips(self, symbol: str, epoch: int) -> float:
        """Calculates realistic spread depending on market session and liquidity."""
        sym_cfg = settings.get_symbol_config(symbol)
        typical = sym_cfg.typical_spread_pips if sym_cfg else 1.2

        if sym_cfg and sym_cfg.asset_class == "synthetic_index":
            # Synthetic indices on Deriv run 24/7/365 with constant liquidity and volatility.
            # They DO NOT close on weekends and DO NOT have London/NY session overlap shifts or weekend 2.5x widening!
            return round(typical * self.rng.uniform(0.95, 1.05), 4)

        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        hour = dt.hour
        weekday = dt.weekday()

        # Weekend / off-market spread widening
        if weekday >= 5 or (weekday == 4 and hour >= 21) or (weekday == 6 and hour < 21):
            return typical * 2.5

        # Session-aware spread adjustments
        if 13 <= hour < 16:
            # London / NY overlap (Peak liquidity)
            return max(0.8, typical * 0.85)
        elif 8 <= hour < 17:
            # London / European core
            return typical
        elif 17 <= hour < 21:
            # Late NY session
            return typical * 1.1
        elif 0 <= hour < 8:
            # Asian session (Lower liquidity)
            return typical * 1.4
        else:
            # Rollover hour (21:00 - 22:00 UTC)
            return typical * 2.0

    def _get_dynamic_slippage_pips(self, symbol: str) -> float:
        """Generates realistic dynamic execution slippage between 0.2 and 0.5 pips."""
        # Bounded between 0.20 and 0.50 pips
        return round(self.rng.uniform(0.20, 0.50), 3)

    def set_quote(self, symbol: str, bid: float, ask: float, timestamp: int):
        sym_cfg = settings.get_symbol_config(symbol)
        pip_size = sym_cfg.pip_size if sym_cfg else 0.0001
        spread_pips = (ask - bid) / pip_size
        self.quotes[symbol] = {
            "bid": bid,
            "ask": ask,
            "spread_pips": spread_pips,
            "timestamp": timestamp
        }
        self.last_bar_epoch = timestamp
        self._update_positions_and_margins()

    def update_quote_from_bar(self, symbol: str, bar: Dict[str, Any]):
        """Updates internal quote using bar close with dynamic session spread."""
        close = float(bar["close"])
        epoch = int(bar["epoch"])
        sym_cfg = settings.get_symbol_config(symbol)
        pip_size = sym_cfg.pip_size if sym_cfg else 0.0001

        spread_pips = self._get_dynamic_spread_pips(symbol, epoch)
        half_spread = (spread_pips * pip_size) / 2.0
        bid = close - half_spread
        ask = close + half_spread

        self.set_quote(symbol, bid=bid, ask=ask, timestamp=epoch)

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        if symbol not in self.quotes:
            raise KeyError(f"No quote available for {symbol}")
        return self.quotes[symbol]

    def get_account_state(self) -> Dict[str, float]:
        return {
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "free_margin": round(self.free_margin, 2),
            "used_margin": round(self.used_margin, 2),
            "initial_balance": round(self.initial_balance, 2)
        }

    def place_order(
        self,
        symbol: str,
        direction: str,
        lot_size: float,
        sl_price: float,
        tp_price: float,
        order_type: str = "MARKET",
        idempotency_key: Optional[str] = None,
        partial_tp_price: Optional[float] = None,
        partial_tp_pips: Optional[float] = None,
        buffer_pips: Optional[float] = None,
        atr: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Places a realistic simulated market order with duplicate prevention and cost simulation.
        """
        quote = self.get_quote(symbol)
        epoch = int(quote["timestamp"])
        sym_cfg = settings.get_symbol_config(symbol)
        pip_size = sym_cfg.pip_size if sym_cfg else 0.0001

        # 1. Duplicate Order Prevention Check
        dedup_key = idempotency_key or f"{symbol}_{direction}_{epoch}"
        if dedup_key in self._processed_order_keys:
            return {
                "status": "REJECTED",
                "reason": "DUPLICATE_ORDER_PREVENTED",
                "message": f"Order with key '{dedup_key}' was already submitted for this bar."
            }

        # Check existing open position in same symbol & direction
        for pos in self.positions.values():
            if pos["symbol"] == symbol and pos["direction"] == direction:
                return {
                    "status": "REJECTED",
                    "reason": "CONCURRENT_SAME_DIRECTION_EXISTS",
                    "message": f"Position in {symbol} ({direction}) already open."
                }

        # 2. Dynamic Slippage & Fill Price Calculation
        slippage_pips = self._get_dynamic_slippage_pips(symbol)
        slip_delta = slippage_pips * pip_size

        if direction == "BUY":
            # BUY fills at Ask + slippage (adverse execution)
            fill_price = quote["ask"] + slip_delta
        else:
            # SELL fills at Bid - slippage (adverse execution)
            fill_price = quote["bid"] - slip_delta

        # 3. Commission Deducted at Entry ($6.00 / lot standard institutional round-turn, 0.0 for synthetic indices)
        comm_per_lot = sym_cfg.commission_per_lot_usd if sym_cfg else 6.0
        comm_usd = comm_per_lot * lot_size

        # 4. Margin Requirement Check: (Lot * ContractSize * FillPrice) / Leverage
        sym_lot_size = sym_cfg.lot_size if sym_cfg else 100000.0
        req_margin = (lot_size * sym_lot_size * fill_price) / self.leverage
        if self.free_margin < req_margin:
            return {
                "status": "REJECTED",
                "reason": "INSUFFICIENT_MARGIN",
                "message": f"Insufficient margin: required ${req_margin:.2f}, free ${self.free_margin:.2f}."
            }

        self.balance -= comm_usd

        # Resolve partial TP price if partial_tp_pips given or broker default
        resolved_partial_pips = partial_tp_pips if partial_tp_pips is not None else self.partial_tp_pips
        resolved_partial_price = partial_tp_price
        if resolved_partial_price is None and resolved_partial_pips is not None:
            resolved_partial_price = (
                fill_price + (resolved_partial_pips * pip_size)
                if direction == "BUY"
                else fill_price - (resolved_partial_pips * pip_size)
            )

        pos_id = f"paper_{uuid.uuid4().hex[:8]}"
        position = {
            "position_id": pos_id,
            "symbol": symbol,
            "direction": direction,
            "lot_size": lot_size,
            "entry_price": fill_price,
            "entry_epoch": epoch,
            "entry_dt": datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(),
            "sl_price": sl_price,
            "tp_price": tp_price,
            "partial_tp_price": resolved_partial_price,
            "partial_tp_pips": resolved_partial_pips,
            "buffer_pips": buffer_pips if buffer_pips is not None else self.buffer_pips,
            "atr": atr,
            "partial_tp_hit": False,
            "breakeven_locked": False,
            "slippage_pips": slippage_pips,
            "commission_usd": comm_usd,
            "swap_usd": 0.0,
            "unrealized_pnl": 0.0,
            "bars_held": 0,
            "max_favorable_excursion_pips": 0.0,
            "max_adverse_excursion_pips": 0.0
        }

        self.positions[pos_id] = position
        self._processed_order_keys.add(dedup_key)
        self._update_positions_and_margins()

        order_record = {
            "order_id": pos_id,
            "status": "FILLED",
            "symbol": symbol,
            "direction": direction,
            "lot_size": lot_size,
            "fill_price": fill_price,
            "slippage_pips": slippage_pips,
            "commission_usd": comm_usd,
            "epoch": epoch
        }
        self.order_history.append(order_record)

        return order_record

    def close_position(
        self,
        position_id: str,
        exit_price: Optional[float] = None,
        exit_reason: str = "MANUAL_CLOSE",
        exit_epoch: Optional[int] = None
    ) -> Dict[str, Any]:
        """Closes an open position and calculates realized PnL, swap, and execution metrics."""
        if position_id not in self.positions:
            return {"status": "ERROR", "message": f"Position {position_id} not found."}

        pos = self.positions.pop(position_id)
        sym = pos["symbol"]
        sym_cfg = settings.get_symbol_config(sym)
        pip_size = sym_cfg.pip_size if sym_cfg else 0.0001
        pip_value = sym_cfg.pip_value_usd if sym_cfg else 10.0

        quote = self.get_quote(sym)
        curr_epoch = exit_epoch or int(quote["timestamp"])

        if exit_price is None:
            # Dynamic slippage on market exit
            slippage_pips = self._get_dynamic_slippage_pips(sym)
            slip_delta = slippage_pips * pip_size
            if pos["direction"] == "BUY":
                exit_price = quote["bid"] - slip_delta
            else:
                exit_price = quote["ask"] + slip_delta

        # Calculate gross price change
        if pos["direction"] == "BUY":
            pips_gain = (exit_price - pos["entry_price"]) / pip_size
        else:
            pips_gain = (pos["entry_price"] - exit_price) / pip_size

        gross_pnl = pips_gain * pip_value * pos["lot_size"]
        total_swap = pos["swap_usd"]
        net_pnl = gross_pnl + total_swap  # Commission was already deducted at entry

        self.balance += gross_pnl + total_swap
        self._update_positions_and_margins()

        trade_record = {
            "position_id": position_id,
            "symbol": sym,
            "direction": pos["direction"],
            "lot_size": pos["lot_size"],
            "entry_price": round(pos["entry_price"], 5),
            "exit_price": round(exit_price, 5),
            "entry_epoch": pos["entry_epoch"],
            "exit_epoch": curr_epoch,
            "entry_dt": pos["entry_dt"],
            "exit_dt": datetime.fromtimestamp(curr_epoch, tz=timezone.utc).isoformat(),
            "pips_gain": round(pips_gain, 2),
            "gross_pnl": round(gross_pnl, 2),
            "commission_usd": round(pos["commission_usd"], 2),
            "swap_usd": round(total_swap, 2),
            "net_pnl": round(net_pnl, 2),
            "slippage_pips": round(pos["slippage_pips"], 3),
            "bars_held": pos["bars_held"],
            "exit_reason": exit_reason,
            "mae_pips": round(pos["max_adverse_excursion_pips"], 2),
            "mfe_pips": round(pos["max_favorable_excursion_pips"], 2)
        }
        self.closed_trades.append(trade_record)

        return {
            "status": "CLOSED",
            "position_id": position_id,
            "trade": trade_record,
            "realized_pnl": round(net_pnl, 2)
        }

    def partial_close_position(
        self,
        position_id: str,
        fraction: float = 0.5,
        exit_price: Optional[float] = None,
        exit_reason: str = "PARTIAL_TP",
        exit_epoch: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Partially closes an open position:
        - Reduces position lot_size by fraction (e.g., 50%).
        - Realizes gross & net PnL proportionally into self.balance.
        - Records partial closed trade into self.closed_trades with exit_reason (e.g. PARTIAL_TP_50%).
        - Updates position lot_size and recalculates margin.
        """
        if position_id not in self.positions:
            return {"status": "ERROR", "message": f"Position {position_id} not found."}

        pos = self.positions[position_id]
        sym = pos["symbol"]
        sym_cfg = settings.get_symbol_config(sym)
        pip_size = sym_cfg.pip_size if sym_cfg else 0.0001
        pip_value = sym_cfg.pip_value_usd if sym_cfg else 10.0

        quote = self.get_quote(sym)
        curr_epoch = exit_epoch or int(quote["timestamp"])

        if exit_price is None:
            # Dynamic slippage on market exit
            slippage_pips = self._get_dynamic_slippage_pips(sym)
            slip_delta = slippage_pips * pip_size
            if pos["direction"] == "BUY":
                exit_price = quote["bid"] - slip_delta
            else:
                exit_price = quote["ask"] + slip_delta

        # Calculate gross price change
        if pos["direction"] == "BUY":
            pips_gain = (exit_price - pos["entry_price"]) / pip_size
        else:
            pips_gain = (pos["entry_price"] - exit_price) / pip_size

        fraction = max(0.0, min(1.0, fraction))
        closed_lot = round(pos["lot_size"] * fraction, 4)
        remaining_lot = round(pos["lot_size"] - closed_lot, 4)

        gross_pnl = pips_gain * pip_value * closed_lot
        swap_portion = pos.get("swap_usd", 0.0) * fraction
        pos["swap_usd"] = pos.get("swap_usd", 0.0) - swap_portion

        comm_portion = pos.get("commission_usd", 0.0) * fraction
        pos["commission_usd"] = pos.get("commission_usd", 0.0) - comm_portion

        net_pnl = gross_pnl + swap_portion

        self.balance += gross_pnl + swap_portion

        if exit_reason == "PARTIAL_TP":
            final_exit_reason = f"PARTIAL_TP_{int(fraction * 100)}%"
        else:
            final_exit_reason = exit_reason

        trade_record = {
            "position_id": position_id,
            "symbol": sym,
            "direction": pos["direction"],
            "lot_size": round(closed_lot, 4),
            "entry_price": round(pos["entry_price"], 5),
            "exit_price": round(exit_price, 5),
            "entry_epoch": pos["entry_epoch"],
            "exit_epoch": curr_epoch,
            "entry_dt": pos["entry_dt"],
            "exit_dt": datetime.fromtimestamp(curr_epoch, tz=timezone.utc).isoformat(),
            "pips_gain": round(pips_gain, 2),
            "gross_pnl": round(gross_pnl, 2),
            "commission_usd": round(comm_portion, 2),
            "swap_usd": round(swap_portion, 2),
            "net_pnl": round(net_pnl, 2),
            "slippage_pips": round(pos.get("slippage_pips", 0.0), 3),
            "bars_held": pos["bars_held"],
            "exit_reason": final_exit_reason,
            "mae_pips": round(pos["max_adverse_excursion_pips"], 2),
            "mfe_pips": round(pos["max_favorable_excursion_pips"], 2),
            "is_partial": True
        }
        self.closed_trades.append(trade_record)

        if remaining_lot <= 0:
            self.positions.pop(position_id, None)
        else:
            pos["lot_size"] = remaining_lot

        self._update_positions_and_margins()

        return {
            "status": "PARTIALLY_CLOSED" if remaining_lot > 0 else "CLOSED",
            "position_id": position_id,
            "trade": trade_record,
            "realized_pnl": round(net_pnl, 2),
            "remaining_lot_size": remaining_lot
        }

    def modify_position(
        self,
        position_id: str,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None
    ) -> bool:
        """Updates sl_price and/or tp_price of an open position."""
        if position_id not in self.positions:
            return False

        pos = self.positions[position_id]
        if sl_price is not None:
            pos["sl_price"] = sl_price
        if tp_price is not None:
            pos["tp_price"] = tp_price
        return True

    def on_bar(self, bar: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Bar-by-bar lifecycle processor:
        - Evaluates High and Low for SL and TP triggers.
        - Enforces Double-Barrel Partial TP (+50% close) and Dynamic Breakeven Lock.
        - Enforces Time-Based Exit (4 bars / 60 minutes).
        - Applies Rollover Financing (Swap).
        - Returns list of trades closed on this bar.
        """
        symbol = bar.get("symbol", "frxEURUSD")
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        epoch = int(bar["epoch"])

        self.update_quote_from_bar(symbol, bar)
        sym_cfg = settings.get_symbol_config(symbol)
        pip_size = sym_cfg.pip_size if sym_cfg else 0.0001
        pip_value = sym_cfg.pip_value_usd if sym_cfg else 10.0

        closed_on_bar = []
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)

        # Check all open positions
        open_pos_ids = list(self.positions.keys())
        for pid in open_pos_ids:
            if pid not in self.positions:
                continue

            pos = self.positions[pid]
            if pos["symbol"] != symbol:
                continue

            pos["bars_held"] += 1

            # Rollover Swap Check (Apply at 21:00 UTC, not applicable to synthetic indices)
            if dt.hour == 21 and dt.minute == 0:
                is_synthetic = sym_cfg and sym_cfg.asset_class == "synthetic_index"
                if not is_synthetic and sym_cfg:
                    swap_points = sym_cfg.swap_long_points if pos["direction"] == "BUY" else sym_cfg.swap_short_points
                    # 1 point = 0.1 pip
                    swap_usd = (swap_points * 0.1) * pip_value * pos["lot_size"]
                    pos["swap_usd"] += swap_usd

            # Track MFE and MAE
            if pos["direction"] == "BUY":
                favorable = (high - pos["entry_price"]) / pip_size
                adverse = (pos["entry_price"] - low) / pip_size
            else:
                favorable = (pos["entry_price"] - low) / pip_size
                adverse = (high - pos["entry_price"]) / pip_size

            pos["max_favorable_excursion_pips"] = max(pos["max_favorable_excursion_pips"], favorable)
            pos["max_adverse_excursion_pips"] = max(pos["max_adverse_excursion_pips"], adverse)

            # 1. Check Hard Stop Loss
            sl_triggered = False
            sl_fill_price = None
            if pos["direction"] == "BUY" and low <= pos["sl_price"]:
                sl_triggered = True
                sl_fill_price = min(pos["sl_price"], close)
            elif pos["direction"] == "SELL" and high >= pos["sl_price"]:
                sl_triggered = True
                sl_fill_price = max(pos["sl_price"], close)

            if sl_triggered:
                exit_reason = "BREAKEVEN_SL" if pos.get("breakeven_locked", False) else "STOP_LOSS"
                res = self.close_position(
                    position_id=pid,
                    exit_price=sl_fill_price,
                    exit_reason=exit_reason,
                    exit_epoch=epoch
                )
                closed_on_bar.append(res["trade"])
                continue

            # 2. Double-Barrel Processor (Partial TP + Dynamic Breakeven Lock)
            partial_tp_target = pos.get("partial_tp_price")
            if partial_tp_target is None:
                if pos.get("partial_tp_pips") is not None:
                    p_pips = float(pos["partial_tp_pips"])
                    partial_tp_target = (
                        pos["entry_price"] + (p_pips * pip_size)
                        if pos["direction"] == "BUY"
                        else pos["entry_price"] - (p_pips * pip_size)
                    )
                elif hasattr(self, "partial_tp_pips") and self.partial_tp_pips is not None:
                    p_pips = float(self.partial_tp_pips)
                    partial_tp_target = (
                        pos["entry_price"] + (p_pips * pip_size)
                        if pos["direction"] == "BUY"
                        else pos["entry_price"] - (p_pips * pip_size)
                    )
                elif "atr" in bar and bar["atr"] is not None:
                    atr_val = float(bar["atr"])
                    partial_tp_target = (
                        pos["entry_price"] + atr_val
                        if pos["direction"] == "BUY"
                        else pos["entry_price"] - atr_val
                    )
                elif pos.get("atr") is not None:
                    atr_val = float(pos["atr"])
                    partial_tp_target = (
                        pos["entry_price"] + atr_val
                        if pos["direction"] == "BUY"
                        else pos["entry_price"] - atr_val
                    )

            if partial_tp_target is not None and not pos.get("partial_tp_hit", False):
                partial_hit = False
                if pos["direction"] == "BUY" and high >= partial_tp_target:
                    partial_hit = True
                elif pos["direction"] == "SELL" and low <= partial_tp_target:
                    partial_hit = True

                if partial_hit:
                    # Execute 50% partial close at partial TP price!
                    part_res = self.partial_close_position(
                        position_id=pid,
                        fraction=0.5,
                        exit_price=partial_tp_target,
                        exit_reason="PARTIAL_TP_50%",
                        exit_epoch=epoch
                    )
                    if part_res.get("status") in ("PARTIALLY_CLOSED", "CLOSED"):
                        closed_on_bar.append(part_res["trade"])

                    pos["partial_tp_hit"] = True

                    # Dynamic Breakeven Lock: Atomically move remaining sl_price
                    buffer_pips = float(pos.get("buffer_pips", getattr(self, "buffer_pips", 1.0)))
                    if pos["direction"] == "BUY":
                        new_sl = pos["entry_price"] + (buffer_pips * pip_size)
                    else:
                        new_sl = pos["entry_price"] - (buffer_pips * pip_size)

                    self.modify_position(pid, sl_price=new_sl)
                    pos["breakeven_locked"] = True

            # If position was fully closed (e.g. fraction=1.0 or remaining_lot=0), skip
            if pid not in self.positions:
                continue

            # 3. Check Take Profit
            tp_triggered = False
            tp_fill_price = None
            if pos["direction"] == "BUY" and high >= pos["tp_price"]:
                tp_triggered = True
                tp_fill_price = max(pos["tp_price"], close)
            elif pos["direction"] == "SELL" and low <= pos["tp_price"]:
                tp_triggered = True
                tp_fill_price = min(pos["tp_price"], close)

            if tp_triggered:
                res = self.close_position(
                    position_id=pid,
                    exit_price=tp_fill_price,
                    exit_reason="TAKE_PROFIT",
                    exit_epoch=epoch
                )
                closed_on_bar.append(res["trade"])
                continue

            # 4. Check Time-Based Exit (Default 4 bars / 60 minutes)
            if pos["bars_held"] >= self.time_exit_bars:
                res = self.close_position(
                    position_id=pid,
                    exit_price=close,
                    exit_reason="TIME_EXIT",
                    exit_epoch=epoch
                )
                closed_on_bar.append(res["trade"])
                continue

        self._update_positions_and_margins()
        return closed_on_bar


    def get_open_positions(self) -> List[Dict[str, Any]]:
        return list(self.positions.values())

    def reconcile(self) -> Dict[str, Any]:
        """Performs full reconciliation audit on positions, margin, and account balance."""
        recalculated_used_margin = 0.0
        recalculated_unrealized_pnl = 0.0

        for pos in self.positions.values():
            sym = pos["symbol"]
            sym_cfg = settings.get_symbol_config(sym)
            pip_size = sym_cfg.pip_size if sym_cfg else 0.0001
            pip_value = sym_cfg.pip_value_usd if sym_cfg else 10.0
            sym_lot_size = sym_cfg.lot_size if sym_cfg else 100000.0

            q = self.quotes.get(sym)
            if q:
                cur_price = q["bid"] if pos["direction"] == "BUY" else q["ask"]
                diff = (cur_price - pos["entry_price"]) if pos["direction"] == "BUY" else (pos["entry_price"] - cur_price)
                pnl = (diff / pip_size) * pip_value * pos["lot_size"]
                recalculated_unrealized_pnl += pnl

            # Margin: (pos["lot_size"] * sym_cfg.lot_size * pos["entry_price"]) / self.leverage
            req_margin = (pos["lot_size"] * sym_lot_size * pos["entry_price"]) / self.leverage
            recalculated_used_margin += req_margin

        equity_diff = abs(self.equity - (self.balance + recalculated_unrealized_pnl))
        margin_diff = abs(self.used_margin - recalculated_used_margin)

        is_sync = (equity_diff < 1e-4) and (margin_diff < 1e-4)

        return {
            "is_synchronized": is_sync,
            "open_position_count": len(self.positions),
            "closed_trade_count": len(self.closed_trades),
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "used_margin": round(self.used_margin, 2),
            "free_margin": round(self.free_margin, 2),
            "equity_discrepancy": round(equity_diff, 6),
            "margin_discrepancy": round(margin_diff, 6)
        }

    def _update_positions_and_margins(self):
        total_unrealized = 0.0
        total_margin = 0.0

        for pos in self.positions.values():
            sym = pos["symbol"]
            sym_cfg = settings.get_symbol_config(sym)
            pip_size = sym_cfg.pip_size if sym_cfg else 0.0001
            pip_value = sym_cfg.pip_value_usd if sym_cfg else 10.0
            sym_lot_size = sym_cfg.lot_size if sym_cfg else 100000.0

            if sym in self.quotes:
                q = self.quotes[sym]
                cur_price = q["bid"] if pos["direction"] == "BUY" else q["ask"]
                diff = (cur_price - pos["entry_price"]) if pos["direction"] == "BUY" else (pos["entry_price"] - cur_price)
                pip_diff = diff / pip_size
                pnl = pip_diff * pip_value * pos["lot_size"]
                pos["unrealized_pnl"] = pnl
                total_unrealized += pnl

            # Margin: (pos["lot_size"] * sym_cfg.lot_size * pos["entry_price"]) / self.leverage
            req_margin = (pos["lot_size"] * sym_lot_size * pos["entry_price"]) / self.leverage
            total_margin += req_margin

        self.equity = self.balance + total_unrealized
        self.used_margin = total_margin
        self.free_margin = max(0.0, self.equity - self.used_margin)
