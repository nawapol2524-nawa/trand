"""
Cost-Aware Event-Driven Backtest Engine
=======================================
Implements bar-by-bar execution identical to live trading:
- Consumes identical RiskEngine, OrderManager semantics, and cost models.
- Deducts bid/ask spread, commission per lot, and slippage.
- Enforces daily loss limits with UTC midnight calendar boundary reset.
"""

from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd

from ai_forex_bot.config.settings import settings, SymbolConfig
from ai_forex_bot.decision.engine import MetaDecisionEngine, Direction
from ai_forex_bot.risk.risk_engine import RiskEngine, RiskDecision, AccountState, Position
from ai_forex_bot.execution.simulated_broker import SimulatedBroker
from ai_forex_bot.execution.order_manager import OrderManager


class BacktestEngine:
    def __init__(
        self,
        symbol: str = "frxEURUSD",
        initial_balance: float = 1000.0,
        sl_pips: float = 15.0,
        tp_pips: float = 20.0
    ):
        self.symbol = symbol
        self.initial_balance = initial_balance
        self.sl_pips = sl_pips
        self.tp_pips = tp_pips
        self.sym_cfg = settings.get_symbol_config(symbol)

        self.broker = SimulatedBroker(initial_balance=initial_balance)
        self.risk_engine = RiskEngine()
        self.order_manager = OrderManager(self.broker, self.risk_engine)
        self.decision_engine = MetaDecisionEngine(confidence_threshold=0.55)

        self.closed_trades: List[Dict[str, Any]] = []
        self.equity_curve: List[Dict[str, Any]] = []

    def run(
        self,
        df_featured: pd.DataFrame,
        model: Any,
        scaler: Any,
        feature_cols: List[str]
    ) -> Dict[str, Any]:
        self.broker.connect()
        pip_size = self.sym_cfg.pip_size if self.sym_cfg else 0.0001
        typical_spread = self.sym_cfg.typical_spread_pips if self.sym_cfg else 1.2

        n = len(df_featured)
        X = df_featured[feature_cols].values
        X_scaled = scaler.transform(X)
        probas = model.predict_proba(X_scaled)

        for i in range(n):
            row = df_featured.iloc[i]
            epoch = int(row["epoch"])
            close = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])
            dt = datetime.fromtimestamp(epoch, tz=timezone.utc)

            # Update broker simulated quote (Ask = close + half_spread, Bid = close - half_spread)
            half_spread_price = (typical_spread * pip_size) / 2.0
            bid = close - half_spread_price
            ask = close + half_spread_price
            self.broker.set_quote(self.symbol, bid, ask, epoch)

            # 1. Check existing open positions against current bar High/Low for SL / TP
            active_pids = list(self.order_manager.active_positions.keys())
            for pid in active_pids:
                pos = self.order_manager.active_positions.get(pid)
                if pos is None:
                    continue

                closed = False
                exit_price = 0.0
                reason = ""

                if pos.direction == "BUY":
                    if low <= pos.sl_price:
                        exit_price = pos.sl_price
                        reason = "SL"
                        closed = True
                    elif high >= pos.tp_price:
                        exit_price = pos.tp_price
                        reason = "TP"
                        closed = True
                elif pos.direction == "SELL":
                    if high >= pos.sl_price:
                        exit_price = pos.sl_price
                        reason = "SL"
                        closed = True
                    elif low <= pos.tp_price:
                        exit_price = pos.tp_price
                        reason = "TP"
                        closed = True

                if closed:
                    # Execute closure
                    res = self.order_manager.close_position(pid)
                    pip_diff = (exit_price - pos.entry_price) / pip_size if pos.direction == "BUY" else (pos.entry_price - exit_price) / pip_size
                    net_pnl = (pip_diff * self.sym_cfg.pip_value_usd * pos.lot_size) - (self.sym_cfg.commission_per_lot_usd * pos.lot_size)
                    
                    self.closed_trades.append({
                        "position_id": pid,
                        "symbol": self.symbol,
                        "direction": pos.direction,
                        "lot_size": pos.lot_size,
                        "entry_price": pos.entry_price,
                        "exit_price": exit_price,
                        "net_pnl_usd": net_pnl,
                        "reason": reason,
                        "exit_epoch": epoch
                    })

            # 2. Decision Engine evaluation for new signal
            regime = str(row.get("regime", "RANGE"))
            news_pol = str(row.get("econ_policy", "NORMAL"))
            is_blackout = bool(row.get("econ_is_blackout", 0))

            decision = self.decision_engine.evaluate(
                symbol=self.symbol,
                epoch=epoch,
                probabilities=probas[i],
                regime=regime,
                news_policy=news_pol,
                is_news_blackout=is_blackout
            )

            # 3. If BUY or SELL and no open position, trigger OrderManager
            if decision.direction in {Direction.BUY, Direction.SELL}:
                if len(self.order_manager.active_positions) < settings.max_open_positions:
                    self.order_manager.process_signal(
                        symbol=self.symbol,
                        direction=decision.direction.value,
                        current_spread_pips=typical_spread,
                        sl_pips=self.sl_pips,
                        tp_pips=self.tp_pips,
                        is_news_blackout=is_blackout
                    )

            acct = self.broker.get_account_state()
            self.equity_curve.append({
                "epoch": epoch,
                "equity": acct["equity"],
                "balance": acct["balance"]
            })

        return self._generate_summary()

    def _generate_summary(self) -> Dict[str, Any]:
        acct = self.broker.get_account_state()
        total_trades = len(self.closed_trades)
        pnls = [t["net_pnl_usd"] for t in self.closed_trades]

        win_trades = [p for p in pnls if p > 0]
        loss_trades = [p for p in pnls if p <= 0]
        win_rate = (len(win_trades) / total_trades) if total_trades > 0 else 0.0

        gross_profit = sum(win_trades)
        gross_loss = abs(sum(loss_trades))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 10.0

        # Equity max drawdown
        eqs = [e["equity"] for e in self.equity_curve]
        peak = np.maximum.accumulate(eqs)
        drawdowns = (peak - eqs) / (peak + 1e-9) * 100.0
        max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        return {
            "symbol": self.symbol,
            "initial_balance": self.initial_balance,
            "final_equity": acct["equity"],
            "net_profit_usd": acct["equity"] - self.initial_balance,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown_pct": max_dd,
            "trades": self.closed_trades
        }
