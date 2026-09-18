import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.preprocessing import StandardScaler

from ai_forex_bot.config.settings import settings
from ai_forex_bot.features.builder import FeatureBuilder
from ai_forex_bot.labels.labeler import CostAwareLabeler
from ai_forex_bot.data.market.split import PurgedTimeSeriesSplitter
from ai_forex_bot.ai.models.base import HistGradientBoostingModel

print("Executing Step 2: Threshold-Independent Score Analysis & Conditional Expectancy...")

sym = "frxEURUSD"
df_base = pd.read_parquet(settings.clean_data_dir / f"{sym}_M15.parquet")
df_h1 = pd.read_parquet(settings.clean_data_dir / f"{sym}_H1.parquet")

df_feat = FeatureBuilder().build_features(df_base, df_h1=df_h1, symbol=sym)
df_labeled = CostAwareLabeler().label_dataset(df_feat, symbol=sym)

meta_cols = {"epoch", "regime", "econ_policy", "target_class", "future_return", "future_net_buy", "future_net_sell"}
feature_cols = [c for c in df_labeled.columns if c not in meta_cols]

splitter = PurgedTimeSeriesSplitter(horizon_bars=4, embargo_bars=0)
bounds = splitter.get_split_indices(df_labeled, train_ratio=0.70, val_ratio=0.15)

train_df = df_labeled.iloc[bounds.train_indices]
val_df = df_labeled.iloc[bounds.val_indices]
test_df = df_labeled.iloc[bounds.test_indices].copy()

X_train = train_df[feature_cols].values
y_train = train_df["target_class"].values
X_val = val_df[feature_cols].values
y_val = val_df["target_class"].values
X_test = test_df[feature_cols].values
y_test = test_df["target_class"].values

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_val_s = scaler.transform(X_val)
X_test_s = scaler.transform(X_test)

# Train and calibrate baseline HGB
hgb = HistGradientBoostingModel({"random_state": 42})
hgb.fit(X_train_s, y_train, feature_names=feature_cols)
hgb.calibrate(X_val_s, y_val, method="isotonic")

probas_test = hgb.predict_proba(X_test_s)
p_buy = probas_test[:, 1]
p_sell = probas_test[:, 2]

# Compute future return and price path metrics over horizon H=4 on original candles
test_df["p_buy"] = p_buy
test_df["p_sell"] = p_sell

# Future return over 4 bars (close[t+4] - close[t]) / close[t]
# MAE / MFE:
# For BUY:
# MAE = (close[t] - min_low[t+1..t+4]) / close[t]
# MFE = (max_high[t+1..t+4] - close[t]) / close[t]
# For SELL:
# MAE = (max_high[t+1..t+4] - close[t]) / close[t]
# MFE = (close[t] - min_low[t+1..t+4]) / close[t]

n_test = len(test_df)
close_arr = test_df["close"].values
high_arr = test_df["high"].values
low_arr = test_df["low"].values
H = 4

mae_buy = np.zeros(n_test)
mfe_buy = np.zeros(n_test)
mae_sell = np.zeros(n_test)
mfe_sell = np.zeros(n_test)
fwd_ret_buy = np.zeros(n_test)
fwd_ret_sell = np.zeros(n_test)

for i in range(n_test):
    c0 = close_arr[i]
    if i + H < n_test:
        w_high = np.max(high_arr[i+1 : i+1+H])
        w_low = np.min(low_arr[i+1 : i+1+H])
        c_end = close_arr[i+H]
    else:
        # edge of test
        w_high = np.max(high_arr[i+1:]) if i+1 < n_test else c0
        w_low = np.min(low_arr[i+1:]) if i+1 < n_test else c0
        c_end = close_arr[-1]
        
    ret = (c_end - c0) / c0
    fwd_ret_buy[i] = ret
    fwd_ret_sell[i] = -ret
    mae_buy[i] = max(0.0, (c0 - w_low) / c0)
    mfe_buy[i] = max(0.0, (w_high - c0) / c0)
    mae_sell[i] = max(0.0, (w_high - c0) / c0)
    mfe_sell[i] = max(0.0, (c0 - w_low) / c0)

test_df["fwd_ret_buy"] = fwd_ret_buy
test_df["fwd_ret_sell"] = fwd_ret_sell
test_df["mae_buy"] = mae_buy
test_df["mfe_buy"] = mfe_buy
test_df["mae_sell"] = mae_sell
test_df["mfe_sell"] = mfe_sell

# Typical transaction cost for EUR/USD: 1.2p spread + 0.6p comm + 0.2p slip = 2.0p = 0.00020
# Normalized by close ~ 1.1000 => ~ 0.0001818 (1.82 bps)
cost_return_pct = (0.0001 * 2.0) / 1.1000

# ----------------------------------------------------------------------
# 1. THRESHOLD-INDEPENDENT SCORE ANALYSIS -> GATE_22_SCORE_BUCKETS.csv
# ----------------------------------------------------------------------
percentiles = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0]
bucket_records = []

