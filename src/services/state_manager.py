"""
State Manager & Broker Reconciliation Service — Phase 4 requirement.
Ensures persistent local state, atomic saves, startup broker recovery,
orphan position discovery, and duplicate trade prevention across restarts.
Hardened with schema versioning, thread-safe atomic writes, and loss classification.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.loss_classifier import LossReason
from src.core.version import SCHEMA_VERSION

logger = logging.getLogger("StateManager")


@dataclass
class PositionState:
    position_id: str
    symbol: str
    direction: str
    volume_lots: float
    entry_price: float
    sl_price: float = 0.0
    tp_price: float = 0.0
    open_time: str = ""
    status: str = "OPEN"      # OPEN, CLOSED, ORPHAN
    close_time: Optional[str] = None
    close_price: Optional[float] = None
    realized_pnl: float = 0.0
    loss_reason: Optional[str] = None


@dataclass
class BotRuntimeState:
    last_reset_date: str
    daily_starting_balance: float
    schema_version: str = SCHEMA_VERSION
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    halt_until: Optional[str] = None
    kill_switch_active: bool = False
    open_positions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    closed_positions_history: List[Dict[str, Any]] = field(default_factory=list)
    orphan_positions: List[Dict[str, Any]] = field(default_factory=list)
    last_updated: str = ""
    reconciliation_count: int = 0


class StateManager:
    """Manages persistent bot state and broker reconciliation with atomic thread safety."""

    def __init__(self, state_dir: Optional[str] = None):
        self.state_dir = Path(state_dir or os.environ.get("STATE_DIR", "./state"))
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "bot_state.json"
        self._lock = threading.Lock()
        self.state: BotRuntimeState = self._load_or_initialize()

    def _load_or_initialize(self) -> BotRuntimeState:
        now_utc = datetime.now(tz=timezone.utc)
        today_str = now_utc.date().isoformat()

        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                loaded_schema = data.get("schema_version", "1.0")

                # Schema migration check
                migrated = False
                if loaded_schema != SCHEMA_VERSION:
                    logger.info("Migrating bot_state schema from %s to %s", loaded_schema, SCHEMA_VERSION)
                    migrated = True

                state = BotRuntimeState(
                    last_reset_date=data.get("last_reset_date", today_str),
                    daily_starting_balance=float(data.get("daily_starting_balance", 10000.0)),
                    schema_version=SCHEMA_VERSION,
                    daily_pnl=float(data.get("daily_pnl", 0.0)),
                    consecutive_losses=int(data.get("consecutive_losses", 0)),
                    halt_until=data.get("halt_until"),
                    kill_switch_active=bool(data.get("kill_switch_active", False)),
                    open_positions=data.get("open_positions", {}),
                    closed_positions_history=data.get("closed_positions_history", []),
                    orphan_positions=data.get("orphan_positions", []),
                    last_updated=data.get("last_updated", now_utc.isoformat()),
                    reconciliation_count=int(data.get("reconciliation_count", 0)),
                )

                if migrated:
                    self.save_state(state)
                return state
            except Exception as e:
                logger.warning("Could not parse existing state file: %s. Reinitializing.", e)

        # Default initial state
        st = BotRuntimeState(
            last_reset_date=today_str,
            daily_starting_balance=10000.0,
            schema_version=SCHEMA_VERSION,
            last_updated=now_utc.isoformat(),
        )
        self.save_state(st)
        return st

    def save_state(self, state: Optional[BotRuntimeState] = None) -> None:
        """Thread-safe atomic write of state file using unique temporary file."""
        with self._lock:
            if state is not None:
                self.state = state

            now_utc = datetime.now(tz=timezone.utc)
            self.state.last_updated = now_utc.isoformat()
            if not getattr(self.state, "schema_version", None):
                self.state.schema_version = SCHEMA_VERSION

            # Unique temp file eliminates race conditions
            unique_tmp = self.state_file.with_name(f"bot_state_{uuid.uuid4().hex[:8]}.tmp")
            try:
                payload = asdict(self.state)
                unique_tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                unique_tmp.replace(self.state_file)
            finally:
                if unique_tmp.exists():
                    try:
                        unique_tmp.unlink(missing_ok=True)
                    except Exception:
                        pass

    def record_new_position(self, pos: PositionState) -> None:
        """Track new position locally."""
        self.state.open_positions[pos.position_id] = asdict(pos)
        self.save_state()

    def record_closed_position(
        self,
        position_id: str,
        close_price: float,
        realized_pnl: float,
        close_time: Optional[datetime] = None,
        loss_reason: Optional[str] = None,
    ) -> None:
        """Update local state on position exit, with loss classification."""
        pos_dict = self.state.open_positions.pop(position_id, None)
        if pos_dict:
            pos_dict["status"] = "CLOSED"
            pos_dict["close_price"] = close_price
            pos_dict["realized_pnl"] = realized_pnl
            pos_dict["close_time"] = (close_time or datetime.now(tz=timezone.utc)).isoformat()

            # Post-trade loss reason tagging
            if realized_pnl < 0:
                pos_dict["loss_reason"] = loss_reason or LossReason.NORMAL_STRATEGY_LOSS

            self.state.closed_positions_history.append(pos_dict)

            # Update daily PnL and consecutive loss streak
            self.state.daily_pnl += realized_pnl
            if realized_pnl > 0:
                self.state.consecutive_losses = 0
            else:
                self.state.consecutive_losses += 1
                if self.state.consecutive_losses >= 5:
                    halt_time = datetime.now(tz=timezone.utc) + timedelta(hours=1)
                    self.state.halt_until = halt_time.isoformat()

            self.save_state()

    def reconcile_with_broker(
        self,
        broker_positions: List[Dict[str, Any]],
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Reconcile local tracked positions with authoritative broker state.
        Handles:
          1. Orphan discovery (in broker, not in local)
          2. Closed detection (in local, not in broker -> SL/TP hit)
          3. Restart recovery (synchronizes volume and IDs)
        """
        now_utc = now or datetime.now(tz=timezone.utc)
        self.state.reconciliation_count += 1

        # Check UTC midnight daily reset
        curr_date_str = now_utc.date().isoformat()
        if self.state.last_reset_date != curr_date_str:
            self.state.last_reset_date = curr_date_str
            self.state.daily_pnl = 0.0
            # Daily starting balance will be updated on next balance query

        broker_by_id = {str(p.get("positionId")): p for p in broker_positions}
        local_ids = set(self.state.open_positions.keys())
        broker_ids = set(broker_by_id.keys())

        orphans_detected: List[str] = []
        closed_detected: List[str] = []

        # 1. Discover orphan positions (in broker but not in local tracking)
        for bid in broker_ids - local_ids:
            bp = broker_by_id[bid]
            orphan_record = {
                "position_id": bid,
                "symbol_id": bp.get("symbolId"),
                "trade_side": bp.get("tradeSide"),
                "volume": bp.get("volume"),
                "entry_price": bp.get("entryPrice"),
                "discovered_at": now_utc.isoformat(),
            }
            self.state.orphan_positions.append(orphan_record)
            orphans_detected.append(bid)

            # Integrate orphan into active tracking so risk limits respect it
            self.state.open_positions[bid] = {
                "position_id": bid,
                "symbol": str(bp.get("symbolId")),
                "direction": str(bp.get("tradeSide")),
                "volume_lots": float(bp.get("volume", 0)) / 100000.0,
                "entry_price": float(bp.get("entryPrice", 0)),
                "sl_price": 0.0,
                "tp_price": 0.0,
                "open_time": now_utc.isoformat(),
                "status": "ORPHAN",
            }

        # 2. Detect closed positions (in local tracking but no longer on broker)
        for lid in local_ids - broker_ids:
            closed_pos = self.state.open_positions.pop(lid)
            closed_pos["status"] = "CLOSED_EXTERNAL"
            closed_pos["close_time"] = now_utc.isoformat()
            self.state.closed_positions_history.append(closed_pos)
            closed_detected.append(lid)

        self.save_state()

        return {
            "reconciliation_time": now_utc.isoformat(),
            "broker_open_count": len(broker_ids),
            "local_open_count": len(self.state.open_positions),
            "orphans_discovered": orphans_detected,
            "closed_detected": closed_detected,
            "status": "IN_SYNC" if len(orphans_detected) == 0 and len(closed_detected) == 0 else "RECONCILED",
        }
