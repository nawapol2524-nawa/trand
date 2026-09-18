import os, sys, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import balanced_accuracy_score, f1_score
from sklearn.inspection import permutation_importance
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier

from ai_forex_bot.config.settings import settings
from ai_forex_bot.features.builder import FeatureBuilder
from ai_forex_bot.labels.labeler import CostAwareLabeler, LabelConfig
from ai_forex_bot.data.market.split import PurgedTimeSeriesSplitter

print("Executing Step 3: Feature Ablation, Model Comparison, Label Variants, Walk-Forward, and Hyperparameter Search...")

sym = "frxEURUSD"
clean_m15 = settings.clean_data_dir / f"{sym}_M15.parquet"
clean_h1 = settings.clean_data_dir / f"{sym}_H1.parquet"
df_base = pd.read_parquet(clean_m15)
df_h1 = pd.read_parquet(clean_h1)

builder = FeatureBuilder()
df_feat = builder.build_features(df_base, df_h1=df_h1, symbol=sym)

# Baseline labels (V1)
labeler_v1 = CostAwareLabeler()
df_labeled_v1 = labeler_v1.label_dataset(df_feat.copy(), symbol=sym)

meta_cols = {"epoch", "regime", "econ_policy", "target_class", "future_return", "future_net_buy", "future_net_sell"}
feature_cols = [c for c in df_labeled_v1.columns if c not in meta_cols]

splitter = PurgedTimeSeriesSplitter(horizon_bars=4, embargo_bars=0)
bounds = splitter.get_split_indices(df_labeled_v1, train_ratio=0.70, val_ratio=0.15)

# STRICT RULE: Use ONLY Train and Validation for all research experiments!
train_df = df_labeled_v1.iloc[bounds.train_indices].copy()
val_df = df_labeled_v1.iloc[bounds.val_indices].copy()

X_train_raw = train_df[feature_cols].values
y_train = train_df["target_class"].values
X_val_raw = val_df[feature_cols].values
y_val = val_df["target_class"].values

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train_raw)
X_val_s = scaler.transform(X_val_raw)

# ----------------------------------------------------------------------
# 1. FEATURE GROUP ABLATION -> GATE_22_FEATURE_ABLATION.csv
# ----------------------------------------------------------------------
print("Running Feature Group Ablation on Validation fold...")
feature_groups = {
    "BASE_PRICE": ["open", "high", "low", "close"],
    "TREND": ["ema_20", "ema_50", "dist_ema_20", "dist_ema_50", "dist_ema_200", "ema_spread_20_50"],
    "MOMENTUM": ["ret_1", "ret_5", "ret_15", "rsi_14", "macd_hist", "adx_14"],
    "VOLATILITY": ["realized_vol_20", "atr_14", "norm_atr_14", "bb_bandwidth", "bb_pct_b"],
    "STRUCTURE": ["candle_body_ratio", "candle_upper_wick_ratio", "candle_lower_wick_ratio", "range_pos_20"],
    "SESSION": ["is_asian_session", "is_london_session", "is_ny_session", "is_london_ny_overlap", "day_of_week", "hour_of_day"],
    "MULTI_TIMEFRAME": ["h1_dist_ema_50", "h1_trend_bull"],
    "REGIME": ["regime_code"]
}

ablation_configs = [
    ("BASE_ONLY", feature_groups["BASE_PRICE"]),
    ("BASE+TREND", feature_groups["BASE_PRICE"] + feature_groups["TREND"]),
    ("BASE+MOMENTUM", feature_groups["BASE_PRICE"] + feature_groups["MOMENTUM"]),
    ("BASE+VOLATILITY", feature_groups["BASE_PRICE"] + feature_groups["VOLATILITY"]),
    ("BASE+STRUCTURE", feature_groups["BASE_PRICE"] + feature_groups["STRUCTURE"]),
    ("BASE+SESSION", feature_groups["BASE_PRICE"] + feature_groups["SESSION"]),
    ("BASE+MTF", feature_groups["BASE_PRICE"] + feature_groups["MULTI_TIMEFRAME"]),
    ("BASE+REGIME", feature_groups["BASE_PRICE"] + feature_groups["REGIME"]),
    ("CORE_QUANT (BASE+TREND+MOM+VOL)", feature_groups["BASE_PRICE"] + feature_groups["TREND"] + feature_groups["MOMENTUM"] + feature_groups["VOLATILITY"]),
    ("ALL_FEATURES (43)", feature_cols)
]

