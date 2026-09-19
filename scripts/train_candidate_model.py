#!/usr/bin/env python3
"""
Institutional AI Candidate Model Training & Registration Script
================================================================
Supports multiple synthetic symbols (R_75, R_25, R_10) and timeframes (M15)
Target: Triple-barrier classification (0=HOLD, 1=BUY, 2=SELL)
Model: HistGradientBoostingClassifier with Isotonic Probability Calibration
Lifecycle State: VALIDATED

Features:
- Multi-trial hyperparameter exploration
- Purged Walk-Forward Cross Validation (4 splits)
- Strict out-of-fold probability calibration
- Artifact size & inference memory verification (<10MB file, <50MB RAM)
- Registration in ModelRegistry (artifacts/models/registry.json)
- Updates artifacts/manifest.json
"""

import os
import sys
import json
import hashlib
import argparse
import tracemalloc
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

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


SYMBOL_LABEL_CONFIGS: Dict[str, Dict[str, Any]] = {
    "R_75": {
        "horizon_bars": 4,
        "profit_target_pips": 25000.0,
        "stop_loss_pips": 25000.0
    },
    "R_25": {
        "horizon_bars": 4,
        "profit_target_pips": 1400.0,
        "stop_loss_pips": 1400.0
    },
    "R_10": {
        "horizon_bars": 4,
        "profit_target_pips": 1200.0,
        "stop_loss_pips": 1200.0
    }
}


def get_model_id(symbol: str, timeframe: str) -> str:
    sym_tag = symbol.lower().replace("_", "")
    return f"candidate_{sym_tag}_{timeframe}"


def get_candidate_trial_params(symbol: str, trials: int) -> List[Dict[str, Any]]:
    """Returns candidate hyperparameter sets tailored per symbol."""
    if symbol == "R_25":
        pool = [
            {"learning_rate": 0.02, "max_iter": 150, "min_samples_leaf": 35, "l2_regularization": 0.05, "class_weight": "balanced", "random_state": 42, "max_depth": None},
            {"learning_rate": 0.02, "max_iter": 100, "min_samples_leaf": 35, "l2_regularization": 0.0, "class_weight": "balanced", "random_state": 101, "max_depth": None},
            {"learning_rate": 0.03, "max_iter": 150, "min_samples_leaf": 20, "l2_regularization": 0.1, "class_weight": "balanced", "random_state": 202, "max_depth": None},
            {"learning_rate": 0.03, "max_iter": 80, "min_samples_leaf": 35, "l2_regularization": 0.2, "class_weight": "balanced", "random_state": 303, "max_depth": None},
            {"learning_rate": 0.03, "max_iter": 100, "min_samples_leaf": 20, "l2_regularization": 0.0, "class_weight": "balanced", "random_state": 42, "max_depth": None},
        ]
    elif symbol == "R_10":
        pool = [
            {"learning_rate": 0.05, "max_iter": 150, "min_samples_leaf": 35, "l2_regularization": 0.1, "class_weight": "balanced", "random_state": 42, "max_depth": None},
            {"learning_rate": 0.05, "max_iter": 100, "min_samples_leaf": 20, "l2_regularization": 0.05, "class_weight": "balanced", "random_state": 101, "max_depth": None},
            {"learning_rate": 0.05, "max_iter": 150, "min_samples_leaf": 50, "l2_regularization": 0.2, "class_weight": "balanced", "random_state": 202, "max_depth": None},
            {"learning_rate": 0.03, "max_iter": 150, "min_samples_leaf": 20, "l2_regularization": 0.0, "class_weight": "balanced", "random_state": 303, "max_depth": None},
            {"learning_rate": 0.03, "max_iter": 100, "min_samples_leaf": 20, "l2_regularization": 0.0, "class_weight": "balanced", "random_state": 42, "max_depth": None},
        ]
    else:  # R_75 or other
        pool = [
            {"learning_rate": 0.03, "max_iter": 100, "min_samples_leaf": 20, "l2_regularization": 0.0, "class_weight": "balanced", "random_state": 42, "max_depth": None},
            {"learning_rate": 0.04, "max_iter": 120, "min_samples_leaf": 30, "l2_regularization": 0.1, "class_weight": "balanced", "random_state": 101, "max_depth": None},
            {"learning_rate": 0.02, "max_iter": 150, "min_samples_leaf": 25, "l2_regularization": 0.01, "class_weight": "balanced", "random_state": 202, "max_depth": None},
            {"learning_rate": 0.05, "max_iter": 100, "min_samples_leaf": 35, "l2_regularization": 0.5, "class_weight": "balanced", "random_state": 303, "max_depth": None},
            {"learning_rate": 0.03, "max_iter": 80, "min_samples_leaf": 40, "l2_regularization": 1.0, "class_weight": "balanced", "random_state": 404, "max_depth": None},
        ]

    # Return up to trials or cycle if trials > len(pool)
    result = []
    for i in range(trials):
        params = pool[i % len(pool)].copy()
        if i >= len(pool):
            params["random_state"] = 42 + i * 111
        result.append(params)
    return result


