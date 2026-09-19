#!/usr/bin/env python3
"""
Institutional AI Model Training & Registry Script for R_75 (Volatility 75 Index)
================================================================================
Timeframe: M15 (with H1 higher timeframe feature alignment)
Target: Triple-barrier classification (0=HOLD, 1=BUY, 2=SELL)
Model: HistGradientBoostingClassifier with Isotonic Probability Calibration
Lifecycle State: VALIDATED
"""

import os
import sys
import json
import hashlib
import tracemalloc
from pathlib import Path
from datetime import datetime, timezone

# Ensure project root is in sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

import numpy as np
import pandas as pd
import joblib
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV

from ai_forex_bot.config.settings import settings
from ai_forex_bot.features.builder import FeatureBuilder
from ai_forex_bot.labels.labeler import CostAwareLabeler, LabelConfig
from ai_forex_bot.ai.models.base import HistGradientBoostingModel
from ai_forex_bot.ai.training.walk_forward import WalkForwardValidator
from ai_forex_bot.ai.evaluation.evaluator import ModelEvaluator
from ai_forex_bot.models.registry import ModelRegistry, ModelLifecycleState


def train_and_register_r75() -> dict:
    print("=" * 80)
    print("STARTING R_75 M15 MODEL TRAINING & REGISTRATION PIPELINE")
    print("=" * 80)

    # 1. Load clean datasets
    clean_m15_path = settings.clean_data_dir / "R_75_M15.parquet"
    clean_h1_path = settings.clean_data_dir / "R_75_H1.parquet"

    print(f"[1/8] Loading dataset files:\n  M15: {clean_m15_path}\n  H1:  {clean_h1_path}")
    if not clean_m15_path.exists():
        raise FileNotFoundError(f"Clean M15 dataset not found at {clean_m15_path}")
    if not clean_h1_path.exists():
        raise FileNotFoundError(f"Clean H1 dataset not found at {clean_h1_path}")

    df_m15 = pd.read_parquet(clean_m15_path)
    df_h1 = pd.read_parquet(clean_h1_path)
    print(f"  M15 raw bars: {len(df_m15):,}, H1 raw bars: {len(df_h1):,}")

    # 2. Compute multi-timeframe causal features
    print("[2/8] Computing multi-timeframe causal features using FeatureBuilder...")
    feature_builder = FeatureBuilder()
    df_features = feature_builder.build_features(df_m15, df_h1=df_h1, symbol="R_75")
    print(f"  Feature-engineered bars: {len(df_features):,}, columns: {len(df_features.columns)}")

    # 3. Compute triple-barrier labels
    # Since pip_size=0.01 for R_75, 250 index points = 25,000 pips
    print("[3/8] Generating triple-barrier target labels with CostAwareLabeler...")
    label_cfg = LabelConfig(
        horizon_bars=4,
        profit_target_pips=25000.0,
        stop_loss_pips=25000.0
    )
    labeler = CostAwareLabeler(config=label_cfg)
    df_labeled = labeler.label_dataset(df_features, symbol="R_75")
    print(f"  Labeled bars: {len(df_labeled):,}")

    # Inspect class balance
    class_counts = df_labeled["target_class"].value_counts().to_dict()
    class_ratios = df_labeled["target_class"].value_counts(normalize=True).to_dict()
    print("  Target Class Distribution:")
    for cls_val in sorted(class_counts.keys()):
        cls_name = {0: "HOLD", 1: "BUY", 2: "SELL"}.get(cls_val, str(cls_val))
        print(f"    Class {cls_val} ({cls_name}): {class_counts[cls_val]:,} bars ({class_ratios[cls_val] * 100:.2f}%)")

    # 4. Separate feature matrix and targets
    print("[4/8] Separating feature matrix and target...")
    meta_cols = {
        "epoch", "regime", "econ_policy", "target_class",
        "future_return", "future_net_buy", "future_net_sell"
    }
    feature_cols = [c for c in df_labeled.columns if c not in meta_cols]
    print(f"  Selected feature count: {len(feature_cols)}")

    # Hyperparameters for candidate model
    candidate_params = {
        "learning_rate": 0.03,
        "max_iter": 100,
        "min_samples_leaf": 20,
        "l2_regularization": 0.0,
        "class_weight": "balanced",
        "random_state": 42,
        "max_depth": None
    }

    # 5. Purged Time-Series Walk-Forward Cross-Validation
    print("[5/8] Performing Purged Time-Series Walk-Forward Cross-Validation (4 splits, purge horizon >= 4)...")
    wf_validator = WalkForwardValidator(
        n_splits=4,
        train_window_bars=12000,
        test_window_bars=3000,
        horizon_bars=4,
        embargo_bars=0
    )

    wf_splits = wf_validator.validate(
        df_labeled,
        model_cls=HistGradientBoostingModel,
        model_params=candidate_params
    )

    cv_bal_accs = [s["metrics"]["balanced_accuracy"] for s in wf_splits]
    cv_f1s = [s["metrics"]["f1_macro"] for s in wf_splits]
    cv_briers = [s["metrics"]["brier_score"] for s in wf_splits]
    all_leak_free = all(s["leak_free"] for s in wf_splits)

    print("  Walk-Forward Validation Splits:")
    for s in wf_splits:
        m = s["metrics"]
        print(f"    Split {s['split_index']}: Train bars: {s['train_bars']:,}, Test bars: {s['test_bars']:,} | "
              f"BalAcc: {m['balanced_accuracy']:.4f}, F1-Macro: {m['f1_macro']:.4f}, Brier: {m['brier_score']:.4f}, "
              f"Leak-Free: {s['leak_free']}")

    cv_summary = {
        "n_splits": len(wf_splits),
        "all_leak_free": all_leak_free,
        "avg_balanced_accuracy": float(np.mean(cv_bal_accs)),
        "avg_f1_macro": float(np.mean(cv_f1s)),
        "avg_brier_score": float(np.mean(cv_briers)),
        "splits": [
            {
                "split_index": s["split_index"],
                "train_bars": s["train_bars"],
                "test_bars": s["test_bars"],
                "balanced_accuracy": s["metrics"]["balanced_accuracy"],
                "f1_macro": s["metrics"]["f1_macro"],
                "brier_score": s["metrics"]["brier_score"],
                "leak_free": s["leak_free"]
            }
            for s in wf_splits
        ]
    }
    print(f"  CV Averages -> BalAcc: {cv_summary['avg_balanced_accuracy']:.4f}, "
          f"F1-Macro: {cv_summary['avg_f1_macro']:.4f}, Brier: {cv_summary['avg_brier_score']:.4f}, "
          f"All Leak-Free: {all_leak_free}")

    # 6. Fit candidate model and calibrate on validation holdout
    print("[6/8] Fitting candidate model & calibrating probabilities on validation holdout...")
    n_total = len(df_labeled)
    split_idx = int(n_total * 0.80)
    safe_train_end = max(0, split_idx - 4)  # 4-bar purge gap to guarantee zero leak

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

    # Base Classifier
    hgb_classifier = HistGradientBoostingClassifier(
        learning_rate=candidate_params["learning_rate"],
        max_iter=candidate_params["max_iter"],
        min_samples_leaf=candidate_params["min_samples_leaf"],
        l2_regularization=candidate_params["l2_regularization"],
        class_weight=candidate_params["class_weight"],
        random_state=candidate_params["random_state"]
    )
    hgb_classifier.fit(X_train_scaled, y_train)

    # Probability Calibration via Isotonic Regression on prefit holdout
    calibrated_clf = CalibratedClassifierCV(
        estimator=hgb_classifier,
        method="isotonic",
        cv="prefit"
    )
    calibrated_clf.fit(X_val_scaled, y_val)

    # Wrap in BaseModel instance for ecosystem compatibility
    model_wrapper = HistGradientBoostingModel(candidate_params)
    model_wrapper.model = hgb_classifier
    model_wrapper.calibrated_model = calibrated_clf
    model_wrapper.feature_names = feature_cols
    model_wrapper.classes_ = hgb_classifier.classes_
    model_wrapper.is_fitted = True

    # Compute validation metrics
    val_preds = model_wrapper.predict(X_val_scaled)
    val_probas = model_wrapper.predict_proba(X_val_scaled)
    val_metrics = ModelEvaluator.evaluate(y_val, val_preds, val_probas, future_returns=f_val)
    val_metrics["cv_summary"] = cv_summary

    print("  Validation Holdout Performance:")
    print(f"    Balanced Accuracy: {val_metrics['balanced_accuracy']:.4f}")
    print(f"    F1 Macro:          {val_metrics['f1_macro']:.4f}")
    print(f"    Brier Score:       {val_metrics['brier_score']:.4f}")
    print(f"    Precision Macro:   {val_metrics['precision_macro']:.4f}")
    print(f"    Recall Macro:      {val_metrics['recall_macro']:.4f}")
    if "win_rate" in val_metrics:
        print(f"    Win Rate:          {val_metrics['win_rate'] * 100:.2f}%")
        print(f"    Profit Factor:     {val_metrics['profit_factor']:.2f}")
        print(f"    Sharpe Ratio:      {val_metrics['sharpe_ratio']:.2f}")

    # 7. Save model artifact and verify resource limits
    print("[7/8] Saving model artifact and validating resource constraints (<10MB file, <50MB inference)...")
    models_dir = settings.root_dir / "artifacts" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = models_dir / "candidate_r75_M15.joblib"

    artifact_payload = {
        "model_id": "candidate_r75_M15",
        "symbol": "R_75",
        "timeframe": "M15",
        "model_name": "HistGradientBoostingClassifier",
        "scaler": scaler,
        "model": model_wrapper,
        "calibrated_model": calibrated_clf,
        "feature_cols": feature_cols,
        "feature_names": feature_cols,
        "params": candidate_params,
        "validation_metrics": val_metrics,
        "cv_summary": cv_summary,
        "trained_at": datetime.now(timezone.utc).isoformat()
    }
    joblib.dump(artifact_payload, artifact_path)

    # Check file size
    file_size_bytes = artifact_path.stat().st_size
    file_size_mb = file_size_bytes / (1024 * 1024)
    print(f"  Artifact File Size: {file_size_mb:.3f} MB (Constraint: < 10.0 MB) -> {'PASS' if file_size_mb < 10.0 else 'FAIL'}")
    if file_size_mb >= 10.0:
        raise ValueError(f"Artifact size {file_size_mb:.2f} MB exceeds 10 MB limit!")

    # Check inference memory
    tracemalloc.start()
    loaded_art = joblib.load(artifact_path)
    X_inf_sample = X_val_scaled[:100]
    _ = loaded_art["model"].predict_proba(X_inf_sample)
    _, peak_mem_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mem_mb = peak_mem_bytes / (1024 * 1024)
    print(f"  Inference Memory Peak: {peak_mem_mb:.3f} MB (Constraint: < 50.0 MB) -> {'PASS' if peak_mem_mb < 50.0 else 'FAIL'}")
    if peak_mem_mb >= 50.0:
        raise ValueError(f"Inference peak memory {peak_mem_mb:.2f} MB exceeds 50 MB limit!")

    # Cryptographic hash
    sha256_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    print(f"  Artifact SHA-256: {sha256_hash}")

    # 8. Register in ModelRegistry and write manifest
    print("[8/8] Registering model in ModelRegistry and updating artifacts/manifest.json...")
    registry = ModelRegistry()
    record = registry.register_model(
        model_id="candidate_r75_M15",
        model_type="HistGradientBoostingClassifier",
        version="2.0.0",
        artifact_path=artifact_path,
        train_start_epoch=int(train_slice["epoch"].iloc[0]),
        train_end_epoch=int(val_slice["epoch"].iloc[-1]),
        train_row_count=n_total,
        feature_names=feature_cols,
        hyperparameters=candidate_params,
        validation_metrics={
            "balanced_accuracy": float(val_metrics.get("balanced_accuracy", 0.0)),
            "f1_macro": float(val_metrics.get("f1_macro", 0.0)),
            "brier_score": float(val_metrics.get("brier_score", 1.0)),
            "precision_macro": float(val_metrics.get("precision_macro", 0.0)),
            "recall_macro": float(val_metrics.get("recall_macro", 0.0)),
            "win_rate": float(val_metrics.get("win_rate", 0.0)),
            "profit_factor": float(val_metrics.get("profit_factor", 0.0)),
            "sharpe_ratio": float(val_metrics.get("sharpe_ratio", 0.0)),
            "cv_summary": cv_summary
        },
        initial_state=ModelLifecycleState.VALIDATED,
        metadata={
            "symbol": "R_75",
            "timeframe": "M15",
            "asset_class": "synthetic_index",
            "train_bars": len(train_slice),
            "val_bars": len(val_slice),
            "purge_gap_bars": split_idx - safe_train_end,
            "governance": {
                "auto_promotion": False,
                "live_trading": False
            }
        }
    )
    print(f"  Registered record ID: {record.model_id}, State: {record.state.value}")

    # Write / update artifacts/manifest.json
    manifest_path = settings.root_dir / "artifacts" / "manifest.json"
    manifest_data = {}
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception:
            manifest_data = {}

    if "models" not in manifest_data:
        manifest_data["models"] = {}

    model_manifest_entry = {
        "model_id": "candidate_r75_M15",
        "artifact_file": "candidate_r75_M15.joblib",
        "model_type": "HistGradientBoostingClassifier",
        "symbol": "R_75",
        "timeframe": "M15",
        "feature_count": len(feature_cols),
        "validation_metrics": {
            "balanced_accuracy": float(val_metrics.get("balanced_accuracy", 0.0)),
            "f1_macro": float(val_metrics.get("f1_macro", 0.0)),
            "brier_score": float(val_metrics.get("brier_score", 1.0)),
            "precision_macro": float(val_metrics.get("precision_macro", 0.0)),
            "recall_macro": float(val_metrics.get("recall_macro", 0.0)),
            "win_rate": float(val_metrics.get("win_rate", 0.0)),
            "profit_factor": float(val_metrics.get("profit_factor", 0.0)),
            "sharpe_ratio": float(val_metrics.get("sharpe_ratio", 0.0)),
            "cv_summary": cv_summary
        },
        "sha256": sha256_hash,
        "hyperparameters": candidate_params,
        "state": "VALIDATED",
        "file_size_mb": round(file_size_mb, 4),
        "inference_memory_mb": round(peak_mem_mb, 4),
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    manifest_data["models"]["candidate_r75_M15"] = model_manifest_entry
    manifest_data["candidate_r75_M15"] = model_manifest_entry  # direct key access
    manifest_data["last_updated"] = datetime.now(timezone.utc).isoformat()

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    print(f"  Manifest written to: {manifest_path}")

    print("=" * 80)
    print("TRAINING, VALIDATION & REGISTRATION COMPLETED SUCCESSFULLY")
    print("=" * 80)

    return {
        "model_id": "candidate_r75_M15",
        "artifact_file": str(artifact_path),
        "sha256": sha256_hash,
        "file_size_mb": file_size_mb,
        "inference_memory_mb": peak_mem_mb,
        "validation_metrics": val_metrics,
        "cv_summary": cv_summary
    }


if __name__ == "__main__":
    train_and_register_r75()
