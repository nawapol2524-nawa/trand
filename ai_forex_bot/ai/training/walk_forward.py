"""
Walk-Forward Time Series Validator
==================================
Performs rolling window out-of-sample evaluation:
[Train Window] ➔ [Validate] ➔ [Step Forward] ➔ [Train Window] ➔ ...
"""

from typing import List, Dict, Any
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from ai_forex_bot.ai.models.base import HistGradientBoostingModel
from ai_forex_bot.ai.evaluation.evaluator import ModelEvaluator


class WalkForwardValidator:
    def __init__(
        self,
        n_splits: int = 4,
        train_window_bars: int = 8000,
        test_window_bars: int = 2000
    ):
        self.n_splits = n_splits
        self.train_window_bars = train_window_bars
        self.test_window_bars = test_window_bars

    def validate(self, df_labeled: pd.DataFrame) -> List[Dict[str, Any]]:
        meta_cols = {
            "epoch", "regime", "econ_policy", "target_class",
            "future_return", "future_net_buy", "future_net_sell"
        }
        feature_cols = [c for c in df_labeled.columns if c not in meta_cols]

        X = df_labeled[feature_cols].values
        y = df_labeled["target_class"].values
        f_rets = df_labeled["future_return"].values

        total_bars = len(df_labeled)
        results = []

        step_size = (total_bars - self.train_window_bars - self.test_window_bars) // max(self.n_splits - 1, 1)

        for i in range(self.n_splits):
            start_train = i * step_size
            end_train = start_train + self.train_window_bars
            start_test = end_train
            end_test = min(start_test + self.test_window_bars, total_bars)

            if end_test <= start_test:
                break

            X_tr, y_tr = X[start_train:end_train], y[start_train:end_train]
            X_te, y_te = X[start_test:end_test], y[start_test:end_test]
            f_te = f_rets[start_test:end_test]

            scaler = StandardScaler()
            X_tr_s = scaler.fit_transform(X_tr)
            X_te_s = scaler.transform(X_te)

            model = HistGradientBoostingModel({"random_state": 42 + i})
            model.fit(X_tr_s, y_tr, feature_names=feature_cols)

            preds = model.predict(X_te_s)
            probas = model.predict_proba(X_te_s)
            metrics = ModelEvaluator.evaluate(y_te, preds, probas, future_returns=f_te)

            results.append({
                "split_index": i,
                "train_bars": len(X_tr),
                "test_bars": len(X_te),
                "test_start_epoch": int(df_labeled["epoch"].iloc[start_test]),
                "test_end_epoch": int(df_labeled["epoch"].iloc[end_test - 1]),
                "metrics": metrics
            })

        return results
