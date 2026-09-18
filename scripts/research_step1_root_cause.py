import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from sklearn.preprocessing import StandardScaler
import joblib

from ai_forex_bot.config.settings import settings
from ai_forex_bot.features.builder import FeatureBuilder
from ai_forex_bot.labels.labeler import CostAwareLabeler
from ai_forex_bot.data.market.split import PurgedTimeSeriesSplitter
from ai_forex_bot.ai.models.base import HistGradientBoostingModel
from ai_forex_bot.decision.engine import MetaDecisionEngine, Direction
from ai_forex_bot.risk.risk_engine import RiskEngine, RiskDecision, AccountState

print("Executing Step 1: Zero-OOS-Trade Root Cause & Signal Trace...")

# 1. Load data
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
p_hold = probas_test[:, 0]
p_buy = probas_test[:, 1]
p_sell = probas_test[:, 2]
p_max_dir = np.maximum(p_buy, p_sell)

# Margin between top probability and second probability
sorted_probas = np.sort(probas_test, axis=1)
margin = sorted_probas[:, -1] - sorted_probas[:, -2]

# ----------------------------------------------------------------------
# 1. PROBABILITY DISTRIBUTION ANALYSIS -> GATE_22_PROBABILITY_DISTRIBUTION.csv
# ----------------------------------------------------------------------
def calc_dist_metrics(arr, name):
    return {
        "variable": name,
        "min": float(np.min(arr)),
        "p50_median": float(np.percentile(arr, 50)),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p97_5": float(np.percentile(arr, 97.5)),
        "p99": float(np.percentile(arr, 99)),
        "p99_5": float(np.percentile(arr, 99.5)),
        "max": float(np.max(arr))
    }

dist_rows = [
    calc_dist_metrics(p_hold, "P(HOLD)"),
    calc_dist_metrics(p_buy, "P(BUY)"),
    calc_dist_metrics(p_sell, "P(SELL)"),
    calc_dist_metrics(p_max_dir, "MAX(P_BUY, P_SELL)"),
    calc_dist_metrics(margin, "PROBABILITY_MARGIN (top - 2nd)")
]

df_dist = pd.DataFrame(dist_rows)
df_dist.to_csv("GATE_22_PROBABILITY_DISTRIBUTION.csv", index=False)
print("Saved GATE_22_PROBABILITY_DISTRIBUTION.csv:")
print(df_dist.to_string())

# ----------------------------------------------------------------------
# 2. SIGNAL PIPELINE TRACE -> GATE_22_SIGNAL_TRACE.csv
# ----------------------------------------------------------------------
n_test = len(test_df)
decision_engine = MetaDecisionEngine(confidence_threshold=0.55)
risk_engine = RiskEngine(max_open_positions=2, max_currency_exposure=2)
account = AccountState(balance=1000.0, equity=1000.0, free_margin=1000.0, initial_balance=1000.0)

counts = {
    "total_observations": n_test,
    "model_argmax_hold": int(np.sum(np.argmax(probas_test, axis=1) == 0)),
    "model_argmax_buy": int(np.sum(np.argmax(probas_test, axis=1) == 1)),
    "model_argmax_sell": int(np.sum(np.argmax(probas_test, axis=1) == 2)),
    "above_confidence_threshold_0_55": 0,
    "above_confidence_threshold_0_30": int(np.sum(p_max_dir >= 0.30)),
    "above_confidence_threshold_0_20": int(np.sum(p_max_dir >= 0.20)),
    "above_confidence_threshold_0_15": int(np.sum(p_max_dir >= 0.15)),
    "veto_low_confidence": 0,
    "veto_hold_prediction": 0,
    "veto_adverse_regime": 0,
    "veto_news_blackout": 0,
    "decision_buy": 0,
    "decision_sell": 0,
    "decision_hold_or_no_trade": 0,
    "risk_approved_buy": 0,
    "risk_approved_sell": 0,
    "final_trades_executed": 0
}

