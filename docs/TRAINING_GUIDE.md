# Model Training & Reproduction Guide

## 1. Quick Start Commands

### Prepare Clean Multi-Timeframe Datasets
```bash
python3 cli.py prepare-data
```

### Run Zero-Leakage Audit
```bash
python3 cli.py run-leakage-audit
```

### Train Baseline Model (EUR/USD M15)
```bash
python3 cli.py train --symbol frxEURUSD --timeframe M15 --model hist_gradient_boosting
```

### Train Gold (XAU/USD M15)
```bash
python3 cli.py train --symbol frxXAUUSD --timeframe M15 --model hist_gradient_boosting
```

### Run Walk-Forward Validation
```bash
python3 cli.py walk-forward --symbol frxEURUSD --timeframe M15 --splits 4
```

## 2. Training Artifacts
Trained models, scalers, and experiment records are persisted in:
- Model weights: `artifacts/models/<run_id>.joblib`
- Fitted scalers: `artifacts/scalers/<symbol>_<timeframe>_scaler.joblib`
- Experiment logs: `artifacts/experiments/experiments.json`
