import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import balanced_accuracy_score, f1_score
from sklearn.ensemble import HistGradientBoostingClassifier

from ai_forex_bot.config.settings import settings
from ai_forex_bot.features.builder import FeatureBuilder
from ai_forex_bot.labels.labeler import CostAwareLabeler
from ai_forex_bot.data.market.split import PurgedTimeSeriesSplitter

print("Executing Step 4: Cross-Sectional Analysis (Symbol, Regime, Session, Cost Sensitivity, Trade Ledger)...")

# ----------------------------------------------------------------------
# 1. SYMBOL ANALYSIS -> GATE_22_SYMBOL_ANALYSIS.csv
# ----------------------------------------------------------------------
symbols = ["frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxXAUUSD"]
symbol_records = []

builder = FeatureBuilder()
labeler = CostAwareLabeler()

for sym in symbols:
    m15_file = settings.clean_data_dir / f"{sym}_M15.parquet"
    h1_file = settings.clean_data_dir / f"{sym}_H1.parquet"
    if not m15_file.exists():
        continue
    
    df_b = pd.read_parquet(m15_file)
    df_h = pd.read_parquet(h1_file) if h1_file.exists() else None
    
    df_f = builder.build_features(df_b, df_h1=df_h, symbol=sym)
    df_l = labeler.label_dataset(df_f, symbol=sym)
    
    meta_cols = {"epoch", "regime", "econ_policy", "target_class", "future_return", "future_net_buy", "future_net_sell"}
    feat_cols = [c for c in df_l.columns if c not in meta_cols]
    
    s_bounds = PurgedTimeSeriesSplitter(horizon_bars=4, embargo_bars=0).get_split_indices(df_l, 0.70, 0.15)
    tr_df = df_l.iloc[s_bounds.train_indices]
    va_df = df_l.iloc[s_bounds.val_indices]
    
    # Class distribution on Val
    p_h = float(np.mean(va_df["target_class"] == 0) * 100)
    p_b = float(np.mean(va_df["target_class"] == 1) * 100)
    p_s = float(np.mean(va_df["target_class"] == 2) * 100)
    
    # Train HGB
    X_tr = tr_df[feat_cols].values
    y_tr = tr_df["target_class"].values
    X_va = va_df[feat_cols].values
    y_va = va_df["target_class"].values
    
    sc = StandardScaler()
    X_tr_s = sc.fit_transform(X_tr)
    X_va_s = sc.transform(X_va)
    
    clf = HistGradientBoostingClassifier(random_state=42, max_iter=100)
    clf.fit(X_tr_s, y_tr)
    preds = clf.predict(X_va_s)
    probas = clf.predict_proba(X_va_s)
    
    b_acc = float(balanced_accuracy_score(y_va, preds))
    mf1 = float(f1_score(y_va, preds, average="macro", zero_division=0))
    
    # Symbol specific cost
    sym_cfg = settings.get_symbol_config(sym)
    pip_size = sym_cfg.pip_size if sym_cfg else 0.0001
    typical_spread = sym_cfg.typical_spread_pips if sym_cfg else 1.2
    comm_pips = (sym_cfg.commission_per_lot_usd / sym_cfg.pip_value_usd) if sym_cfg else 0.6
    cost_pips = typical_spread + comm_pips + 0.2
    ref_price = float(va_df["close"].mean())
    cost_bps = ((cost_pips * pip_size) / ref_price) * 10000
    
    # Top 5% BUY conditional return
    p_buy_val = probas[:, 1]
    k_top = max(1, int(len(va_df) * 0.05))
    top_buy_idx = np.argsort(p_buy_val)[::-1][:k_top]
    mean_buy_ret_bps = float(np.mean(va_df["future_return"].iloc[top_buy_idx]) * 10000)
    net_buy_ret_bps = mean_buy_ret_bps - cost_bps
    
    symbol_records.append({
        "symbol": sym,
        "timeframe": "M15",
        "validation_samples": len(va_df),
        "hold_class_pct": f"{p_h:.1f}",
        "buy_class_pct": f"{p_b:.1f}",
        "sell_class_pct": f"{p_s:.1f}",
        "val_balanced_acc": f"{b_acc:.4f}",
        "val_macro_f1": f"{mf1:.4f}",
        "typical_cost_bps": f"{cost_bps:.2f}",
        "top_5pct_buy_gross_ret_bps": f"{mean_buy_ret_bps:.2f}",
        "top_5pct_buy_net_ret_bps": f"{net_buy_ret_bps:.2f}",
        "edge_survival_status": "EDGE_SURVIVED" if net_buy_ret_bps > 0 else "COST_ERODED"
    })

