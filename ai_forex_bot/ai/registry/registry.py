"""
Model Registry & Experiment Tracking
====================================
Maintains immutable records of trained models, calibrations, dataset versions, and evaluation metrics.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
import uuid

from ai_forex_bot.config.settings import settings
from ai_forex_bot.ai.models.base import BaseModel


class ModelRegistry:
    def __init__(self, registry_dir: Optional[Path] = None):
        self.root_dir = settings.root_dir
        self.registry_dir = registry_dir or (self.root_dir / "artifacts" / "models")
        self.experiments_file = self.root_dir / "artifacts" / "experiments" / "experiments.json"
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.experiments_file.parent.mkdir(parents=True, exist_ok=True)

    def register_model(
        self,
        model: BaseModel,
        symbol: str,
        timeframe: str,
        metrics: Dict[str, Any],
        dataset_meta: Dict[str, Any],
        seed: int = 42
    ) -> str:
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        run_id = f"{symbol}_{timeframe}_{ts_str}_{uuid.uuid4().hex[:6]}"
        artifact_path = self.registry_dir / f"{run_id}.joblib"
        model.save(artifact_path)

        record = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "model_type": model.model_name,
            "random_seed": seed,
            "artifact_file": str(artifact_path.name),
            "metrics": metrics,
            "dataset_metadata": dataset_meta,
            "model_metadata": model.metadata()
        }

        # Append to experiments ledger
        experiments = []
        if self.experiments_file.exists():
            try:
                with open(self.experiments_file, "r") as f:
                    experiments = json.load(f)
            except Exception:
                experiments = []

        experiments.append(record)
        with open(self.experiments_file, "w") as f:
            json.dump(experiments, f, indent=2)

        return run_id