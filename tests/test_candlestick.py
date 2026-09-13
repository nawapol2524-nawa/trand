"""
Unit tests for synthetic_candlestick.py
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.abspath("."))
import synthetic_candlestick as sc

class TestSyntheticCandlestick(unittest.TestCase):

    def test_pin_bar_rejection_high_score(self):
        # 12 base candles around 1000.0
        candles = []
        for i in range(11):
            candles.append({'open': 1000.0, 'high': 1005.0, 'low': 995.0, 'close': 1000.0})

        # Latest candle is a strong Pin Bar:
        # High: 1002, Low: 970, Open: 998, Close: 1001
        # Range: 32, Lower wick: 998 - 970 = 28 (87.5% wick!), Upper wick: 1
        candles.append({'open': 998.0, 'high': 1002.0, 'low': 970.0, 'close': 1001.0})

        lower_bb = 985.0
        upper_bb = 1030.0
        pip_size = 1.0

        res = sc.analyze_candlestick_setup(candles, lower_bb, upper_bb, pip_size, rsi=28.0)
        self.assertTrue(res['has_setup'])
        self.assertGreaterEqual(res['quality_score'], 70.0)
        self.assertIn("Pin", res['pattern_name'])
        # Dynamic SL should be around (1001 - (970 - 2)) = 33 -> capped at 25.0
        self.assertEqual(res['dynamic_sl_pips'], 25.0)
        self.assertGreater(res['estimated_rr'], 1.0)
        print("✅ Pin Bar test passed! Score:", res['quality_score'], "Name:", res['pattern_name'])

    def test_falling_knife_rejection(self):
        # 12 candles, latest is a big red marubozu (falling knife)
        candles = []
        for i in range(11):
            candles.append({'open': 1000.0, 'high': 1005.0, 'low': 995.0, 'close': 1000.0})

        # Big red candle: Open: 1000, Close: 970, Low: 969, High: 1001
        candles.append({'open': 1000.0, 'high': 1001.0, 'low': 969.0, 'close': 970.0})

        lower_bb = 985.0
        upper_bb = 1030.0
        pip_size = 1.0

        res = sc.analyze_candlestick_setup(candles, lower_bb, upper_bb, pip_size, rsi=22.0)
        # Should NOT trigger a setup despite oversold RSI
        self.assertFalse(res['has_setup'])
        self.assertLess(res['quality_score'], 50.0)
        self.assertEqual(res['pattern_name'], "None")
        print("✅ Falling Knife rejection passed! Score:", res['quality_score'], "(Successfully blocked)")

    def test_bullish_engulfing(self):
        candles = []
        for i in range(10):
            candles.append({'open': 1000.0, 'high': 1005.0, 'low': 995.0, 'close': 1000.0})

        # Prev candle: Red (Open: 1000, Close: 990)
        candles.append({'open': 1000.0, 'high': 1001.0, 'low': 989.0, 'close': 990.0})
        # Curr candle: Green engulfing (Open: 989, Close: 1003, High: 1004, Low: 988)
        candles.append({'open': 989.0, 'high': 1004.0, 'low': 988.0, 'close': 1003.0})

        lower_bb = 992.0
        upper_bb = 1030.0
        pip_size = 1.0

        res = sc.analyze_candlestick_setup(candles, lower_bb, upper_bb, pip_size, rsi=34.0)
        self.assertTrue(res['has_setup'])
        self.assertIn("Engulf", res['pattern_name'])
        print("✅ Bullish Engulfing passed! Score:", res['quality_score'], "Name:", res['pattern_name'])
        print("✅ Bullish Engulfing passed! Score:", res['quality_score'], "Name:", res['pattern_name'])

    def test_liquidity_sweep_and_pinbar(self):
        candles = []
        # Swing low was 980.0
        for i in range(11):
            candles.append({'open': 1000.0, 'high': 1005.0, 'low': 980.0 if i == 5 else 990.0, 'close': 995.0})

        # Latest sweeps prior swing low (980) down to 972, then closes at 985!
        candles.append({'open': 982.0, 'high': 986.0, 'low': 972.0, 'close': 985.0})

        lower_bb = 980.0
        upper_bb = 1020.0
        pip_size = 1.0

        res = sc.analyze_candlestick_setup(candles, lower_bb, upper_bb, pip_size, rsi=30.0)
        self.assertTrue(res['has_setup'])
        self.assertIn("Sweep", res['pattern_name'])
        # Dynamic SL: (985 - (972 - 2)) = 15 pips
        self.assertEqual(res['dynamic_sl_pips'], 15.0)
        print("✅ Liquidity Sweep passed! Score:", res['quality_score'], "Name:", res['pattern_name'], "SL:", res['dynamic_sl_pips'])

    def test_bearish_exit_shooting_star(self):
        candles = []
        for i in range(11):
            candles.append({'open': 1000.0, 'high': 1005.0, 'low': 995.0, 'close': 1000.0})

        # Reached Upper BB (1050), High: 1052, Low: 1038, Open: 1040, Close: 1041
        # Upper wick: 1052 - 1041 = 11 (78% wick at top)
        candles.append({'open': 1040.0, 'high': 1052.0, 'low': 1038.0, 'close': 1041.0})

        lower_bb = 1000.0
        upper_bb = 1050.0
        pip_size = 1.0

        res = sc.analyze_candlestick_setup(candles, lower_bb, upper_bb, pip_size, rsi=72.0)
        self.assertTrue(res['bearish_exit'])
        print("✅ Bearish Exit (Shooting Star on Upper BB) passed! Exit triggered:", res['bearish_exit'])

if __name__ == '__main__':
    unittest.main()
