# Cost-Aware Backtesting & Simulation Architecture

## 1. Single-Semantic Alignment
The Backtest Engine (`ai_forex_bot.backtest.engine.BacktestEngine`) executes using the exact same `RiskEngine`, `OrderManager`, and `MetaDecisionEngine` modules as live execution.

## 2. Realistic Friction Models
- **Bid / Ask Spread:** BUY fills at Ask, SELL fills at Bid.
- **Broker Commissions:** \$6.00 per standard lot deducted upon position entry.
- **Execution Slippage:** Simulated randomized or constant slippage perturbations.
- **Daily Reset Invariance:** Simulates timeline clock progression, ensuring kill switch resets at UTC midnight.

## 3. Monte Carlo Robustness
The Monte Carlo Simulator (`ai_forex_bot.backtest.monte_carlo.MonteCarloSimulator`) performs 1,000 bootstrap resamplings of trade return sequences to yield 95% and 99% Value-at-Risk / Drawdown confidence bounds and Ruin Probabilities.
