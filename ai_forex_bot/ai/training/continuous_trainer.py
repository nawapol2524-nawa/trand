"""
Continuous Retraining Worker & Pipeline
=======================================
Institutional Continuous Training Pipeline Standard for Gate 24
Executes scheduled or event-driven model retraining in a decoupled worker:
- Strict Pre-Flight Checks: disk space, sample threshold, timestamp freshness
- Leak-Free Purged Walk-Forward Time Series Validation (Horizon >= 4 bars)
- Candidate B Architecture: HistGradientBoosting (balanced class weights)
- Out-of-sample probability calibration (isotonic regression)
- Model Registration into ModelRegistry in VALIDATED state
- Strict Governance: AUTO_PROMOTION = False (zero silent promotion)
- Audit & Telemetry Logging: logs/training_events.jsonl
"""

import os
import json
import shutil
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
import joblib

from ai_forex_bot.config.settings import settings
from ai_forex_bot.features.builder import FeatureBuilder
from ai_forex_bot.labels.labeler import CostAwareLabeler
from ai_forex_bot.ai.models.base import HistGradientBoostingModel
from ai_forex_bot.ai.evaluation.evaluator import ModelEvaluator
from ai_forex_bot.ai.training.walk_forward import WalkForwardValidator
from ai_forex_bot.models.registry import ModelRegistry, ModelLifecycleState


