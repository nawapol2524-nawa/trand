#!/usr/bin/env python3
"""
Synthetic Benchmark Generator for Deriv Volatility 75 Index (R_75)
==================================================================
Simulates continuous 24/7/365 price series using Geometric Brownian Motion
with stochastic volatility calibrated to 75% annualized volatility.

Generates:
- M15 benchmark dataset (~25,000 bars)
- H1 benchmark dataset (~6,200 bars) resampled deterministically
- Validates via DataValidator (strict OHLC, positive prices, monotonic epochs, zero NaNs)
- Saves clean parquets to data/clean/
- Updates data/clean/dataset_manifest.json with SHA-256 hashes and validation reports
"""

import os
import sys
import json
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd

# Add workspace root to sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

from ai_forex_bot.config.settings import settings
from ai_forex_bot.data.validation.validator import DataValidator
from ai_forex_bot.data.market.resampler import Resampler


def generate_r75_m15_series(
    num_bars: int = 25000,
    start_epoch: int = 1758165300,
    initial_price: float = 250000.0,
    target_annual_vol: float = 0.75,
    seed: int = 42
) -> pd.DataFrame:
    """
    Generates high-fidelity M15 OHLC bars for R_75 via stochastic volatility GBM.
    Continuous trading: 24 hours x 365.25 days per year, zero weekend gaps.
    """
    np.random.seed(seed)
    sub_steps_per_bar = 15  # 1-minute sub-steps per 15-minute bar
    total_steps = num_bars * sub_steps_per_bar

    # Delta t in annual units (365.25 days per year)
    seconds_per_step = 900.0 / sub_steps_per_bar  # 60.0s
    dt_year = seconds_per_step / (365.25 * 86400.0)

    # Stochastic volatility parameters (mean-reverting around target_annual_vol)
    kappa = 2.0      # Speed of mean reversion
    xi = 0.20         # Volatility of volatility
    mu = 0.01         # Drift

    log_vol = np.zeros(total_steps)
    log_vol[0] = np.log(target_annual_vol)
    zv = np.random.normal(0, 1, total_steps)
    zs = np.random.normal(0, 1, total_steps)

    for t in range(1, total_steps):
        log_vol[t] = (
            log_vol[t - 1]
            + kappa * (np.log(target_annual_vol) - log_vol[t - 1]) * dt_year
            + xi * np.sqrt(dt_year) * zv[t]
        )

    inst_vol = np.exp(log_vol)
    log_returns = (mu - 0.5 * inst_vol**2) * dt_year + inst_vol * np.sqrt(dt_year) * zs

    log_prices = np.zeros(total_steps + 1)
    log_prices[0] = np.log(initial_price)
    log_prices[1:] = np.log(initial_price) + np.cumsum(log_returns)
    prices = np.exp(log_prices)

    # Reshape into M15 bars
    sub_matrix = prices[:-1].reshape(num_bars, sub_steps_per_bar)
    next_step_matrix = prices[1:].reshape(num_bars, sub_steps_per_bar)

    # Calculate raw OHLC
    raw_opens = sub_matrix[:, 0]
    raw_closes = next_step_matrix[:, -1]
    raw_highs = np.maximum.reduce([sub_matrix.max(axis=1), raw_opens, raw_closes])
    raw_lows = np.minimum.reduce([sub_matrix.min(axis=1), raw_opens, raw_closes])

    # Round to Deriv R_75 tick size (pip_size: 0.01)
    opens = np.round(raw_opens, 2)
    closes = np.round(raw_closes, 2)

    # Ensure continuous inter-bar flow: open[i] equals close[i-1]
    for i in range(1, num_bars):
        opens[i] = closes[i - 1]

    highs = np.round(raw_highs, 2)
    lows = np.round(raw_lows, 2)

    # Invariant enforcement: strict inequalities and positive prices
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    lows = np.maximum(lows, 0.01)

    # Guardrail: cap single-bar relative range to 7.0% (well below 8.0% spike threshold)
    max_range = opens * 0.070
    bar_range = highs - lows
    excess_mask = bar_range > max_range
    if np.any(excess_mask):
        highs[excess_mask] = opens[excess_mask] + max_range[excess_mask] * 0.5
        lows[excess_mask] = opens[excess_mask] - max_range[excess_mask] * 0.5
        highs = np.maximum(highs, np.maximum(opens, closes))
        lows = np.minimum(lows, np.minimum(opens, closes))

    epochs = [start_epoch + i * 900 for i in range(num_bars)]

    df = pd.DataFrame({
        "epoch": epochs,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes
    })
    return df


