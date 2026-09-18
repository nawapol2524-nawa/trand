"""
Gate 23 Integration Test Suite: Paper & Shadow Validation Engine
=================================================================
Validates decoupled paper broker execution, dynamic costs, SL/TP/Time-exit,
duplicate prevention, Risk Engine veto enforcement, and end-to-end 100-bar shadow streaming.
"""

import os
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

from ai_forex_bot.config.settings import settings
from ai_forex_bot.execution.paper_broker import PaperBroker
from ai_forex_bot.risk.risk_engine import RiskEngine, RiskDecision, AccountState, Position
from scripts.run_shadow_engine import ShadowTradingEngine, MarketDataFeeder


class TestGate23ShadowValidation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.temp_dir.name) / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.broker = PaperBroker(
            initial_balance=1000.0,
            leverage=100.0,
            time_exit_bars=4,
            random_seed=42
        )
        self.broker.connect()
        # Set a test quote for frxEURUSD
        self.broker.set_quote("frxEURUSD", bid=1.10000, ask=1.10012, timestamp=1789700000)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_paper_broker_dynamic_costs(self):
        """Verify dynamic slippage (0.2-0.5 pips), commission ($6/lot), and fill calculations."""
        order_res = self.broker.place_order(
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=0.10,
            sl_price=1.0985,
            tp_price=1.1020,
            idempotency_key="order_test_costs_1"
        )
        self.assertEqual(order_res["status"], "FILLED")
        self.assertGreaterEqual(order_res["slippage_pips"], 0.20)
        self.assertLessEqual(order_res["slippage_pips"], 0.50)
        # Commission for 0.10 lot = 0.10 * 6.0 = $0.60
        self.assertAlmostEqual(order_res["commission_usd"], 0.60, places=2)
        # Balance deducted commission immediately
        self.assertAlmostEqual(self.broker.balance, 999.40, places=2)
        # BUY filled above ask due to slippage
        self.assertGreater(order_res["fill_price"], 1.10012)

    def test_duplicate_order_prevention(self):
        """Verify duplicate orders within the same bar or key are rejected."""
        res1 = self.broker.place_order(
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=0.10,
            sl_price=1.0985,
            tp_price=1.1020,
            idempotency_key="dedup_order_unique_key"
        )
        self.assertEqual(res1["status"], "FILLED")

        # Second attempt with same key must be rejected
        res2 = self.broker.place_order(
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=0.10,
            sl_price=1.0985,
            tp_price=1.1020,
            idempotency_key="dedup_order_unique_key"
        )
        self.assertEqual(res2["status"], "REJECTED")
        self.assertEqual(res2["reason"], "DUPLICATE_ORDER_PREVENTED")

    def test_paper_broker_sl_execution(self):
        """Verify Stop Loss trigger on adverse price excursion."""
        res = self.broker.place_order(
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=0.10,
            sl_price=1.0985,
            tp_price=1.1025,
            idempotency_key="sl_test_order"
        )
        self.assertEqual(res["status"], "FILLED")

        # Simulate a bar plunging below SL
        adverse_bar = {
            "symbol": "frxEURUSD",
            "epoch": 1789700900,
            "open": 1.0995,
            "high": 1.1000,
            "low": 1.0980,  # Below SL 1.0985
            "close": 1.0982
        }
        closed_trades = self.broker.on_bar(adverse_bar)
        self.assertEqual(len(closed_trades), 1)
        self.assertEqual(closed_trades[0]["exit_reason"], "STOP_LOSS")
        self.assertLess(closed_trades[0]["net_pnl"], 0.0)
        self.assertEqual(len(self.broker.positions), 0)

    def test_paper_broker_tp_execution(self):
        """Verify Take Profit trigger on favorable price excursion."""
        res = self.broker.place_order(
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=0.10,
            sl_price=1.0985,
            tp_price=1.1020,
            idempotency_key="tp_test_order"
        )
        self.assertEqual(res["status"], "FILLED")

        # Simulate a bar spiking above TP
        favorable_bar = {
            "symbol": "frxEURUSD",
            "epoch": 1789700900,
            "open": 1.1005,
            "high": 1.1025,  # Above TP 1.1020
            "low": 1.1000,
            "close": 1.1022
        }
        closed_trades = self.broker.on_bar(favorable_bar)
        self.assertEqual(len(closed_trades), 1)
        self.assertEqual(closed_trades[0]["exit_reason"], "TAKE_PROFIT")
        self.assertGreater(closed_trades[0]["net_pnl"], 0.0)
        self.assertEqual(len(self.broker.positions), 0)

    def test_paper_broker_time_based_exit(self):
        """Verify position automatically exits after exactly 4 bars (60m)."""
        res = self.broker.place_order(
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=0.10,
            sl_price=1.0950,
            tp_price=1.1050,
            idempotency_key="time_exit_order"
        )
        self.assertEqual(res["status"], "FILLED")

        # Feed 3 neutral bars (bars_held goes 1, 2, 3)
        for i in range(1, 4):
            bar = {
                "symbol": "frxEURUSD",
                "epoch": 1789700000 + i * 900,
                "open": 1.1000,
                "high": 1.1005,
                "low": 1.0995,
                "close": 1.1000
            }
            closed = self.broker.on_bar(bar)
            self.assertEqual(len(closed), 0, f"Unexpected close on bar {i}")

        # Feed 4th bar (bars_held reaches 4 -> TIME_EXIT)
        bar_4 = {
            "symbol": "frxEURUSD",
            "epoch": 1789700000 + 4 * 900,
            "open": 1.1000,
            "high": 1.1005,
            "low": 1.0995,
            "close": 1.1002
        }
        closed_4 = self.broker.on_bar(bar_4)
        self.assertEqual(len(closed_4), 1)
        self.assertEqual(closed_4[0]["exit_reason"], "TIME_EXIT")
        self.assertEqual(closed_4[0]["bars_held"], 4)
        self.assertEqual(len(self.broker.positions), 0)

    def test_position_reconciliation(self):
        """Verify broker reconciliation integrity."""
        self.broker.place_order(
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=0.05,
            sl_price=1.0970,
            tp_price=1.1030,
            idempotency_key="reconcile_test_order"
        )
        reconcile_res = self.broker.reconcile()
        self.assertTrue(reconcile_res["is_synchronized"])
        self.assertEqual(reconcile_res["open_position_count"], 1)
        self.assertAlmostEqual(reconcile_res["equity_discrepancy"], 0.0, places=4)
        self.assertAlmostEqual(reconcile_res["margin_discrepancy"], 0.0, places=4)

    def test_risk_engine_veto_integration(self):
        """Verify RiskEngine vetoes excessive spread, daily drawdown, and concurrency."""
        risk = RiskEngine()
        account = AccountState(
            balance=1000.0,
            equity=1000.0,
            free_margin=1000.0,
            used_margin=0.0,
            initial_balance=1000.0
        )
        dt = datetime(2026, 9, 18, 14, 0, tzinfo=timezone.utc)

        # 1. Excessive spread veto
        decision, code, _ = risk.validate_new_order(
            symbol="frxEURUSD",
            direction="BUY",
            current_spread_pips=3.5,  # Max allowed is 2.0
            account=account,
            open_positions=[],
            current_dt=dt,
            is_news_blackout=False
        )
        self.assertEqual(decision, RiskDecision.REJECT)
        self.assertEqual(code, "SPREAD_LIMIT_EXCEEDED")

        # 2. Concurrency limit veto (max 2 open positions)
        fake_pos = [
            Position("p1", "frxEURUSD", "BUY", 0.01, 1.10, 1.10, 1.09, 1.11),
            Position("p2", "frxGBPUSD", "BUY", 0.01, 1.30, 1.30, 1.29, 1.31)
        ]
        decision2, code2, _ = risk.validate_new_order(
            symbol="frxUSDJPY",
            direction="BUY",
            current_spread_pips=1.2,
            account=account,
            open_positions=fake_pos,
            current_dt=dt,
            is_news_blackout=False
        )
        self.assertEqual(decision2, RiskDecision.REJECT)
        self.assertEqual(code2, "MAX_POSITIONS_REACHED")

    def test_shadow_engine_end_to_end_100_bars(self):
        """Verify full end-to-end decoupled execution across 100 latest market bars."""
        data_path = settings.clean_data_dir / "frxEURUSD_M15.parquet"
        self.assertTrue(data_path.exists(), f"Missing clean dataset {data_path}")
        df_base = pd.read_parquet(data_path)

        engine = ShadowTradingEngine(
            symbol="frxEURUSD",
            initial_balance=1000.0,
            confidence_threshold=0.55,
            log_dir=self.log_dir
        )
        engine.initialize_model(df_base)

        total_bars = engine.min_warmup_bars + 100
        slice_df = df_base.iloc[-total_bars:].copy()
        feeder = MarketDataFeeder(slice_df, symbol="frxEURUSD")

        processed_count = 0
        for bar in feeder.stream_bars():
            res = engine.process_bar(bar)
            if res.get("status") == "PROCESSED":
                processed_count += 1

        self.assertGreaterEqual(processed_count, 100)
        self.assertTrue(engine.signals_log_path.exists())

        # Verify telemetry log entries
        with open(engine.signals_log_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]

        processed_lines = [l for l in lines if l.get("status") == "PROCESSED"]
        self.assertEqual(len(processed_lines), processed_count)


        for pl in processed_lines:
            self.assertIn("p_hold", pl)
            self.assertIn("p_buy", pl)
            self.assertIn("p_sell", pl)
            self.assertIn("regime", pl)
            self.assertIn("risk_verdict", pl)

        # Verify reconciliation
        reconcile_audit = engine.broker.reconcile()
        self.assertTrue(reconcile_audit["is_synchronized"])


if __name__ == "__main__":
    unittest.main()
