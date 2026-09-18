"""
Unit Tests for Gate 24: Continuous Retraining & Model Registry Pipeline
======================================================================
Tests:
- Pre-flight checks: disk space, sample thresholds, data freshness
- ModelRegistry state transitions & audit history
- Zero Silent Promotion / Champion Protection
- Gated promotion criteria & rollback to previous champion
- Dry run execution & telemetry logging
"""

import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
import pandas as pd

from ai_forex_bot.models.registry import ModelRegistry, ModelLifecycleState, ModelRecord
from ai_forex_bot.ai.training.continuous_trainer import ContinuousTrainer, PreflightCheckResult


class TestGate24RetrainingPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="gate24_test_")
        self.temp_path = Path(self.temp_dir)
        self.registry_file = self.temp_path / "artifacts" / "models" / "registry.json"
        self.log_file = self.temp_path / "logs" / "training_events.jsonl"
        self.registry = ModelRegistry(registry_file=self.registry_file)

        # Create dummy artifact file for registration tests
        self.dummy_artifact = self.temp_path / "artifacts" / "models" / "test_model.joblib"
        self.dummy_artifact.parent.mkdir(parents=True, exist_ok=True)
        self.dummy_artifact.write_bytes(b"dummy_model_bytes_for_hash_calculation")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_model_registry_lifecycle_transitions(self):
        """Test complete model lifecycle state transitions and audit history."""
        record = self.registry.register_model(
            model_id="candidate_model_01",
            model_type="hist_gradient_boosting",
            version="2.0.0",
            artifact_path=self.dummy_artifact,
            train_start_epoch=1758165300,
            train_end_epoch=1789700400,
            train_row_count=10000,
            feature_names=["f1", "f2"],
            hyperparameters={"lr": 0.03},
            validation_metrics={"balanced_accuracy": 0.45},
            initial_state=ModelLifecycleState.CANDIDATE
        )

        self.assertEqual(record.state, ModelLifecycleState.CANDIDATE)
        self.assertTrue(len(record.model_hash) > 10)

        # Transition CANDIDATE -> VALIDATED
        self.registry.transition_state("candidate_model_01", ModelLifecycleState.VALIDATED, reason="CV_PASSED")
        self.assertEqual(self.registry.get_model("candidate_model_01").state, ModelLifecycleState.VALIDATED)

        # Transition VALIDATED -> SHADOW
        self.registry.transition_state("candidate_model_01", ModelLifecycleState.SHADOW, reason="ENTER_SHADOW_RUN")
        self.assertEqual(self.registry.get_model("candidate_model_01").state, ModelLifecycleState.SHADOW)

        # Promote SHADOW -> CHAMPION
        promoted = self.registry.promote_challenger_to_champion("candidate_model_01", min_balanced_acc=0.40)
        self.assertTrue(promoted)
        self.assertEqual(self.registry.champion_id, "candidate_model_01")
        self.assertEqual(self.registry.get_champion().state, ModelLifecycleState.CHAMPION)

        # Verify state history
        history = self.registry.get_model("candidate_model_01").state_history
        self.assertEqual(len(history), 4)  # Init, VALIDATED, SHADOW, CHAMPION

    def test_champion_protection_against_unverified_promotion(self):
        """Test that challenger with sub-threshold accuracy is rejected from promotion."""
        self.registry.register_model(
            model_id="weak_model_01",
            model_type="hist_gradient_boosting",
            version="2.0.0",
            artifact_path=self.dummy_artifact,
            train_start_epoch=1000,
            train_end_epoch=2000,
            train_row_count=5000,
            feature_names=["f1"],
            hyperparameters={},
            validation_metrics={"balanced_accuracy": 0.33},  # Below 0.40 threshold
            initial_state=ModelLifecycleState.VALIDATED
        )

        promoted = self.registry.promote_challenger_to_champion("weak_model_01", min_balanced_acc=0.40)
        self.assertFalse(promoted)
        self.assertEqual(self.registry.get_model("weak_model_01").state, ModelLifecycleState.REJECTED)
        self.assertIsNone(self.registry.get_champion())

    def test_rollback_to_previous_champion(self):
        """Test promoting two successive models, then executing rollback to the previous champion."""
        # 1. Promote Model A to Champion
        self.registry.register_model(
            model_id="model_A",
            model_type="hist_gradient_boosting",
            version="2.0.0",
            artifact_path=self.dummy_artifact,
            train_start_epoch=1000,
            train_end_epoch=2000,
            train_row_count=5000,
            feature_names=["f1"],
            hyperparameters={},
            validation_metrics={"balanced_accuracy": 0.44},
            initial_state=ModelLifecycleState.VALIDATED
        )
        self.registry.promote_challenger_to_champion("model_A")
        self.assertEqual(self.registry.champion_id, "model_A")

        # 2. Promote Model B to Champion (Model A becomes previous champion in ROLLBACK state)
        self.registry.register_model(
            model_id="model_B",
            model_type="hist_gradient_boosting",
            version="2.0.0",
            artifact_path=self.dummy_artifact,
            train_start_epoch=1000,
            train_end_epoch=3000,
            train_row_count=6000,
            feature_names=["f1"],
            hyperparameters={},
            validation_metrics={"balanced_accuracy": 0.46},
            initial_state=ModelLifecycleState.VALIDATED
        )
        self.registry.promote_challenger_to_champion("model_B")
        self.assertEqual(self.registry.champion_id, "model_B")
        self.assertEqual(self.registry.previous_champion_id, "model_A")
        self.assertEqual(self.registry.get_model("model_A").state, ModelLifecycleState.ROLLBACK)

        # 3. Trigger Rollback to Model A
        rollback_success = self.registry.rollback_to_previous_champion(reason="MODEL_B_LATENCY_SPIKE")
        self.assertTrue(rollback_success)
        self.assertEqual(self.registry.champion_id, "model_A")
        self.assertEqual(self.registry.get_model("model_A").state, ModelLifecycleState.CHAMPION)
        self.assertEqual(self.registry.get_model("model_B").state, ModelLifecycleState.ROLLBACK)

    def test_preflight_checks_pass(self):
        """Test preflight checks pass when sufficient disk space and new data exist."""
        trainer = ContinuousTrainer(
            symbol="frxEURUSD",
            timeframe="M15",
            min_new_samples=100,
            min_disk_mb=100.0,
            registry=self.registry,
            log_file=self.log_file
        )

        df_dummy = pd.DataFrame({
            "epoch": np.arange(1000, 2000, 1),
            "close": np.random.randn(1000)
        })

        res = trainer.run_preflight_checks(df=df_dummy, prior_rows_override=500)
        self.assertTrue(res.passed)
        self.assertEqual(res.metrics["new_samples"], 500)
        self.assertIn("PREFLIGHT_OK", res.reason)

    def test_preflight_checks_fail_insufficient_samples(self):
        """Test preflight checks reject when new sample threshold is not reached."""
        trainer = ContinuousTrainer(
            symbol="frxEURUSD",
            timeframe="M15",
            min_new_samples=200,
            registry=self.registry,
            log_file=self.log_file
        )

        df_dummy = pd.DataFrame({
            "epoch": np.arange(1000, 1100, 1),
            "close": np.random.randn(100)
        })

        # Prior rows = 1050, current rows = 1100 -> only 50 new samples (< 200)
        res = trainer.run_preflight_checks(df=df_dummy, prior_rows_override=1050)
        self.assertFalse(res.passed)
        self.assertIn("INSUFFICIENT_NEW_DATA", res.reason)

    def test_preflight_checks_fail_insufficient_disk(self):
        """Test preflight checks reject when available disk space is below minimum threshold."""
        trainer = ContinuousTrainer(
            symbol="frxEURUSD",
            timeframe="M15",
            min_disk_mb=500000.0,  # Unreasonably high threshold (500 GB)
            registry=self.registry,
            log_file=self.log_file
        )

        df_dummy = pd.DataFrame({
            "epoch": np.arange(1000, 2000, 1),
            "close": np.random.randn(1000)
        })

        res = trainer.run_preflight_checks(df=df_dummy, prior_rows_override=0)
        self.assertFalse(res.passed)
        self.assertIn("INSUFFICIENT_DISK_SPACE", res.reason)

    def test_zero_silent_promotion_invariant(self):
        """Verify that ContinuousTrainer enforces auto_promotion = False invariant."""
        trainer = ContinuousTrainer(
            symbol="frxEURUSD",
            timeframe="M15",
            auto_promotion=True,  # Attempt to enable auto-promotion
            registry=self.registry,
            log_file=self.log_file
        )
        self.assertFalse(trainer.auto_promotion, "AUTO_PROMOTION must be forced to False by invariant")

    def test_dry_run_mode(self):
        """Verify dry-run mode completes preflight without saving artifacts or mutating registry."""
        trainer = ContinuousTrainer(
            symbol="frxEURUSD",
            timeframe="M15",
            min_new_samples=50,
            registry=self.registry,
            log_file=self.log_file
        )

        initial_model_count = len(self.registry.models)
        result = trainer.execute_retraining(trigger="MANUAL", dry_run=True, force_preflight=True)

        self.assertTrue(result["success"])
        self.assertTrue(result["dry_run"])
        # Registry must NOT have any new entries
        self.assertEqual(len(self.registry.models), initial_model_count)

    def test_telemetry_event_logging(self):
        """Verify that continuous retraining events are properly logged to JSONL."""
        trainer = ContinuousTrainer(
            symbol="frxEURUSD",
            timeframe="M15",
            registry=self.registry,
            log_file=self.log_file
        )

        trainer.log_event("TEST_EVENT_01", {"status": "SUCCESS", "code": 200})
        self.assertTrue(self.log_file.exists())

        with open(self.log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["event_type"], "TEST_EVENT_01")
        self.assertEqual(record["details"]["status"], "SUCCESS")
        self.assertFalse(record["auto_promotion"])


if __name__ == "__main__":
    unittest.main()
