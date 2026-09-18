import unittest
from datetime import datetime, timezone
from ai_forex_bot.risk.risk_engine import RiskEngine, RiskDecision, AccountState, Position

class TestCurrencyConcentration(unittest.TestCase):
    def setUp(self):
        # Configure RiskEngine with max_open_positions=5, max_currency_exposure=2
        # This isolates currency concentration from total position count limit.
        self.risk = RiskEngine(max_open_positions=5, max_currency_exposure=2)
        self.account = AccountState(
            balance=10000.0,
            equity=10000.0,
            free_margin=10000.0,
            initial_balance=10000.0
        )
        self.now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)

    def test_currency_concentration_rejection(self):
        """
        Gate 21 Real Currency Concentration Audit:
        Open positions:
        1. EURUSD BUY (Long EUR, Short USD)
        2. GBPUSD BUY (Long GBP, Short USD)
        At this point, USD is shorted 2 times.
        
        Candidate 3:
        AUDUSD BUY (Long AUD, Short USD)
        Expected: REJECT with CURRENCY_CONCENTRATION_LIMIT because USD Short count would become 3 > 2.
        
        Candidate 4:
        USDJPY SELL (Short USD, Long JPY)
        Expected: REJECT with CURRENCY_CONCENTRATION_LIMIT because USD is also shorted.
        
        Candidate 5:
        USDJPY BUY (Long USD, Short JPY)
        Expected: APPROVE because USD is LONG (counter-exposure), so USD Short count is not increased.
        """
        p1 = Position(
            position_id="P1",
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=0.1,
            entry_price=1.0850,
            current_price=1.0850,
            sl_price=1.0800,
            tp_price=1.0950
        )
        p2 = Position(
            position_id="P2",
            symbol="frxGBPUSD",
            direction="BUY",
            lot_size=0.1,
            entry_price=1.2750,
            current_price=1.2750,
            sl_price=1.2700,
            tp_price=1.2850
        )
        open_positions = [p1, p2]

        # Candidate 3: AUDUSD BUY -> Should trigger CURRENCY_CONCENTRATION_LIMIT on USD
        # Note: if AUDUSD is not in symbols.yaml, let us check with another USD pair or frxUSDJPY
        # Let us test with another BUY on frxEURUSD or frxGBPUSD or frxUSDJPY
        dec3, reason3, msg3 = self.risk.validate_new_order(
            symbol="frxEURUSD",
            direction="BUY",
            current_spread_pips=1.0,
            account=self.account,
            open_positions=open_positions,
            current_dt=self.now
        )
        self.assertEqual(dec3, RiskDecision.REJECT)
        self.assertEqual(reason3, "CURRENCY_CONCENTRATION_LIMIT")
        self.assertIn("USD", msg3)

        # Candidate 4: USDJPY SELL -> USD is base currency, SELL means SHORT USD
        dec4, reason4, msg4 = self.risk.validate_new_order(
            symbol="frxUSDJPY",
            direction="SELL",
            current_spread_pips=1.0,
            account=self.account,
            open_positions=open_positions,
            current_dt=self.now
        )
        self.assertEqual(dec4, RiskDecision.REJECT)
        self.assertEqual(reason4, "CURRENCY_CONCENTRATION_LIMIT")
        self.assertIn("USD", msg4)

        # Candidate 5: USDJPY BUY -> USD is base currency, BUY means LONG USD
        # Does not add to USD SHORT concentration
        dec5, reason5, msg5 = self.risk.validate_new_order(
            symbol="frxUSDJPY",
            direction="BUY",
            current_spread_pips=1.0,
            account=self.account,
            open_positions=open_positions,
            current_dt=self.now
        )
        self.assertEqual(dec5, RiskDecision.APPROVE)
        self.assertEqual(reason5, "APPROVED")

if __name__ == "__main__":
    unittest.main()
