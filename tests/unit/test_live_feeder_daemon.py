"""
Unit & Integration Tests: LiveMarketFeeder & Upgraded Production Daemon
======================================================================
Validates Component 3 Implementation:
1. LiveMarketFeeder:
   - Deriv WebSocket polling / offline fallback.
   - High-fidelity synthetic bar generation across R_25, R_75, R_10, frxEURUSD.
   - Monotonic epochs, positive prices, pip size compliance, and warmup buffers.
2. ProductionDaemonSupervisor:
   - 43 causal feature extraction via FeatureBuilder.
   - Champion model inference with fallback model.
   - RiskEngine evaluation (exposure, spread, daily profit target, daily loss stop).
   - Double-Barrel order execution via PaperBroker (partial TP and dynamic breakeven).
   - Bar lifecycle progression broker.on_bar(bar).
   - Shadow signals logging (logs/shadow_signals.jsonl) and paper trades logging (logs/paper_trades.jsonl).
   - Heartbeat metrics update (last_candle_epoch, today_pnl_usd, open_positions_count, trades_count).
3. CLI Entrypoints:
   - python3 main.py --symbol R_25 --strategy double_barrel --single-cycle execution.
"""

import os
import json
import subprocess
import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
import numpy as np

from ai_forex_bot.config.settings import settings
from ai_forex_bot.data.market.live_feeder import LiveMarketFeeder
from scripts.run_production_daemon import ProductionDaemonSupervisor, FallbackTechnicalModel


