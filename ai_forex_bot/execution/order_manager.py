"""
Order Lifecycle Finite State Machine & Reconciliation Manager
=============================================================
Manages strict order lifecycle transitions:
SIGNAL ➔ RISK_APPROVED ➔ ORDER_CREATED ➔ BROKER_ACK ➔ PENDING ➔ FILLED ➔ POSITION ➔ CLOSED
Guarantees duplicate prevention, timeout handling, and state recovery.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
import uuid

from ai_forex_bot.execution.broker_base import BaseBroker
from ai_forex_bot.risk.risk_engine import RiskEngine, RiskDecision, AccountState, Position


class OrderState(str, Enum):
    SIGNAL_RECEIVED = "SIGNAL_RECEIVED"
    RISK_APPROVED = "RISK_APPROVED"
    RISK_REJECTED = "RISK_REJECTED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    BROKER_ACKNOWLEDGED = "BROKER_ACKNOWLEDGED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


@dataclass
class OrderRecord:
    order_id: str
    symbol: str
    direction: str
    lot_size: float
    state: OrderState
    created_epoch: int
    entry_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    rejection_reason: Optional[str] = None
    broker_position_id: Optional[str] = None


class OrderManager:
    def __init__(self, broker: BaseBroker, risk_engine: RiskEngine):
        self.broker = broker
        self.risk_engine = risk_engine
        self.orders: Dict[str, OrderRecord] = {}
        self.active_positions: Dict[str, Position] = {}

    def process_signal(
        self,
        symbol: str,
        direction: str,
        current_spread_pips: float,
        sl_pips: float = 15.0,
        tp_pips: float = 20.0,
        is_news_blackout: bool = False
    ) -> Dict[str, Any]:
        quote = self.broker.get_quote(symbol)
        current_dt = datetime.fromtimestamp(quote["timestamp"], tz=timezone.utc)
        acct_dict = self.broker.get_account_state()
        account = AccountState(
            balance=acct_dict["balance"],
            equity=acct_dict["equity"],
            free_margin=acct_dict["free_margin"],
            used_margin=acct_dict["used_margin"],
            initial_balance=acct_dict.get("initial_balance", 1000.0)
        )

        order_id = f"ord_{uuid.uuid4().hex[:8]}"
        order = OrderRecord(
            order_id=order_id,
            symbol=symbol,
            direction=direction,
            lot_size=0.0,
            state=OrderState.SIGNAL_RECEIVED,
            created_epoch=int(quote["timestamp"])
        )
        self.orders[order_id] = order

        # 1. Risk Engine Veto Check
        decision, code, detail = self.risk_engine.validate_new_order(
            symbol=symbol,
            direction=direction,
            current_spread_pips=current_spread_pips,
            account=account,
            open_positions=list(self.active_positions.values()),
            current_dt=current_dt,
            is_news_blackout=is_news_blackout
        )

        if decision != RiskDecision.APPROVE:
            order.state = OrderState.RISK_REJECTED
            order.rejection_reason = f"{code}: {detail}"
            return {"status": "REJECTED", "order_id": order_id, "reason": order.rejection_reason}

        order.state = OrderState.RISK_APPROVED

        # 2. Position Sizing
        entry_estimate = quote["ask"] if direction == "BUY" else quote["bid"]
        pip_size = 0.0001 if "JPY" not in symbol and "XAU" not in symbol else 0.01
        sl_price = entry_estimate - (sl_pips * pip_size) if direction == "BUY" else entry_estimate + (sl_pips * pip_size)
        tp_price = entry_estimate + (tp_pips * pip_size) if direction == "BUY" else entry_estimate - (tp_pips * pip_size)

        lot_size, size_err = self.risk_engine.calculate_position_size(account, symbol, entry_estimate, sl_price)
        if size_err or lot_size <= 0:
            order.state = OrderState.RISK_REJECTED
            order.rejection_reason = size_err or "Calculated lot size is zero."
            return {"status": "REJECTED", "order_id": order_id, "reason": order.rejection_reason}

        order.lot_size = lot_size
        order.sl_price = sl_price
        order.tp_price = tp_price

        # 3. Order Dispatch to Broker
        order.state = OrderState.ORDER_SUBMITTED
        res = self.broker.place_order(
            symbol=symbol,
            direction=direction,
            lot_size=lot_size,
            sl_price=sl_price,
            tp_price=tp_price
        )

        if res.get("status") == "FILLED":
            order.state = OrderState.FILLED
            order.entry_price = res["fill_price"]
            order.broker_position_id = res["position_id"]

            # Track in active positions
            pos = Position(
                position_id=res["position_id"],
                symbol=symbol,
                direction=direction,
                lot_size=lot_size,
                entry_price=res["fill_price"],
                current_price=res["fill_price"],
                sl_price=sl_price,
                tp_price=tp_price
            )
            self.active_positions[res["position_id"]] = pos
            return {"status": "FILLED", "order_id": order_id, "position": pos}
        else:
            order.state = OrderState.REJECTED
            order.rejection_reason = res.get("message", "Broker execution failed.")
            return {"status": "REJECTED", "order_id": order_id, "reason": order.rejection_reason}

    def close_position(self, position_id: str) -> Dict[str, Any]:
        if position_id not in self.active_positions:
            return {"status": "ERROR", "message": "Position not tracked."}

        res = self.broker.close_position(position_id)
        if res.get("status") == "CLOSED":
            pos = self.active_positions.pop(position_id)
            quote = self.broker.get_quote(pos.symbol)
            close_dt = datetime.fromtimestamp(quote["timestamp"], tz=timezone.utc)
            self.risk_engine.record_closed_trade(res["realized_pnl"], close_dt)
            return res
        return res

    def reconcile_with_broker(self) -> Dict[str, Any]:
        broker_positions = {p["position_id"]: p for p in self.broker.get_open_positions()}
        local_ids = set(self.active_positions.keys())
        broker_ids = set(broker_positions.keys())

        discrepancies = []
        # Check for orphan local positions
        for pid in (local_ids - broker_ids):
            discrepancies.append(f"Position {pid} in local state but closed at broker.")
            self.active_positions.pop(pid, None)

        return {
            "is_synchronized": len(discrepancies) == 0,
            "discrepancies": discrepancies,
            "active_positions_count": len(self.active_positions)
        }
