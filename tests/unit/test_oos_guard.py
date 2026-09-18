"""
Gate 22R Automated Test Suite: OOS Guard & Cryptographic Access Control
======================================================================
Implements all 15 required institutional compliance tests (Tests A through O).
"""

import os
import copy
import json
import hashlib
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import numpy as np
import pandas as pd

from ai_forex_bot.config.settings import settings
from ai_forex_bot.data.market.split import PurgedTimeSeriesSplitter
from ai_forex_bot.data.oos_guard import (
    OOSGuard,
    OOSDataset,
    OOSManifest,
    CandidateManifest,
    OOSEvaluationSession,
    OOSAccessPolicy,
    OOSAccessViolation
)
from ai_forex_bot.features.builder import FeatureBuilder


class TestOOSGuardProtocol(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)

        # Create dummy clean data
        n = 100
        start_epoch = 1800000000
        epochs = [start_epoch + i * 900 for i in range(n)]
        close = 1.1000 + np.cumsum(np.random.normal(0, 0.0001, n))
        self.df = pd.DataFrame({
            "epoch": epochs,
            "open": close - 0.0001,
            "high": close + 0.0002,
            "low": close - 0.0002,
            "close": close,
            "volume": 100
        })

        self.df_bytes = self.df.to_parquet()
        self.df_hash = hashlib.sha256(self.df_bytes).hexdigest()

        self.candidates_data = [
            {
                "candidate_id": "Candidate_Test",
                "model_type": "HistGradientBoostingClassifier",
                "hyperparameters": {"learning_rate": 0.03, "class_weight": "balanced"},
                "feature_set": ["f1", "f2"],
                "feature_count": 2,
                "label_version": "LABEL_V1",
                "horizon": 4,
                "decision_policy": {"confidence_threshold": 0.55}
            }
        ]
        self.cand_manifest = CandidateManifest(
            candidates=self.candidates_data,
            created_at="2026-09-18T12:00:00Z",
            git_commit="test_commit"
        )
        self.cand_manifest_path = self.work_dir / "candidate_manifest.json"
        self.cand_manifest.save(self.cand_manifest_path)

        self.oos_manifest = OOSManifest(
            symbol="frxEURUSD",
            timeframe="M15",
            oos_start="2026-09-18T12:00:00Z",
            oos_end="2026-09-19T13:00:00Z",
            row_count=len(self.df),
            dataset_sha256=self.df_hash,
            feature_pipeline_sha256="fake_feat_hash",
            label_pipeline_sha256="fake_label_hash",
            splitter_sha256="fake_split_hash",
            config_sha256="fake_config_hash",
            git_commit_before_unlock="test_commit",
            candidate_manifest_hash=self.cand_manifest.compute_hash(),
            creation_timestamp="2026-09-18T12:00:00Z"
        )
        self.oos_manifest_path = self.work_dir / "oos_manifest.json"
        self.oos_manifest.save(self.oos_manifest_path)

        self.log_path = self.work_dir / "test_access_log.jsonl"

    def tearDown(self):
        self.temp_dir.cleanup()
        # Restore environment
        if "LIVE_TRADING" in os.environ:
            del os.environ["LIVE_TRADING"]

    def test_A_research_script_attempting_oos_read_must_fail(self):
        """Test A: Research script attempting OOS read without session -> MUST FAIL."""
        with self.assertRaises(OOSAccessViolation):
            OOSAccessPolicy.verify_access(
                session=None,
                candidate_manifest=self.cand_manifest,
                oos_manifest=self.oos_manifest,
                log_path=self.log_path
            )

    def test_B_final_evaluator_with_valid_token_must_pass(self):
        """Test B: Final evaluator with valid token and open session -> MUST PASS."""
        session = OOSEvaluationSession(
            session_id="SESS_001",
            token="VALID_TOKEN",
            candidate_manifest_path=self.cand_manifest_path,
            oos_manifest_path=self.oos_manifest_path,
            git_commit="test_commit"
        )
        session.open_session()
        result = OOSAccessPolicy.verify_access(
            session=session,
            candidate_manifest=self.cand_manifest,
            oos_manifest=self.oos_manifest,
            log_path=self.log_path
        )
        self.assertTrue(result)

    def test_C_wrong_dataset_hash_must_fail(self):
        """Test C: Wrong dataset hash -> MUST FAIL."""
        bad_manifest = copy.deepcopy(self.oos_manifest)
        bad_manifest.dataset_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
        with self.assertRaises(OOSAccessViolation):
            bad_manifest.validate_dataframe(self.df)

    def test_D_wrong_candidate_manifest_must_fail(self):
        """Test D: Wrong candidate manifest hash -> MUST FAIL."""
        bad_cand_manifest = copy.deepcopy(self.cand_manifest)
        bad_cand_manifest.candidates[0]["candidate_id"] = "Tampered_Candidate"
        session = OOSEvaluationSession(
            session_id="SESS_001",
            token="VALID_TOKEN",
            candidate_manifest_path=self.cand_manifest_path,
            oos_manifest_path=self.oos_manifest_path,
            git_commit="test_commit"
        )
        session.open_session()
        with self.assertRaises(OOSAccessViolation):
            OOSAccessPolicy.verify_access(
                session=session,
                candidate_manifest=bad_cand_manifest,
                oos_manifest=self.oos_manifest,
                log_path=self.log_path
            )

    def test_E_second_oos_evaluation_must_fail(self):
        """Test E: Second OOS evaluation -> MUST FAIL."""
        session = OOSEvaluationSession(
            session_id="SESS_001",
            token="VALID_TOKEN",
            candidate_manifest_path=self.cand_manifest_path,
            oos_manifest_path=self.oos_manifest_path,
            git_commit="test_commit"
        )
        session.open_session()
        session.close_and_consume(log_path=self.log_path)
        with self.assertRaises(OOSAccessViolation):
            OOSAccessPolicy.verify_access(
                session=session,
                candidate_manifest=self.cand_manifest,
                oos_manifest=self.oos_manifest,
                log_path=self.log_path
            )

    def test_F_candidate_changes_after_manifest_freeze_must_fail(self):
        """Test F: Candidate changes after manifest freeze -> MUST FAIL."""
        tampered_candidates = copy.deepcopy(self.candidates_data)
        tampered_candidates[0]["hyperparameters"]["learning_rate"] = 0.99
        tampered_manifest = CandidateManifest(
            candidates=tampered_candidates,
            created_at="2026-09-18T12:00:00Z",
            git_commit="test_commit"
        )
        session = OOSEvaluationSession(
            session_id="SESS_001",
            token="VALID_TOKEN",
            candidate_manifest_path=self.cand_manifest_path,
            oos_manifest_path=self.oos_manifest_path,
            git_commit="test_commit"
        )
        session.open_session()
        with self.assertRaises(OOSAccessViolation):
            OOSAccessPolicy.verify_access(
                session=session,
                candidate_manifest=tampered_manifest,
                oos_manifest=self.oos_manifest,
                log_path=self.log_path
            )

    def test_G_threshold_modification_after_freeze_must_fail(self):
        """Test G: Threshold modification after freeze -> MUST FAIL."""
        tampered_candidates = copy.deepcopy(self.candidates_data)
        tampered_candidates[0]["decision_policy"]["confidence_threshold"] = 0.50
        tampered_manifest = CandidateManifest(
            candidates=tampered_candidates,
            created_at="2026-09-18T12:00:00Z",
            git_commit="test_commit"
        )
        session = OOSEvaluationSession(
            session_id="SESS_001",
            token="VALID_TOKEN",
            candidate_manifest_path=self.cand_manifest_path,
            oos_manifest_path=self.oos_manifest_path,
            git_commit="test_commit"
        )
        session.open_session()
        with self.assertRaises(OOSAccessViolation):
            OOSAccessPolicy.verify_access(
                session=session,
                candidate_manifest=tampered_manifest,
                oos_manifest=self.oos_manifest,
                log_path=self.log_path
            )

    def test_H_feature_list_modification_after_freeze_must_fail(self):
        """Test H: Feature list modification after freeze -> MUST FAIL."""
        tampered_candidates = copy.deepcopy(self.candidates_data)
        tampered_candidates[0]["feature_set"].append("f3_leak")
        tampered_manifest = CandidateManifest(
            candidates=tampered_candidates,
            created_at="2026-09-18T12:00:00Z",
            git_commit="test_commit"
        )
        session = OOSEvaluationSession(
            session_id="SESS_001",
            token="VALID_TOKEN",
            candidate_manifest_path=self.cand_manifest_path,
            oos_manifest_path=self.oos_manifest_path,
            git_commit="test_commit"
        )
        session.open_session()
        with self.assertRaises(OOSAccessViolation):
            OOSAccessPolicy.verify_access(
                session=session,
                candidate_manifest=tampered_manifest,
                oos_manifest=self.oos_manifest,
                log_path=self.log_path
            )

    def test_I_label_version_modification_must_fail(self):
        """Test I: Label version modification -> MUST FAIL."""
        tampered_candidates = copy.deepcopy(self.candidates_data)
        tampered_candidates[0]["label_version"] = "LABEL_V2"
        tampered_manifest = CandidateManifest(
            candidates=tampered_candidates,
            created_at="2026-09-18T12:00:00Z",
            git_commit="test_commit"
        )
        session = OOSEvaluationSession(
            session_id="SESS_001",
            token="VALID_TOKEN",
            candidate_manifest_path=self.cand_manifest_path,
            oos_manifest_path=self.oos_manifest_path,
            git_commit="test_commit"
        )
        session.open_session()
        with self.assertRaises(OOSAccessViolation):
            OOSAccessPolicy.verify_access(
                session=session,
                candidate_manifest=tampered_manifest,
                oos_manifest=self.oos_manifest,
                log_path=self.log_path
            )

    def test_J_live_trading_prohibits_oos_access(self):
        """Test J: OOS access when LIVE_TRADING=true -> MUST FAIL; LIVE_TRADING=false -> permitted only for evaluator."""
        session = OOSEvaluationSession(
            session_id="SESS_001",
            token="VALID_TOKEN",
            candidate_manifest_path=self.cand_manifest_path,
            oos_manifest_path=self.oos_manifest_path,
            git_commit="test_commit"
        )
        session.open_session()

        os.environ["LIVE_TRADING"] = "true"
        with self.assertRaises(OOSAccessViolation):
            OOSAccessPolicy.verify_access(
                session=session,
                candidate_manifest=self.cand_manifest,
                oos_manifest=self.oos_manifest,
                log_path=self.log_path
            )

        os.environ["LIVE_TRADING"] = "false"
        self.assertTrue(
            OOSAccessPolicy.verify_access(
                session=session,
                candidate_manifest=self.cand_manifest,
                oos_manifest=self.oos_manifest,
                log_path=self.log_path
            )
        )

    def test_K_no_future_data_inside_feature_matrix(self):
        """Test K: No future data appears inside feature matrix."""
        fb = FeatureBuilder()
        n = 300
        start_epoch = 1800000000
        epochs = [start_epoch + i * 900 for i in range(n)]
        close = 1.1000 + np.cumsum(np.random.normal(0, 0.0001, n))
        df_rich = pd.DataFrame({
            "epoch": epochs,
            "open": close - 0.0001,
            "high": close + 0.0002,
            "low": close - 0.0002,
            "close": close,
            "volume": 1000
        })
        df_feat = fb.build_features(df_rich, symbol="frxEURUSD")

        # In a causal feature matrix, changing future rows (t+1..T) must NOT alter row t features
        df_tampered = df_rich.copy()
        df_tampered.loc[250:, "open"] *= 1.05
        df_tampered.loc[250:, "high"] *= 1.05
        df_tampered.loc[250:, "low"] *= 1.05
        df_tampered.loc[250:, "close"] *= 1.05
        df_feat_tampered = fb.build_features(df_tampered, symbol="frxEURUSD")

        # Rows 0 to 200 features must be identical
        feature_cols = [c for c in df_feat.columns if c not in {"epoch", "regime", "econ_policy"}]
        np.testing.assert_allclose(
            df_feat.loc[:200, feature_cols].values,
            df_feat_tampered.loc[:200, feature_cols].values,
            rtol=1e-5,
            err_msg="Future data leaked backward into historical feature rows!"
        )

    def test_L_research_pipeline_cannot_indirectly_load_oos_via_helper(self):
        """Test L: Research pipeline cannot indirectly load OOS via helper."""
        splitter = PurgedTimeSeriesSplitter(horizon_bars=4)
        with self.assertRaises(OOSAccessViolation):
            splitter.get_test_dataframe(self.df, session=None)

    def test_M_contaminated_old_test_cannot_be_selected_as_benchmark(self):
        """Test M: Contaminated Old Test cannot be selected as candidate benchmark."""
        session = OOSEvaluationSession(
            session_id="SESS_001",
            token="VALID_TOKEN",
            candidate_manifest_path=self.cand_manifest_path,
            oos_manifest_path=self.oos_manifest_path,
            git_commit="test_commit"
        )
        session.open_session()

        # Mock hashlib to return contaminated hash
        with mock.patch("ai_forex_bot.data.oos_guard.hashlib.sha256") as mock_sha:
            mock_sha.return_value.hexdigest.return_value = OOSDataset.CONTAMINATED_TEST_SLICE_HASH
            with self.assertRaises(OOSAccessViolation):
                OOSDataset.load_oos_data(
                    df_or_path=self.df,
                    session=session,
                    oos_manifest=self.oos_manifest,
                    candidate_manifest=self.cand_manifest,
                    log_path=self.log_path
                )


    def test_N_no_synthetic_oos_rows_can_enter_evaluator(self):
        """Test N: No synthetic OOS rows can enter evaluator."""
        df_synth = self.df.copy()
        df_synth["is_synthetic"] = True
        with self.assertRaises(OOSAccessViolation):
            self.oos_manifest.validate_dataframe(df_synth)

    def test_O_duplicate_timestamp_overlapping_oos_rows_are_rejected(self):
        """Test O: Duplicate timestamp / overlapping OOS rows are rejected."""
        df_dup = self.df.copy()
        df_dup.loc[5, "epoch"] = df_dup.loc[4, "epoch"] # duplicate timestamp
        with self.assertRaises(OOSAccessViolation):
            self.oos_manifest.validate_dataframe(df_dup)


if __name__ == "__main__":
    unittest.main()