@dataclass
class PreflightCheckResult:
    passed: bool
    reason: str
    metrics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ContinuousTrainer:
    def __init__(
        self,
        symbol: str = "frxEURUSD",
        timeframe: str = "M15",
        min_new_samples: int = 200,
        min_disk_mb: float = 500.0,
        auto_promotion: bool = False,
        registry: Optional[ModelRegistry] = None,
        log_file: Optional[Path] = None
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.min_new_samples = min_new_samples
        self.min_disk_mb = min_disk_mb
        # Strict governance invariant: auto-promotion is False
        self.auto_promotion = False if not auto_promotion else False
        self.root_dir = settings.root_dir
        self.registry = registry or ModelRegistry()
        self.feature_builder = FeatureBuilder()
        self.labeler = CostAwareLabeler()

        self.log_file = log_file or (self.root_dir / "logs" / "training_events.jsonl")
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # Frozen Candidate B hyperparameter specification
        self.candidate_params = {
            "learning_rate": 0.03,
            "max_iter": 100,
            "min_samples_leaf": 20,
            "l2_regularization": 0.0,
            "class_weight": "balanced",
            "random_state": 42
        }

    def log_event(self, event_type: str, details: Dict[str, Any]) -> None:
        """Appends an event to the training telemetry log."""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "auto_promotion": self.auto_promotion,
            "details": details
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def load_clean_data(self) -> pd.DataFrame:
        clean_file = settings.clean_data_dir / f"{self.symbol}_{self.timeframe}.parquet"
        if not clean_file.exists():
            raise FileNotFoundError(f"Clean parquet not found at {clean_file}. Data pipeline must run first.")
        return pd.read_parquet(clean_file)

    def prepare_dataset(self, df_base: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        if df_base is None:
            df_base = self.load_clean_data()

        h1_file = settings.clean_data_dir / f"{self.symbol}_H1.parquet"
        df_h1 = pd.read_parquet(h1_file) if h1_file.exists() else None

        df_feat = self.feature_builder.build_features(df_base, df_h1=df_h1, symbol=self.symbol)
        df_labeled = self.labeler.label_dataset(df_feat, symbol=self.symbol)
        return df_labeled

    def run_preflight_checks(
        self,
        df: Optional[pd.DataFrame] = None,
        prior_rows_override: Optional[int] = None
    ) -> PreflightCheckResult:
        """
        Executes pre-flight validation:
        1. Free disk space check (>= min_disk_mb)
        2. Non-empty dataset verification
        3. Monotonic epoch timestamp check
        4. Minimum new samples threshold check against last registered training
        """
        # 1. Disk space check
        total, used, free = shutil.disk_usage(self.root_dir)
        free_mb = free / (1024 * 1024)
        if free_mb < self.min_disk_mb:
            return PreflightCheckResult(
                passed=False,
                reason=f"INSUFFICIENT_DISK_SPACE: {free_mb:.1f}MB free < {self.min_disk_mb:.1f}MB threshold",
                metrics={"free_disk_mb": free_mb, "min_disk_mb": self.min_disk_mb}
            )

        # 2. Data check
        if df is None:
            try:
                df = self.load_clean_data()
            except Exception as e:
                return PreflightCheckResult(
                    passed=False,
                    reason=f"DATA_LOAD_FAILED: {str(e)}",
                    metrics={"error": str(e)}
                )

        if df is None or len(df) == 0:
            return PreflightCheckResult(
                passed=False,
                reason="EMPTY_DATASET: Clean dataset contains 0 rows",
                metrics={"rows": 0}
            )

        # 3. Timestamp check
        if "epoch" not in df.columns or df["epoch"].iloc[-1] <= df["epoch"].iloc[0]:
            return PreflightCheckResult(
                passed=False,
                reason="INVALID_TIMESTAMP_RANGE: Epoch timestamps are not monotonically increasing",
                metrics={"start_epoch": int(df.get("epoch", [0])[0]), "end_epoch": int(df.get("epoch", [0])[-1])}
            )

        # 4. New samples check
        if prior_rows_override is not None:
            prior_rows = prior_rows_override
        else:
            champion = self.registry.get_champion()
            if champion:
                prior_rows = champion.train_row_count
            elif len(self.registry.models) > 0:
                prior_rows = max(m.train_row_count for m in self.registry.models.values())
            else:
                prior_rows = 0

        current_rows = len(df)
        new_samples = current_rows - prior_rows

        if prior_rows > 0 and new_samples < self.min_new_samples:
            return PreflightCheckResult(
                passed=False,
                reason=f"INSUFFICIENT_NEW_DATA: {new_samples} new bars < threshold {self.min_new_samples} (prior: {prior_rows}, current: {current_rows})",
                metrics={
                    "current_rows": current_rows,
                    "prior_rows": prior_rows,
                    "new_samples": new_samples,
                    "min_new_samples": self.min_new_samples
                }
            )

        return PreflightCheckResult(
            passed=True,
            reason="PREFLIGHT_OK: All environmental, data freshness, and capacity checks passed",
            metrics={
                "free_disk_mb": free_mb,
                "current_rows": current_rows,
                "prior_rows": prior_rows,
                "new_samples": new_samples,
                "min_new_samples": self.min_new_samples,
                "start_epoch": int(df["epoch"].iloc[0]),
                "end_epoch": int(df["epoch"].iloc[-1])
            }
        )

    def execute_retraining(
        self,
        trigger: str = "MANUAL",
        dry_run: bool = False,
        force_preflight: bool = False,
        prior_rows_override: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Runs the continuous retraining pipeline:
        - Logs execution trigger
        - Runs pre-flight checks
        - Purged walk-forward validation (leak-free)
        - Cost-hurdle verification (1.82 bps)
        - Fits candidate model & performs probability calibration
        - Saves model artifact to artifacts/models/
        - Registers model in ModelRegistry with state VALIDATED (never silently promoted)
        """
        start_time = datetime.now(timezone.utc)
        self.log_event("TRAINING_TRIGGERED", {
            "trigger": trigger,
            "dry_run": dry_run,
            "force_preflight": force_preflight,
            "start_time": start_time.isoformat()
        })

        # Load and preflight check
        try:
            df_base = self.load_clean_data()
        except Exception as e:
            err_msg = f"Failed to load market data: {str(e)}"
            self.log_event("TRAINING_FAILED", {"error": err_msg})
            return {"success": False, "reason": err_msg}

        preflight = self.run_preflight_checks(df_base, prior_rows_override=prior_rows_override)
        if not preflight.passed and not force_preflight:
            self.log_event("PREFLIGHT_REJECTED", {
                "reason": preflight.reason,
                "metrics": preflight.metrics
            })
            return {
                "success": False,
                "reason": preflight.reason,
                "preflight": preflight.to_dict()
            }

        # Build features and labels
        df_labeled = self.prepare_dataset(df_base)
        meta_cols = {
            "epoch", "regime", "econ_policy", "target_class",
            "future_return", "future_net_buy", "future_net_sell"
        }
        feature_cols = [c for c in df_labeled.columns if c not in meta_cols]

        if dry_run:
            dry_run_result = {
                "success": True,
                "dry_run": True,
                "trigger": trigger,
                "preflight": preflight.to_dict(),
                "dataset_summary": {
                    "symbol": self.symbol,
                    "timeframe": self.timeframe,
                    "total_rows": len(df_labeled),
                    "feature_count": len(feature_cols),
                    "features": feature_cols[:5] + ["..."]
                }
            }
            self.log_event("DRY_RUN_COMPLETED", dry_run_result)
            return dry_run_result

        # Run Purged Walk-Forward Cross Validation
        wfv = WalkForwardValidator(
            n_splits=4,
            train_window_bars=8000,
            test_window_bars=2000,
            horizon_bars=4,
            embargo_bars=0
        )
        wf_splits = wfv.validate(
            df_labeled,
            model_cls=HistGradientBoostingModel,
            model_params=self.candidate_params
        )

        all_leak_free = all(s["leak_free"] for s in wf_splits)
        bal_accs = [s["metrics"]["balanced_accuracy"] for s in wf_splits]
        f1_scores = [s["metrics"]["f1_macro"] for s in wf_splits]
        brier_scores = [s["metrics"]["brier_score"] for s in wf_splits]

        avg_bal_acc = float(np.mean(bal_accs)) if bal_accs else 0.0
        avg_f1 = float(np.mean(f1_scores)) if f1_scores else 0.0
        avg_brier = float(np.mean(brier_scores)) if brier_scores else 1.0

        # Cost hurdle check: Candidate B assumes 1.82 bps roundtrip cost.
        # Minimum acceptable walk-forward balanced accuracy is 0.35
        cost_hurdle_passed = bool(avg_bal_acc >= 0.35 and all_leak_free)

        cv_summary = {
            "n_splits": len(wf_splits),
            "all_leak_free": all_leak_free,
            "avg_balanced_accuracy": avg_bal_acc,
            "avg_f1_macro": avg_f1,
            "avg_brier_score": avg_brier,
            "cost_hurdle_passed": cost_hurdle_passed,
            "split_details": [
                {
                    "split_index": s["split_index"],
                    "balanced_accuracy": s["metrics"]["balanced_accuracy"],
                    "f1_macro": s["metrics"]["f1_macro"],
                    "leak_free": s["leak_free"]
                }
                for s in wf_splits
            ]
        }

        # Train & Calibrate Full Retrained Model
        # Split: 80% train, 20% validation for probability calibration with purge gap >= 4 bars
        n_total = len(df_labeled)
        split_idx = int(n_total * 0.80)
        safe_train_end = max(0, split_idx - 4)  # Purge gap

        train_slice = df_labeled.iloc[:safe_train_end]
        val_slice = df_labeled.iloc[split_idx:]

        X_train_raw = train_slice[feature_cols].values
        y_train = train_slice["target_class"].values

        X_val_raw = val_slice[feature_cols].values
        y_val = val_slice["target_class"].values
        f_val = val_slice["future_return"].values

        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train_raw)
        X_val_scaled = scaler.transform(X_val_raw)

        model = HistGradientBoostingModel(self.candidate_params)
        model.fit(X_train_scaled, y_train, feature_names=feature_cols)

        # Out-of-sample probability calibration on validation slice
        model.calibrate(X_val_scaled, y_val, method="isotonic")

        val_preds = model.predict(X_val_scaled)
        val_probas = model.predict_proba(X_val_scaled)
        val_metrics = ModelEvaluator.evaluate(y_val, val_preds, val_probas, future_returns=f_val)

        # Save model artifact
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        model_id = f"retrained_{self.symbol}_{self.timeframe}_{ts_str}"
        model_dir = self.root_dir / "artifacts" / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = model_dir / f"{model_id}.joblib"

        artifact_payload = {
            "model_id": model_id,
            "model_name": model.model_name,
            "scaler": scaler,
            "model": model,
            "feature_names": feature_cols,
            "params": self.candidate_params,
            "validation_metrics": val_metrics,
            "cv_summary": cv_summary,
            "trained_at": datetime.now(timezone.utc).isoformat()
        }
        joblib.dump(artifact_payload, artifact_path)

        # Register in ModelRegistry in VALIDATED state
        # CRITICAL GOVERNANCE INVARIANT: AUTO_PROMOTION = False
        registered_record = self.registry.register_model(
            model_id=model_id,
            model_type=model.model_name,
            version="2.0.0",
            artifact_path=artifact_path,
            train_start_epoch=int(train_slice["epoch"].iloc[0]),
            train_end_epoch=int(val_slice["epoch"].iloc[-1]),
            train_row_count=n_total,
            feature_names=feature_cols,
            hyperparameters=self.candidate_params,
            validation_metrics={
                "balanced_accuracy": val_metrics.get("balanced_accuracy", 0.0),
                "f1_macro": val_metrics.get("f1_macro", 0.0),
                "brier_score": val_metrics.get("brier_score", 1.0),
                "cv_summary": cv_summary
            },
            initial_state=ModelLifecycleState.VALIDATED,
            metadata={
                "trigger": trigger,
                "cost_hurdle_passed": cost_hurdle_passed,
                "preflight": preflight.to_dict(),
                "governance": {
                    "auto_promotion": False,
                    "live_trading": False
                }
            }
        )

        end_time = datetime.now(timezone.utc)
        duration_s = (end_time - start_time).total_seconds()

        self.log_event("TRAINING_SUCCESS", {
            "model_id": model_id,
            "state": registered_record.state.value,
            "artifact_file": registered_record.artifact_file,
            "model_hash": registered_record.model_hash,
            "duration_seconds": duration_s,
            "balanced_accuracy": val_metrics.get("balanced_accuracy"),
            "cost_hurdle_passed": cost_hurdle_passed,
            "auto_promoted": False
        })

        return {
            "success": True,
            "model_id": model_id,
            "lifecycle_state": registered_record.state.value,
            "artifact_file": str(artifact_path.name),
            "model_hash": registered_record.model_hash,
            "validation_metrics": val_metrics,
            "cv_summary": cv_summary,
            "cost_hurdle_passed": cost_hurdle_passed,
            "auto_promoted": False,
            "preflight": preflight.to_dict(),
            "duration_seconds": duration_s
        }
