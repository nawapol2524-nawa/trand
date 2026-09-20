"""
Deriv Real/Demo Live Execution Broker
=====================================
Direct connection to Deriv Cloud API via REST Authentication & WebSocket Gateway:
- Authenticates using Personal Access Token (PAT) + Deriv-App-ID.
- Auto-discovers Demo Account (e.g., DOT94482469) or Real Account (ROT...).
- Acquires dynamic WebSocket One-Time-Password (OTP) session token.
- Maintains a thread-safe multiplexed WebSocket connection running in background.
- Live streaming balance, equity, and tick subscriptions.
- Executes Multiplier contracts (MULTUP / MULTDOWN) for 24/7 Synthetic Indices
  (R_75, R_25, R_10, etc.) with real Deriv execution and instant settlement.
- Implements full BaseBroker interface with automatic fallback handling.
"""

import os
import json
import time
import uuid
import asyncio
import logging
import threading
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timezone

from ai_forex_bot.execution.broker_base import BaseBroker
from ai_forex_bot.config.settings import settings

logger = logging.getLogger("DerivBroker")


DEFAULT_SYMBOL_MULTIPLIERS = {
    "R_10": 400,
    "R_25": 160,
    "R_50": 80,
    "R_75": 100,
    "R_100": 100,
    "1HZ10V": 400,
    "1HZ25V": 160,
    "1HZ75V": 100,
    "frxEURUSD": 100,
    "frxGBPUSD": 100,
}


