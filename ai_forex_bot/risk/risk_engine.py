"""
Independent Risk Engine & Portfolio Exposure Monitor
====================================================
Acts as absolute veto gatekeeper:
- Dynamic risk-based position sizing from equity and stop loss pips.
- Daily/weekly loss limits with UTC midnight calendar boundary reset.
- Maximum drawdown and consecutive loss protection.
- Cross-currency exposure monitoring (prevents hidden USD concentration).
- Per-symbol spread limit verification.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
import math
import numpy as np

from ai_forex_bot.config.settings import settings, SymbolConfig
from ai_forex_bot.risk.kill_switch import EmergencyKillSwitch


class RiskDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


@dataclass
class AccountState:
    balance: float
    equity: float
    free_margin: float
    used_margin: float = 0.0
    initial_balance: float = 1000.0


@dataclass
class Position:
    position_id: str
    symbol: str
    direction: str  # BUY or SELL
    lot_size: float
    entry_price: float
    current_price: float
    sl_price: float
    tp_price: float
    unrealized_pnl: float = 0.0


class SignalValidationResult(tuple):
    """
    Validation result tuple (decision, reason, detail) supporting property access.
    """
    def __new__(cls, decision: RiskDecision, reason: str, detail: str = ""):
        return super().__new__(cls, (decision, reason, detail))

    @property
    def decision(self) -> RiskDecision:
        return self[0]

    @property
    def reason(self) -> str:
        return self[1]

    @property
    def detail(self) -> str:
        return self[2]


class RiskEngine:
    def __init__(
        self,
        max_open_positions: Optional[int] = None,
        max_currency_exposure: int = 2,
        daily_loss_limit: Optional[float] = None,
        weekly_loss_limit: Optional[float] = None,
        max_risk_pct: Optional[float] = None,
        daily_profit_target_usd: Optional[float] = None,
        leverage: Optional[float] = None
    ):
        self.daily_loss_limit = daily_loss_limit if daily_loss_limit is not None else settings.max_daily_loss_usd
        self.weekly_loss_limit = weekly_loss_limit if weekly_loss_limit is not None else settings.max_weekly_loss_usd
        self.max_open_positions = max_open_positions if max_open_positions is not None else settings.max_open_positions
        self.max_risk_pct = max_risk_pct if max_risk_pct is not None else settings.max_risk_per_trade_pct
        self.max_currency_exposure = max_currency_exposure
        self.daily_profit_target_usd = daily_profit_target_usd if daily_profit_target_usd is not None else 15.0
        self.leverage = leverage if leverage is not None else float(settings.raw_system.get("risk", {}).get("leverage", 500.0))

        self.current_calendar_day: Optional[str] = None
        self.current_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.daily_realized_loss: float = 0.0
        self.daily_realized_pnl: float = 0.0
        self.weekly_realized_loss: float = 0.0
        self.kill_switch_active: bool = False
        self.kill_switch_reason: str = ""
        self.emergency_kill_switch = EmergencyKillSwitch()

    def check_daily_reset(self, current_dt: datetime) -> bool:
        """
        Evaluates UTC calendar boundary.
        Unlatches kill switch and zeroes daily loss and daily realized PnL on UTC midnight transition,
        independent of whether any trade events occurred.
        """
        cal_day = current_dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
        if self.current_calendar_day is None:
            self.current_calendar_day = cal_day
            self.current_date = cal_day
            return False

        if cal_day != self.current_calendar_day:
            self.current_calendar_day = cal_day
            self.current_date = cal_day
            self.daily_realized_loss = 0.0
            self.daily_realized_pnl = 0.0
            if self.kill_switch_active and "DAILY_LOSS_LIMIT" in self.kill_switch_reason:
                self.kill_switch_active = False
                self.kill_switch_reason = ""
            return True
        return False

    def record_closed_trade(self, pnl_usd: float, close_dt: datetime):
        self.check_daily_reset(close_dt)
        self.daily_realized_pnl += pnl_usd
        if pnl_usd < 0:
            loss = abs(pnl_usd)
            self.daily_realized_loss += loss
            self.weekly_realized_loss += loss

            if self.daily_realized_loss >= self.daily_loss_limit:
                self.kill_switch_active = True
                self.kill_switch_reason = f"DAILY_LOSS_LIMIT_BREACHED: ${self.daily_realized_loss:.2f} >= ${self.daily_loss_limit:.2f}"

    def validate_signal(
        self,
        signal: Optional[Dict[str, Any]] = None,
        current_dt: Optional[datetime] = None,
        **kwargs
    ) -> SignalValidationResult:
        """
        Validates candidate trading signal against daily limits and circuit breakers.
        Rejects signal if daily profit target or loss limit is reached.
        """
        if current_dt is None and isinstance(signal, dict):
            if "current_dt" in signal:
                current_dt = signal["current_dt"]
            elif "timestamp" in signal:
                current_dt = datetime.fromtimestamp(signal["timestamp"], tz=timezone.utc)
            elif "datetime" in signal:
                current_dt = signal["datetime"]

        if current_dt is not None:
            self.check_daily_reset(current_dt)

        # 1. Daily Profit Target Check
        if self.daily_realized_pnl >= self.daily_profit_target_usd:
            return SignalValidationResult(
                RiskDecision.REJECT,
                "DAILY_PROFIT_TARGET_REACHED",
                f"Daily profit target reached: ${self.daily_realized_pnl:.2f} >= ${self.daily_profit_target_usd:.2f}"
            )

        # 2. Daily Loss Limit Check
        if self.daily_realized_pnl <= -self.daily_loss_limit:
            return SignalValidationResult(
                RiskDecision.REJECT,
                "DAILY_LOSS_LIMIT_REACHED",
                f"Daily loss limit reached: ${self.daily_realized_pnl:.2f} <= -${self.daily_loss_limit:.2f}"
            )

        if self.kill_switch_active:
            return SignalValidationResult(
                RiskDecision.REJECT, "GLOBAL_KILL_SWITCH_ACTIVE", self.kill_switch_reason
            )

        if self.emergency_kill_switch.is_kill_switch_active():
            return SignalValidationResult(
                RiskDecision.REJECT, "EMERGENCY_KILL_SWITCH_ACTIVE", self.emergency_kill_switch.reason
            )

        return SignalValidationResult(RiskDecision.APPROVE, "APPROVED", "Signal passed risk validation.")

    def calculate_position_size(
        self,
        account: AccountState,
        symbol: str,
        entry_price: float,
        sl_price: float
    ) -> Tuple[float, Optional[str]]:
        sym_cfg = settings.get_symbol_config(symbol)
        if sym_cfg is None:
            return 0.0, f"Unknown symbol: {symbol}"

        sl_distance = abs(entry_price - sl_price)
        if sl_distance <= 0:
            return 0.0, "Invalid stop loss: distance must be positive."

        sl_pips = sl_distance / sym_cfg.pip_size
        risk_capital_usd = account.equity * (self.max_risk_pct / 100.0)

        # Value per pip for 1.0 standard lot
        pip_value_std = sym_cfg.pip_value_usd
        raw_lot = risk_capital_usd / (sl_pips * pip_value_std + 1e-9)

        # Snap to lot step and enforce bounds
        lot_step = sym_cfg.lot_step
        snapped_lot = round(raw_lot / lot_step) * lot_step
        final_lot = float(np.clip(snapped_lot, sym_cfg.min_lot, sym_cfg.max_lot))

        # Margin check & Dynamic Margin Clamping for Micro-Wallets
        margin_per_lot = (sym_cfg.lot_size * entry_price) / self.leverage
        margin_required = final_lot * margin_per_lot

        if margin_required > account.free_margin:
            # Scale down to maximum lot affordable within free margin (with 5% buffer)
            max_affordable_lot = (account.free_margin * 0.95) / (margin_per_lot + 1e-9)
            # Snap down to nearest valid lot step
            max_affordable_snapped = math.floor(max_affordable_lot / lot_step) * lot_step
            max_affordable_snapped = round(max_affordable_snapped, 4)

            if max_affordable_snapped >= sym_cfg.min_lot:
                final_lot = min(final_lot, max_affordable_snapped)
            else:
                margin_for_min = sym_cfg.min_lot * margin_per_lot
                return 0.0, f"Insufficient free margin for min lot ({sym_cfg.min_lot}): required ${margin_for_min:.2f}, available ${account.free_margin:.2f}"

        return final_lot, None

    def validate_new_order(
        self,
        symbol: str,
        direction: str,
        current_spread_pips: float,
        account: AccountState,
        open_positions: List[Position],
        current_dt: datetime,
        is_news_blackout: bool = False
    ) -> Tuple[RiskDecision, str, str]:
        self.check_daily_reset(current_dt)

        # 1. Daily Profit Target Check
        if self.daily_realized_pnl >= self.daily_profit_target_usd:
            return (
                RiskDecision.REJECT,
                "DAILY_PROFIT_TARGET_REACHED",
                f"Daily profit target reached: ${self.daily_realized_pnl:.2f} >= ${self.daily_profit_target_usd:.2f}"
            )

        # 2. Daily Loss Limit Check
        if self.daily_realized_pnl <= -self.daily_loss_limit:
            return (
                RiskDecision.REJECT,
                "DAILY_LOSS_LIMIT_REACHED",
                f"Daily loss limit reached: ${self.daily_realized_pnl:.2f} <= -${self.daily_loss_limit:.2f}"
            )

        if self.kill_switch_active:
            return RiskDecision.REJECT, "GLOBAL_KILL_SWITCH_ACTIVE", self.kill_switch_reason

        if self.emergency_kill_switch.is_kill_switch_active():
            return RiskDecision.REJECT, "EMERGENCY_KILL_SWITCH_ACTIVE", self.emergency_kill_switch.reason

        if is_news_blackout:
            return RiskDecision.REJECT, "NEWS_BLACKOUT_ACTIVE", "High-impact economic event window active."



        sym_cfg = settings.get_symbol_config(symbol)
        if sym_cfg is None:
            return RiskDecision.REJECT, "UNKNOWN_SYMBOL", f"Symbol {symbol} not configured."

        # Spread check
        if current_spread_pips > sym_cfg.max_spread_pips:
            return (
                RiskDecision.REJECT,
                "SPREAD_LIMIT_EXCEEDED",
                f"Spread {current_spread_pips:.1f}p exceeds symbol max {sym_cfg.max_spread_pips:.1f}p"
            )

        # Max open positions count
        if len(open_positions) >= self.max_open_positions:
            return (
                RiskDecision.REJECT,
                "MAX_POSITIONS_REACHED",
                f"Open positions ({len(open_positions)}) >= limit ({self.max_open_positions})"
            )

        # Max drawdown check
        dd_pct = ((account.initial_balance - account.equity) / account.initial_balance) * 100.0
        if dd_pct >= settings.max_drawdown_pct:
            return (
                RiskDecision.REJECT,
                "MAX_DRAWDOWN_EXCEEDED",
                f"Account drawdown {dd_pct:.1f}% >= limit {settings.max_drawdown_pct:.1f}%"
            )

        # Currency exposure concentration check (applies to forex pairs only)
        if sym_cfg.asset_class == "forex":
            base_curr = sym_cfg.base_currency
            quote_curr = sym_cfg.quote_currency
            candidate_exposures = [
                (base_curr, "LONG" if direction == "BUY" else "SHORT"),
                (quote_curr, "SHORT" if direction == "BUY" else "LONG")
            ]

            for cand_curr, cand_side in candidate_exposures:
                if not cand_curr:
                    continue
                curr_count = 0
                for p in open_positions:
                    p_cfg = settings.get_symbol_config(p.symbol)
                    if not p_cfg or p_cfg.asset_class != "forex":
                        continue
                    p_base = p_cfg.base_currency
                    p_quote = p_cfg.quote_currency
                    p_base_side = "LONG" if p.direction == "BUY" else "SHORT"
                    p_quote_side = "SHORT" if p.direction == "BUY" else "LONG"

                    if (p_base == cand_curr and p_base_side == cand_side) or (p_quote == cand_curr and p_quote_side == cand_side):
                        curr_count += 1

                if curr_count >= self.max_currency_exposure:
                    return (
                        RiskDecision.REJECT,
                        "CURRENCY_CONCENTRATION_LIMIT",
                        f"Exceeds max allowed concurrent {cand_side} exposure to currency {cand_curr} ({curr_count} >= {self.max_currency_exposure})"
                    )

        return RiskDecision.APPROVE, "APPROVED", "All risk checks passed."
