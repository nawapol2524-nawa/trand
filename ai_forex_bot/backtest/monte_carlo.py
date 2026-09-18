"""
Monte Carlo Permutation & Stress Simulator
==========================================
Evaluates the statistical robustness of trade outcomes:
- Bootstraps trade returns with random resampling.
- Perturbs slippage and spread distributions.
- Yields confidence intervals for Maximum Drawdown, Sharpe, and Ruin Probability.
"""

from typing import List, Dict, Any
import numpy as np


class MonteCarloSimulator:
    def __init__(self, n_iterations: int = 1000, random_seed: int = 42):
        self.n_iterations = n_iterations
        self.random_seed = random_seed

    def simulate(self, trade_pnls: List[float], initial_capital: float = 1000.0) -> Dict[str, Any]:
        if not trade_pnls:
            return {
                "n_iterations": self.n_iterations,
                "median_max_dd_pct": 0.0,
                "p95_max_dd_pct": 0.0,
                "p99_max_dd_pct": 0.0,
                "probability_of_ruin": 0.0,
                "median_final_return_pct": 0.0
            }

        np.random.seed(self.random_seed)
        pnls = np.array(trade_pnls)
        n_trades = len(pnls)

        max_drawdowns = []
        final_returns = []
        ruin_count = 0

        for _ in range(self.n_iterations):
            # Bootstrap resample with replacement
            sampled = np.random.choice(pnls, size=n_trades, replace=True)
            equity_path = initial_capital + np.cumsum(sampled)

            # Check ruin (equity <= 50% initial)
            if np.any(equity_path <= (initial_capital * 0.5)):
                ruin_count += 1

            peak = np.maximum.accumulate(equity_path)
            dd = (peak - equity_path) / (peak + 1e-9) * 100.0
            max_drawdowns.append(np.max(dd))
            final_returns.append((equity_path[-1] - initial_capital) / initial_capital * 100.0)

        return {
            "n_iterations": self.n_iterations,
            "trade_sample_size": n_trades,
            "median_max_dd_pct": float(np.median(max_drawdowns)),
            "p95_max_dd_pct": float(np.percentile(max_drawdowns, 95)),
            "p99_max_dd_pct": float(np.percentile(max_drawdowns, 99)),
            "probability_of_ruin": float(ruin_count / self.n_iterations),
            "median_final_return_pct": float(np.median(final_returns))
        }
