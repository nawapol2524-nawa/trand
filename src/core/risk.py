"""
Risk Engine & Capital Preservation Model — Implementation of RISK_MODEL.md v1.0.0 FROZEN.
Strict mathematical gatekeeper. AI layer has ZERO authority to override risk parameters.
Upgraded with Multi-Level Defense (Levels 0-4) and Pre-Trade Spread Guard.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.core.models import Direction, RiskDecision


@dataclass
class RiskConfig:
    max_risk_per_trade_pct: float = 0.01      # 1.0% equity per trade
    max_daily_loss_pct: float = 0.05          # 5.0% drawdown from daily starting balance
    max_consecutive_losses: int = 5           # 5 consecutive losses -> 1h halt
    consecutive_loss_halt_hours: float = 1.0  # 1 hour halt
    max_open_positions: int = 3               # 3 concurrent open positions total
    max_symbol_exposure_pct: float = 0.05     # 5.0% exposure per symbol
    max_positions_per_symbol: int = 1         # Max 1 open position per symbol
    atr_multiplier_sl: float = 1.5            # 1.5x ATR for Stop Loss
    rr_ratio: float = 2.0                     # 1:2 Risk to Reward
    min_volume: float = 0.01
    max_volume: float = 10.0
    volume_step: float = 0.01
    max_data_staleness_seconds: float = 300.0 # 5 minutes maximum bar age
    defensive_drawdown_threshold: float = 0.025 # 2.5% daily drawdown -> Level 1 Defensive
    emergency_kill_switch: bool = False       # Programmatic kill switch override


class RiskEngine:
    """
    Deterministic Risk Engine implementing institutional capital preservation rules.
    Operates strictly in UTC timezone with Multi-Level Defense.
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()

    def is_kill_switch_active(self) -> bool:
        """Check if emergency kill switch is active via environment variable or config override."""
        if getattr(self.config, "emergency_kill_switch", False):
            return True
        val = os.environ.get("EMERGENCY_KILL_SWITCH", "false").strip().lower()
        return val in ("true", "1", "yes", "on")

    def check_daily_reset(
        self,
        current_time: datetime,
        last_reset_date: Optional[datetime.date],
        current_balance: float,
    ) -> tuple[bool, datetime.date, float]:
        """
        Evaluate UTC midnight daily reset.
        Returns: (did_reset: bool, new_reset_date: date, new_starting_balance: float)
        """
        curr_utc_date = current_time.astimezone(timezone.utc).date()
        if last_reset_date != curr_utc_date:
            return True, curr_utc_date, current_balance
        return False, curr_utc_date, current_balance

    @staticmethod
    def evaluate_spread(
        symbol: str,
        current_spread_pips: float,
        max_allowed_spread_pips: float,
    ) -> tuple[bool, Optional[str]]:
        """
        Pre-trade spread validation guard.
        Blocks execution if market spread is abnormally wide (e.g. news/illiquidity).
        """
        if current_spread_pips > max_allowed_spread_pips:
            return (
                False,
                f"SPREAD GUARD: Current spread {current_spread_pips:.2f} pips exceeds allowed {max_allowed_spread_pips:.2f} pips for {symbol}",
            )
        return True, None

    def calculate_lot_size(
        self,
        symbol: str,
        equity: float,
        entry_price: float,
        sl_distance: float,
        lot_size_units: float = 100000.0,
    ) -> tuple[float, Optional[str]]:
        """
        Calculate position volume according to RISK_MODEL.md:
          Risk Amount = Equity * 0.01
          Lot Size = Risk Amount / (Stop Distance * Point Value)
        Returns: (clamped_volume: float, reject_reason: Optional[str])
        """
        if equity <= 0:
            return 0.0, "Account equity is zero or negative"
        if sl_distance <= 0:
            return 0.0, f"Invalid stop distance: {sl_distance}"

        risk_amount = equity * self.config.max_risk_per_trade_pct

        if symbol == "USDJPY":
            # For USDJPY, quote currency is JPY, so 1 point in USD = units / exit_price
            raw_lots = (risk_amount * entry_price) / (sl_distance * lot_size_units)
        elif symbol == "XAUUSD":
            # For Gold, 1 lot = 100 oz. 1 point = $1 / lot
            raw_lots = risk_amount / (sl_distance * 100.0)
        else:
            raw_lots = risk_amount / (sl_distance * lot_size_units)

        if raw_lots < self.config.min_volume:
            return 0.0, f"Calculated volume {raw_lots:.4f} is below min_volume {self.config.min_volume} (over-leveraging prohibited)"

        clamped = min(raw_lots, self.config.max_volume)
        stepped = round(clamped / self.config.volume_step) * self.config.volume_step
        final_volume = round(stepped, 2)

        return final_volume, None

    def evaluate_order(
        self,
        symbol: str,
        direction: Direction,
        entry_price: float,
        atr_val: float,
        equity: float,
        daily_starting_balance: float,
        daily_pnl: float,
        consecutive_losses: int,
        halt_until: Optional[datetime],
        open_positions: List[Dict[str, Any]],
        data_timestamp: Optional[datetime] = None,
        now: Optional[datetime] = None,
        lot_size_units: float = 100000.0,
        current_spread_pips: Optional[float] = None,
        max_spread_pips: Optional[float] = None,
    ) -> RiskDecision:
        """
        Strict evaluation of new trade against all capital preservation mandates,
        incorporating Multi-Level Defense (Levels 0-4) and Pre-Trade Spread Guard.
        """
        now_utc = now or datetime.now(tz=timezone.utc)

        # Level 4: Emergency Kill Switch Gate
        if self.is_kill_switch_active():
            return RiskDecision(
                approved=False,
                reason="HARD GATE: Emergency kill switch is active (EMERGENCY_KILL_SWITCH=true)",
                block_reason="KILL_SWITCH_ACTIVE",
                defense_level=4,
            )

        # Level 3: Consecutive Loss Halt Gate
        if halt_until is not None and now_utc < halt_until:
            remaining = (halt_until - now_utc).total_seconds() / 60.0
            return RiskDecision(
                approved=False,
                reason=f"HARD GATE: Trading halted due to {consecutive_losses} consecutive losses. Remaining: {remaining:.1f} mins",
                block_reason="CONSECUTIVE_LOSS_HALT",
                defense_level=3,
            )

        # Level 3: Maximum Daily Loss Gate (5% drawdown from daily starting balance)
        daily_loss_pct = (daily_pnl / daily_starting_balance) if daily_starting_balance > 0 else 0.0
        if daily_loss_pct <= -self.config.max_daily_loss_pct:
            return RiskDecision(
                approved=False,
                reason=f"HARD GATE: Daily loss limit reached ({daily_loss_pct:.2%} <= -{self.config.max_daily_loss_pct:.2%})",
                block_reason="DAILY_LOSS_LIMIT",
                defense_level=3,
            )

        # Pre-Trade Spread Guard
        if current_spread_pips is not None and max_spread_pips is not None:
            spread_ok, spread_reason = self.evaluate_spread(symbol, current_spread_pips, max_spread_pips)
            if not spread_ok:
                return RiskDecision(
                    approved=False,
                    reason=f"HARD GATE: {spread_reason}",
                    block_reason="SPREAD_TOO_HIGH",
                    defense_level=0,
                )

        # Maximum Concurrent Positions Gate (3 total)
        total_open = len(open_positions)
        if total_open >= self.config.max_open_positions:
            return RiskDecision(
                approved=False,
                reason=f"HARD GATE: Max open positions limit reached ({total_open}/{self.config.max_open_positions})",
                block_reason="MAX_POSITIONS_REACHED",
                defense_level=0,
            )

        # Maximum Exposure per Symbol (1 position per symbol)
        symbol_positions = [p for p in open_positions if p.get("symbol") == symbol]
        if len(symbol_positions) >= self.config.max_positions_per_symbol:
            return RiskDecision(
                approved=False,
                reason=f"HARD GATE: Symbol {symbol} already has an open position ({len(symbol_positions)}/{self.config.max_positions_per_symbol})",
                block_reason="SYMBOL_EXPOSURE_LIMIT",
                defense_level=0,
            )

        # Data Staleness Gate
        if data_timestamp is not None:
            age = (now_utc - data_timestamp).total_seconds()
            if age > self.config.max_data_staleness_seconds:
                return RiskDecision(
                    approved=False,
                    reason=f"HARD GATE: Market data is stale ({age:.1f}s > {self.config.max_data_staleness_seconds}s)",
                    block_reason="STALE_DATA",
                    defense_level=0,
                )

        # Dynamic Position Sizing Calculation
        sl_distance = max(atr_val * self.config.atr_multiplier_sl, 1e-5)
        volume, reject_reason = self.calculate_lot_size(
            symbol=symbol,
            equity=equity,
            entry_price=entry_price,
            sl_distance=sl_distance,
            lot_size_units=lot_size_units,
        )

        if reject_reason or volume <= 0.0:
            return RiskDecision(
                approved=False,
                reason=f"HARD GATE: Position sizing rejected: {reject_reason}",
                block_reason="SIZING_REJECTED",
                defense_level=0,
            )

        # Multi-Level Defense Assessment (Level 0 vs Level 1 vs Level 2)
        defense_level = 0
        allocated_volume = volume
        level_notes: List[str] = []

        if daily_loss_pct <= -self.config.defensive_drawdown_threshold:
            defense_level = 1
            # Halve position size to protect capital during intraday drawdown
            allocated_volume = max(round(volume * 0.5, 2), self.config.min_volume)
            level_notes.append(f"Level 1 Defensive Mode (Drawdown {daily_loss_pct:.1%}): volume halved to {allocated_volume:.2f} lots")

        if consecutive_losses >= 3:
            defense_level = max(defense_level, 2)
            level_notes.append(f"Level 2 Restricted Mode: {consecutive_losses} streak losses")

        notes_str = f" [{', '.join(level_notes)}]" if level_notes else ""
        return RiskDecision(
            approved=True,
            reason=f"All risk gates passed. Allocated volume: {allocated_volume:.2f} lots (Base: {volume:.2f}){notes_str}",
            adjusted_volume=allocated_volume,
            defense_level=defense_level,
        )