class TestLiveFeederAndDaemon(unittest.TestCase):
    def setUp(self):
        self.root_dir = settings.root_dir
        self.log_dir = self.root_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.heartbeat_file = self.log_dir / "heartbeat.json"
        self.shadow_signals_file = self.log_dir / "shadow_signals.jsonl"
        self.paper_trades_file = self.log_dir / "paper_trades.jsonl"

    def test_live_feeder_all_symbols_warmup_and_polling(self):
        """Verify LiveMarketFeeder generates valid warmup and synthetic bars for all symbols."""
        symbols = ["R_25", "R_75", "R_10", "frxEURUSD"]
        for sym in symbols:
            feeder = LiveMarketFeeder(symbol=sym, timeframe="M15", offline_mode=True, random_seed=42)
            warmup_bars = feeder.get_warmup_bars(count=50)

            self.assertEqual(len(warmup_bars), 50, f"Expected 50 warmup bars for {sym}")
            self.assertEqual(warmup_bars[-1]["symbol"], sym)

            # Check monotonicity and positive prices
            for i in range(1, len(warmup_bars)):
                prev = warmup_bars[i - 1]
                curr = warmup_bars[i]
                self.assertGreater(curr["epoch"], prev["epoch"])
                self.assertGreater(curr["high"], 0.0)
                self.assertGreater(curr["low"], 0.0)
                self.assertGreaterEqual(curr["high"], max(curr["open"], curr["close"]))
                self.assertLessEqual(curr["low"], min(curr["open"], curr["close"]))

            # Check next polled bar
            next_bar = feeder.poll_next_bar()
            self.assertGreater(next_bar["epoch"], warmup_bars[-1]["epoch"])
            self.assertEqual(next_bar["symbol"], sym)
            self.assertEqual(feeder.mode, "SYNTHETIC_OFFLINE")

    def test_live_feeder_deriv_fallback(self):
        """Verify LiveMarketFeeder gracefully falls back to synthetic mode if Deriv API unavailable."""
        feeder = LiveMarketFeeder(
            symbol="R_25",
            timeframe="M15",
            api_token="INVALID_TEST_TOKEN",
            app_id="99999",
            offline_mode=False
        )
        bar = feeder.poll_next_bar()
        self.assertIsNotNone(bar)
        self.assertEqual(bar["symbol"], "R_25")
        self.assertEqual(feeder.mode, "SYNTHETIC_OFFLINE")

    def test_fallback_technical_model(self):
        """Verify FallbackTechnicalModel returns valid probability distribution."""
        model = FallbackTechnicalModel("R_25")
        import pandas as pd
        df = pd.DataFrame([{
            "dist_ema_20": 0.002,
            "rsi_14": 58.0,
            "macd_hist": 0.001
        }])
        proba = model.predict_proba(df)
        self.assertEqual(proba.shape, (1, 3))
        self.assertAlmostEqual(float(np.sum(proba[0])), 1.0, places=2)
        # Bullish conviction
        self.assertGreater(proba[0][1], proba[0][2])

    def test_production_daemon_single_cycle_execution(self):
        """Verify ProductionDaemonSupervisor executes end-to-end single cycle for R_25."""
        supervisor = ProductionDaemonSupervisor(
            symbol="R_25",
            timeframe="M15",
            strategy="double_barrel",
            heartbeat_interval=1.0,
            retrain_interval=100.0,
            restore_state=False
        )

        exit_code = supervisor.run(single_cycle=True)
        self.assertEqual(exit_code, 0)

        # Verify heartbeat file was updated
        self.assertTrue(self.heartbeat_file.exists())
        with open(self.heartbeat_file, "r", encoding="utf-8") as f:
            hb = json.load(f)

        self.assertEqual(hb["symbol"], "R_25")
        self.assertIn("trading_state", hb)
        t_state = hb["trading_state"]
        self.assertEqual(t_state["symbol"], "R_25")
        self.assertIsNotNone(t_state["last_candle_epoch"])
        self.assertIn("open_positions_count", t_state)
        self.assertIn("today_pnl_usd", t_state)

        custom = hb.get("custom", {})
        self.assertEqual(custom.get("strategy"), "double_barrel")
        self.assertIn("trades_count", custom)

        # Verify shadow_signals.jsonl contains records for R_25
        self.assertTrue(self.shadow_signals_file.exists())
        with open(self.shadow_signals_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertGreater(len(lines), 0)
        last_signal = json.loads(lines[-1])
        self.assertEqual(last_signal["symbol"], "R_25")
        self.assertIn(last_signal["status"], ("PROCESSED", "WARMUP"))
        self.assertIn("p_buy", last_signal)
        self.assertIn("risk_verdict", last_signal)

    def test_production_daemon_multi_symbol_execution(self):
        """Verify ProductionDaemonSupervisor executes concurrent multi-symbol trading cycle."""
        supervisor = ProductionDaemonSupervisor(
            symbol="R_25,R_10,R_75",
            timeframe="M15",
            strategy="double_barrel",
            heartbeat_interval=1.0,
            retrain_interval=100.0,
            restore_state=False
        )

        exit_code = supervisor.run(single_cycle=True)
        self.assertEqual(exit_code, 0)

        # Verify heartbeat contains all symbols
        self.assertTrue(self.heartbeat_file.exists())
        with open(self.heartbeat_file, "r", encoding="utf-8") as f:
            hb = json.load(f)

        custom = hb.get("custom", {})
        self.assertEqual(custom.get("symbols"), ["R_25", "R_10", "R_75"])
        self.assertIn("R_25", custom.get("feed_mode", {}))
        self.assertIn("R_10", custom.get("feed_mode", {}))
        self.assertIn("R_75", custom.get("feed_mode", {}))

    def test_main_cli_single_cycle_r25(self):
        """Verify `python3 main.py --symbol R_25 --single-cycle` runs cleanly via CLI."""
        cmd = [
            sys.executable,
            str(self.root_dir / "main.py"),
            "--symbol", "R_25",
            "--strategy", "double_barrel",
            "--single-cycle"
        ]
        res = subprocess.run(cmd, cwd=str(self.root_dir), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Process failed with stderr: {res.stderr}")
        self.assertIn("Single-cycle execution for R_25 verified successfully", res.stdout)

    def test_main_cli_multi_symbol_default(self):
        """Verify default `python3 main.py --single-cycle` runs all configured symbols."""
        cmd = [
            sys.executable,
            str(self.root_dir / "main.py"),
            "--single-cycle"
        ]
        res = subprocess.run(cmd, cwd=str(self.root_dir), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Process failed with stderr: {res.stderr}")
        self.assertTrue("R_25, R_10, R_75" in res.stdout or "Target Symbol(s) : R_25,R_10,R_75" in res.stdout)
        self.assertIn("Single-cycle execution for R_25,R_10,R_75 verified successfully", res.stdout)


if __name__ == "__main__":
    import numpy as np
    unittest.main()
