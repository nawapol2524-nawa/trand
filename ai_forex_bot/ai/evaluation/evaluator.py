"""
Institutional Model Evaluation Engine
======================================
Computes multi-dimensional performance metrics:
- Classification metrics: Precision, Recall, F1, Balanced Accuracy, Brier Score, ROC-AUC
- Financial metrics: Win Rate, Average Net Return, Profit Factor, Sharpe Ratio, Sortino Ratio, Max Drawdown
"""

from typing import Dict, Any, Optional
import numpy as np
import pandas as pd
from sklearn.metrics import (
    precision_score, recall_score, f1_score, balanced_accuracy_score,
    brier_score_loss, log_loss
)


class ModelEvaluator:
    @staticmethod
    def evaluate(
        y_true: np.ndarray,
        y_pred: np.ndarray,
        y_proba: np.ndarray,
        future_returns: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        """
        Evaluates predictions against true labels and forward returns.
        """
        metrics: Dict[str, Any] = {}

        # 1. Classification Metrics
        metrics["balanced_accuracy"] = float(balanced_accuracy_score(y_true, y_pred))
        metrics["f1_macro"] = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
        metrics["precision_macro"] = float(precision_score(y_true, y_pred, average="macro", zero_division=0))
        metrics["recall_macro"] = float(recall_score(y_true, y_pred, average="macro", zero_division=0))

        # Per-class metrics (0=HOLD, 1=BUY, 2=SELL)
        for c in [0, 1, 2]:
            mask_true = (y_true == c)
            mask_pred = (y_pred == c)
            prec = float(precision_score(mask_true, mask_pred, zero_division=0))
            rec = float(recall_score(mask_true, mask_pred, zero_division=0))
            metrics[f"precision_class_{c}"] = prec
            metrics[f"recall_class_{c}"] = rec

        # Brier Score (multi-class one-vs-rest average)
        n_classes = y_proba.shape[1]
        brier_scores = []
        for c in range(n_classes):
            binary_true = (y_true == c).astype(int)
            brier_scores.append(brier_score_loss(binary_true, y_proba[:, c]))
        metrics["brier_score"] = float(np.mean(brier_scores))

        # 2. Trading Relevance Metrics
        if future_returns is not None:
            # Active trades: where model predicted BUY (1) or SELL (2)
            buy_mask = (y_pred == 1)
            sell_mask = (y_pred == 2)
            active_mask = buy_mask | sell_mask

            total_signals = int(active_mask.sum())
            metrics["total_signals"] = total_signals
            metrics["signal_rate"] = float(total_signals / len(y_true)) if len(y_true) > 0 else 0.0

            if total_signals > 0:
                trade_returns = np.zeros(total_signals)
                # For BUY: profit is positive return
                # For SELL: profit is negative return (short)
                trade_idx = 0
                for i in range(len(y_pred)):
                    if y_pred[i] == 1:
                        trade_returns[trade_idx] = future_returns[i]
                        trade_idx += 1
                    elif y_pred[i] == 2:
                        trade_returns[trade_idx] = -future_returns[i]
                        trade_idx += 1

                wins = trade_returns > 0
                win_rate = float(np.mean(wins))
                avg_ret = float(np.mean(trade_returns))

                gross_profits = trade_returns[trade_returns > 0].sum()
                gross_losses = np.abs(trade_returns[trade_returns < 0].sum())
                profit_factor = float(gross_profits / (gross_losses + 1e-9)) if gross_losses > 0 else 10.0

                # Cumulative return & Max Drawdown
                cum_ret = np.cumsum(trade_returns)
                peak = np.maximum.accumulate(cum_ret)
                dd = peak - cum_ret
                max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

                # Annualized Sharpe (assuming ~252 * 24 1-hour periods)
                ret_std = float(np.std(trade_returns))
                sharpe = float((avg_ret / (ret_std + 1e-9)) * np.sqrt(252 * 24)) if ret_std > 0 else 0.0

                downside = trade_returns[trade_returns < 0]
                downside_std = float(np.std(downside)) if len(downside) > 0 else 1e-9
                sortino = float((avg_ret / (downside_std + 1e-9)) * np.sqrt(252 * 24))

                metrics["win_rate"] = win_rate
                metrics["avg_return_per_trade"] = avg_ret
                metrics["profit_factor"] = profit_factor
                metrics["max_drawdown"] = max_dd
                metrics["sharpe_ratio"] = sharpe
                metrics["sortino_ratio"] = sortino
            else:
                metrics["win_rate"] = 0.0
                metrics["avg_return_per_trade"] = 0.0
                metrics["profit_factor"] = 0.0
                metrics["max_drawdown"] = 0.0
                metrics["sharpe_ratio"] = 0.0
                metrics["sortino_ratio"] = 0.0

        return metrics
