# Troubleshooting & Operational Guide

## 1. Common Issues & Resolutions

### Missing Clean Datasets
- **Symptom:** `FileNotFoundError: Clean parquet not found`
- **Fix:** Execute `python3 cli.py prepare-data` to resample raw M1 datasets into M5, M15, H1, H4, D1.

### OpenMP / LightGBM Library Warning
- **Symptom:** `Library not loaded: @rpath/libomp.dylib` on macOS
- **Fix:** The system defaults to native `HistGradientBoostingModel` from `scikit-learn` which requires zero external C++ runtimes and runs at identical speed.

### Zero Signals in Holdout Evaluation
- **Explanation:** In institutional forex modeling, uncalibrated models or high-friction cost targets correctly classify noisy regimes as `HOLD`. This is intended design behavior to prevent overtrading and fee drag.
