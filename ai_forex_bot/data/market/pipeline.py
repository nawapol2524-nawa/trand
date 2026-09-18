"""
Historical Data Ingestion & Manifest Pipeline
=============================================
Manages ingestion, cleaning, multi-timeframe generation, and metadata manifest creation.
"""

import hashlib
import json
from pathlib import Path
from typing import Dict, Any, List
import pandas as pd

from ai_forex_bot.config.settings import settings
from ai_forex_bot.data.validation.validator import DataValidator, ValidationReport
from ai_forex_bot.data.market.resampler import Resampler


class HistoricalDataPipeline:
    def __init__(self, raw_dir: Path = settings.raw_data_dir, clean_dir: Path = settings.clean_data_dir):
        self.raw_dir = raw_dir
        self.clean_dir = clean_dir
        self.validator = DataValidator()
        self.clean_dir.mkdir(parents=True, exist_ok=True)

    def process_all(self, timeframes: List[str] = None) -> Dict[str, Any]:
        if timeframes is None:
            timeframes = ["M1", "M5", "M15", "H1", "H4", "D1"]

        manifest: Dict[str, Any] = {
            "schema_version": "1.0.0",
            "pipeline_version": "2.0.0-institutional",
            "symbols": {}
        }

        for symbol in settings.symbols.keys():
            raw_files = list(self.raw_dir.glob(f"{symbol}_*.parquet"))
            if not raw_files:
                continue

            raw_file = raw_files[0]
            with open(raw_file, "rb") as f:
                raw_hash = hashlib.sha256(f.read()).hexdigest()

            df_m1 = pd.read_parquet(raw_file)
            val_rep = self.validator.validate(df_m1, symbol=symbol, timeframe="M1")

            symbol_meta: Dict[str, Any] = {
                "raw_file": str(raw_file.name),
                "raw_sha256": raw_hash,
                "m1_rows": len(df_m1),
                "validation": val_rep.to_dict(),
                "timeframes": {}
            }

            for tf in timeframes:
                df_tf = Resampler.resample(df_m1, tf)
                clean_path = self.clean_dir / f"{symbol}_{tf}.parquet"
                df_tf.to_parquet(clean_path, index=False)
                
                with open(clean_path, "rb") as f:
                    tf_hash = hashlib.sha256(f.read()).hexdigest()

                symbol_meta["timeframes"][tf] = {
                    "rows": len(df_tf),
                    "file": str(clean_path.name),
                    "sha256": tf_hash,
                    "start_time": str(pd.to_datetime(df_tf["epoch"].iloc[0], unit="s", utc=True)),
                    "end_time": str(pd.to_datetime(df_tf["epoch"].iloc[-1], unit="s", utc=True))
                }

            manifest["symbols"][symbol] = symbol_meta

        manifest_path = self.clean_dir / "dataset_manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        return manifest
