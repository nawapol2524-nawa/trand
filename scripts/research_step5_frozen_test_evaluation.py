import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import balanced_accuracy_score, f1_score, precision_score, recall_score
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV

from ai_forex_bot.config.settings import settings
from ai_forex_bot.features.builder import FeatureBuilder
from ai_forex_bot.labels.labeler import CostAwareLabeler
from ai_forex_bot.data.market.split import PurgedTimeSeriesSplitter
from ai_forex_bot.backtest.engine import BacktestEngine
from ai_forex_bot.ai.models.base import BaseModel

print("Executing Step 5: Pre-Selected Candidate Evaluation on Frozen Test...")

sym = "frxEURUSD"
clean_m15 = settings.clean_data_dir / f"{sym}_M15.parquet"
clean_h1 = settings.clean_data_dir / f"{sym}_H1.parquet"
df_base = pd.read_parquet(clean_m15)
df_h1 = pd.read_parquet(clean_h1)

builder = FeatureBuilder()
df_feat = builder.build_features(df_base, df_h1=df_h1, symbol=sym)
labeler = CostAwareLabeler()
df_labeled = labeler.label_dataset(df_feat, symbol=sym)

meta_cols = {"epoch", "regime", "econ_policy", "target_class", "future_return", "future_net_buy", "future_net_sell"}
feature_cols = [c for c in df_labeled.columns if c not in meta_cols]

splitter = PurgedTimeSeriesSplitter(horizon_bars=4, embargo_bars=0)
bounds = splitter.get_split_indices(df_labeled, train_ratio=0.70, val_ratio=0.15)

train_df = df_labeled.iloc[bounds.train_indices].copy()
val_df = df_labeled.iloc[bounds.val_indices].copy()
test_df = df_labeled.iloc[bounds.test_indices].copy()

# Feature subsets
feature_groups = {
    "BASE_PRICE": ["open", "high", "low", "close"],
    "TREND": ["ema_20", "ema_50", "dist_ema_20", "dist_ema_50", "dist_ema_200", "ema_spread_20_50"],
    "MOMENTUM": ["ret_1", "ret_5", "ret_15", "rsi_14", "macd_hist", "adx_14"],
    "VOLATILITY": ["realized_vol_20", "atr_14", "norm_atr_14", "bb_bandwidth", "bb_pct_b"]
}
core_quant_cols = [c for c in (feature_groups["BASE_PRICE"] + feature_groups["TREND"] + feature_groups["MOMENTUM"] + feature_groups["VOLATILITY"]) if c in feature_cols]

y_train = train_df["target_class"].values
y_val = val_df["target_class"].values
y_test = test_df["target_class"].values

# Definition of the 3 Candidates
candidates = {
    "Candidate_A_Baseline_HGB": {
        "features": feature_cols,
        "model_params": {"random_state": 42, "max_iter": 100, "class_weight": None},
        "description": "Baseline Hardened HistGradientBoosting (43 features, unweighted)"
    },
    "Candidate_B_Class_Weighted_HGB": {
        "features": feature_cols,
        "model_params": {"random_state": 42, "learning_rate": 0.03, "max_iter": 100, "min_samples_leaf": 20, "class_weight": "balanced"},
        "description": "Balanced Class-Weighted HGB (Top Validation Balanced Accuracy = 0.5036)"
    },
    "Candidate_C_Core_Quant_Regularized": {
        "features": core_quant_cols,
        "model_params": {"random_state": 42, "learning_rate": 0.05, "max_iter": 100, "min_samples_leaf": 50, "l2_regularization": 1.0, "class_weight": "balanced"},
        "description": "Regularized HGB on Core Quant features (24 features, pruned noisy sessions)"
    }
}

final_results = []

