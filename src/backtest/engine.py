"""
Backtest Engine — Gate 30 Implementation.
Replays historical M5 and H1 candles using frozen strategies, deterministic risk model,
and OfflineDeterministicAIProvider. Bit-for-bit deterministic and zero network calls.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from src.ai.context import AIContextBuilder
from src.ai.event_detector import EventDetector
from src.ai.provider import OfflineDeterministicAIProvider
from src.ai.validator import DeterministicGate
from src.core.models import Bar, Direction, Timeframe
from src.strategies import forex_trend_breakout, xau_mean_reversion


@dataclass
class BacktestConfig:
    initial_balance: float = 10000.0
    risk_per_trade_pct: float = 0.01        # 1.0% per trade (RISK_MODEL.md)
    max_daily_loss_pct: float = 0.05        # 5.0% daily drawdown limit (RISK_MODEL.md)
    max_consecutive_losses: int = 5         # 5 losses -> 1h halt
    max_open_positions: int = 3             # 3 concurrent open positions max
    atr_multiplier_sl: float = 1.5          # 1.5x ATR for SL
    rr_ratio: float = 2.0                   # 1:2 Risk-Reward ratio
    spread_multiplier: float = 1.0          # 1.0 (base), 1.25 (+25%), 1.50 (+50%), 2.0 (+100%)
    slippage_points: Dict[str, float] = field(default_factory=lambda: {
        "EURUSD": 0.0,
        "GBPUSD": 0.0,
        "USDJPY": 0.0,
        "XAUUSD": 0.0,
    })
    base_spreads: Dict[str, float] = field(default_factory=lambda: {
        "EURUSD": 0.00011,   # 1.1 pips
        "GBPUSD": 0.00012,   # 1.2 pips
        "USDJPY": 0.015,     # 1.5 pips
        "XAUUSD": 0.18,      # 18 cents
    })
    lot_sizes: Dict[str, float] = field(default_factory=lambda: {
        "EURUSD": 100000.0,
        "GBPUSD": 100000.0,
        "USDJPY": 100000.0,
        "XAUUSD": 100.0,
    })
    min_volume: float = 0.01
    max_volume: float = 10.0
    volume_step: float = 0.01


@dataclass
class PositionRecord:
    position_id: str
    symbol: str
    direction: Direction
    entry_time: datetime
    entry_price: float
    sl_price: float
    tp_price: float
    volume_lots: float
    volume_units: float
    spread_cost: float
    slippage_cost: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # 'SL', 'TP', 'END_OF_DATA'
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    r_multiple: float = 0.0
    duration_minutes: float = 0.0


@dataclass
class BacktestMetrics:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    expectancy_usd: float = 0.0
    expectancy_r: float = 0.0
    gross_profit_usd: float = 0.0
    gross_loss_usd: float = 0.0
    net_pnl_usd: float = 0.0
    net_pnl_pct: float = 0.0
    initial_balance: float = 10000.0
    ending_balance: float = 10000.0
    ending_equity: float = 10000.0
    max_drawdown_usd: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    avg_trade_duration_minutes: float = 0.0
    spread_multiplier: float = 1.0
    slippage_mode: str = "0.0"
    symbol_breakdown: Dict[str, Any] = field(default_factory=dict)
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)


def load_historical_bars(filepath: str, symbol: str, tf: Timeframe) -> List[Bar]:
    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)
    bars = []
    for r in raw:
        dt = datetime.fromtimestamp(r["timestamp"] / 1000, tz=timezone.utc)
        bars.append(Bar(
            symbol=symbol,
            timeframe=tf,
            timestamp=dt,
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=float(r.get("volume", 0.0)),
        ))
    return bars


class BacktestEngine:
    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.ai_provider = OfflineDeterministicAIProvider()

    def run(
        self,
        historical_dir: Optional[str] = None,
        symbols: Optional[List[str]] = None,
    ) -> tuple[BacktestMetrics, List[PositionRecord]]:
        if symbols is None:
            symbols = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]

        # Default path resolution: prefer data/historical, fallback to committed test fixture
        if historical_dir is None:
            if os.path.exists("data/historical") and os.path.isdir("data/historical"):
                historical_dir = "data/historical"
            else:
                fixture_dir = os.path.join(
                    os.path.dirname(__file__), "..", "..", "tests", "fixtures", "synthetic_backtest_data"
                )
                if os.path.exists(fixture_dir):
                    historical_dir = fixture_dir
                else:
                    historical_dir = "data/historical"

        # 1. Load historical bars for all symbols
        m5_data: Dict[str, List[Bar]] = {}
        h1_data: Dict[str, List[Bar]] = {}

        for sym in symbols:
            m5_path = os.path.join(historical_dir, f"{sym}_M5.json")
            h1_path = os.path.join(historical_dir, f"{sym}_H1.json")
            if os.path.exists(m5_path):
                m5_data[sym] = load_historical_bars(m5_path, sym, Timeframe.M5)
            if os.path.exists(h1_path):
                h1_data[sym] = load_historical_bars(h1_path, sym, Timeframe.H1)

        # 2. Extract unified sorted M5 timeline
        all_timestamps = set()
        for sym, bars in m5_data.items():
            for b in bars:
                all_timestamps.add(b.timestamp)
        timeline = sorted(list(all_timestamps))
        if not timeline:
            raise FileNotFoundError(
                f"No historical bar data found in '{historical_dir}' for symbols {symbols}."
            )

        # Index lookup maps: (sym, timestamp) -> bar
        bar_lookup: Dict[tuple[str, datetime], Bar] = {}
        for sym, bars in m5_data.items():
            for b in bars:
                bar_lookup[(sym, b.timestamp)] = b

        # 3. Initialize state
        balance = self.config.initial_balance
        equity = balance
        daily_starting_balance = balance
        daily_pnl = 0.0
        current_day: Optional[datetime.date] = None
        consecutive_losses = 0
        halt_until: Optional[datetime] = None

        open_positions: List[PositionRecord] = []
        closed_trades: List[PositionRecord] = []
        equity_curve: List[Dict[str, Any]] = []

        detectors: Dict[str, EventDetector] = {
            sym: EventDetector(cooldown_seconds=300.0) for sym in symbols
        }

        # Track bar history index per symbol
        m5_history: Dict[str, List[Bar]] = {sym: [] for sym in symbols}
        h1_history: Dict[str, List[Bar]] = {sym: [] for sym in symbols}

        # 4. Step-by-step chronological simulation
        pos_id_seq = 0

        for t in timeline:
            day_t = t.date()
            if current_day != day_t:
                # Daily UTC midnight reset
                current_day = day_t
                daily_starting_balance = balance
                daily_pnl = 0.0

            # Update histories with bars that closed at or before t
            for sym in symbols:
                b = bar_lookup.get((sym, t))
                if b is not None:
                    m5_history[sym].append(b)

                # Append H1 bars that closed by time t
                if sym in h1_data:
                    closed_h1 = [hb for hb in h1_data[sym] if hb.timestamp <= t]
                    h1_history[sym] = closed_h1

            # 4.1 Process Open Positions against current bar (t)
            remaining_positions: List[PositionRecord] = []
            for pos in open_positions:
                curr_bar = bar_lookup.get((pos.symbol, t))
                if curr_bar is None:
                    remaining_positions.append(pos)
                    continue

                spread = self.config.base_spreads[pos.symbol] * self.config.spread_multiplier
                slip = self.config.slippage_points.get(pos.symbol, 0.0)

                exit_triggered = False
                exit_price = 0.0
                exit_reason = ""

                if pos.direction == Direction.LONG:
                    # Check SL and TP
                    hit_sl = curr_bar.low <= pos.sl_price
                    hit_tp = curr_bar.high >= pos.tp_price

                    if hit_sl and hit_tp:
                        # Conservative worst-case: SL hits first
                        exit_triggered = True
                        exit_price = pos.sl_price - (spread / 2.0) - slip
                        exit_reason = "SL"
                    elif hit_sl:
                        exit_triggered = True
                        exit_price = pos.sl_price - (spread / 2.0) - slip
                        exit_reason = "SL"
                    elif hit_tp:
                        exit_triggered = True
                        exit_price = pos.tp_price - (spread / 2.0) - slip
                        exit_reason = "TP"

                elif pos.direction == Direction.SHORT:
                    hit_sl = curr_bar.high >= pos.sl_price
                    hit_tp = curr_bar.low <= pos.tp_price

                    if hit_sl and hit_tp:
                        exit_triggered = True
                        exit_price = pos.sl_price + (spread / 2.0) + slip
                        exit_reason = "SL"
                    elif hit_sl:
                        exit_triggered = True
                        exit_price = pos.sl_price + (spread / 2.0) + slip
                        exit_reason = "SL"
                    elif hit_tp:
                        exit_triggered = True
                        exit_price = pos.tp_price + (spread / 2.0) + slip
                        exit_reason = "TP"

                if exit_triggered:
                    pos.exit_time = t
                    pos.exit_price = exit_price
                    pos.exit_reason = exit_reason

                    # Compute PnL
                    lot_size = self.config.lot_sizes[pos.symbol]
                    if pos.symbol == "USDJPY":
                        # For USDJPY: (exit - entry) * lots * 100000 / exit_price
                        if pos.direction == Direction.LONG:
                            raw_pnl = (pos.exit_price - pos.entry_price) * pos.volume_lots * lot_size / pos.exit_price
                        else:
                            raw_pnl = (pos.entry_price - pos.exit_price) * pos.volume_lots * lot_size / pos.exit_price
                    else:
                        if pos.direction == Direction.LONG:
                            raw_pnl = (pos.exit_price - pos.entry_price) * pos.volume_lots * lot_size
                        else:
                            raw_pnl = (pos.entry_price - pos.exit_price) * pos.volume_lots * lot_size

                    pos.gross_pnl = round(raw_pnl, 2)
                    pos.net_pnl = pos.gross_pnl
                    sl_dist = abs(pos.entry_price - pos.sl_price)
                    if sl_dist > 0:
                        achieved_dist = (pos.exit_price - pos.entry_price) if pos.direction == Direction.LONG else (pos.entry_price - pos.exit_price)
                        pos.r_multiple = round(achieved_dist / sl_dist, 2)

                    pos.duration_minutes = (pos.exit_time - pos.entry_time).total_seconds() / 60.0

                    # Update account
                    balance += pos.net_pnl
                    daily_pnl += pos.net_pnl

                    if pos.net_pnl > 0:
                        consecutive_losses = 0
                    else:
                        consecutive_losses += 1
                        if consecutive_losses >= self.config.max_consecutive_losses:
                            halt_until = t + timedelta(hours=1)

                    closed_trades.append(pos)
                else:
                    remaining_positions.append(pos)

            open_positions = remaining_positions

            # 4.2 Evaluate New Entry Signals (if not halted and limits allow)
            is_halted = halt_until is not None and t < halt_until
            daily_loss_breached = (daily_pnl / daily_starting_balance) <= -self.config.max_daily_loss_pct if daily_starting_balance > 0 else False
            open_symbols = {p.symbol for p in open_positions}

            if not is_halted and not daily_loss_breached and len(open_positions) < self.config.max_open_positions:
                for sym in symbols:
                    if sym in open_symbols:
                        continue  # max 1 position per symbol
                    if len(open_positions) >= self.config.max_open_positions:
                        break

                    m5_hist = m5_history[sym]
                    min_bars = 55 if sym == "XAUUSD" else 222
                    if len(m5_hist) < min_bars:
                        continue

                    # Slice newest at index 0 for evaluate()
                    m5_slice = list(reversed(m5_hist))

                    sig = None
                    if sym == "XAUUSD":
                        h1_slice = list(reversed(h1_history[sym]))
                        if len(h1_slice) >= 51:
                            sig = xau_mean_reversion.evaluate(m5_slice, h1_slice, now=t)
                    else:
                        sig = forex_trend_breakout.evaluate(m5_slice, now=t)

                    if sig is not None:
                        # Build AIContext
                        ctx = AIContextBuilder.build(
                            symbol=sym,
                            timeframe=Timeframe.M5,
                            m5_bars=m5_slice,
                            account_risk_state={
                                "daily_pnl_pct": round(daily_pnl / daily_starting_balance, 4),
                                "kill_switch_active": False,
                            },
                            current_position={
                                "open_positions": len(open_positions),
                                "symbol_exposure": len(open_positions) / self.config.max_open_positions,
                            },
                            recent_trade_state={"consecutive_losses": consecutive_losses},
                            now=t,
                        )

                        # Event Detector
                        should_invoke, event = detectors[sym].should_invoke(ctx, now=t, force_review=True)
                        if should_invoke:
                            # AI Proposal Layer (Offline Rule-Based)
                            proposal = self.ai_provider.analyze(ctx)

                            # Deterministic Gatekeeper
                            val_res = DeterministicGate.validate(
                                proposal=proposal,
                                context=ctx,
                                max_daily_loss_pct=self.config.max_daily_loss_pct,
                                max_open_positions=self.config.max_open_positions,
                                now=t,
                            )

                            if val_res.passed and proposal.direction == sig.direction:
                                # Order Execution
                                spread = self.config.base_spreads[sym] * self.config.spread_multiplier
                                slip = self.config.slippage_points.get(sym, 0.0)

                                entry_price = (
                                    sig.price + (spread / 2.0) + slip
                                    if sig.direction == Direction.LONG
                                    else sig.price - (spread / 2.0) - slip
                                )

                                atr_val = ctx.atr
                                sl_dist = max(atr_val * self.config.atr_multiplier_sl, spread * 2.0)
                                tp_dist = sl_dist * self.config.rr_ratio

                                if sig.direction == Direction.LONG:
                                    sl_price = entry_price - sl_dist
                                    tp_price = entry_price + tp_dist
                                else:
                                    sl_price = entry_price + sl_dist
                                    tp_price = entry_price - tp_dist

                                # Position Sizing (RISK_MODEL.md: 1% risk)
                                risk_amount = balance * self.config.risk_per_trade_pct
                                lot_size = self.config.lot_sizes[sym]

                                if sym == "USDJPY":
                                    raw_lots = (risk_amount * entry_price) / (sl_dist * lot_size)
                                else:
                                    raw_lots = risk_amount / (sl_dist * lot_size)

                                # Clamp and step
                                clamped_lots = max(self.config.min_volume, min(self.config.max_volume, raw_lots))
                                final_lots = round(clamped_lots / self.config.volume_step) * self.config.volume_step
                                final_lots = round(final_lots, 2)

                                pos_id_seq += 1
                                pos = PositionRecord(
                                    position_id=f"POS_{pos_id_seq:05d}",
                                    symbol=sym,
                                    direction=sig.direction,
                                    entry_time=t,
                                    entry_price=entry_price,
                                    sl_price=sl_price,
                                    tp_price=tp_price,
                                    volume_lots=final_lots,
                                    volume_units=final_lots * lot_size,
                                    spread_cost=spread * final_lots * lot_size,
                                    slippage_cost=slip * final_lots * lot_size,
                                )
                                open_positions.append(pos)
                                open_symbols.add(sym)

            # Record floating equity
            unrealized_pnl = 0.0
            for pos in open_positions:
                curr_bar = bar_lookup.get((pos.symbol, t))
                if curr_bar is not None:
                    lot_size = self.config.lot_sizes[pos.symbol]
                    if pos.symbol == "USDJPY":
                        if pos.direction == Direction.LONG:
                            unrealized_pnl += (curr_bar.close - pos.entry_price) * pos.volume_lots * lot_size / curr_bar.close
                        else:
                            unrealized_pnl += (pos.entry_price - curr_bar.close) * pos.volume_lots * lot_size / curr_bar.close
                    else:
                        if pos.direction == Direction.LONG:
                            unrealized_pnl += (curr_bar.close - pos.entry_price) * pos.volume_lots * lot_size
                        else:
                            unrealized_pnl += (pos.entry_price - curr_bar.close) * pos.volume_lots * lot_size

            equity = balance + unrealized_pnl
            equity_curve.append({
                "timestamp": t.isoformat(),
                "balance": round(balance, 2),
                "equity": round(equity, 2),
                "open_positions": len(open_positions),
            })

        # 5. Close any remaining open positions at the end of simulation
        last_t = timeline[-1]
        for pos in open_positions:
            curr_bar = bar_lookup.get((pos.symbol, last_t))
            if curr_bar is not None:
                spread = self.config.base_spreads[pos.symbol] * self.config.spread_multiplier
                slip = self.config.slippage_points.get(pos.symbol, 0.0)
                exit_price = curr_bar.close - (spread / 2.0) - slip if pos.direction == Direction.LONG else curr_bar.close + (spread / 2.0) + slip
                pos.exit_time = last_t
                pos.exit_price = exit_price
                pos.exit_reason = "END_OF_DATA"

                lot_size = self.config.lot_sizes[pos.symbol]
                if pos.symbol == "USDJPY":
                    raw_pnl = (pos.exit_price - pos.entry_price) * pos.volume_lots * lot_size / pos.exit_price if pos.direction == Direction.LONG else (pos.entry_price - pos.exit_price) * pos.volume_lots * lot_size / pos.exit_price
                else:
                    raw_pnl = (pos.exit_price - pos.entry_price) * pos.volume_lots * lot_size if pos.direction == Direction.LONG else (pos.entry_price - pos.exit_price) * pos.volume_lots * lot_size

                pos.gross_pnl = round(raw_pnl, 2)
                pos.net_pnl = pos.gross_pnl
                sl_dist = abs(pos.entry_price - pos.sl_price)
                if sl_dist > 0:
                    achieved_dist = (pos.exit_price - pos.entry_price) if pos.direction == Direction.LONG else (pos.entry_price - pos.exit_price)
                    pos.r_multiple = round(achieved_dist / sl_dist, 2)
                pos.duration_minutes = (pos.exit_time - pos.entry_time).total_seconds() / 60.0
                balance += pos.net_pnl
                closed_trades.append(pos)

        # 6. Compute Comprehensive Statistical Metrics
        metrics = self._calculate_metrics(
            trades=closed_trades,
            equity_curve=equity_curve,
            initial_balance=self.config.initial_balance,
            final_balance=balance,
            spread_mult=self.config.spread_multiplier,
            slip_desc=str(list(self.config.slippage_points.values())[0]),
        )
        return metrics, closed_trades

    def _calculate_metrics(
        self,
        trades: List[PositionRecord],
        equity_curve: List[Dict[str, Any]],
        initial_balance: float,
        final_balance: float,
        spread_mult: float,
        slip_desc: str,
    ) -> BacktestMetrics:
        total = len(trades)
        if total == 0:
            return BacktestMetrics(
                initial_balance=initial_balance,
                ending_balance=final_balance,
                ending_equity=final_balance,
                spread_multiplier=spread_mult,
                slippage_mode=slip_desc,
                equity_curve=equity_curve,
            )

        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]
        n_wins = len(wins)
        n_losses = len(losses)
        win_rate = (n_wins / total) * 100.0

        gross_profit = sum(t.net_pnl for t in wins)
        gross_loss = abs(sum(t.net_pnl for t in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        net_pnl = final_balance - initial_balance
        net_pnl_pct = (net_pnl / initial_balance) * 100.0

        expectancy_usd = net_pnl / total
        expectancy_r = sum(t.r_multiple for t in trades) / total

        # Max Drawdown from equity curve
        peak = initial_balance
        max_dd_usd = 0.0
        max_dd_pct = 0.0
        for pt in equity_curve:
            eq = pt["equity"]
            if eq > peak:
                peak = eq
            dd_usd = peak - eq
            dd_pct = (dd_usd / peak) * 100.0 if peak > 0 else 0.0
            if dd_usd > max_dd_usd:
                max_dd_usd = dd_usd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        # Consecutive streaks
        max_consec_losses = 0
        curr_consec_losses = 0
        max_consec_wins = 0
        curr_consec_wins = 0
        for t in trades:
            if t.net_pnl <= 0:
                curr_consec_losses += 1
                curr_consec_wins = 0
                if curr_consec_losses > max_consec_losses:
                    max_consec_losses = curr_consec_losses
            else:
                curr_consec_wins += 1
                curr_consec_losses = 0
                if curr_consec_wins > max_consec_wins:
                    max_consec_wins = curr_consec_wins

        # Sharpe and Sortino ratios based on trade returns
        trade_returns = [t.net_pnl / initial_balance for t in trades]
        mean_ret = np.mean(trade_returns)
        std_ret = np.std(trade_returns)
        neg_returns = [r for r in trade_returns if r < 0]
        downside_std = np.std(neg_returns) if neg_returns else 1e-6

        # Annualization factor: assuming ~250 trading days, ~10 trades/day
        annual_factor = math.sqrt(250 * 5)
        sharpe = float((mean_ret / std_ret) * annual_factor) if std_ret > 1e-8 else 0.0
        sortino = float((mean_ret / downside_std) * annual_factor) if downside_std > 1e-8 else 0.0

        durations = [t.duration_minutes for t in trades]
        avg_dur = float(np.mean(durations)) if durations else 0.0

        # Per symbol breakdown
        symbols = sorted(list(set(t.symbol for t in trades)))
        sym_breakdown = {}
        for s in symbols:
            s_trades = [t for t in trades if t.symbol == s]
            s_wins = [t for t in s_trades if t.net_pnl > 0]
            s_losses = [t for t in s_trades if t.net_pnl <= 0]
            s_gross_p = sum(t.net_pnl for t in s_wins)
            s_gross_l = abs(sum(t.net_pnl for t in s_losses))
            s_pf = (s_gross_p / s_gross_l) if s_gross_l > 0 else (99.0 if s_gross_p > 0 else 0.0)
            sym_breakdown[s] = {
                "trades": len(s_trades),
                "wins": len(s_wins),
                "losses": len(s_losses),
                "win_rate_pct": round((len(s_wins) / len(s_trades)) * 100.0, 2),
                "profit_factor": round(s_pf, 2),
                "gross_profit_usd": round(s_gross_p, 2),
                "gross_loss_usd": round(s_gross_l, 2),
                "net_pnl_usd": round(sum(t.net_pnl for t in s_trades), 2),
                "avg_duration_minutes": round(float(np.mean([t.duration_minutes for t in s_trades])), 1) if s_trades else 0.0,
            }

        return BacktestMetrics(
            total_trades=total,
            winning_trades=n_wins,
            losing_trades=n_losses,
            win_rate_pct=round(win_rate, 2),
            profit_factor=round(profit_factor, 2),
            expectancy_usd=round(expectancy_usd, 2),
            expectancy_r=round(expectancy_r, 2),
            gross_profit_usd=round(gross_profit, 2),
            gross_loss_usd=round(gross_loss, 2),
            net_pnl_usd=round(net_pnl, 2),
            net_pnl_pct=round(net_pnl_pct, 2),
            initial_balance=round(initial_balance, 2),
            ending_balance=round(final_balance, 2),
            ending_equity=round(final_balance, 2),
            max_drawdown_usd=round(max_dd_usd, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            max_consecutive_losses=max_consec_losses,
            max_consecutive_wins=max_consec_wins,
            avg_trade_duration_minutes=round(avg_dur, 1),
            spread_multiplier=spread_mult,
            slippage_mode=slip_desc,
            symbol_breakdown=sym_breakdown,
            equity_curve=equity_curve,
        )


def run_full_suite() -> Dict[str, Any]:
    """Runs baseline backtest and cost stress test variants."""
    stress_scenarios = [
        ("BASE_COST", 1.0, 0.0),
        ("SPREAD_PLUS_25PCT", 1.25, 0.0),
        ("SPREAD_PLUS_50PCT", 1.50, 0.0),
        ("SPREAD_PLUS_100PCT", 2.00, 0.0),
        ("SLIPPAGE_HALF_PIP", 1.0, 0.00005),
        ("SLIPPAGE_ONE_PIP", 1.0, 0.00010),
        ("SLIPPAGE_TWO_PIPS", 1.0, 0.00020),
        ("WORST_CASE_STRESS", 2.0, 0.00020),
    ]

    all_results = {}
    for name, sp_mult, slip in stress_scenarios:
        slip_dict = {
            "EURUSD": slip,
            "GBPUSD": slip,
            "USDJPY": slip * 100.0,
            "XAUUSD": slip * 100.0,
        }
        cfg = BacktestConfig(
            spread_multiplier=sp_mult,
            slippage_points=slip_dict,
        )
        engine = BacktestEngine(cfg)
        metrics, trades = engine.run()
        all_results[name] = {
            "metrics": asdict(metrics),
            "trades_count": len(trades),
        }

    return all_results


if __name__ == "__main__":
    cfg = BacktestConfig()
    engine = BacktestEngine(cfg)
    metrics, trades = engine.run()
    print("=== BASELINE FROZEN BACKTEST RESULTS ===")
    print(f"Total Trades: {metrics.total_trades}")
    print(f"Win Rate: {metrics.win_rate_pct}% ({metrics.winning_trades}W / {metrics.losing_trades}L)")
    print(f"Profit Factor: {metrics.profit_factor}")
    print(f"Net PnL: ${metrics.net_pnl_usd:.2f} ({metrics.net_pnl_pct:.2f}%)")
    print(f"Expectancy: ${metrics.expectancy_usd:.2f} | {metrics.expectancy_r:.2f}R")
    print(f"Max Drawdown: ${metrics.max_drawdown_usd:.2f} ({metrics.max_drawdown_pct:.2f}%)")
    print(f"Sharpe Ratio: {metrics.sharpe_ratio} | Sortino: {metrics.sortino_ratio}")
    print(f"Max Consecutive Losses: {metrics.max_consecutive_losses}")
    print(f"Avg Trade Duration: {metrics.avg_trade_duration_minutes:.1f} mins")
    print("Symbol Breakdown:", json.dumps(metrics.symbol_breakdown, indent=2))