df_symbols = pd.DataFrame(symbol_records)
df_symbols.to_csv("GATE_22_SYMBOL_ANALYSIS.csv", index=False)
print("Saved GATE_22_SYMBOL_ANALYSIS.csv")

# ----------------------------------------------------------------------
# 2. REGIME & SESSION ANALYSIS ON EUR/USD VALIDATION FOLD
# ----------------------------------------------------------------------
# Use EUR/USD Validation fold (3,625 bars)
sym = "frxEURUSD"
clean_m15 = settings.clean_data_dir / f"{sym}_M15.parquet"
clean_h1 = settings.clean_data_dir / f"{sym}_H1.parquet"
df_b = pd.read_parquet(clean_m15)
df_h = pd.read_parquet(clean_h1)
df_f = builder.build_features(df_b, df_h1=df_h, symbol=sym)
df_l = labeler.label_dataset(df_f, symbol=sym)

feat_cols = [c for c in df_l.columns if c not in meta_cols]
s_bounds = PurgedTimeSeriesSplitter(horizon_bars=4, embargo_bars=0).get_split_indices(df_l, 0.70, 0.15)
tr_df = df_l.iloc[s_bounds.train_indices].copy()
va_df = df_l.iloc[s_bounds.val_indices].copy()

X_tr = tr_df[feat_cols].values
y_tr = tr_df["target_class"].values
X_va = va_df[feat_cols].values
y_va = va_df["target_class"].values

sc = StandardScaler()
X_tr_s = sc.fit_transform(X_tr)
X_va_s = sc.transform(X_va)

clf = HistGradientBoostingClassifier(random_state=42, max_iter=100)
clf.fit(X_tr_s, y_tr)
probas_va = clf.predict_proba(X_va_s)
va_df["p_buy"] = probas_va[:, 1]
va_df["p_sell"] = probas_va[:, 2]

# Forward returns over H=4
close_va = va_df["close"].values
n_va = len(va_df)
fwd_ret_buy_va = np.zeros(n_va)
fwd_ret_sell_va = np.zeros(n_va)
for i in range(n_va):
    c0 = close_va[i]
    c_end = close_va[i+4] if i+4 < n_va else close_va[-1]
    fwd_ret_buy_va[i] = (c_end - c0) / c0
    fwd_ret_sell_va[i] = (c0 - c_end) / c0
va_df["fwd_ret_buy"] = fwd_ret_buy_va
va_df["fwd_ret_sell"] = fwd_ret_sell_va

cost_bps = 1.82

# REGIME ANALYSIS -> GATE_22_REGIME_ANALYSIS.csv
regime_records = []
for reg, grp in va_df.groupby("regime", observed=False):
    cnt = len(grp)
    p_h = float(np.mean(grp["target_class"] == 0) * 100)
    p_b = float(np.mean(grp["target_class"] == 1) * 100)
    p_s = float(np.mean(grp["target_class"] == 2) * 100)
    g_buy = float(grp["fwd_ret_buy"].mean() * 10000)
    n_buy = g_buy - cost_bps
    g_sell = float(grp["fwd_ret_sell"].mean() * 10000)
    n_sell = g_sell - cost_bps
    
    # Top 10% in this regime
    top_buy_g = float(grp.sort_values("p_buy", ascending=False).iloc[:max(1, int(cnt*0.1))]["fwd_ret_buy"].mean() * 10000)
    top_buy_n = top_buy_g - cost_bps
    
    works_summary = "Directional edge present; BUY net expectancy positive in top tier" if top_buy_n > 0 else "Negative expectancy; adverse regime or cost erosion"
    
    regime_records.append({
        "regime": reg,
        "sample_count": cnt,
        "sample_share_pct": f"{cnt / n_va * 100:.1f}",
        "hold_class_pct": f"{p_h:.1f}",
        "buy_class_pct": f"{p_b:.1f}",
        "sell_class_pct": f"{p_s:.1f}",
        "unconditional_gross_buy_bps": f"{g_buy:.2f}",
        "unconditional_net_buy_bps": f"{n_buy:.2f}",
        "top_10pct_buy_gross_bps": f"{top_buy_g:.2f}",
        "top_10pct_buy_net_bps": f"{top_buy_n:.2f}",
        "regime_suitability": works_summary
    })

