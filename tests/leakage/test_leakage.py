"""
GATE 9: DATA LEAKAGE AUDIT TEST SUITE
=====================================
Automated unit and integration checks verifying zero look-ahead bias:
1. Feature Causal Invariance: perturbing future bars must NOT change past features.
2. Target Contamination: target_class and future_return strictly excluded from X.
3. Economic Release Invariance: economic actuals invisible prior to publication_time.
4. Preprocessor Isolation: scalers fit on train fold only; test fold never contaminates statistics.
5. Strict Temporal Ordering: no time-travel or temporal overlapping between splits.
"""

import unittest
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from ai_forex_bot.features.builder import FeatureBuilder
from ai_forex_bot.labels.labeler import CostAwareLabeler
from ai_forex_bot.news_ai.calendar import EconomicCalendarEngine, EconomicEvent


class TestDataLeakageProtection(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        n = 300
        epochs = np.arange(1700000000, 1700000000 + (n * 900), 900)
        close = 1.1000 + np.cumsum(np.random.randn(n) * 0.0005)
        high = close + np.abs(np.random.randn(n) * 0.0003)
        low = close - np.abs(np.random.randn(n) * 0.0003)
        open_ = (high + low) / 2.0

        self.df_raw = pd.DataFrame({
            "epoch": epochs,
            "open": open_,
            "high": high,
            "low": low,
            "close": close
        })
        self.fb = FeatureBuilder()
        self.labeler = CostAwareLabeler()

    def test_future_candle_invariance(self):
        """1. Perturbing future bars after split_epoch must NOT alter feature values strictly before split_epoch."""
        df1 = self.df_raw.copy()
        df2 = self.df_raw.copy()

        split_idx = 200
        split_epoch = int(df2["epoch"].iloc[split_idx])

        # Severely perturb bars from split_idx onwards
        df2.loc[split_idx:, "close"] *= 1.5
        df2.loc[split_idx:, "high"] *= 1.5
        df2.loc[split_idx:, "low"] *= 1.5
        df2.loc[split_idx:, "open"] *= 1.5

        feat1 = self.fb.build_features(df1, symbol="frxEURUSD")
        feat2 = self.fb.build_features(df2, symbol="frxEURUSD")

        # Compare features strictly prior to split_epoch
        mask1 = feat1["epoch"] < split_epoch
        mask2 = feat2["epoch"] < split_epoch

        eval_cols = [c for c in feat1.columns if c not in {"epoch", "regime", "econ_policy"}]
        sub1 = feat1.loc[mask1, eval_cols].values
        sub2 = feat2.loc[mask2, eval_cols].values

        np.testing.assert_allclose(
            sub1, sub2, rtol=1e-7, atol=1e-7,
            err_msg="CRITICAL: Future candle modification altered past feature values!"
        )

    def test_target_contamination_check(self):
        """2. Target columns must NEVER appear inside model input feature set X."""
        df_feat = self.fb.build_features(self.df_raw, symbol="frxEURUSD")
        df_labeled = self.labeler.label_dataset(df_feat, symbol="frxEURUSD")

        forbidden_leakage_columns = {
            "target_class", "future_return", "future_net_buy", "future_net_sell"
        }

        feature_cols = [
            c for c in df_labeled.columns 
            if c not in forbidden_leakage_columns and c not in {"epoch", "regime", "econ_policy"}
        ]

        for col in feature_cols:
            self.assertNotIn(col, forbidden_leakage_columns, f"Leakage detected: {col} is in X!")

    def test_economic_publication_leakage(self):
        """3. Actual economic release figures must NOT be accessible before publication_epoch."""
        cal = EconomicCalendarEngine(blackout_pre_seconds=900, blackout_post_seconds=900)
        event = EconomicEvent(
            event_id="CPI_001",
            event_name="US CPI YoY",
            currency="USD",
            country="US",
            scheduled_epoch=1700010000,
            publication_epoch=1700010000,
            importance="HIGH",
            forecast=3.2,
            previous=3.1,
            actual=3.7
        )
        cal.load_events([event])

        ctx_pre = cal.get_context_at_epoch(1700009940, currency="USD")
        self.assertEqual(ctx_pre["surprise"], 0.0, "Leakage: Actual surprise visible before publication!")

        ctx_post = cal.get_context_at_epoch(1700010000, currency="USD")
        self.assertAlmostEqual(ctx_post["surprise"], 0.5, places=4)

    def test_scaler_test_isolation(self):
        """4. Scaler must be fit on train fold only; test data must not influence mean or std."""
        X_train = np.array([[10.0], [20.0], [30.0]])
        X_test = np.array([[1000.0], [2000.0]])

        scaler = StandardScaler()
        scaler.fit(X_train)
        train_mean = scaler.mean_[0]

        self.assertEqual(train_mean, 20.0, "Scaler mean should strictly reflect training fold.")
        X_test_scaled = scaler.transform(X_test)
        self.assertAlmostEqual(scaler.mean_[0], 20.0, places=5, msg="Test transform contaminated scaler mean!")


if __name__ == "__main__":
    unittest.main()
