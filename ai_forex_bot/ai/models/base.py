"""
AI Model Hierarchy & Interfaces
===============================
Standard BaseModel interface providing:
- fit(), predict(), predict_proba()
- save(), load(), metadata()
- Built-in probability calibration (Platt scaling / Isotonic regression)
- Implementations: HistGradientBoosting, RandomForest, LogisticRegression
"""

from abc import ABC, abstractmethod
import json
from pathlib import Path
from typing import Dict, Any, Optional
import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression


class BaseModel(ABC):
    def __init__(self, model_name: str, config: Optional[Dict[str, Any]] = None):
        self.model_name = model_name
        self.config = config or {}
        self.model: Any = None
        self.calibrated_model: Optional[CalibratedClassifierCV] = None
        self.feature_names: Optional[list] = None
        self.classes_: Optional[np.ndarray] = None
        self.is_fitted: bool = False

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: Optional[list] = None):
        pass

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("Model is not fitted yet.")
        if self.calibrated_model is not None:
            return self.calibrated_model.predict(X)
        return self.model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("Model is not fitted yet.")
        if self.calibrated_model is not None:
            return self.calibrated_model.predict_proba(X)
        return self.model.predict_proba(X)

    def calibrate(self, X_val: np.ndarray, y_val: np.ndarray, method: str = "isotonic"):
        """
        Calibrate model probabilities using dedicated validation fold.
        """
        if not self.is_fitted:
            raise RuntimeError("Base model must be fitted before calibration.")
        calibrator = CalibratedClassifierCV(estimator=self.model, method=method, cv="prefit")
        calibrator.fit(X_val, y_val)
        self.calibrated_model = calibrator

    def save(self, filepath: Path):
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model_name": self.model_name,
            "config": self.config,
            "feature_names": self.feature_names,
            "classes_": self.classes_,
            "model": self.model,
            "calibrated_model": self.calibrated_model,
            "is_fitted": self.is_fitted
        }
        joblib.dump(payload, filepath)

    def load(self, filepath: Path):
        payload = joblib.load(filepath)
        self.model_name = payload["model_name"]
        self.config = payload["config"]
        self.feature_names = payload["feature_names"]
        self.classes_ = payload["classes_"]
        self.model = payload["model"]
        self.calibrated_model = payload.get("calibrated_model")
        self.is_fitted = payload["is_fitted"]

    def metadata(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "config": self.config,
            "is_calibrated": self.calibrated_model is not None,
            "num_features": len(self.feature_names) if self.feature_names else 0,
            "classes": [int(c) for c in self.classes_] if self.classes_ is not None else []
        }


class HistGradientBoostingModel(BaseModel):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        super().__init__("hist_gradient_boosting", cfg)
        self.model = HistGradientBoostingClassifier(
            max_iter=cfg.get("max_iter", 100),
            learning_rate=cfg.get("learning_rate", 0.05),
            max_depth=cfg.get("max_depth", 6),
            min_samples_leaf=cfg.get("min_samples_leaf", 30),
            l2_regularization=cfg.get("l2_regularization", 0.0),
            class_weight=cfg.get("class_weight", None),
            random_state=cfg.get("random_state", 42)
        )

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: Optional[list] = None):
        self.feature_names = feature_names
        self.model.fit(X, y)
        self.classes_ = self.model.classes_
        self.is_fitted = True


class RandomForestModel(BaseModel):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        super().__init__("random_forest", cfg)
        self.model = RandomForestClassifier(
            n_estimators=cfg.get("n_estimators", 100),
            max_depth=cfg.get("max_depth", 8),
            min_samples_leaf=cfg.get("min_samples_leaf", 20),
            random_state=cfg.get("random_state", 42),
            n_jobs=-1
        )

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: Optional[list] = None):
        self.feature_names = feature_names
        self.model.fit(X, y)
        self.classes_ = self.model.classes_
        self.is_fitted = True


class LogisticRegressionModel(BaseModel):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        super().__init__("logistic_regression", cfg)
        self.model = LogisticRegression(
            max_iter=cfg.get("max_iter", 1000),
            C=cfg.get("C", 1.0),
            random_state=cfg.get("random_state", 42)
        )

    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: Optional[list] = None):
        self.feature_names = feature_names
        self.model.fit(X, y)
        self.classes_ = self.model.classes_
        self.is_fitted = True