df_regime = pd.DataFrame(regime_records)
df_regime.to_csv("GATE_22_REGIME_ANALYSIS.csv", index=False)
print("Saved GATE_22_REGIME_ANALYSIS.csv")

# SESSION ANALYSIS -> GATE_22_SESSION_ANALYSIS.csv
session_cols = [
    ("is_asian_session", "ASIA"),
    ("is_london_session", "LONDON"),
    ("is_ny_session", "NEW_YORK"),
    ("is_london_ny_overlap", "LONDON_NY_OVERLAP")
]
session_records = []
for col, name in session_cols:
    grp = va_df[va_df[col] == 1]
    cnt = len(grp)
    if cnt == 0: continue
    g_buy = float(grp["fwd_ret_buy"].mean() * 10000)
    n_buy = g_buy - cost_bps
    top_buy_g = float(grp.sort_values("p_buy", ascending=False).iloc[:max(1, int(cnt*0.1))]["fwd_ret_buy"].mean() * 10000)
    top_buy_n = top_buy_g - cost_bps
    
    session_records.append({
        "session": name,
        "sample_count": cnt,
        "share_pct": f"{cnt / n_va * 100:.1f}",
        "unconditional_gross_bps": f"{g_buy:.2f}",
        "unconditional_net_bps": f"{n_buy:.2f}",
        "top_10pct_gross_bps": f"{top_buy_g:.2f}",
        "top_10pct_net_bps": f"{top_buy_n:.2f}",
        "session_edge_status": "PROFITABLE_AFTER_COST" if top_buy_n > 0 else "ERODED_BY_COST"
    })

df_session = pd.DataFrame(session_records)
df_session.to_csv("GATE_22_SESSION_ANALYSIS.csv", index=False)
print("Saved GATE_22_SESSION_ANALYSIS.csv")

# ----------------------------------------------------------------------
# 3. COST SENSITIVITY RESEARCH -> GATE_22_COST_SENSITIVITY.csv
# ----------------------------------------------------------------------
# Evaluate top 1%, 2%, 5% probability tiers against multiplier variations
cost_scenarios = [
    ("1.0X_SPREAD_1.0X_SLIP", 1.2, 0.2),
    ("1.5X_SPREAD_1.0X_SLIP", 1.8, 0.2),
    ("2.0X_SPREAD_1.0X_SLIP", 2.4, 0.2),
    ("3.0X_SPREAD_1.0X_SLIP", 3.6, 0.2),
    ("1.0X_SPREAD_2.0X_SLIP", 1.2, 0.4),
    ("1.0X_SPREAD_3.0X_SLIP", 1.2, 0.6),
    ("2.0X_SPREAD_2.0X_SLIP", 2.4, 0.4),
    ("3.0X_SPREAD_3.0X_SLIP", 3.6, 0.6),
]

cost_records = []
top_buy_1pct = va_df.sort_values("p_buy", ascending=False).iloc[:max(1, int(n_va * 0.01))]
top_buy_2pct = va_df.sort_values("p_buy", ascending=False).iloc[:max(1, int(n_va * 0.02))]
top_buy_5pct = va_df.sort_values("p_buy", ascending=False).iloc[:max(1, int(n_va * 0.05))]

g_ret_1 = float(top_buy_1pct["fwd_ret_buy"].mean() * 10000)
g_ret_2 = float(top_buy_2pct["fwd_ret_buy"].mean() * 10000)
g_ret_5 = float(top_buy_5pct["fwd_ret_buy"].mean() * 10000)

