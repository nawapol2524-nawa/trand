"""
Unit Tests: Synthetic Index Execution & Daemon Logging Standard
================================================================
Validates:
1. Dynamic spread on synthetic indices (Deriv 24/7/365, NO weekend penalty).
2. Commission ($0.0 for synthetic indices like R_75, $6/lot for forex).
3. Margin accounting: (lot_size * contract_size * price) / leverage.
4. Gross PnL: pips_gain * pip_value * lot_size (= price_delta * lot_size for R_75).
5. Position reconciliation: equity and margin synchronization.
6. Heartbeat and daemon logging symbol attribution.
"""

import os
import json
import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from ai_forex_bot.config.settings import settings
from ai_forex_bot.execution.paper_broker import PaperBroker
from ai_forex_bot.monitoring.health import SystemHealthMonitor
from scripts.run_production_daemon import ProductionDaemonSupervisor


class TestSyntheticPaperBroker(unittest.TestCase):
    def setUp(self):
        self.broker = PaperBroker(initial_balance=10000.0, leverage=100.0, random_seed=42)
        self.broker.connect()
        # Set quotes: R_75 around 1000.00, frxEURUSD around 1.10000
        self.broker.set_quote("R_75", bid=1000.00, ask=1000.25, timestamp=1789700000)
        self.broker.set_quote("frxEURUSD", bid=1.10000, ask=1.10012, timestamp=1789700000)

    def test_synthetic_index_spread_no_weekend_penalty(self):
        """Synthetic indices run 24/7/365 with constant liquidity: strictly NO weekend penalty."""
        sym_cfg = settings.get_symbol_config("R_75")
        self.assertIsNotNone(sym_cfg)
        self.assertEqual(sym_cfg.asset_class, "synthetic_index")

        # Epoch for a Saturday (e.g. 2026-09-19 12:00:00 UTC -> Saturday)
        saturday_dt = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
        sat_epoch = int(saturday_dt.timestamp())

        spread_synth = self.broker._get_dynamic_spread_pips("R_75", sat_epoch)
        # Typical is 25.0. Organic variation is 0.95 to 1.05 -> [23.75, 26.25]
        # Must NEVER be widened by 2.5x (62.5 pips)
        self.assertGreaterEqual(spread_synth, 23.5)
        self.assertLessEqual(spread_synth, 26.5)

        # In contrast, forex (frxEURUSD) on Saturday MUST have weekend widening (typical 1.1 * 2.5 = 2.75)
        spread_forex = self.broker._get_dynamic_spread_pips("frxEURUSD", sat_epoch)
        self.assertAlmostEqual(spread_forex, 1.1 * 2.5, places=2)

    def test_commission_calculation(self):
        """Commission is $0.0/lot for R_75, but $6.0/lot for standard forex."""
        init_balance = self.broker.balance

        # Order 1: R_75 (1.0 lot)
        order_synth = self.broker.place_order(
            symbol="R_75",
            direction="BUY",
            lot_size=1.0,
            sl_price=990.0,
            tp_price=1020.0,
            idempotency_key="synth_comm_test"
        )
        self.assertEqual(order_synth["status"], "FILLED")
        self.assertEqual(order_synth["commission_usd"], 0.0)
        # Balance must not be charged commission for R_75
        self.assertEqual(self.broker.balance, init_balance)

        # Order 2: frxEURUSD (1.0 lot) -> $6.00 commission
        order_forex = self.broker.place_order(
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=1.0,
            sl_price=1.0950,
            tp_price=1.1050,
            idempotency_key="forex_comm_test"
        )
        self.assertEqual(order_forex["status"], "FILLED")
        self.assertAlmostEqual(order_forex["commission_usd"], 6.0, places=2)
        self.assertAlmostEqual(self.broker.balance, init_balance - 6.0, places=2)

    def test_margin_calculation_and_reconciliation(self):
        """Margin requirement is (lot_size * contract_size * fill_price) / leverage."""
        # For R_75: lot_size=1.0, contract_size=1.0, fill_price ~ 1000.25, leverage=100.0
        # Expected margin ~ (1.0 * 1.0 * 1000.25) / 100.0 = 10.0025
        order = self.broker.place_order(
            symbol="R_75",
            direction="BUY",
            lot_size=1.0,
            sl_price=990.0,
            tp_price=1020.0,
            idempotency_key="margin_test_1"
        )
        self.assertEqual(order["status"], "FILLED")

        expected_margin = (1.0 * 1.0 * order["fill_price"]) / 100.0
        self.assertAlmostEqual(self.broker.used_margin, expected_margin, places=2)
        self.assertAlmostEqual(self.broker.free_margin, self.broker.equity - expected_margin, places=2)

        # Verify full reconciliation
        audit = self.broker.reconcile()
        self.assertTrue(audit["is_synchronized"])
        self.assertEqual(audit["equity_discrepancy"], 0.0)
        self.assertEqual(audit["margin_discrepancy"], 0.0)

    def test_gross_pnl_calculation_r75(self):
        """Gross PnL on R_75: pips_gain * pip_value * lot_size == price_delta * lot_size."""
        order = self.broker.place_order(
            symbol="R_75",
            direction="BUY",
            lot_size=1.0,
            sl_price=950.0,
            tp_price=1100.0,
            idempotency_key="pnl_test_1"
        )
        pos_id = order["order_id"]
        entry_price = order["fill_price"]
        exit_price = entry_price + 15.50  # +$15.50 price change

        res = self.broker.close_position(
            position_id=pos_id,
            exit_price=exit_price,
            exit_reason="PROFIT_TARGET"
        )
        self.assertEqual(res["status"], "CLOSED")
        trade = res["trade"]

        # Expected price delta * lot_size = 15.50 * 1.0 = $15.50
        self.assertAlmostEqual(trade["gross_pnl"], 15.50, places=2)
        self.assertAlmostEqual(trade["net_pnl"], 15.50, places=2)  # No commission, no swap

    def test_on_bar_no_swap_for_synthetic_index(self):
        """Rollover swap is NOT applied to synthetic index positions at 21:00 UTC."""
        order = self.broker.place_order(
            symbol="R_75",
            direction="BUY",
            lot_size=1.0,
            sl_price=900.0,
            tp_price=1100.0,
            idempotency_key="swap_test_1"
        )
        pos_id = order["order_id"]

        # Feed bar at 21:00 UTC
        rollover_dt = datetime(2026, 9, 21, 21, 0, 0, tzinfo=timezone.utc)
        bar = {
            "symbol": "R_75",
            "epoch": int(rollover_dt.timestamp()),
            "open": 1000.0,
            "high": 1002.0,
            "low": 998.0,
            "close": 1001.0
        }
        self.broker.on_bar(bar)

        self.assertIn(pos_id, self.broker.positions)
        self.assertEqual(self.broker.positions[pos_id]["swap_usd"], 0.0)

    def test_health_monitor_heartbeat_records_symbol(self):
        """Heartbeat record includes explicit symbol attribution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            hb_file = tmp_path / "heartbeat.json"
            monitor = SystemHealthMonitor(root_dir=tmp_path, heartbeat_file=hb_file)

            hb_data = monitor.record_heartbeat(
                symbol="R_75",
                open_positions_count=1,
                today_pnl_usd=12.50
            )
            self.assertEqual(hb_data["symbol"], "R_75")
            self.assertEqual(hb_data["trading_state"]["symbol"], "R_75")

            # Check disk file
            with open(hb_file, "r", encoding="utf-8") as f:
                disk_data = json.load(f)
            self.assertEqual(disk_data["symbol"], "R_75")
            self.assertEqual(disk_data["trading_state"]["symbol"], "R_75")


if __name__ == "__main__":
    unittest.main()
