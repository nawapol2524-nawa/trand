import unittest
import numpy as np
import pandas as pd
from ai_forex_bot.features.builder import FeatureBuilder
from ai_forex_bot.market.regime.classifier import RegimeClassifier

class TestRegimeCausality(unittest.TestCase):
    def setUp(self):
        # Generate 500 bars
        n = 500
        np.random.seed(42)
        epochs = [1720000000 + i * 900 for i in range(n)]
        close = 1.0800 + np.cumsum(np.random.normal(0, 0.0003, n))
        high = close + np.abs(np.random.normal(0, 0.0002, n))
        low = close - np.abs(np.random.normal(0, 0.0002, n))
        open_ = close + np.random.normal(0, 0.0001, n)
        
        self.df_base = pd.DataFrame({
            "epoch": epochs,
            "open": open_,
            "high": high,
            "low": low,
            "close": close
        })
        self.builder = FeatureBuilder()
        self.df_feat = self.builder.build_features(self.df_base.copy(), symbol="frxEURUSD")

    def test_future_candle_perturbation_regime_invariant(self):
        """
        Gate 21 Adversarial Test:
        Perturb all future candles from T+1 onward.
        Assert that regime classification at T and all previous bars <= T remains 100% identical.
        """
        classifier = RegimeClassifier()
        regime_orig = classifier.classify_series(self.df_feat)
        
        # Select cutoff T
        T = 200
        cutoff_epoch = self.df_feat["epoch"].iloc[T]
        
        # Create adversarial perturbed copy where future data is radically changed
        df_perturbed = self.df_base.copy()
        future_mask = df_perturbed["epoch"] > cutoff_epoch
        df_perturbed.loc[future_mask, "close"] *= 10.0
        df_perturbed.loc[future_mask, "high"] *= 12.0
        df_perturbed.loc[future_mask, "low"] *= 0.1
        df_perturbed.loc[future_mask, "open"] *= 9.0
        
        df_feat_perturbed = self.builder.build_features(df_perturbed, symbol="frxEURUSD")
        regime_perturbed = classifier.classify_series(df_feat_perturbed)
        
        # Check all bars up to T
        regime_orig_slice = regime_orig.iloc[:T+1].values
        regime_pert_slice = regime_perturbed.iloc[:T+1].values
        
        mismatches = np.sum(regime_orig_slice != regime_pert_slice)
        self.assertEqual(
            mismatches, 0,
            f"Future perturbation contaminated past regimes! Found {mismatches} mismatched regime labels."
        )

if __name__ == "__main__":
    unittest.main()
