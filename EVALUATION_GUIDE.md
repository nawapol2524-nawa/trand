# Model Evaluation Guide

## 1. Metrics Overview
The evaluation suite reports two distinct layers of performance:
1. **Statistical & Calibration Quality:**
   - Balanced Accuracy, F1 Macro, Precision / Recall per class
   - Brier Score: measures probability calibration accuracy (lower is better, < 0.10 is excellent)
2. **Economic & Trading Quality:**
   - Win rate on active model signals
   - Profit Factor: gross profit / gross loss
   - Maximum Drawdown
   - Annualized Sharpe and Sortino ratios