def compute_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def main():
    print("=" * 70)
    print("DERIV VOLATILITY 75 INDEX (R_75) BENCHMARK GENERATION")
    print("=" * 70)

    clean_dir = settings.clean_data_dir
    clean_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate M15 bars
    print("\n[1/5] Generating ~25,000 M15 bars (stochastic volatility GBM, 75% annual vol)...")
    num_m15_bars = 25000
    start_epoch = 1758165300  # 2025-09-18 03:15:00 UTC (matching benchmark epoch alignment)
    df_m15 = generate_r75_m15_series(
        num_bars=num_m15_bars,
        start_epoch=start_epoch,
        initial_price=250000.0,
        target_annual_vol=0.75,
        seed=42
    )

    # Verify annualized volatility
    log_rets = np.diff(np.log(df_m15["close"].values))
    bars_per_year = 365.25 * 86400.0 / 900.0
    empirical_vol = np.std(log_rets) * np.sqrt(bars_per_year)
    print(f"      Rows generated: {len(df_m15):,}")
    print(f"      Empirical annualized volatility: {empirical_vol:.2%}")
    print(f"      Price range: ${df_m15['low'].min():,.2f} - ${df_m15['high'].max():,.2f}")
    print(f"      Start: {pd.to_datetime(df_m15['epoch'].iloc[0], unit='s', utc=True)}")
    print(f"      End:   {pd.to_datetime(df_m15['epoch'].iloc[-1], unit='s', utc=True)}")

    # 2. Resample to H1
    print("\n[2/5] Resampling M15 to H1 (~6,200 bars)...")
    df_h1 = Resampler.resample(df_m15, "H1")
    print(f"      H1 Rows generated: {len(df_h1):,}")
    print(f"      H1 Start: {pd.to_datetime(df_h1['epoch'].iloc[0], unit='s', utc=True)}")
    print(f"      H1 End:   {pd.to_datetime(df_h1['epoch'].iloc[-1], unit='s', utc=True)}")

    # 3. Validate with DataValidator
    print("\n[3/5] Validating datasets via DataValidator...")
    val_m15 = DataValidator(max_weekday_gap_seconds=900)
    rep_m15 = val_m15.validate(df_m15, symbol="R_75", timeframe="M15")
    print(f"      M15 Validation valid: {rep_m15.is_valid}, errors: {rep_m15.errors}")
    assert rep_m15.is_valid, f"M15 validation failed: {rep_m15.errors}"

    val_h1 = DataValidator(max_weekday_gap_seconds=3600)
    rep_h1 = val_h1.validate(df_h1, symbol="R_75", timeframe="H1")
    print(f"      H1 Validation valid:  {rep_h1.is_valid}, errors: {rep_h1.errors}")
    assert rep_h1.is_valid, f"H1 validation failed: {rep_h1.errors}"

    # 4. Save parquets
    print("\n[4/5] Saving clean parquet files...")
    m15_file = clean_dir / "R_75_M15.parquet"
    h1_file = clean_dir / "R_75_H1.parquet"

    df_m15.to_parquet(m15_file, index=False)
    df_h1.to_parquet(h1_file, index=False)

    m15_sha256 = compute_sha256(m15_file)
    h1_sha256 = compute_sha256(h1_file)

    print(f"      Saved {m15_file} ({os.path.getsize(m15_file):,} bytes, SHA-256: {m15_sha256})")
    print(f"      Saved {h1_file} ({os.path.getsize(h1_file):,} bytes, SHA-256: {h1_sha256})")

    # 5. Update dataset_manifest.json
    print("\n[5/5] Updating data/clean/dataset_manifest.json...")
    manifest_path = clean_dir / "dataset_manifest.json"
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {
            "schema_version": "1.0.0",
            "pipeline_version": "2.0.0-institutional",
            "symbols": {}
        }

    manifest["symbols"]["R_75"] = {
        "raw_file": "R_75_M15.parquet",
        "raw_sha256": m15_sha256,
        "m1_rows": 0,
        "validation": rep_m15.to_dict(),
        "timeframes": {
            "M15": {
                "rows": len(df_m15),
                "file": "R_75_M15.parquet",
                "sha256": m15_sha256,
                "start_time": str(pd.to_datetime(df_m15["epoch"].iloc[0], unit="s", utc=True)),
                "end_time": str(pd.to_datetime(df_m15["epoch"].iloc[-1], unit="s", utc=True))
            },
            "H1": {
                "rows": len(df_h1),
                "file": "R_75_H1.parquet",
                "sha256": h1_sha256,
                "start_time": str(pd.to_datetime(df_h1["epoch"].iloc[0], unit="s", utc=True)),
                "end_time": str(pd.to_datetime(df_h1["epoch"].iloc[-1], unit="s", utc=True))
            }
        }
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"      Manifest updated successfully at {manifest_path}")
    print("\nAll tasks completed successfully!")


if __name__ == "__main__":
    main()