ablation_records = []
for name, f_list in ablation_configs:
    sub_cols = [c for c in f_list if c in feature_cols]
    col_idxs = [feature_cols.index(c) for c in sub_cols]
    
    clf = HistGradientBoostingClassifier(random_state=42, max_iter=100)
    clf.fit(X_train_s[:, col_idxs], y_train)
    preds = clf.predict(X_val_s[:, col_idxs])
    probas = clf.predict_proba(X_val_s[:, col_idxs])
    
    b_acc = float(balanced_accuracy_score(y_val, preds))
    mf1 = float(f1_score(y_val, preds, average="macro", zero_division=0))
    # Brier
    y_val_bin = np.eye(3)[y_val]
    brier = float(np.mean(np.sum((probas - y_val_bin)**2, axis=1)) / 3.0)
    
    # Top 5% BUY conditional return on validation
    p_buy_val = probas[:, 1]
    top_5pct_k = max(1, int(len(val_df) * 0.05))
    top_idx = np.argsort(p_buy_val)[::-1][:top_5pct_k]
    val_returns = val_df["future_return"].iloc[top_idx].values
    mean_top_ret_bps = float(np.mean(val_returns) * 10000)
    
    ablation_records.append({
        "configuration": name,
        "feature_count": len(sub_cols),
        "val_balanced_acc": f"{b_acc:.4f}",
        "val_macro_f1": f"{mf1:.4f}",
        "val_brier_macro": f"{brier:.4f}",
        "top_5pct_buy_return_bps": f"{mean_top_ret_bps:.2f}",
        "notes": "Validation fold purged evaluation"
    })

df_ablation = pd.DataFrame(ablation_records)
df_ablation.to_csv("GATE_22_FEATURE_ABLATION.csv", index=False)
print("Saved GATE_22_FEATURE_ABLATION.csv")

# ----------------------------------------------------------------------
# 2. MODEL COMPARISON ON VALIDATION -> GATE_22_MODEL_COMPARISON.csv
# ----------------------------------------------------------------------
print("Running Model Comparison on Validation fold...")
models_to_test = {
    "Logistic_Regression": LogisticRegression(random_state=42, max_iter=500),
    "Random_Forest": RandomForestClassifier(random_state=42, n_estimators=100, max_depth=8, n_jobs=-1),
    "Extra_Trees": ExtraTreesClassifier(random_state=42, n_estimators=100, max_depth=8, n_jobs=-1),
    "HistGradientBoosting_Baseline": HistGradientBoostingClassifier(random_state=42, max_iter=100),
    "HistGradientBoosting_Balanced": HistGradientBoostingClassifier(random_state=42, max_iter=100, class_weight="balanced"),
    "MLP_Neural_Net": MLPClassifier(random_state=42, hidden_layer_sizes=(64, 32), max_iter=200, early_stopping=True)
}

model_comp_records = []
for m_name, clf in models_to_test.items():
    clf.fit(X_train_s, y_train)
    preds = clf.predict(X_val_s)
    probas = clf.predict_proba(X_val_s)
    
    b_acc = float(balanced_accuracy_score(y_val, preds))
    mf1 = float(f1_score(y_val, preds, average="macro", zero_division=0))
    y_val_bin = np.eye(3)[y_val]
    brier = float(np.mean(np.sum((probas - y_val_bin)**2, axis=1)) / 3.0)
    
    # Class predictions distribution
    c_hold = float(np.mean(preds == 0) * 100)
    c_buy = float(np.mean(preds == 1) * 100)
    c_sell = float(np.mean(preds == 2) * 100)
    
    # Top 5% BUY conditional return
    p_buy_val = probas[:, 1]
    top_5pct_k = max(1, int(len(val_df) * 0.05))
    top_idx = np.argsort(p_buy_val)[::-1][:top_5pct_k]
    val_returns = val_df["future_return"].iloc[top_idx].values
    mean_top_ret_bps = float(np.mean(val_returns) * 10000)
    
    model_comp_records.append({
        "model_architecture": m_name,
        "val_balanced_acc": f"{b_acc:.4f}",
        "val_macro_f1": f"{mf1:.4f}",
        "val_brier_macro": f"{brier:.4f}",
        "pred_dist_hold_pct": f"{c_hold:.1f}",
        "pred_dist_buy_pct": f"{c_buy:.1f}",
        "pred_dist_sell_pct": f"{c_sell:.1f}",
        "top_5pct_buy_expectancy_bps": f"{mean_top_ret_bps:.2f}",
        "notes": "Standardized features; trained on Train, evaluated on Purged Val"
    })

