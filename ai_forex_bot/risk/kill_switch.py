"""
Emergency Kill-Switch & State Recovery Engine
============================================
Institutional Production Resilience Standard for Gate 26
Provides:
1. Dual-trigger Emergency Kill Switch (File-based flag and programmatic/CLI)
2. Immediate execution rejection & safe posture lock
3. State persistence & portfolio reconciliation on cold restart
4. Immutable audit logging of all emergency interventions
"""

import os
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple

from ai_forex_bot.config.settings import settings
from ai_forex_bot.execution.paper_broker import PaperBroker


class EmergencyKillSwitch:
    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or settings.root_dir
        self.flag_file = self.root_dir / "KILL_SWITCH"
        self.flag_file_alt = self.root_dir / "KILL_SWITCH.flag"
        self.log_file = self.root_dir / "logs" / "kill_switch.jsonl"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self._in_memory_active: bool = False
        self._in_memory_reason: str = ""

    def log_event(self, event_type: str, details: Dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "details": details
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def is_kill_switch_active(self) -> bool:
        """
        Checks both physical file flag and in-memory flag.
        If file flag exists on disk, activates in-memory state.
        """
        if self.flag_file.exists():
            try:
                content = self.flag_file.read_text(encoding="utf-8").strip()
            except Exception:
                content = ""
            self._in_memory_active = True
            self._in_memory_reason = content or "FILE_FLAG_TRIGGERED: KILL_SWITCH present"
            return True

        if self.flag_file_alt.exists():
            try:
                content = self.flag_file_alt.read_text(encoding="utf-8").strip()
            except Exception:
                content = ""
            self._in_memory_active = True
            self._in_memory_reason = content or "FILE_FLAG_TRIGGERED: KILL_SWITCH.flag present"
            return True

        return self._in_memory_active

    @property
    def reason(self) -> str:
        self.is_kill_switch_active()
        return self._in_memory_reason

    def activate_kill_switch(self, reason: str = "MANUAL_ACTIVATION") -> None:
        """Activates kill-switch in-memory and drops persistent file flag."""
        self._in_memory_active = True
        self._in_memory_reason = reason
        try:
            self.flag_file.write_text(f"{reason}\nTimestamp: {datetime.now(timezone.utc).isoformat()}", encoding="utf-8")
        except Exception as e:
            pass

        self.log_event("KILL_SWITCH_ACTIVATED", {"reason": reason, "flag_file": str(self.flag_file.name)})

    def reset_kill_switch(self, reason: str = "MANUAL_RESET") -> None:
        """Removes file flags and resets in-memory kill-switch state."""
        self._in_memory_active = False
        self._in_memory_reason = ""

        if self.flag_file.exists():
            try:
                self.flag_file.unlink()
            except Exception:
                pass

        if self.flag_file_alt.exists():
            try:
                self.flag_file_alt.unlink()
            except Exception:
                pass

        self.log_event("KILL_SWITCH_RESET", {"reason": reason})


class StateRecoveryManager:
    """Manages persistent portfolio state and cold restart recovery."""
    def __init__(self, state_file: Optional[Path] = None, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or settings.root_dir
        self.state_file = state_file or (self.root_dir / "artifacts" / "state" / "portfolio_state.json")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def save_portfolio_state(self, broker: PaperBroker, metadata: Optional[Dict[str, Any]] = None) -> Path:
        """Saves complete broker state atomically."""
        temp_file = self.state_file.with_suffix(".tmp")
        payload = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "balance": broker.balance,
            "equity": broker.equity,
            "used_margin": broker.used_margin,
            "free_margin": broker.free_margin,
            "positions": list(broker.positions.values()),
            "closed_trade_count": len(broker.closed_trades),
            "processed_order_keys": list(broker._processed_order_keys),
            "metadata": metadata or {}
        }
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        os.replace(temp_file, self.state_file)
        return self.state_file

    def load_portfolio_state(self) -> Optional[Dict[str, Any]]:
        """Loads persistent portfolio state from disk if present."""
        if not self.state_file.exists():
            return None
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def restore_broker_state(self, broker: PaperBroker) -> Tuple[bool, str]:
        """Restores positions, balance, and margin state into PaperBroker."""
        state = self.load_portfolio_state()
        if not state:
            return False, "No persistent state file found."

        try:
            restored_bal = float(state.get("balance", broker.initial_balance))
            if restored_bal <= 0:
                broker.balance = broker.initial_balance
                broker.equity = broker.initial_balance
                broker.free_margin = broker.initial_balance
                broker.used_margin = 0.0
                broker.positions.clear()
                return True, f"Sanitized non-positive balance. Reset to initial {broker.initial_balance:.2f} USDT."

            broker.balance = restored_bal
            broker.equity = float(state.get("equity", broker.balance))
            broker.used_margin = float(state.get("used_margin", 0.0))
            broker.free_margin = float(state.get("free_margin", broker.balance))

            raw_positions = state.get("positions", [])
            # Discard stale positions older than 24 hours
            now_epoch = int(datetime.now(timezone.utc).timestamp())
            valid_positions = {}
            for p in raw_positions:
                entry_epoch = int(p.get("entry_epoch", 0))
                if entry_epoch > 0 and (now_epoch - entry_epoch) < 86400:
                    valid_positions[p["position_id"]] = p
            broker.positions = valid_positions
            broker._processed_order_keys = set(state.get("processed_order_keys", []))

            # Re-sync quotes if available and reconcile
            recon = broker.reconcile()
            return True, f"Restored {len(broker.positions)} open positions. Synchronized: {recon['is_synchronized']}"
        except Exception as e:
            return False, f"Failed to restore broker state: {str(e)}"