trace_records = []
for i in range(n_test):
    row = test_df.iloc[i]
    epoch = int(row["epoch"])
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    regime = str(row.get("regime", "RANGE"))
    news_pol = str(row.get("econ_policy", "NORMAL"))
    is_blackout = bool(row.get("econ_is_blackout", 0))
    probs = probas_test[i]
    
    # Trace decision engine
    dec = decision_engine.evaluate(
        symbol=sym,
        epoch=epoch,
        probabilities=probs,
        regime=regime,
        news_policy=news_pol,
        is_news_blackout=is_blackout
    )
    
    if probs[1] >= 0.55 or probs[2] >= 0.55:
        counts["above_confidence_threshold_0_55"] += 1
        
    if dec.direction == Direction.BUY:
        counts["decision_buy"] += 1
    elif dec.direction == Direction.SELL:
        counts["decision_sell"] += 1
    else:
        counts["decision_hold_or_no_trade"] += 1
        if "Adverse market regime" in dec.reason:
            counts["veto_adverse_regime"] += 1
        elif "blackout" in dec.reason.lower():
            counts["veto_news_blackout"] += 1
        elif "below confidence threshold" in dec.reason.lower():
            counts["veto_low_confidence"] += 1
        elif dec.direction == Direction.HOLD:
            counts["veto_hold_prediction"] += 1

trace_summary = [
    {"funnel_stage": "1_TOTAL_TEST_SAMPLES", "count": counts["total_observations"], "pct": 100.0, "description": "Total OOS test observations in 2026-07 to 2026-09"},
    {"funnel_stage": "2_MODEL_ARGMAX_HOLD", "count": counts["model_argmax_hold"], "pct": counts["model_argmax_hold"]/n_test*100, "description": "Raw model probability ranked HOLD highest"},
    {"funnel_stage": "2_MODEL_ARGMAX_BUY", "count": counts["model_argmax_buy"], "pct": counts["model_argmax_buy"]/n_test*100, "description": "Raw model probability ranked BUY highest"},
    {"funnel_stage": "2_MODEL_ARGMAX_SELL", "count": counts["model_argmax_sell"], "pct": counts["model_argmax_sell"]/n_test*100, "description": "Raw model probability ranked SELL highest"},
    {"funnel_stage": "3_CONFIDENCE_GE_0_55", "count": counts["above_confidence_threshold_0_55"], "pct": counts["above_confidence_threshold_0_55"]/n_test*100, "description": "Directional probability >= 0.55 entry threshold"},
    {"funnel_stage": "3_CONFIDENCE_GE_0_20", "count": counts["above_confidence_threshold_0_20"], "pct": counts["above_confidence_threshold_0_20"]/n_test*100, "description": "Directional probability >= 0.20 diagnostic tier"},
    {"funnel_stage": "3_CONFIDENCE_GE_0_15", "count": counts["above_confidence_threshold_0_15"], "pct": counts["above_confidence_threshold_0_15"]/n_test*100, "description": "Directional probability >= 0.15 diagnostic tier"},
    {"funnel_stage": "4_DECISION_BUY", "count": counts["decision_buy"], "pct": counts["decision_buy"]/n_test*100, "description": "Decision engine passed BUY order signal"},
    {"funnel_stage": "4_DECISION_SELL", "count": counts["decision_sell"], "pct": counts["decision_sell"]/n_test*100, "description": "Decision engine passed SELL order signal"},
    {"funnel_stage": "4_VETO_LOW_CONFIDENCE", "count": counts["veto_low_confidence"], "pct": counts["veto_low_confidence"]/n_test*100, "description": "Vetoed: P(BUY) and P(SELL) strictly < 0.55 threshold"},
    {"funnel_stage": "4_VETO_ADVERSE_REGIME", "count": counts["veto_adverse_regime"], "pct": counts["veto_adverse_regime"]/n_test*100, "description": "Vetoed: Market regime HIGH_VOLATILITY or UNCERTAIN"},
    {"funnel_stage": "4_VETO_NEWS_BLACKOUT", "count": counts["veto_news_blackout"], "pct": counts["veto_news_blackout"]/n_test*100, "description": "Vetoed: News blackout active"},
    {"funnel_stage": "5_FINAL_TRADES_EXECUTED", "count": counts["final_trades_executed"], "pct": counts["final_trades_executed"]/n_test*100, "description": "Executed broker orders filled"}
]

df_trace = pd.DataFrame(trace_summary)
df_trace.to_csv("GATE_22_SIGNAL_TRACE.csv", index=False)
print("\nSaved GATE_22_SIGNAL_TRACE.csv:")
print(df_trace.to_string())