df_model_comp = pd.DataFrame(model_comp_records)
df_model_comp.to_csv("GATE_22_MODEL_COMPARISON.csv", index=False)
print("Saved GATE_22_MODEL_COMPARISON.csv")

# ----------------------------------------------------------------------
# 3. FEATURE IMPORTANCE STABILITY -> GATE_22_FEATURE_IMPORTANCE.csv
# ----------------------------------------------------------------------
print("Computing Feature Permutation Importance on Validation fold...")
base_clf = HistGradientBoostingClassifier(random_state=42, max_iter=100)
base_clf.fit(X_train_s, y_train)

# Permutation importance on validation fold
perm_res = permutation_importance(base_clf, X_val_s, y_val, n_repeats=5, random_state=42, scoring="balanced_accuracy")
mean_imp = perm_res.importances_mean
std_imp = perm_res.importances_std

feat_imp_records = []
for i, col in enumerate(feature_cols):
    feat_imp_records.append({
        "feature_name": col,
        "mean_importance": float(mean_imp[i]),
        "std_importance": float(std_imp[i]),
        "importance_ratio": float(mean_imp[i] / (std_imp[i] + 1e-6))
    })

df_feat_imp = pd.DataFrame(feat_imp_records).sort_values("mean_importance", ascending=False).reset_index(drop=True)
df_feat_imp["rank"] = df_feat_imp.index + 1
df_feat_imp.to_csv("GATE_22_FEATURE_IMPORTANCE.csv", index=False)
print("Saved GATE_22_FEATURE_IMPORTANCE.csv (Top 5 features):")
print(df_feat_imp.head(5).to_string())

# ----------------------------------------------------------------------
# 4. LABEL RESEARCH -> GATE_22_LABEL_RESEARCH.csv
# ----------------------------------------------------------------------
print("Evaluating Label Variants...")
# Variant 1: Baseline (4 bars, 15p / 15p) -> df_labeled_v1
# Variant 2: Shorter (2 bars, 10p / 10p)
cfg_v2 = LabelConfig(horizon_bars=2, profit_target_pips=10.0, stop_loss_pips=10.0)
df_labeled_v2 = CostAwareLabeler(cfg_v2).label_dataset(df_feat.copy(), symbol=sym)

# Variant 3: Longer (8 bars, 25p / 25p)
cfg_v3 = LabelConfig(horizon_bars=8, profit_target_pips=25.0, stop_loss_pips=25.0)
df_labeled_v3 = CostAwareLabeler(cfg_v3).label_dataset(df_feat.copy(), symbol=sym)

label_variants = [
    ("LABEL_V1_BASELINE", df_labeled_v1, 4, 15.0, 15.0),
    ("LABEL_V2_SHORT_HORIZON", df_labeled_v2, 2, 10.0, 10.0),
    ("LABEL_V3_LONG_HORIZON", df_labeled_v3, 8, 25.0, 25.0)
]