for c_name, c_spec in candidates.items():
    f_cols = c_spec["features"]
    X_tr = train_df[f_cols].values
    X_va = val_df[f_cols].values
    X_te = test_df[f_cols].values
    
    sc = StandardScaler()
    X_tr_s = sc.fit_transform(X_tr)
    X_va_s = sc.transform(X_va)
    X_te_s = sc.transform(X_te)
    
    # Train base model
    base_clf = HistGradientBoostingClassifier(**c_spec["model_params"])
    base_clf.fit(X_tr_s, y_train)
    
    # Calibrate on validation fold
    calibrator = CalibratedClassifierCV(estimator=base_clf, method="isotonic", cv="prefit")
    calibrator.fit(X_va_s, y_val)
    
    # Predict on Frozen Test
    preds_test = calibrator.predict(X_te_s)
    probas_test = calibrator.predict_proba(X_te_s)
    
    # Predictive metrics
    b_acc = float(balanced_accuracy_score(y_test, preds_test))
    mf1 = float(f1_score(y_test, preds_test, average="macro", zero_division=0))
    prec = precision_score(y_test, preds_test, average=None, zero_division=0)
    rec = recall_score(y_test, preds_test, average=None, zero_division=0)
    
    # Briers
    y_test_bin = np.eye(3)[y_test]
    b0 = float(np.mean((probas_test[:, 0] - y_test_bin[:, 0])**2))
    b1 = float(np.mean((probas_test[:, 1] - y_test_bin[:, 1])**2))
    b2 = float(np.mean((probas_test[:, 2] - y_test_bin[:, 2])**2))
    b_macro = float((b0 + b1 + b2) / 3.0)
    
    # Backtest evaluation
    class WrapperModel:
        def __init__(self, cal_obj):
            self.cal = cal_obj
        def predict_proba(self, X):
            return self.cal.predict_proba(X)
            
    bt = BacktestEngine(symbol="frxEURUSD", initial_balance=1000.0, sl_pips=15.0, tp_pips=20.0)
    bt_res = bt.run(test_df, WrapperModel(calibrator), sc, f_cols)
    
    trades = bt_res["total_trades"]
    net_pnl = bt_res["net_profit_usd"]
    win_rate = f"{bt_res['win_rate']*100:.1f}%" if trades > 0 else "N/A"
    pf = f"{bt_res['profit_factor']:.2f}" if trades > 0 else "N/A"
    exp = f"{net_pnl / trades:.2f}" if trades > 0 else "N/A"
    max_dd = f"{bt_res['max_drawdown_pct']:.2f}%"
    
    final_results.append({
        "candidate": c_name,
        "description": c_spec["description"],
        "feature_count": len(f_cols),
        "test_balanced_acc": f"{b_acc:.4f}",
        "test_macro_f1": f"{mf1:.4f}",
        "test_brier_macro": f"{b_macro:.4f}",
        "test_brier_hold": f"{b0:.4f}",
        "test_brier_buy": f"{b1:.4f}",
        "test_brier_sell": f"{b2:.4f}",
        "precision_hold": f"{prec[0]:.4f}" if len(prec) > 0 else "0.0000",
        "precision_buy": f"{prec[1]:.4f}" if len(prec) > 1 else "0.0000",
        "precision_sell": f"{prec[2]:.4f}" if len(prec) > 2 else "0.0000",
        "recall_hold": f"{rec[0]:.4f}" if len(rec) > 0 else "0.0000",
        "recall_buy": f"{rec[1]:.4f}" if len(rec) > 1 else "0.0000",
        "recall_sell": f"{rec[2]:.4f}" if len(rec) > 2 else "0.0000",
        "oos_trades_count": trades,
        "win_rate": win_rate,
        "profit_factor": pf,
        "expectancy_usd": exp,
        "net_pnl_usd": f"{net_pnl:.2f}",
        "max_drawdown": max_dd,
        "status": "EVALUATED_ON_FROZEN_TEST_HOLD_DISMISSED" if trades == 0 else "OOS_TRADES_EXECUTED"
    })

df_final = pd.DataFrame(final_results)
df_final.to_csv("GATE_22_FINAL_TEST_RESULTS.csv", index=False)
print("Saved GATE_22_FINAL_TEST_RESULTS.csv:")
print(df_final.to_string())
