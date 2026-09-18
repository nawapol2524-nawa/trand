import unittest
from datetime import datetime, timezone
from ai_forex_bot.risk.risk_engine import RiskEngine, RiskDecision, AccountState

class TestRiskEngine(unittest.TestCase):
    def setUp(self):
        self.risk = RiskEngine()
        self.account = AccountState(balance=1000.0, equity=1000.0, free_margin=1000.0)

    def test_daily_reset_zero_trades(self):
        dt1 = datetime(2026, 9, 18, 14, 0, tzinfo=timezone.utc)
        self.risk.check_daily_reset(dt1)
        
        # Simulate loss breaching threshold
        self.risk.record_closed_trade(-2.50, dt1)
        self.assertTrue(self.risk.kill_switch_active)

        # Midnight boundary transition with 0 trades
        dt2 = datetime(2026, 9, 19, 0, 1, tzinfo=timezone.utc)
        reset = self.risk.check_daily_reset(dt2)
        self.assertTrue(reset)
        self.assertFalse(self.risk.kill_switch_active)
        self.assertEqual(self.risk.daily_realized_loss, 0.0)

    def test_position_sizing(self):
        lots, err = self.risk.calculate_position_size(self.account, "frxEURUSD", 1.1000, 1.0985)
        self.assertIsNone(err)
        self.assertGreaterEqual(lots, 0.01)

if __name__ == "__main__":
    unittest.main()