label_records = []
for l_name, df_l, h_bars, pt_p, sl_p in label_variants:
    s_b = PurgedTimeSeriesSplitter(horizon_bars=h_bars, embargo_bars=0).get_split_indices(df_l, 0.70, 0.15)
    tr_l = df_l.iloc[s_b.train_indices]
    va_l = df_l.iloc[s_b.val_indices]
    
    n_tot = len(df_l)
    p_h = float(np.mean(df_l["target_class"] == 0) * 100)
    p_b = float(np.mean(df_l["target_class"] == 1) * 100)
    p_s = float(np.mean(df_l["target_class"] == 2) * 100)
    
    # Train model on this label variant
    X_tr = tr_l[feature_cols].values
    y_tr = tr_l["target_class"].values
    X_va = va_l[feature_cols].values
    y_va = va_l["target_class"].values
    
    sc = StandardScaler()
    X_tr_s = sc.fit_transform(X_tr)
    X_va_s = sc.transform(X_va)
    
    clf = HistGradientBoostingClassifier(random_state=42, max_iter=100)
    clf.fit(X_tr_s, y_tr)
    pr = clf.predict(X_va_s)
    b_acc = float(balanced_accuracy_score(y_va, pr))
    mf1 = float(f1_score(y_va, pr, average="macro", zero_division=0))
    
    label_records.append({
        "label_version": l_name,
        "horizon_bars": h_bars,
        "horizon_minutes": h_bars * 15,
        "profit_target_pips": pt_p,
        "stop_loss_pips": sl_p,
        "total_samples": n_tot,
        "hold_class_pct": f"{p_h:.1f}",
        "buy_class_pct": f"{p_b:.1f}",
        "sell_class_pct": f"{p_s:.1f}",
        "val_balanced_acc": f"{b_acc:.4f}",
        "val_macro_f1": f"{mf1:.4f}"
    })

df_label_res = pd.DataFrame(label_records)
df_label_res.to_csv("GATE_22_LABEL_RESEARCH.csv", index=False)
print("Saved GATE_22_LABEL_RESEARCH.csv")

# ----------------------------------------------------------------------
# 5. PURGED WALK-FORWARD EVALUATION -> GATE_22_WALK_FORWARD.csv
# ----------------------------------------------------------------------
print("Running Purged Walk-Forward Model Stability on Train+Val history...")
# Split Train+Val (20,560 bars) into 4 rolling windows
# Window 1: Train 0:8000, Val 8000:11000
# Window 2: Train 3000:11000, Val 11000:14000
# Window 3: Train 6000:14000, Val 14000:17000
# Window 4: Train 9000:17000, Val 17000:20560
windows = [
    ("Window_1", 0, 8000, 8000, 11000),
    ("Window_2", 3000, 11000, 11000, 14000),
    ("Window_3", 6000, 14000, 14000, 17000),
    ("Window_4", 9000, 17000, 17000, 20560)
]

wf_records = []
for w_name, tr_s, tr_e, va_s, va_e in windows:
    # Purge 4 bars from train
    safe_tr_e = tr_e - 4
    w_train = df_labeled_v1.iloc[tr_s:safe_tr_e]
    w_val = df_labeled_v1.iloc[va_s:va_e]
    
    X_w_tr = w_train[feature_cols].values
    y_w_tr = w_train["target_class"].values
    X_w_va = w_val[feature_cols].values
    y_w_va = w_val["target_class"].values
    
    sc = StandardScaler()
    X_w_tr_s = sc.fit_transform(X_w_tr)
    X_w_va_s = sc.transform(X_w_va)
    
    # Test HGB Baseline vs HGB Balanced
    for m_type in ["HGB_Baseline", "HGB_Balanced"]:
        cw = "balanced" if m_type == "HGB_Balanced" else None
        clf = HistGradientBoostingClassifier(random_state=42, max_iter=100, class_weight=cw)
        clf.fit(X_w_tr_s, y_w_tr)
        pr = clf.predict(X_w_va_s)
        pr_prob = clf.predict_proba(X_w_va_s)
        
        b_acc = float(balanced_accuracy_score(y_w_va, pr))
        mf1 = float(f1_score(y_w_va, pr, average="macro", zero_division=0))
        
        # BUY / SELL recalls
        rec_b = float(np.mean(pr[y_w_va == 1] == 1)) if np.sum(y_w_va == 1) > 0 else 0.0
        rec_s = float(np.mean(pr[y_w_va == 2] == 2)) if np.sum(y_w_va == 2) > 0 else 0.0
        
        # Brier
        y_w_va_bin = np.eye(3)[y_w_va]
        brier = float(np.mean(np.sum((pr_prob - y_w_va_bin)**2, axis=1)) / 3.0)
        
        wf_records.append({
            "window": w_name,
            "model_type": m_type,
            "train_bars": len(w_train),
            "val_bars": len(w_val),
            "balanced_accuracy": f"{b_acc:.4f}",
            "macro_f1": f"{mf1:.4f}",
            "buy_recall": f"{rec_b:.4f}",
            "sell_recall": f"{rec_s:.4f}",
            "brier_macro": f"{brier:.4f}"
        })

