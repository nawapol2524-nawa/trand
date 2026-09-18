"""
Purged & Embargoed Walk-Forward Time Series Validator
=====================================================
Performs rolling window out-of-sample evaluation with strict horizon purging:
[Train Window] ➔ [Purge Gap >= H] ➔ [Embargo] ➔ [Test Window] ➔ [Step Forward]
"""

from typing import List, Dict, Any, Optional
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
        test_window_bars: int = 2000,
        horizon_bars: int = 4,
        embargo_bars: int = 0
    ):
        self.n_splits = n_splits
        self.train_window_bars = train_window_bars
        self.test_window_bars = test_window_bars
        self.horizon_bars = horizon_bars
        self.embargo_bars = embargo_bars

    def validate(
        self,
        df_labeled: pd.DataFrame,
        model_cls: Any = HistGradientBoostingModel,
        model_params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        meta_cols = {
            "epoch", "regime", "econ_policy", "target_class",
            "future_return", "future_net_buy", "future_net_sell"
        }
        feature_cols = [c for c in df_labeled.columns if c not in meta_cols]

        X = df_labeled[feature_cols].values
        y = df_labeled["target_class"].values
        f_rets = df_labeled["future_return"].values
        epochs = df_labeled["epoch"].values

        total_bars = len(df_labeled)
        results = []

        total_split_span = self.train_window_bars + self.embargo_bars + self.test_window_bars
        step_size = (total_bars - total_split_span) // max(self.n_splits - 1, 1)

        for i in range(self.n_splits):
            start_train = i * step_size
            raw_end_train = start_train + self.train_window_bars
            safe_end_train = max(start_train, raw_end_train - self.horizon_bars)
            purged_bars = raw_end_train - safe_end_train

            start_test = raw_end_train + self.embargo_bars
            raw_end_test = min(start_test + self.test_window_bars, total_bars)
            safe_end_test = max(start_test, raw_end_test - self.horizon_bars)

            if safe_end_test <= start_test or safe_end_train <= start_train:
                break

            X_tr, y_tr = X[start_train:safe_end_train], y[start_train:safe_end_train]
            X_te, y_te = X[start_test:safe_end_test], y[start_test:safe_end_test]
            f_te = f_rets[start_test:safe_end_test]

            scaler = StandardScaler()
            X_tr_s = scaler.fit_transform(X_tr)
            X_te_s = scaler.transform(X_te)

            params = {"random_state": 42 + i}
            if model_params:
                params.update(model_params)

            model = model_cls(params)
            model.fit(X_tr_s, y_tr, feature_names=feature_cols)

            preds = model.predict(X_te_s)
            probas = model.predict_proba(X_te_s)
            metrics = ModelEvaluator.evaluate(y_te, preds, probas, future_returns=f_te)

            # Strict causality timestamps
            train_last_bar_idx = safe_end_train - 1
            train_target_max_epoch = int(epochs[train_last_bar_idx + self.horizon_bars])
            test_start_epoch = int(epochs[start_test])
            leak_free = bool(train_target_max_epoch < test_start_epoch)

            results.append({
                "split_index": i,
                "train_start_bar": start_train,
                "train_end_bar": safe_end_train,
                "train_bars": len(X_tr),
                "purge_gap_bars": purged_bars,
                "embargo_bars": self.embargo_bars,
                "test_start_bar": start_test,
                "test_end_bar": safe_end_test,
                "test_bars": len(X_te),
                "train_target_max_epoch": train_target_max_epoch,
                "test_start_epoch": test_start_epoch,
                "leak_free": leak_free,
                "metrics": metrics
            })

        return results
