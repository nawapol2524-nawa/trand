import unittest
import pandas as pd
import numpy as np
from ai_forex_bot.data.validation.validator import DataValidator

class TestDataValidator(unittest.TestCase):
    def setUp(self):
        self.validator = DataValidator()
        self.valid_df = pd.DataFrame({
            "epoch": [1700000000, 1700000060, 1700000120],
            "open": [1.1000, 1.1005, 1.1010],
            "high": [1.1010, 1.1015, 1.1020],
            "low": [1.0995, 1.1000, 1.1005],
            "close": [1.1005, 1.1010, 1.1015]
        })

    def test_valid_data(self):
        rep = self.validator.validate(self.valid_df, "EURUSD")
        self.assertTrue(rep.is_valid)
        self.assertEqual(len(rep.errors), 0)

    def test_invalid_ohlc(self):
        bad_df = self.valid_df.copy()
        bad_df.loc[1, "low"] = 1.1050  # Low > High
        rep = self.validator.validate(bad_df, "EURUSD")
        self.assertFalse(rep.is_valid)
        self.assertGreater(rep.invalid_ohlc_inequalities, 0)

    def test_duplicate_epoch(self):
        dup_df = self.valid_df.copy()
        dup_df.loc[2, "epoch"] = dup_df.loc[1, "epoch"]
        rep = self.validator.validate(dup_df, "EURUSD")
        self.assertFalse(rep.is_valid)
        self.assertEqual(rep.duplicate_timestamps, 1)

if __name__ == "__main__":
    unittest.main()