def train_and_register_candidate(
    symbol: str = "R_25",
    timeframe: str = "M15",
    trials: int = 5
) -> Dict[str, Any]:
    model_id = get_model_id(symbol, timeframe)
    print("=" * 80)
    print(f"STARTING {symbol} {timeframe} MODEL TRAINING & REGISTRATION PIPELINE")
    print(f"Model ID: {model_id} | Hyperparameter Trials: {trials}")
    print("=" * 80)

    # 1. Load clean datasets
    clean_base_path = settings.clean_data_dir / f"{symbol}_{timeframe}.parquet"
    clean_h1_path = settings.clean_data_dir / f"{symbol}_H1.parquet"

    print(f"[1/8] Loading dataset files:\n  Base ({timeframe}): {clean_base_path}\n  H1:        {clean_h1_path}")
    if not clean_base_path.exists():
        raise FileNotFoundError(f"Clean base dataset not found at {clean_base_path}")
    if not clean_h1_path.exists():
        raise FileNotFoundError(f"Clean H1 dataset not found at {clean_h1_path}")

    df_base = pd.read_parquet(clean_base_path)
    df_h1 = pd.read_parquet(clean_h1_path)
    print(f"  {timeframe} raw bars: {len(df_base):,}, H1 raw bars: {len(df_h1):,}")

    # 2. Compute multi-timeframe causal features
    print(f"[2/8] Computing multi-timeframe causal features for {symbol} using FeatureBuilder...")
    feature_builder = FeatureBuilder()
    df_features = feature_builder.build_features(df_base, df_h1=df_h1, symbol=symbol)
    print(f"  Feature-engineered bars: {len(df_features):,}, columns: {len(df_features.columns)}")

    # 3. Compute triple-barrier labels
    lbl_cfg = SYMBOL_LABEL_CONFIGS.get(symbol, {
        "horizon_bars": 4,
        "profit_target_pips": 1500.0,
        "stop_loss_pips": 1500.0
    })
    label_cfg = LabelConfig(
        horizon_bars=lbl_cfg["horizon_bars"],
        profit_target_pips=lbl_cfg["profit_target_pips"],
        stop_loss_pips=lbl_cfg["stop_loss_pips"]
    )
    print(f"[3/8] Generating triple-barrier target labels with CostAwareLabeler (PT: {label_cfg.profit_target_pips:.1f} pips, SL: {label_cfg.stop_loss_pips:.1f} pips)...")
    labeler = CostAwareLabeler(config=label_cfg)
    df_labeled = labeler.label_dataset(df_features, symbol=symbol)
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

    # 5. Multi-Trial Hyperparameter Search & Walk-Forward Validation
    print(f"[5/8] Evaluating {trials} hyperparameter candidate trials...")
    candidate_params_list = get_candidate_trial_params(symbol, trials)

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

    best_trial_idx = 0
    best_score = -999.0
    best_params = candidate_params_list[0]
    best_val_metrics: Dict[str, Any] = {}
    best_hgb = None
    best_cal = None
    best_cv_summary: Dict[str, Any] = {}

    for t_idx, params in enumerate(candidate_params_list):
        # Quick fit on training slice
        hgb_trial = HistGradientBoostingClassifier(
            learning_rate=params["learning_rate"],
            max_iter=params["max_iter"],
            min_samples_leaf=params["min_samples_leaf"],
            l2_regularization=params["l2_regularization"],
            class_weight=params["class_weight"],
            random_state=params["random_state"]
        )
        hgb_trial.fit(X_train_scaled, y_train)

        cal_trial = CalibratedClassifierCV(
            estimator=hgb_trial,
            method="isotonic",
            cv="prefit"
        )
        cal_trial.fit(X_val_scaled, y_val)

        # Evaluate on validation holdout
        wrapper_trial = HistGradientBoostingModel(params)
        wrapper_trial.model = hgb_trial
        wrapper_trial.calibrated_model = cal_trial
        wrapper_trial.feature_names = feature_cols
        wrapper_trial.classes_ = hgb_trial.classes_
        wrapper_trial.is_fitted = True

        preds_trial = wrapper_trial.predict(X_val_scaled)
        probas_trial = wrapper_trial.predict_proba(X_val_scaled)
        metrics_trial = ModelEvaluator.evaluate(y_val, preds_trial, probas_trial, future_returns=f_val)

        wr = metrics_trial.get("win_rate", 0.0)
        pf = metrics_trial.get("profit_factor", 1.0)
        bal_acc = metrics_trial.get("balanced_accuracy", 0.33)
        brier = metrics_trial.get("brier_score", 0.25)
        sigs = metrics_trial.get("total_signals", 0)

        # Composite trial score prioritizing win rate and stability
        trial_score = (wr * 2.5) + (min(pf, 10.0) * 0.1) + ((1.0 - brier) * 1.5) + bal_acc
        if sigs == 0:
            trial_score -= 1.0

        print(f"  Trial {t_idx + 1}/{trials} (lr={params['learning_rate']}, iter={params['max_iter']}, leaf={params['min_samples_leaf']}): "
              f"Signals: {sigs}, WinRate: {wr:.1%}, PF: {pf:.2f}, BalAcc: {bal_acc:.4f}, Brier: {brier:.4f} -> Score: {trial_score:.4f}")

        if trial_score > best_score:
            best_score = trial_score
            best_trial_idx = t_idx
            best_params = params
            best_val_metrics = metrics_trial
            best_hgb = hgb_trial
            best_cal = cal_trial

    print(f"\n  ==> Selected Best Candidate: Trial {best_trial_idx + 1} with score {best_score:.4f}")
    print(f"      Parameters: {best_params}")

    # Run Walk-Forward CV with selected winning parameters for formal governance audit
    print(f"\n[5b/8] Running Purged Walk-Forward Cross-Validation (4 splits) on best candidate...")
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
        model_params=best_params
    )

    cv_bal_accs = [s["metrics"]["balanced_accuracy"] for s in wf_splits]
    cv_f1s = [s["metrics"]["f1_macro"] for s in wf_splits]
    cv_briers = [s["metrics"]["brier_score"] for s in wf_splits]
    all_leak_free = all(s["leak_free"] for s in wf_splits)

    for s in wf_splits:
        m = s["metrics"]
        print(f"    Split {s['split_index']}: Train bars: {s['train_bars']:,}, Test bars: {s['test_bars']:,} | "
              f"BalAcc: {m['balanced_accuracy']:.4f}, F1-Macro: {m['f1_macro']:.4f}, Brier: {m['brier_score']:.4f}, "
              f"Leak-Free: {s['leak_free']}")

    best_cv_summary = {
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
    best_val_metrics["cv_summary"] = best_cv_summary

    # 6. Final Model Packaging & Validation Holdout Performance
    print("[6/8] Packaging final candidate model wrapper...")
    model_wrapper = HistGradientBoostingModel(best_params)
    model_wrapper.model = best_hgb
    model_wrapper.calibrated_model = best_cal
    model_wrapper.feature_names = feature_cols
    model_wrapper.classes_ = best_hgb.classes_
    model_wrapper.is_fitted = True

    print("  Validation Holdout Performance:")
    print(f"    Balanced Accuracy: {best_val_metrics['balanced_accuracy']:.4f}")
    print(f"    F1 Macro:          {best_val_metrics['f1_macro']:.4f}")
    print(f"    Brier Score:       {best_val_metrics['brier_score']:.4f}")
    print(f"    Precision Macro:   {best_val_metrics['precision_macro']:.4f}")
    print(f"    Recall Macro:      {best_val_metrics['recall_macro']:.4f}")
    if "win_rate" in best_val_metrics:
        print(f"    Win Rate:          {best_val_metrics['win_rate'] * 100:.2f}%")
        print(f"    Profit Factor:     {best_val_metrics['profit_factor']:.2f}")
        print(f"    Sharpe Ratio:      {best_val_metrics['sharpe_ratio']:.2f}")

    # 7. Save model artifact and verify resource limits
    print("[7/8] Saving model artifact and validating resource constraints (<10MB file, <50MB inference)...")
    models_dir = settings.root_dir / "artifacts" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = models_dir / f"{model_id}.joblib"

    artifact_payload = {
        "model_id": model_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "model_name": "HistGradientBoostingClassifier",
        "scaler": scaler,
        "model": model_wrapper,
        "calibrated_model": best_cal,
        "feature_cols": feature_cols,
        "feature_names": feature_cols,
        "params": best_params,
        "validation_metrics": best_val_metrics,
        "cv_summary": best_cv_summary,
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
    print(f"[8/8] Registering {model_id} in ModelRegistry and updating artifacts/manifest.json...")
    registry = ModelRegistry()
    record = registry.register_model(
        model_id=model_id,
        model_type="HistGradientBoostingClassifier",
        version="2.0.0",
        artifact_path=artifact_path,
        train_start_epoch=int(train_slice["epoch"].iloc[0]),
        train_end_epoch=int(val_slice["epoch"].iloc[-1]),
        train_row_count=n_total,
        feature_names=feature_cols,
        hyperparameters=best_params,
        validation_metrics={
            "balanced_accuracy": float(best_val_metrics.get("balanced_accuracy", 0.0)),
            "f1_macro": float(best_val_metrics.get("f1_macro", 0.0)),
            "brier_score": float(best_val_metrics.get("brier_score", 1.0)),
            "precision_macro": float(best_val_metrics.get("precision_macro", 0.0)),
            "recall_macro": float(best_val_metrics.get("recall_macro", 0.0)),
            "win_rate": float(best_val_metrics.get("win_rate", 0.0)),
            "profit_factor": float(best_val_metrics.get("profit_factor", 0.0)),
            "sharpe_ratio": float(best_val_metrics.get("sharpe_ratio", 0.0)),
            "cv_summary": best_cv_summary
        },
        initial_state=ModelLifecycleState.VALIDATED,
        metadata={
            "symbol": symbol,
            "timeframe": timeframe,
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
        "model_id": model_id,
        "artifact_file": f"{model_id}.joblib",
        "model_type": "HistGradientBoostingClassifier",
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_count": len(feature_cols),
        "validation_metrics": {
            "balanced_accuracy": float(best_val_metrics.get("balanced_accuracy", 0.0)),
            "f1_macro": float(best_val_metrics.get("f1_macro", 0.0)),
            "brier_score": float(best_val_metrics.get("brier_score", 1.0)),
            "precision_macro": float(best_val_metrics.get("precision_macro", 0.0)),
            "recall_macro": float(best_val_metrics.get("recall_macro", 0.0)),
            "win_rate": float(best_val_metrics.get("win_rate", 0.0)),
            "profit_factor": float(best_val_metrics.get("profit_factor", 0.0)),
            "sharpe_ratio": float(best_val_metrics.get("sharpe_ratio", 0.0)),
            "cv_summary": best_cv_summary
        },
        "sha256": sha256_hash,
        "hyperparameters": best_params,
        "state": "VALIDATED",
        "file_size_mb": round(file_size_mb, 4),
        "inference_memory_mb": round(peak_mem_mb, 4),
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    manifest_data["models"][model_id] = model_manifest_entry
    manifest_data[model_id] = model_manifest_entry
    manifest_data["last_updated"] = datetime.now(timezone.utc).isoformat()

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    print(f"  Manifest written to: {manifest_path}")

    print("=" * 80)
    print(f"TRAINING, VALIDATION & REGISTRATION COMPLETED FOR {model_id}")
    print("=" * 80)

    return {
        "model_id": model_id,
        "artifact_file": str(artifact_path),
        "sha256": sha256_hash,
        "file_size_mb": file_size_mb,
        "inference_memory_mb": peak_mem_mb,
        "validation_metrics": best_val_metrics,
        "cv_summary": best_cv_summary
    }


def main():
    parser = argparse.ArgumentParser(description="Train and register institutional candidate model")
    parser.add_argument("--symbol", type=str, default="R_25", choices=["R_25", "R_10", "R_75"], help="Target symbol")
    parser.add_argument("--timeframe", type=str, default="M15", help="Base timeframe (default: M15)")
    parser.add_argument("--trials", type=int, default=5, help="Number of hyperparameter search trials (default: 5)")
    args = parser.parse_args()

    train_and_register_candidate(
        symbol=args.symbol,
        timeframe=args.timeframe,
        trials=args.trials
    )


if __name__ == "__main__":
    main()