class DerivBroker(BaseBroker):
    def __init__(
        self,
        token: Optional[str] = None,
        app_id: Optional[str] = None,
        account_type: str = "demo",
        account_id: Optional[str] = None,
        default_stake: float = 1.0,
        leverage: float = 100.0,
        partial_tp_pips: Optional[float] = None,
        buffer_pips: float = 1.0
    ):
        self.token = token or os.getenv("DERIV_API_TOKEN", "")
        self.app_id = app_id or os.getenv("DERIV_APP_ID", "34lQGsI4JVHDtfZhaHAqk")
        self.account_type = account_type.lower()
        self.account_id = account_id
        self.default_stake = default_stake
        self.leverage = leverage
        self.partial_tp_pips = partial_tp_pips
        self.buffer_pips = buffer_pips

        self.initial_balance: float = 10000.0
        self.balance: float = 10000.0
        self.equity: float = 10000.0
        self.free_margin: float = 10000.0
        self.used_margin: float = 0.0

        self.positions: Dict[str, Dict[str, Any]] = {}
        self.closed_trades: List[Dict[str, Any]] = []
        self.quotes: Dict[str, Dict[str, Any]] = {}
        self.order_history: List[Dict[str, Any]] = []
        self._processed_order_keys: Set[str] = set()

        self.connected = False
        self._ws = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._req_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._subscribed_symbols: Set[str] = set()
        self._subscribed_contracts: Set[int] = set()
        self._lock = threading.RLock()

    # ----------------------------------------------------------------------
    # Connection Lifecycle
    # ----------------------------------------------------------------------

    def connect(self) -> bool:
        """Authenticates with Deriv REST API, acquires WebSocket OTP, and starts daemon client."""
        if not self.token:
            logger.error("[DERIV] DERIV_API_TOKEN is not set.")
            return False

        try:
            # 1. Fetch available accounts via REST
            accounts = self._rest_get_accounts()
            if not accounts:
                logger.error("[DERIV] No trading accounts found for provided token.")
                return False

            target_acc = None
            if self.account_id:
                target_acc = next((a for a in accounts if a.get("account_id") == self.account_id), None)
            if not target_acc:
                target_acc = next((a for a in accounts if a.get("account_type") == self.account_type), accounts[0])

            self.account_id = target_acc.get("account_id")
            self.account_type = target_acc.get("account_type", "demo")
            bal_str = target_acc.get("balance", "10000.00")
            self.balance = float(bal_str)
            self.initial_balance = self.balance
            self.equity = self.balance
            self.free_margin = self.balance

            logger.info(f"[DERIV] Discovered Account: {self.account_id} ({self.account_type.upper()}) Balance: ${self.balance:.2f} USD")

            # 2. Request OTP WebSocket URL
            ws_url = self._rest_get_otp_ws_url(self.account_id)
            if not ws_url:
                logger.error("[DERIV] Failed to acquire WebSocket OTP session URL.")
                return False

            # 3. Start background asyncio event loop thread
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="DerivWSWorker")
            self._thread.start()

            # 4. Connect WebSocket via loop
            future = asyncio.run_coroutine_threadsafe(self._async_connect(ws_url), self._loop)
            connected = future.result(timeout=15.0)
            self.connected = connected
            if connected:
                logger.info(f"[DERIV] WebSocket Gateway connected successfully for {self.account_id}")
            return connected
        except Exception as e:
            logger.error(f"[DERIV] Connection failed: {e}", exc_info=True)
            self.connected = False
            return False

    def disconnect(self):
        """Cleanly disconnects the WebSocket session."""
        self.connected = False
        if self._loop and self._loop.is_running() and self._ws:
            try:
                fut = asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
                fut.result(timeout=3.0)
            except Exception:
                pass
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def health_check(self) -> Dict[str, Any]:
        return {
            "status": "HEALTHY" if self.connected else "DISCONNECTED",
            "connected": self.connected,
            "broker": f"DerivBroker ({self.account_type.upper()}: {self.account_id})",
            "open_positions": len(self.positions),
            "closed_trades": len(self.closed_trades),
            "equity": round(self.equity, 2),
            "balance": round(self.balance, 2),
            "free_margin": round(self.free_margin, 2),
            "used_margin": round(self.used_margin, 2)
        }

    # ----------------------------------------------------------------------
    # REST Helpers
    # ----------------------------------------------------------------------

    def _rest_get_accounts(self) -> List[Dict[str, Any]]:
        url = "https://api.derivws.com/trading/v1/options/accounts"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Deriv-App-ID": self.app_id,
            "Accept": "application/json"
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", [])

    def _rest_get_otp_ws_url(self, account_id: str) -> Optional[str]:
        url = f"https://api.derivws.com/trading/v1/options/accounts/{account_id}/otp"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Deriv-App-ID": self.app_id,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", {}).get("url")

    # ----------------------------------------------------------------------
    # Async WebSocket Core
    # ----------------------------------------------------------------------

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _async_connect(self, ws_url: str) -> bool:
        import websockets
        self._ws = await websockets.connect(ws_url, ping_interval=20, ping_timeout=20)
        self._loop.create_task(self._listener())

        # Subscribe to balance stream
        b_res = await self._send({"balance": 1, "subscribe": 1})
        b_val = b_res.get("balance", {}).get("balance")
        if b_val is not None:
            self.balance = float(b_val)
            self.equity = self.balance
            self.free_margin = self.balance
        return True

    async def _listener(self):
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                rid = msg.get("req_id")
                if rid and rid in self._pending_requests:
                    fut = self._pending_requests.pop(rid)
                    if not fut.done():
                        fut.set_result(msg)

                msg_type = msg.get("msg_type")
                if msg_type == "balance":
                    bal = msg.get("balance", {}).get("balance")
                    if bal is not None:
                        with self._lock:
                            self.balance = float(bal)
                            self._update_equity()
                elif msg_type == "tick":
                    tick = msg.get("tick", {})
                    sym = tick.get("symbol")
                    if sym:
                        bid = float(tick.get("bid", 0.0))
                        ask = float(tick.get("ask", 0.0))
                        pip_size = 10 ** (-int(tick.get("pip_size", 4)))
                        spread = (ask - bid) / pip_size if pip_size > 0 else 0.0
                        with self._lock:
                            self.quotes[sym] = {
                                "bid": bid,
                                "ask": ask,
                                "spread_pips": spread,
                                "timestamp": int(tick.get("epoch", time.time()))
                            }
                elif msg_type == "proposal_open_contract":
                    self._handle_poc_update(msg.get("proposal_open_contract", {}))
        except Exception as e:
            logger.warning(f"[DERIV] WebSocket listener terminated: {e}")
            self.connected = False

    def _handle_poc_update(self, poc: Dict[str, Any]):
        cid = str(poc.get("contract_id", ""))
        if not cid:
            return

        with self._lock:
            if cid in self.positions:
                pos = self.positions[cid]
                profit = float(poc.get("profit", 0.0))
                pos["unrealized_pnl"] = profit
                pos["current_spot"] = float(poc.get("current_spot", pos.get("entry_price", 0.0)))
                self._update_equity()

                # If contract is settled/closed on Deriv
                if poc.get("is_sold") == 1 or poc.get("status") in ("won", "lost", "sold"):
                    exit_reason = "DERIV_CONTRACT_SETTLED"
                    if poc.get("status") == "won":
                        exit_reason = "PROFIT_TARGET"
                    elif poc.get("status") == "lost":
                        exit_reason = "STOP_LOSS"
                    self._finalize_closed_contract(cid, poc, exit_reason)

    def _finalize_closed_contract(self, cid: str, poc: Dict[str, Any], exit_reason: str):
        if cid not in self.positions:
            return
        pos = self.positions.pop(cid)
        sold_for = float(poc.get("sell_price", poc.get("bid_price", pos.get("stake", 1.0))))
        net_pnl = float(poc.get("profit", sold_for - pos.get("stake", 1.0)))
        exit_price = float(poc.get("exit_tick", poc.get("current_spot", pos.get("entry_price", 0.0))))
        exit_epoch = int(poc.get("sell_time", time.time()))

        trade = {
            "trade_id": f"trade_{cid}",
            "position_id": cid,
            "symbol": pos["symbol"],
            "direction": pos["direction"],
            "lot_size": pos["lot_size"],
            "stake": pos.get("stake", 1.0),
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "entry_epoch": pos["entry_epoch"],
            "exit_epoch": exit_epoch,
            "bars_held": pos.get("bars_held", 0),
            "gross_pnl": net_pnl,
            "commission_usd": pos.get("commission_usd", 0.0),
            "swap_usd": 0.0,
            "net_pnl": net_pnl,
            "exit_reason": exit_reason,
            "exit_dt": datetime.fromtimestamp(exit_epoch, tz=timezone.utc).isoformat()
        }
        self.closed_trades.append(trade)
        self._update_equity()
        logger.info(f"[DERIV TRADE CLOSED] ID: {cid} | Symbol: {pos['symbol']} | Net PnL: ${net_pnl:+.2f} USD | Reason: {exit_reason}")

    async def _send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._req_id += 1
        rid = self._req_id
        payload["req_id"] = rid
        fut = self._loop.create_future()
        self._pending_requests[rid] = fut
        await self._ws.send(json.dumps(payload))
        return await asyncio.wait_for(fut, timeout=12.0)

    def send_request(self, payload: Dict[str, Any], timeout: float = 12.0) -> Dict[str, Any]:
        """Synchronous helper that executes request via async WebSocket loop."""
        if not self.connected or not self._loop:
            raise ConnectionError("DerivBroker is not connected.")
        future = asyncio.run_coroutine_threadsafe(self._send(payload), self._loop)
        return future.result(timeout=timeout)

    # ----------------------------------------------------------------------
    # Quotes & Subscriptions
    # ----------------------------------------------------------------------

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        with self._lock:
            if symbol in self.quotes:
                return self.quotes[symbol]

        # Subscribe if not yet subscribed
        if self.connected and symbol not in self._subscribed_symbols:
            try:
                res = self.send_request({"ticks": symbol})
                if "tick" in res:
                    tick = res["tick"]
                    bid = float(tick.get("bid", 0.0))
                    ask = float(tick.get("ask", 0.0))
                    pip_size = 10 ** (-int(tick.get("pip_size", 4)))
                    spread = (ask - bid) / pip_size if pip_size > 0 else 0.0
                    q = {
                        "bid": bid,
                        "ask": ask,
                        "spread_pips": spread,
                        "timestamp": int(tick.get("epoch", time.time()))
                    }
                    with self._lock:
                        self.quotes[symbol] = q
                        self._subscribed_symbols.add(symbol)
                    return q
            except Exception as e:
                logger.warning(f"[DERIV] Failed to fetch tick for {symbol}: {e}")

        # Fallback to last known or generate from symbol settings
        sym_cfg = settings.get_symbol_config(symbol)
        typical = sym_cfg.typical_spread_pips if sym_cfg else 1.2
        return {
            "bid": 1000.0,
            "ask": 1000.0 + (typical * (sym_cfg.pip_size if sym_cfg else 0.0001)),
            "spread_pips": typical,
            "timestamp": int(time.time())
        }

    def update_quote_from_bar(self, symbol: str, bar: Dict[str, Any]):
        """Updates internal quote using live bar close."""
        close = float(bar["close"])
        epoch = int(bar["epoch"])
        sym_cfg = settings.get_symbol_config(symbol)
        pip_size = sym_cfg.pip_size if sym_cfg else 0.0001
        typical = sym_cfg.typical_spread_pips if sym_cfg else 1.2

        half_spread = (typical * pip_size) / 2.0
        bid = close - half_spread
        ask = close + half_spread
        with self._lock:
            self.quotes[symbol] = {
                "bid": bid,
                "ask": ask,
                "spread_pips": typical,
                "timestamp": epoch
            }

    # ----------------------------------------------------------------------
    # Account State & Margins
    # ----------------------------------------------------------------------

    def _update_equity(self):
        unrealized = sum(p.get("unrealized_pnl", 0.0) for p in self.positions.values())
        self.used_margin = sum(p.get("stake", 1.0) for p in self.positions.values())
        self.equity = max(0.0, self.balance + unrealized)
        self.free_margin = max(0.0, self.equity - self.used_margin)

    def get_account_state(self) -> Dict[str, float]:
        with self._lock:
            self._update_equity()
            return {
                "balance": round(self.balance, 2),
                "equity": round(self.equity, 2),
                "free_margin": round(self.free_margin, 2),
                "used_margin": round(self.used_margin, 2),
                "initial_balance": round(self.initial_balance, 2)
            }

    # ----------------------------------------------------------------------
    # Order Execution (Multipliers)
    # ----------------------------------------------------------------------

    def _get_multiplier_for_symbol(self, symbol: str) -> int:
        return DEFAULT_SYMBOL_MULTIPLIERS.get(symbol, 100)

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
        Executes a real Multiplier contract (MULTUP/MULTDOWN) on Deriv Demo/Real.
        """
        quote = self.get_quote(symbol)
        epoch = int(quote["timestamp"])
        sym_cfg = settings.get_symbol_config(symbol)
        pip_size = sym_cfg.pip_size if sym_cfg else 0.0001

        # Duplicate check
        dedup_key = idempotency_key or f"{symbol}_{direction}_{epoch}"
        with self._lock:
            if dedup_key in self._processed_order_keys:
                return {
                    "status": "REJECTED",
                    "reason": "DUPLICATE_ORDER_KEY",
                    "idempotency_key": dedup_key
                }

        # Stake calculation (Deriv minimum multiplier stake is $1.00 USD)
        stake = max(1.0, round(lot_size * 100.0, 2))
        if "stake" in kwargs:
            stake = max(1.0, float(kwargs["stake"]))

        with self._lock:
            if self.free_margin < stake:
                return {
                    "status": "REJECTED",
                    "reason": "INSUFFICIENT_MARGIN",
                    "free_margin": round(self.free_margin, 2),
                    "required_stake": stake
                }

        contract_type = "MULTUP" if direction.upper() == "BUY" else "MULTDOWN"
        multiplier = self._get_multiplier_for_symbol(symbol)

        # 1. Request Proposal from Deriv
        proposal_req = {
            "proposal": 1,
            "amount": stake,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": "USD",
            "multiplier": multiplier,
            "underlying_symbol": symbol
        }

        try:
            p_res = self.send_request(proposal_req, timeout=8.0)
            if "error" in p_res:
                err_msg = p_res["error"].get("message", "Unknown proposal error")
                logger.error(f"[DERIV ORDER ERROR] Proposal rejected for {symbol}: {err_msg}")
                return {
                    "status": "REJECTED",
                    "reason": f"DERIV_PROPOSAL_ERROR: {err_msg}"
                }

            prop = p_res.get("proposal", {})
            prop_id = prop.get("id")
            ask_price = prop.get("ask_price", stake)
            fill_price = float(prop.get("spot", quote.get("ask" if direction == "BUY" else "bid", 0.0)))
            commission = float(prop.get("commission", 0.0))

            # 2. Buy Contract on Deriv
            buy_req = {
                "buy": prop_id,
                "price": ask_price
            }
            b_res = self.send_request(buy_req, timeout=8.0)
            if "error" in b_res:
                err_msg = b_res["error"].get("message", "Unknown buy error")
                logger.error(f"[DERIV ORDER ERROR] Buy contract rejected: {err_msg}")
                return {
                    "status": "REJECTED",
                    "reason": f"DERIV_BUY_ERROR: {err_msg}"
                }

            buy_info = b_res.get("buy", {})
            contract_id = str(buy_info.get("contract_id", uuid.uuid4().hex[:10]))
            purchase_epoch = int(buy_info.get("purchase_time", epoch))

            # Deduct stake from local balance tracking until balance stream updates
            with self._lock:
                self.balance = float(buy_info.get("balance_after", self.balance - stake))

            # 3. Register Position
            position = {
                "position_id": contract_id,
                "symbol": symbol,
                "direction": direction.upper(),
                "lot_size": lot_size,
                "stake": stake,
                "multiplier": multiplier,
                "entry_price": fill_price,
                "entry_epoch": purchase_epoch,
                "entry_dt": datetime.fromtimestamp(purchase_epoch, tz=timezone.utc).isoformat(),
                "sl_price": sl_price,
                "tp_price": tp_price,
                "partial_tp_price": partial_tp_price,
                "partial_tp_pips": partial_tp_pips,
                "buffer_pips": buffer_pips if buffer_pips is not None else self.buffer_pips,
                "atr": atr,
                "partial_tp_hit": False,
                "breakeven_locked": False,
                "slippage_pips": 0.0,
                "commission_usd": commission,
                "swap_usd": 0.0,
                "unrealized_pnl": 0.0,
                "current_spot": fill_price,
                "bars_held": 0
            }

            with self._lock:
                self.positions[contract_id] = position
                self._processed_order_keys.add(dedup_key)
                self._update_equity()

            # Subscribe to proposal_open_contract for live tracking
            try:
                self.send_request({"proposal_open_contract": 1, "contract_id": int(contract_id), "subscribe": 1}, timeout=5.0)
            except Exception:
                pass

            logger.info(
                f"[DERIV ORDER FILLED] ID: {contract_id} | {direction} {symbol} | Stake: ${stake:.2f} (x{multiplier}) | Spot: {fill_price}"
            )

            return {
                "order_id": contract_id,
                "status": "FILLED",
                "symbol": symbol,
                "direction": direction,
                "lot_size": lot_size,
                "stake": stake,
                "fill_price": fill_price,
                "slippage_pips": 0.0,
                "commission_usd": commission,
                "epoch": purchase_epoch
            }
        except Exception as e:
            logger.error(f"[DERIV] Order execution failed: {e}", exc_info=True)
            return {
                "status": "REJECTED",
                "reason": f"EXCEPTION: {str(e)}"
            }

    # ----------------------------------------------------------------------
    # Position Closure & Management
    # ----------------------------------------------------------------------

    def close_position(
        self,
        position_id: str,
        exit_price: Optional[float] = None,
        exit_reason: str = "MANUAL",
        exit_epoch: Optional[int] = None
    ) -> Dict[str, Any]:
        """Closes an open Deriv contract via sell request."""
        with self._lock:
            if position_id not in self.positions:
                return {"status": "ERROR", "reason": "POSITION_NOT_FOUND"}
            pos = self.positions[position_id]

        cid_int = int(position_id) if position_id.isdigit() else None
        sold_for = None
        balance_after = None

        if cid_int and self.connected:
            try:
                res = self.send_request({"sell": cid_int, "price": 0}, timeout=8.0)
                if "sell" in res:
                    sold_for = float(res["sell"].get("sold_for", pos.get("stake", 1.0)))
                    balance_after = float(res["sell"].get("balance_after", self.balance))
            except Exception as e:
                logger.warning(f"[DERIV] Sell contract {position_id} request error: {e}")

        now_epoch = exit_epoch or int(time.time())
        stake = pos.get("stake", 1.0)
        final_sold = sold_for if sold_for is not None else stake + pos.get("unrealized_pnl", 0.0)
        net_pnl = final_sold - stake

        with self._lock:
            self.positions.pop(position_id, None)
            if balance_after is not None:
                self.balance = balance_after
            else:
                self.balance += final_sold
            self._update_equity()

            trade = {
                "trade_id": f"trade_{position_id}",
                "position_id": position_id,
                "symbol": pos["symbol"],
                "direction": pos["direction"],
                "lot_size": pos["lot_size"],
                "stake": stake,
                "entry_price": pos["entry_price"],
                "exit_price": exit_price or pos.get("current_spot", pos["entry_price"]),
                "entry_epoch": pos["entry_epoch"],
                "exit_epoch": now_epoch,
                "bars_held": pos.get("bars_held", 0),
                "gross_pnl": net_pnl,
                "commission_usd": pos.get("commission_usd", 0.0),
                "swap_usd": 0.0,
                "net_pnl": net_pnl,
                "exit_reason": exit_reason,
                "exit_dt": datetime.fromtimestamp(now_epoch, tz=timezone.utc).isoformat()
            }
            self.closed_trades.append(trade)

        logger.info(
            f"[DERIV POSITION CLOSED] ID: {position_id} | Symbol: {pos['symbol']} | Net PnL: ${net_pnl:+.2f} USD | Reason: {exit_reason}"
        )
        return {
            "status": "CLOSED",
            "trade": trade
        }

    def on_bar(self, bar: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Evaluates open positions against bar data (SL, TP, breakeven lock) and closes any triggered positions.
        """
        sym = bar["symbol"]
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        epoch = int(bar["epoch"])

        self.update_quote_from_bar(sym, bar)
        closed_this_bar = []

        with self._lock:
            active_ids = [pid for pid, p in self.positions.items() if p.get("symbol") == sym]

        for pid in active_ids:
            with self._lock:
                if pid not in self.positions:
                    continue
                pos = self.positions[pid]

            pos["bars_held"] = pos.get("bars_held", 0) + 1
            direction = pos["direction"]
            sl_price = pos["sl_price"]
            tp_price = pos["tp_price"]

            # SL trigger
            if direction == "BUY" and low <= sl_price:
                res = self.close_position(pid, exit_price=sl_price, exit_reason="STOP_LOSS", exit_epoch=epoch)
                if res.get("status") == "CLOSED":
                    closed_this_bar.append(res["trade"])
                continue
            elif direction == "SELL" and high >= sl_price:
                res = self.close_position(pid, exit_price=sl_price, exit_reason="STOP_LOSS", exit_epoch=epoch)
                if res.get("status") == "CLOSED":
                    closed_this_bar.append(res["trade"])
                continue

            # TP trigger
            if direction == "BUY" and high >= tp_price:
                res = self.close_position(pid, exit_price=tp_price, exit_reason="PROFIT_TARGET", exit_epoch=epoch)
                if res.get("status") == "CLOSED":
                    closed_this_bar.append(res["trade"])
                continue
            elif direction == "SELL" and low <= tp_price:
                res = self.close_position(pid, exit_price=tp_price, exit_reason="PROFIT_TARGET", exit_epoch=epoch)
                if res.get("status") == "CLOSED":
                    closed_this_bar.append(res["trade"])
                continue

            # Breakeven lock check
            ptp = pos.get("partial_tp_price")
            if ptp and not pos.get("breakeven_locked"):
                if (direction == "BUY" and high >= ptp) or (direction == "SELL" and low <= ptp):
                    pos["breakeven_locked"] = True
                    pos["sl_price"] = pos["entry_price"]
                    logger.info(f"[DERIV BREAKEVEN LOCKED] ID: {pid} SL shifted to entry {pos['entry_price']}")

        return closed_this_bar

    def get_open_positions(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.positions.values())

    def reconcile(self) -> Dict[str, Any]:
        with self._lock:
            self._update_equity()
            return {
                "is_synchronized": True,
                "account_id": self.account_id,
                "account_type": self.account_type,
                "balance": round(self.balance, 2),
                "equity": round(self.equity, 2),
                "open_positions_count": len(self.positions),
                "closed_trades_count": len(self.closed_trades)
            }
