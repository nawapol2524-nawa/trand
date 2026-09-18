"""
Integration Tests for Gate 26: 24/7 Autonomous Production Host Deployment
========================================================================
Tests:
- Dual-trigger Emergency Kill-Switch (file-based flag and programmatic reset)
- RiskEngine immediate rejection on kill-switch trigger
- Portfolio state persistence and cold restart recovery
- SystemHealthMonitor heartbeat writing and probe staleness detection
- ProductionDaemonSupervisor single-cycle lifecycle and graceful shutdown
"""

import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta

from ai_forex_bot.config.settings import settings
from ai_forex_bot.risk.kill_switch import EmergencyKillSwitch, StateRecoveryManager
from ai_forex_bot.risk.risk_engine import RiskEngine, RiskDecision, AccountState
from ai_forex_bot.monitoring.health import SystemHealthMonitor
from ai_forex_bot.execution.paper_broker import PaperBroker
from scripts.run_production_daemon import ProductionDaemonSupervisor


class TestGate26ProductionDeployment(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="gate26_test_")
        self.temp_path = Path(self.temp_dir)
        self.kill_switch = EmergencyKillSwitch(root_dir=self.temp_path)
        self.state_manager = StateRecoveryManager(root_dir=self.temp_path)
        self.health_monitor = SystemHealthMonitor(
            root_dir=self.temp_path,
            heartbeat_file=self.temp_path / "logs" / "heartbeat.json"
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_emergency_kill_switch_file_flag_detection(self):
        """Verify dropping KILL_SWITCH file activates kill-switch and reset clears it."""
        self.assertFalse(self.kill_switch.is_kill_switch_active())

        # Drop file flag
        flag_file = self.temp_path / "KILL_SWITCH"
        flag_file.write_text("HOST_MAINTENANCE_EMERGENCY", encoding="utf-8")

        self.assertTrue(self.kill_switch.is_kill_switch_active())
        self.assertIn("HOST_MAINTENANCE_EMERGENCY", self.kill_switch.reason)

        # Reset
        self.kill_switch.reset_kill_switch(reason="TEST_RESET")
        self.assertFalse(self.kill_switch.is_kill_switch_active())
        self.assertFalse(flag_file.exists())

    def test_risk_engine_blocks_orders_on_kill_switch(self):
        """Verify RiskEngine immediately rejects orders when emergency kill switch is active."""
        risk_engine = RiskEngine()
        # Mock risk engine's emergency kill switch to use test dir
        risk_engine.emergency_kill_switch = self.kill_switch

        acct = AccountState(balance=1000.0, equity=1000.0, free_margin=1000.0)
        dt = datetime.now(timezone.utc)

        # 1. Normal order passes (assuming spread within limit)
        dec, code, detail = risk_engine.validate_new_order(
            symbol="frxEURUSD",
            direction="BUY",
            current_spread_pips=1.2,
            account=acct,
            open_positions=[],
            current_dt=dt
        )
        self.assertEqual(dec, RiskDecision.APPROVE)

        # 2. Trigger kill switch
        self.kill_switch.activate_kill_switch(reason="API_LATENCY_CIRCUIT_BREAKER")

        dec2, code2, detail2 = risk_engine.validate_new_order(
            symbol="frxEURUSD",
            direction="BUY",
            current_spread_pips=1.2,
            account=acct,
            open_positions=[],
            current_dt=dt
        )
        self.assertEqual(dec2, RiskDecision.REJECT)
        self.assertEqual(code2, "EMERGENCY_KILL_SWITCH_ACTIVE")
        self.assertIn("API_LATENCY_CIRCUIT_BREAKER", detail2)

    def test_state_recovery_manager_roundtrip(self):
        """Verify portfolio state persistence and exact reconstruction on broker restart."""
        broker_1 = PaperBroker(initial_balance=1000.0)
        broker_1.connect()
        broker_1.set_quote("frxEURUSD", bid=1.0850, ask=1.0852, timestamp=1789700000)

        # Place trade
        order = broker_1.place_order(
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=0.05,
            sl_price=1.0835,
            tp_price=1.0870
        )
        self.assertEqual(order["status"], "FILLED")
        self.assertEqual(len(broker_1.positions), 1)
        pos_id = list(broker_1.positions.keys())[0]

        # Save state
        saved_path = self.state_manager.save_portfolio_state(broker_1)
        self.assertTrue(saved_path.exists())

        # Instantiate fresh broker (simulating restart)
        broker_2 = PaperBroker(initial_balance=1000.0)
        broker_2.connect()
        self.assertEqual(len(broker_2.positions), 0)

        # Restore state
        restored, msg = self.state_manager.restore_broker_state(broker_2)
        self.assertTrue(restored, msg)
        self.assertEqual(len(broker_2.positions), 1)
        self.assertIn(pos_id, broker_2.positions)
        self.assertEqual(broker_2.positions[pos_id]["lot_size"], 0.05)
        self.assertEqual(broker_2.balance, broker_1.balance)

    def test_system_health_monitor_heartbeat_and_probe(self):
        """Verify heartbeat recording and probe verification for fresh vs stale timestamps."""
        # 1. Record healthy heartbeat
        hb = self.health_monitor.record_heartbeat(
            champion_model_id="test_model_champ",
            open_positions_count=2,
            today_pnl_usd=15.50
        )
        self.assertEqual(hb["overall_status"], "HEALTHY")
        self.assertTrue(self.health_monitor.heartbeat_file.exists())

        # 2. Probe passes
        healthy, reason, data = self.health_monitor.check_health_probe(max_stale_seconds=60.0)
        self.assertTrue(healthy)
        self.assertEqual(reason, "SYSTEM_HEALTHY")
        self.assertEqual(data["trading_state"]["champion_model_id"], "test_model_champ")

        # 3. Simulate stale heartbeat (age > threshold)
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=150)).isoformat()
        with open(self.health_monitor.heartbeat_file, "r", encoding="utf-8") as f:
            stale_data = json.load(f)
        stale_data["timestamp"] = stale_time
        with open(self.health_monitor.heartbeat_file, "w", encoding="utf-8") as f:
            json.dump(stale_data, f)

        healthy_stale, reason_stale, _ = self.health_monitor.check_health_probe(max_stale_seconds=60.0)
        self.assertFalse(healthy_stale)
        self.assertIn("HEARTBEAT_STALE", reason_stale)

    def test_production_daemon_single_cycle_execution(self):
        """Verify production daemon runs a complete supervision cycle and exits cleanly."""
        daemon = ProductionDaemonSupervisor(
            symbol="frxEURUSD",
            timeframe="M15",
            heartbeat_interval=1.0,
            retrain_interval=1.0,
            restore_state=False
        )
        daemon.root_dir = self.temp_path
        daemon.log_dir = self.temp_path / "logs"
        daemon.daemon_log_file = daemon.log_dir / "daemon_events.jsonl"
        daemon.kill_switch = self.kill_switch
        daemon.health_monitor = self.health_monitor
        daemon.state_manager = self.state_manager

        exit_code = daemon.run(single_cycle=True)
        self.assertEqual(exit_code, 0)
        self.assertTrue(self.state_manager.state_file.exists())


if __name__ == "__main__":
    unittest.main()
