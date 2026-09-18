"""
Autonomous AI Training Pipeline
===============================
Executes deterministic, leak-free training:
- Strict chronological train/validation/test splits.
- Scaler fit on train fold only.
- Out-of-sample probability calibration.
- Multi-metric evaluation and model registry storage.
"""

from pathlib import Path
from typing import Dict, Any, Tuple, Optional
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
import joblib

from ai_forex_bot.config.settings import settings
from ai_forex_bot.features.builder import FeatureBuilder
from ai_forex_bot.labels.labeler import CostAwareLabeler
from ai_forex_bot.ai.models.base import BaseModel, HistGradientBoostingModel, RandomForestModel, LogisticRegressionModel
from ai_forex_bot.ai.evaluation.evaluator import ModelEvaluator
from ai_forex_bot.ai.registry.registry import ModelRegistry


class TrainingPipeline:
    def __init__(
        self,
        symbol: str = "frxEURUSD",
        timeframe: str = "M15",
        model_type: str = "hist_gradient_boosting",
        train_ratio: float = 0.70,
        val_ratio: float = 0.15,
        random_seed: int = 42
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.model_type = model_type
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.random_seed = random_seed
        self.feature_builder = FeatureBuilder()
        self.labeler = CostAwareLabeler()
        self.registry = ModelRegistry()

    def prepare_data(self) -> pd.DataFrame:
        clean_file = settings.clean_data_dir / f"{self.symbol}_{self.timeframe}.parquet"
        h1_file = settings.clean_data_dir / f"{self.symbol}_H1.parquet"

        if not clean_file.exists():
            raise FileNotFoundError(f"Clean parquet not found at {clean_file}. Run data pipeline first.")

        df_base = pd.read_parquet(clean_file)
        df_h1 = pd.read_parquet(h1_file) if h1_file.exists() else None

        df_feat = self.feature_builder.build_features(df_base, df_h1=df_h1, symbol=self.symbol)
        df_labeled = self.labeler.label_dataset(df_feat, symbol=self.symbol)
        return df_labeled

    def train(self) -> Dict[str, Any]:
        df = self.prepare_data()

        # Non-feature metadata columns
        meta_cols = {
            "epoch", "regime", "econ_policy", "target_class",
            "future_return", "future_net_buy", "future_net_sell"
        }
        feature_cols = [c for c in df.columns if c not in meta_cols]

        X = df[feature_cols].values
        y = df["target_class"].values
        f_rets = df["future_return"].values

        # Strict Purged Temporal Split (Marcos López de Prado)
        n = len(df)
        from ai_forex_bot.data.market.split import PurgedTimeSeriesSplitter
        splitter = PurgedTimeSeriesSplitter(horizon_bars=self.labeler.config.horizon_bars, embargo_bars=0)
        split_bounds = splitter.get_split_indices(df, train_ratio=self.train_ratio, val_ratio=self.val_ratio)

        X_train = X[split_bounds.train_indices]
        y_train = y[split_bounds.train_indices]
        f_train = f_rets[split_bounds.train_indices]

        X_val = X[split_bounds.val_indices]
        y_val = y[split_bounds.val_indices]
        f_val = f_rets[split_bounds.val_indices]

        X_test = X[split_bounds.test_indices]
        y_test = y[split_bounds.test_indices]
        f_test = f_rets[split_bounds.test_indices]

        # Preprocessing: StandardScaler fit ONLY on train split
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_val_scaled = scaler.transform(X_val)
        X_test_scaled = scaler.transform(X_test)

        # Save scaler
        scaler_path = settings.root_dir / "artifacts" / "scalers" / f"{self.symbol}_{self.timeframe}_scaler.joblib"
        scaler_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"scaler": scaler, "feature_cols": feature_cols}, scaler_path)

        # Instantiate Model
        if self.model_type == "hist_gradient_boosting":
            model: BaseModel = HistGradientBoostingModel({"random_state": self.random_seed})
        elif self.model_type == "random_forest":
            model: BaseModel = RandomForestModel({"random_state": self.random_seed})
        else:
            model: BaseModel = LogisticRegressionModel({"random_state": self.random_seed})

        # Fit Base Model on Train
        model.fit(X_train_scaled, y_train, feature_names=feature_cols)

        # Probability Calibration on Validation Fold
        model.calibrate(X_val_scaled, y_val, method=settings.calibration_method)

        # Evaluation on Validation and Test
        val_pred = model.predict(X_val_scaled)
        val_proba = model.predict_proba(X_val_scaled)
        val_metrics = ModelEvaluator.evaluate(y_val, val_pred, val_proba, future_returns=f_val)

        test_pred = model.predict(X_test_scaled)
        test_proba = model.predict_proba(X_test_scaled)
        test_metrics = ModelEvaluator.evaluate(y_test, test_pred, test_proba, future_returns=f_test)

        # Register Artifact
        dataset_meta = {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "total_rows": n,
            "train_rows": len(X_train),
            "val_rows": len(X_val),
            "test_rows": len(X_test),
            "purged_train_rows": split_bounds.purged_train_count,
            "purged_val_rows": split_bounds.purged_val_count,
            "train_val_leak_free": split_bounds.train_val_leak_free,
            "val_test_leak_free": split_bounds.val_test_leak_free,
            "start_epoch": int(df["epoch"].iloc[0]),
            "end_epoch": int(df["epoch"].iloc[-1]),
            "feature_count": len(feature_cols)
        }

        all_metrics = {
            "validation": val_metrics,
            "test_oos": test_metrics
        }

        run_id = self.registry.register_model(
            model=model,
            symbol=self.symbol,
            timeframe=self.timeframe,
            metrics=all_metrics,
            dataset_meta=dataset_meta,
            seed=self.random_seed
        )

        return {
            "run_id": run_id,
            "model_type": self.model_type,
            "metrics": all_metrics,
            "dataset_meta": dataset_meta,
            "scaler_file": str(scaler_path.name)
        }
