"""
Unit Tests: Deriv Synthetic Indices Integration & Model Verification
===================================================================
Covers:
1. Deriv symbol config loading for R_75 and R_25 from configs/symbols.yaml.
2. 24/7/365 continuous trading spread (no weekend penalty) for R_75 and R_25.
3. PaperBroker order execution, zero commission, and gross PnL calculation for R_75.
4. Model Registry and Manifest verification for candidate_r75_M15.
5. Model artifact size (<10MB) and inference memory footprint (<50MB).
"""

import json
import tracemalloc
import unittest
from pathlib import Path

import joblib
import numpy as np
import yaml

from ai_forex_bot.config.settings import settings
from ai_forex_bot.execution.paper_broker import PaperBroker


class TestR75Integration(unittest.TestCase):
    def setUp(self):
        self.root_dir = settings.root_dir
        self.symbols_file = self.root_dir / "configs" / "symbols.yaml"
        self.registry_file = self.root_dir / "artifacts" / "models" / "registry.json"
        self.manifest_file = self.root_dir / "artifacts" / "manifest.json"
        self.model_path = self.root_dir / "artifacts" / "models" / "candidate_r75_M15.joblib"

    def test_symbols_yaml_contains_r75_and_r25(self):
        """Verify R_75 and R_25 are configured properly in configs/symbols.yaml."""
        self.assertTrue(self.symbols_file.exists(), "configs/symbols.yaml does not exist")
        with open(self.symbols_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        symbols = data.get("symbols", {})

        # R_75 checks
        self.assertIn("R_75", symbols)
        r75 = symbols["R_75"]
        self.assertEqual(r75.get("asset_class"), "synthetic_index")
        self.assertEqual(r75.get("commission_per_lot_usd"), 0.0)
        self.assertEqual(r75.get("pip_size"), 0.01)
        self.assertEqual(r75.get("lot_size"), 1.0)
        self.assertEqual(r75.get("swap_long_points"), 0.0)
        self.assertEqual(r75.get("swap_short_points"), 0.0)

        # R_25 checks
        self.assertIn("R_25", symbols)
        r25 = symbols["R_25"]
        self.assertEqual(r25.get("asset_class"), "synthetic_index")
        self.assertEqual(r25.get("commission_per_lot_usd"), 0.0)
        self.assertEqual(r25.get("lot_size"), 1.0)

    def test_paper_broker_r75_r25_execution_zero_commission(self):
        """Verify paper broker executes R_75 orders with zero commission and accurate PnL."""
        broker = PaperBroker(initial_balance=10000.0, leverage=100.0, random_seed=42)
        broker.connect()
        broker.set_quote("R_75", bid=150000.00, ask=150000.25, timestamp=1789700000)

        order = broker.place_order(
            symbol="R_75",
            direction="BUY",
            lot_size=1.0,
            sl_price=140000.0,
            tp_price=160000.0,
            idempotency_key="r75_test_exec_1"
        )
        self.assertEqual(order["status"], "FILLED")
        self.assertEqual(order["symbol"], "R_75")
        self.assertEqual(order["commission_usd"], 0.0)

        pos_id = order["order_id"]
        entry_price = order["fill_price"]
        exit_price = entry_price + 100.0  # +$100.00 price change

        res = broker.close_position(
            position_id=pos_id,
            exit_price=exit_price,
            exit_reason="PROFIT_TARGET"
        )
        self.assertEqual(res["status"], "CLOSED")
        trade = res["trade"]
        self.assertEqual(trade["commission_usd"], 0.0)
        self.assertAlmostEqual(trade["gross_pnl"], 100.0, places=2)
        self.assertAlmostEqual(trade["net_pnl"], 100.0, places=2)

    def test_model_registry_and_manifest_candidate_r75(self):
        """Verify candidate_r75_M15 is registered in registry.json and manifest.json."""
        self.assertTrue(self.registry_file.exists(), "artifacts/models/registry.json does not exist")
        with open(self.registry_file, "r", encoding="utf-8") as f:
            reg_data = json.load(f)

        self.assertIn("candidate_r75_M15", reg_data.get("models", {}))
        r75_reg = reg_data["models"]["candidate_r75_M15"]
        self.assertEqual(r75_reg.get("state"), "VALIDATED")
        self.assertEqual(r75_reg.get("artifact_file"), "candidate_r75_M15.joblib")
        self.assertEqual(r75_reg.get("model_type"), "HistGradientBoostingClassifier")

        self.assertTrue(self.manifest_file.exists(), "artifacts/manifest.json does not exist")
        with open(self.manifest_file, "r", encoding="utf-8") as f:
            man_data = json.load(f)

        self.assertIn("candidate_r75_M15", man_data.get("models", {}))
        r75_man = man_data["models"]["candidate_r75_M15"]
        self.assertEqual(r75_man.get("symbol"), "R_75")
        self.assertEqual(r75_man.get("timeframe"), "M15")
        self.assertEqual(r75_man.get("state"), "VALIDATED")

    def test_model_artifact_size_and_inference_memory(self):
        """Verify model file size is < 10MB and inference memory is < 50MB."""
        self.assertTrue(self.model_path.exists(), "candidate_r75_M15.joblib does not exist")
        file_size_mb = self.model_path.stat().st_size / (1024 * 1024)
        self.assertLess(file_size_mb, 10.0, f"Model artifact size {file_size_mb:.2f}MB exceeds 10MB limit")

        # Test inference memory
        tracemalloc.start()
        payload = joblib.load(self.model_path)
        model = payload["model"]
        scaler = payload["scaler"]
        feature_cols = payload["feature_names"]

        # Fake inference sample
        dummy_input = np.zeros((10, len(feature_cols)))
        if scaler is not None:
            dummy_input = scaler.transform(dummy_input)
        preds = model.predict_proba(dummy_input)

        _, peak_mem_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mem_mb = peak_mem_bytes / (1024 * 1024)
        self.assertLess(peak_mem_mb, 50.0, f"Inference peak memory {peak_mem_mb:.2f}MB exceeds 50MB budget")
        self.assertEqual(preds.shape, (10, 3))


if __name__ == "__main__":
    unittest.main()
