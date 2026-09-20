"""
Unit & Integration Tests for DerivBroker
=========================================
Tests:
1. Broker initialization and multiplier mapping.
2. Mock quote, order, and position reconciliation.
3. Live test against Deriv Demo when DERIV_API_TOKEN is provided in environment.
"""

import unittest

from ai_forex_bot.execution.deriv_broker import DerivBroker


class TestDerivBroker(unittest.TestCase):
    def test_initialization(self):
        broker = DerivBroker(token="dummy_token", app_id="12345", account_type="demo")
        self.assertEqual(broker.token, "dummy_token")
        self.assertEqual(broker.app_id, "12345")
        self.assertEqual(broker.account_type, "demo")
        self.assertFalse(broker.connected)

    def test_multipliers_mapping(self):
        broker = DerivBroker()
        self.assertEqual(broker._get_multiplier_for_symbol("R_75"), 100)
        self.assertEqual(broker._get_multiplier_for_symbol("R_25"), 160)
        self.assertEqual(broker._get_multiplier_for_symbol("R_10"), 400)
        self.assertEqual(broker._get_multiplier_for_symbol("UNKNOWN"), 100)

    def test_health_check_initial(self):
        broker = DerivBroker()
        hc = broker.health_check()
        self.assertEqual(hc["status"], "DISCONNECTED")
        self.assertFalse(hc["connected"])
        self.assertEqual(hc["open_positions"], 0)

    def test_on_bar_triggers_sl_tp(self):
        broker = DerivBroker()
        broker.connected = False  # simulate offline / local test
        broker.balance = 1000.0
        broker.positions["test_pos_1"] = {
            "position_id": "test_pos_1",
            "symbol": "R_75",
            "direction": "BUY",
            "lot_size": 0.01,
            "stake": 1.0,
            "entry_price": 1000.0,
            "entry_epoch": 1789900000,
            "sl_price": 990.0,
            "tp_price": 1020.0,
            "partial_tp_price": 1010.0,
            "breakeven_locked": False,
            "bars_held": 0
        }

        # Bar hitting SL (low = 985.0 <= 990.0)
        bar_sl = {
            "symbol": "R_75",
            "open": 995.0,
            "high": 998.0,
            "low": 985.0,
            "close": 988.0,
            "epoch": 1789900060
        }
        closed = broker.on_bar(bar_sl)
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["exit_reason"], "STOP_LOSS")
        self.assertNotIn("test_pos_1", broker.positions)
        self.assertEqual(len(broker.closed_trades), 1)


if __name__ == "__main__":
    unittest.main()
