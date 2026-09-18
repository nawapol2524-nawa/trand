import unittest
import numpy as np
import pandas as pd
from ai_forex_bot.data.market.split import PurgedTimeSeriesSplitter
from ai_forex_bot.labels.labeler import CostAwareLabeler, LabelConfig

class TestPurgedSplit(unittest.TestCase):
    def setUp(self):
        # Create a synthetic sequence of 1000 candles with 15-minute timestamps
        n = 1000
        start_epoch = 1720000000
        epochs = [start_epoch + i * 900 for i in range(n)]
        close = 1.0800 + np.cumsum(np.random.normal(0, 0.0002, n))
        high = close + 0.0003
        low = close - 0.0003
        open_ = close - 0.0001
        
        self.df = pd.DataFrame({
            "epoch": epochs,
            "open": open_,
            "high": high,
            "low": low,
            "close": close
        })

    def test_label_boundary_purging(self):
        """
        Gate 21 Core Assertion:
        For every train sample i:
        target_end_epoch(i) < val_start_epoch
        And for every validation sample j:
        target_end_epoch(j) < test_start_epoch
        """
        horizon = 4
        splitter = PurgedTimeSeriesSplitter(horizon_bars=horizon, embargo_bars=0)
        bounds = splitter.get_split_indices(self.df, train_ratio=0.70, val_ratio=0.15)
        
        # 1. Assert purging occurred
        self.assertEqual(bounds.purged_train_count, horizon)
        self.assertEqual(bounds.purged_val_count, horizon)
        
        # 2. Strict timestamp verification
        # Last train sample index
        last_train_idx = bounds.train_indices[-1]
        # In labeling, sample at index k has target evaluated up to k + horizon
        train_target_max_epoch = int(self.df["epoch"].iloc[last_train_idx + horizon])
        
        # Validation start epoch
        val_start_epoch = bounds.val_start_epoch
        
        self.assertLess(
            train_target_max_epoch,
            val_start_epoch,
            f"Train target horizon ({train_target_max_epoch}) overlaps validation start ({val_start_epoch})"
        )
        
        # 3. Validation to Test boundary
        last_val_idx = bounds.val_indices[-1]
        val_target_max_epoch = int(self.df["epoch"].iloc[last_val_idx + horizon])
        test_start_epoch = bounds.test_start_epoch
        
        self.assertLess(
            val_target_max_epoch,
            test_start_epoch,
            f"Validation target horizon ({val_target_max_epoch}) overlaps test start ({test_start_epoch})"
        )
        
        # 4. Check leak_free flags
        self.assertTrue(bounds.train_val_leak_free)
        self.assertTrue(bounds.val_test_leak_free)

if __name__ == "__main__":
    unittest.main()