for sc_name, sp_p, sl_p in cost_scenarios:
    # Total round trip pips = spread + slippage + commission (0.6p)
    tot_pips = sp_p + sl_p + 0.6
    sc_cost_bps = ((tot_pips * 0.0001) / 1.1000) * 10000
    
    n_ret_1 = g_ret_1 - sc_cost_bps
    n_ret_2 = g_ret_2 - sc_cost_bps
    n_ret_5 = g_ret_5 - sc_cost_bps
    
    cost_records.append({
        "scenario": sc_name,
        "spread_pips": sp_p,
        "slippage_pips": sl_p,
        "commission_pips": 0.6,
        "total_cost_bps": f"{sc_cost_bps:.2f}",
        "top_1pct_gross_bps": f"{g_ret_1:.2f}",
        "top_1pct_net_bps": f"{n_ret_1:.2f}",
        "top_1pct_status": "SURVIVED" if n_ret_1 > 0 else "ERODED",
        "top_2pct_gross_bps": f"{g_ret_2:.2f}",
        "top_2pct_net_bps": f"{n_ret_2:.2f}",
        "top_2pct_status": "SURVIVED" if n_ret_2 > 0 else "ERODED",
        "top_5pct_gross_bps": f"{g_ret_5:.2f}",
        "top_5pct_net_bps": f"{n_ret_5:.2f}",
        "top_5pct_status": "SURVIVED" if n_ret_5 > 0 else "ERODED"
    })

df_cost_sens = pd.DataFrame(cost_records)
df_cost_sens.to_csv("GATE_22_COST_SENSITIVITY.csv", index=False)
print("Saved GATE_22_COST_SENSITIVITY.csv")

# ----------------------------------------------------------------------
# 4. CANONICAL TRADE LEDGER -> GATE_22_TRADE_LEDGER.csv
# ----------------------------------------------------------------------
# Create canonical ledger schema with any executed trades from validation experiments
ledger_cols = [
    "trade_id", "symbol", "timestamp", "direction", "signal_probability",
    "confidence", "regime", "session", "entry", "exit", "size",
    "gross_pnl", "spread_cost", "commission", "slippage", "swap",
    "net_pnl", "holding_time", "MAE", "MFE", "model_version",
    "feature_version", "label_version"
]

# Populate ledger with Top 1% validation research trades
ledger_rows = []
for idx, r in top_buy_1pct.iterrows():
    c0 = r["close"]
    # 4 bars holding time
    epoch = int(r["epoch"])
    dt_str = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    fwd_ret = r["fwd_ret_buy"]
    c_exit = c0 * (1.0 + fwd_ret)
    
    # 0.1 standard lot (10,000 units)
    # pip_val = $1.00 per pip for 0.1 lot
    lot = 0.1
    gross_pnl = ((c_exit - c0) / 0.0001) * 1.0
    sp_cost = 1.2 * 1.0
    comm_cost = 0.6 * 1.0
    slip_cost = 0.2 * 1.0
    swap_cost = 0.0
    net_pnl = gross_pnl - sp_cost - comm_cost - slip_cost
    
    ledger_rows.append({
        "trade_id": f"TRD_VAL_{idx:05d}",
        "symbol": "frxEURUSD",
        "timestamp": dt_str,
        "direction": "BUY",
        "signal_probability": f"{r['p_buy']:.4f}",
        "confidence": f"{r['p_buy']:.4f}",
        "regime": r.get("regime", "RANGE"),
        "session": "LONDON" if r.get("is_london_session", 0) else ("NEW_YORK" if r.get("is_ny_session", 0) else "ASIA"),
        "entry": f"{c0:.5f}",
        "exit": f"{c_exit:.5f}",
        "size": lot,
        "gross_pnl": f"{gross_pnl:.2f}",
        "spread_cost": f"{sp_cost:.2f}",
        "commission": f"{comm_cost:.2f}",
        "slippage": f"{slip_cost:.2f}",
        "swap": f"{swap_cost:.2f}",
        "net_pnl": f"{net_pnl:.2f}",
        "holding_time": "60m",
        "MAE": "N/A",
        "MFE": "N/A",
        "model_version": "HistGradientBoosting_V1",
        "feature_version": "FEAT_V1_43COLS",
        "label_version": "LABEL_V1_4BAR_15P"
    })

df_ledger = pd.DataFrame(ledger_rows, columns=ledger_cols)
df_ledger.to_csv("GATE_22_TRADE_LEDGER.csv", index=False)
print("Saved GATE_22_TRADE_LEDGER.csv")
print("Step 4 complete!")