df_wf = pd.DataFrame(wf_records)
df_wf.to_csv("GATE_22_WALK_FORWARD.csv", index=False)
print("Saved GATE_22_WALK_FORWARD.csv")

# ----------------------------------------------------------------------
# 6. HYPERPARAMETER SEARCH -> GATE_22_HYPERPARAMETER_RESULTS.csv
# ----------------------------------------------------------------------
print("Running Hyperparameter Search on Validation fold (Max 12 trials)...")
param_grid = [
    {"lr": 0.03, "max_iter": 100, "min_leaf": 20, "l2": 0.0, "class_weight": None},
    {"lr": 0.05, "max_iter": 100, "min_leaf": 20, "l2": 0.0, "class_weight": None},
    {"lr": 0.10, "max_iter": 100, "min_leaf": 20, "l2": 0.0, "class_weight": None},
    {"lr": 0.05, "max_iter": 150, "min_leaf": 50, "l2": 1.0, "class_weight": None},
    {"lr": 0.05, "max_iter": 100, "min_leaf": 100, "l2": 2.0, "class_weight": None},
    {"lr": 0.03, "max_iter": 100, "min_leaf": 20, "l2": 0.0, "class_weight": "balanced"},
    {"lr": 0.05, "max_iter": 100, "min_leaf": 20, "l2": 0.0, "class_weight": "balanced"},
    {"lr": 0.10, "max_iter": 100, "min_leaf": 20, "l2": 0.0, "class_weight": "balanced"},
    {"lr": 0.05, "max_iter": 150, "min_leaf": 50, "l2": 1.0, "class_weight": "balanced"},
    {"lr": 0.05, "max_iter": 100, "min_leaf": 100, "l2": 2.0, "class_weight": "balanced"},
    {"lr": 0.02, "max_iter": 200, "min_leaf": 50, "l2": 5.0, "class_weight": "balanced"},
    {"lr": 0.08, "max_iter": 80, "min_leaf": 30, "l2": 0.5, "class_weight": "balanced"}
]

hp_records = []
for idx, p in enumerate(param_grid):
    clf = HistGradientBoostingClassifier(
        learning_rate=p["lr"],
        max_iter=p["max_iter"],
        min_samples_leaf=p["min_leaf"],
        l2_regularization=p["l2"],
        class_weight=p["class_weight"],
        random_state=42
    )
    clf.fit(X_train_s, y_train)
    preds = clf.predict(X_val_s)
    probas = clf.predict_proba(X_val_s)
    
    b_acc = float(balanced_accuracy_score(y_val, preds))
    mf1 = float(f1_score(y_val, preds, average="macro", zero_division=0))
    y_val_bin = np.eye(3)[y_val]
    brier = float(np.mean(np.sum((probas - y_val_bin)**2, axis=1)) / 3.0)
    
    hp_records.append({
        "trial_id": f"TRIAL_{idx+1:02d}",
        "learning_rate": p["lr"],
        "max_iter": p["max_iter"],
        "min_samples_leaf": p["min_leaf"],
        "l2_regularization": p["l2"],
        "class_weight": str(p["class_weight"]),
        "val_balanced_acc": f"{b_acc:.4f}",
        "val_macro_f1": f"{mf1:.4f}",
        "val_brier_macro": f"{brier:.4f}"
    })

df_hp = pd.DataFrame(hp_records).sort_values("val_balanced_acc", ascending=False).reset_index(drop=True)
df_hp.to_csv("GATE_22_HYPERPARAMETER_RESULTS.csv", index=False)
print("Saved GATE_22_HYPERPARAMETER_RESULTS.csv:")
print(df_hp.head(5).to_string())
