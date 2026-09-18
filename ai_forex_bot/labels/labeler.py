"""
Cost-Aware Target & Labeling Engine
===================================
Produces realistic, fee-adjusted directional labels:
- Deducts round-trip spread, brokerage commissions, and execution slippage.
- Generates 3-class target: BUY (1), HOLD (0), SELL (-1 or 2).
- Triple-barrier horizon evaluation (profit target vs stop loss vs time expiration).
"""

from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd

from ai_forex_bot.config.settings import settings


@dataclass
class LabelConfig:
    horizon_bars: int = 4  # 4 bars on M15 = 1 hour horizon
    profit_target_pips: float = 15.0
    stop_loss_pips: float = 15.0
    min_edge_ratio: float = 1.5  # Required gross move / round-trip cost ratio


class CostAwareLabeler:
    def __init__(self, config: Optional[LabelConfig] = None):
        self.config = config or LabelConfig()

    def label_dataset(
        self,
        df: pd.DataFrame,
        symbol: str = "frxEURUSD",
        target_mode: str = "triple_barrier"
    ) -> pd.DataFrame:
        """
        Appends target labels to feature dataframe:
        - future_return: Raw price return over horizon H
        - future_net_return_buy: Expected return for long position after costs
        - future_net_return_sell: Expected return for short position after costs
        - target_class: 1 (BUY), -1 or 2 (SELL), 0 (HOLD)
        """
        df = df.copy().sort_values("epoch").reset_index(drop=True)
        sym_cfg = settings.get_symbol_config(symbol)
        pip_size = sym_cfg.pip_size if sym_cfg else 0.0001
        typical_spread = sym_cfg.typical_spread_pips if sym_cfg else 1.2
        commission_pips = (sym_cfg.commission_per_lot_usd / sym_cfg.pip_value_usd) if sym_cfg else 0.6
        slippage_pips = 0.2  # conservative slippage assumption

        round_trip_cost_pips = typical_spread + commission_pips + slippage_pips
        round_trip_cost_price = round_trip_cost_pips * pip_size

        close = df["close"]
        high = df["high"]
        low = df["low"]
        H = self.config.horizon_bars
        n = len(df)

        targets = np.zeros(n, dtype=int)
        raw_future_returns = np.zeros(n, dtype=float)
        net_buy_returns = np.zeros(n, dtype=float)
        net_sell_returns = np.zeros(n, dtype=float)

        pt_price = self.config.profit_target_pips * pip_size
        sl_price = self.config.stop_loss_pips * pip_size

        for i in range(n - H):
            c0 = close.iloc[i]
            window_high = high.iloc[i+1 : i+1+H].max()
            window_low = low.iloc[i+1 : i+1+H].min()
            c_end = close.iloc[i+H]

            raw_ret = (c_end - c0) / c0
            raw_future_returns[i] = raw_ret

            # Net return calculations
            net_buy = (c_end - c0 - round_trip_cost_price) / c0
            net_sell = (c0 - c_end - round_trip_cost_price) / c0
            net_buy_returns[i] = net_buy
            net_sell_returns[i] = net_sell

            if target_mode == "triple_barrier":
                # Check if upper profit barrier hit before lower stop barrier
                max_favorable_buy = window_high - c0
                max_adverse_buy = c0 - window_low

                max_favorable_sell = c0 - window_low
                max_adverse_sell = window_high - c0

                if max_favorable_buy >= pt_price and max_adverse_buy < sl_price:
                    targets[i] = 1  # BUY
                elif max_favorable_sell >= pt_price and max_adverse_sell < sl_price:
                    targets[i] = 2  # SELL (using 2 for multi-class classifiers: 0=HOLD, 1=BUY, 2=SELL)
                else:
                    targets[i] = 0  # HOLD
            else:
                # Fixed threshold mode
                min_edge = round_trip_cost_price * self.config.min_edge_ratio
                if (c_end - c0) > min_edge:
                    targets[i] = 1
                elif (c0 - c_end) > min_edge:
                    targets[i] = 2
                else:
                    targets[i] = 0

        # Mask out final H bars where future outcome is unobservable (avoid NaN contamination)
        valid_mask = np.arange(n) < (n - H)
        df["future_return"] = raw_future_returns
        df["future_net_buy"] = net_buy_returns
        df["future_net_sell"] = net_sell_returns
        df["target_class"] = targets

        df = df.iloc[:-H].copy()
        df.reset_index(drop=True, inplace=True)
        return df