for side in ["BUY", "SELL"]:
    score_col = "p_buy" if side == "BUY" else "p_sell"
    ret_col = "fwd_ret_buy" if side == "BUY" else "fwd_ret_sell"
    mae_col = "mae_buy" if side == "BUY" else "mae_sell"
    mfe_col = "mfe_buy" if side == "BUY" else "mfe_sell"
    
    # Sort descending by probability
    sorted_df = test_df.sort_values(score_col, ascending=False).reset_index(drop=True)
    
    for pct in percentiles:
        k = max(1, int(round(n_test * (pct / 100.0))))
        bucket = sorted_df.iloc[:k]
        
        prob_mean = float(bucket[score_col].mean())
        prob_median = float(bucket[score_col].median())
        mean_ret = float(bucket[ret_col].mean())
        median_ret = float(bucket[ret_col].median())
        win_rate = float((bucket[ret_col] > 0).mean() * 100.0)
        gross_ret = mean_ret
        net_ret = gross_ret - cost_return_pct
        mean_mae = float(bucket[mae_col].mean())
        mean_mfe = float(bucket[mfe_col].mean())
        
        bucket_records.append({
            "direction": side,
            "top_pct_bucket": f"Top_{pct}%",
            "sample_count": k,
            "mean_probability": f"{prob_mean:.4f}",
            "median_probability": f"{prob_median:.4f}",
            "win_rate_pct": f"{win_rate:.1f}",
            "mean_realized_gross_return_bps": f"{gross_ret * 10000:.2f}",
            "median_gross_return_bps": f"{median_ret * 10000:.2f}",
            "estimated_cost_bps": f"{cost_return_pct * 10000:.2f}",
            "mean_net_return_bps": f"{net_ret * 10000:.2f}",
            "mean_mae_bps": f"{mean_mae * 10000:.2f}",
            "mean_mfe_bps": f"{mean_mfe * 10000:.2f}"
        })

df_buckets = pd.DataFrame(bucket_records)
df_buckets.to_csv("GATE_22_SCORE_BUCKETS.csv", index=False)
print("Saved GATE_22_SCORE_BUCKETS.csv:")
print(df_buckets.to_string())

# Monotonicity test via Spearman correlation
corr_buy, pval_buy = spearmanr(test_df["p_buy"], test_df["fwd_ret_buy"])
corr_sell, pval_sell = spearmanr(test_df["p_sell"], test_df["fwd_ret_sell"])
print(f"\nSpearman Monotonicity: BUY corr={corr_buy:.4f} (p={pval_buy:.4e}), SELL corr={corr_sell:.4f} (p={pval_sell:.4e})")

# ----------------------------------------------------------------------
# 2. CONDITIONAL EXPECTANCY -> GATE_22_CONDITIONAL_EXPECTANCY.csv
# ----------------------------------------------------------------------
exp_records = []

# Overall baseline
base_buy_ret = float(test_df["fwd_ret_buy"].mean())
base_sell_ret = float(test_df["fwd_ret_sell"].mean())
exp_records.append({
    "dimension": "GLOBAL_UNCONDITIONAL",
    "subgroup": "ALL_TEST_SAMPLES",
    "sample_count": n_test,
    "gross_expectancy_buy_bps": f"{base_buy_ret * 10000:.2f}",
    "net_expectancy_buy_bps": f"{(base_buy_ret - cost_return_pct) * 10000:.2f}",
    "gross_expectancy_sell_bps": f"{base_sell_ret * 10000:.2f}",
    "net_expectancy_sell_bps": f"{(base_sell_ret - cost_return_pct) * 10000:.2f}"
})

# By Probability Deciles
test_df["buy_decile"] = pd.qcut(test_df["p_buy"], 5, duplicates="drop")
for dec, grp in test_df.groupby("buy_decile", observed=False):
    g_ret = float(grp["fwd_ret_buy"].mean())
    exp_records.append({
        "dimension": "PROBABILITY_QUINTILE_BUY",
        "subgroup": str(dec),
        "sample_count": len(grp),
        "gross_expectancy_buy_bps": f"{g_ret * 10000:.2f}",
        "net_expectancy_buy_bps": f"{(g_ret - cost_return_pct) * 10000:.2f}",
        "gross_expectancy_sell_bps": "N/A",
        "net_expectancy_sell_bps": "N/A"
    })

# By Regime
for reg, grp in test_df.groupby("regime", observed=False):
    g_buy = float(grp["fwd_ret_buy"].mean())
    g_sell = float(grp["fwd_ret_sell"].mean())
    exp_records.append({
        "dimension": "MARKET_REGIME",
        "subgroup": str(reg),
        "sample_count": len(grp),
        "gross_expectancy_buy_bps": f"{g_buy * 10000:.2f}",
        "net_expectancy_buy_bps": f"{(g_buy - cost_return_pct) * 10000:.2f}",
        "gross_expectancy_sell_bps": f"{g_sell * 10000:.2f}",
        "net_expectancy_sell_bps": f"{(g_sell - cost_return_pct) * 10000:.2f}"
    })

# By Session
session_cols = [
    ("is_asian_session", "ASIA"),
    ("is_london_session", "LONDON"),
    ("is_ny_session", "NEW_YORK"),
    ("is_london_ny_overlap", "LONDON_NY_OVERLAP")
]
for col, name in session_cols:
    grp = test_df[test_df[col] == 1]
    if len(grp) > 0:
        g_buy = float(grp["fwd_ret_buy"].mean())
        g_sell = float(grp["fwd_ret_sell"].mean())
        exp_records.append({
            "dimension": "MARKET_SESSION",
            "subgroup": name,
            "sample_count": len(grp),
            "gross_expectancy_buy_bps": f"{g_buy * 10000:.2f}",
            "net_expectancy_buy_bps": f"{(g_buy - cost_return_pct) * 10000:.2f}",
            "gross_expectancy_sell_bps": f"{g_sell * 10000:.2f}",
            "net_expectancy_sell_bps": f"{(g_sell - cost_return_pct) * 10000:.2f}"
        })

df_exp = pd.DataFrame(exp_records)
df_exp.to_csv("GATE_22_CONDITIONAL_EXPECTANCY.csv", index=False)
print("\nSaved GATE_22_CONDITIONAL_EXPECTANCY.csv:")
print(df_exp.to_string())
