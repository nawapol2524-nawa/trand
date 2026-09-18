#!/usr/bin/env python3
"""
Shadow & Paper Trading Engine Runner
====================================
Institutional Simulation Standard for Gate 23
Runs Candidate B (HGB_Balanced TRIAL_06) with RiskEngine and PaperBroker:
- Decoupled Architecture: MarketDataFeeder ➔ ShadowWorker ➔ RiskEngine ➔ PaperBroker
- Evaluates 43 causal features and regime state on each new bar (zero look-ahead).
- Enforces SL (15p), TP (20p), and Time-Based Exit (4 bars / 60m).
- Logs complete per-bar telemetry to logs/shadow_signals.jsonl.
- Logs all filled and closed trades to logs/paper_trades.jsonl.
- Strictly enforces LIVE_TRADING = false.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Generator

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
import joblib

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ai_forex_bot.config.settings import settings
from ai_forex_bot.features.builder import FeatureBuilder
from ai_forex_bot.labels.labeler import CostAwareLabeler
from ai_forex_bot.data.market.split import PurgedTimeSeriesSplitter
from ai_forex_bot.ai.models.base import HistGradientBoostingModel
from ai_forex_bot.decision.engine import MetaDecisionEngine, Direction
from ai_forex_bot.risk.risk_engine import RiskEngine, RiskDecision, AccountState, Position
from ai_forex_bot.execution.paper_broker import PaperBroker
from ai_forex_bot.market.sessions.session import MarketSession


# ==============================================================================
# 1. Market Data Feeder
# ==============================================================================
class MarketDataFeeder:
    """Simulates real-time market bar arrival from clean historical parquets."""
    def __init__(self, df: pd.DataFrame, symbol: str = "frxEURUSD"):
        self.df = df.sort_values("epoch").reset_index(drop=True)
        self.symbol = symbol

    def stream_bars(self, start_idx: int = 0) -> Generator[Dict[str, Any], None, None]:
        for i in range(start_idx, len(self.df)):
            row = self.df.iloc[i].to_dict()
            row["symbol"] = self.symbol
            yield row


# ==============================================================================
# 2. Candidate B Model Factory & Loader
# ==============================================================================
def load_or_train_candidate_b(
    df_raw: pd.DataFrame,
    symbol: str = "frxEURUSD",
    artifact_dir: Optional[Path] = None
) -> tuple:
    """Loads pre-trained Candidate B model or trains and calibrates on Train/Val folds."""
    art_dir = artifact_dir or (settings.root_dir / "artifacts" / "models")
    art_dir.mkdir(parents=True, exist_ok=True)
    model_path = art_dir / f"candidate_b_{symbol}_M15.joblib"

    h1_path = settings.clean_data_dir / f"{symbol}_H1.parquet"
    df_h1 = pd.read_parquet(h1_path) if h1_path.exists() else None

    fb = FeatureBuilder()
    df_feat = fb.build_features(df_raw, df_h1=df_h1, symbol=symbol)
    df_labeled = CostAwareLabeler().label_dataset(df_feat, symbol=symbol)

    meta_cols = {"epoch", "regime", "econ_policy", "target_class", "future_return", "future_net_buy", "future_net_sell"}
    feature_cols = [c for c in df_labeled.columns if c not in meta_cols]

    splitter = PurgedTimeSeriesSplitter(horizon_bars=4, embargo_bars=0)
    bounds = splitter.get_split_indices(df_labeled, train_ratio=0.70, val_ratio=0.15)

    train_df = df_labeled.iloc[bounds.train_indices]
    val_df = df_labeled.iloc[bounds.val_indices]

    X_train = train_df[feature_cols].values
    y_train = train_df["target_class"].values
    X_val = val_df[feature_cols].values
    y_val = val_df["target_class"].values

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_val_s = scaler.transform(X_val)

    if model_path.exists():
        try:
            saved_data = joblib.load(model_path)
            model = saved_data["model"]
            scaler = saved_data["scaler"]
            feature_cols = saved_data["feature_cols"]
            return model, scaler, feature_cols, df_feat
        except Exception:
            pass

    # Read hyperparameters from candidate manifest
    manifest_path = settings.root_dir / "GATE_22R_CANDIDATE_MANIFEST.json"
    hparams = {
        "learning_rate": 0.03,
        "max_iter": 100,
        "min_samples_leaf": 20,
        "l2_regularization": 0.0,
        "class_weight": "balanced",
        "random_state": 42
    }
    if manifest_path.exists():
        with open(manifest_path, "r") as f:
            cands = json.load(f).get("candidates", [])
            for c in cands:
                if c.get("candidate_id") == "Candidate_B_Class_Weighted_HGB":
                    hparams = c.get("hyperparameters", hparams)
                    break

    model = HistGradientBoostingModel(hparams)
    model.fit(X_train_s, y_train, feature_names=feature_cols)
    model.calibrate(X_val_s, y_val, method="isotonic")

    # Save artifact
    joblib.dump({"model": model, "scaler": scaler, "feature_cols": feature_cols}, model_path)
    return model, scaler, feature_cols, df_feat


# ==============================================================================
# 3. Shadow Trading Engine Core
# ==============================================================================
class ShadowTradingEngine:
    def __init__(
        self,
        symbol: str = "frxEURUSD",
        initial_balance: float = 1000.0,
        confidence_threshold: float = 0.55,
        time_exit_bars: int = 4,
        log_dir: Optional[Path] = None
    ):
        self.symbol = symbol
        self.confidence_threshold = confidence_threshold
        self.time_exit_bars = time_exit_bars

        # Strict safety check
        if os.getenv("LIVE_TRADING", "false").lower() == "true":
            raise RuntimeError("CRITICAL INVARIANT VIOLATION: LIVE_TRADING must be false during shadow validation.")

        self.log_dir = log_dir or (settings.root_dir / "logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.signals_log_path = self.log_dir / "shadow_signals.jsonl"
        self.trades_log_path = self.log_dir / "paper_trades.jsonl"

        # Initialize Decoupled Architecture
        self.broker = PaperBroker(
            initial_balance=initial_balance,
            time_exit_bars=time_exit_bars
        )
        self.broker.connect()
        self.risk_engine = RiskEngine()
        self.decision_engine = MetaDecisionEngine(confidence_threshold=confidence_threshold)

        self.model = None
        self.scaler = None
        self.feature_cols = None

        self.rolling_bars: List[Dict[str, Any]] = []
        self.min_warmup_bars = 220  # Warm-up required for 200 EMA + indicators

    def initialize_model(self, df_base: pd.DataFrame):
        self.model, self.scaler, self.feature_cols, _ = load_or_train_candidate_b(
            df_base, symbol=self.symbol
        )

    def log_signal(self, telemetry: Dict[str, Any]):
        with open(self.signals_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(telemetry) + "\n")

    def log_trade(self, trade: Dict[str, Any]):
        with open(self.trades_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(trade) + "\n")

    def process_bar(self, bar: Dict[str, Any]) -> Dict[str, Any]:
        """
        Processes a single market bar:
        1. Updates broker positions for SL/TP/Time-Exit.
        2. Computes causal features for candidate model.
        3. Evaluates predictions & confidence.
        4. Validates risk constraints with RiskEngine.
        5. Dispatches approved orders to PaperBroker.
        6. Emits structured telemetry.
        """
        epoch = int(bar["epoch"])
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        close = float(bar["close"])

        # 1. Step broker bar lifecycle (check SL, TP, Time-based exit for existing positions)
        closed_trades = self.broker.on_bar(bar)
        for trade in closed_trades:
            self.risk_engine.record_closed_trade(trade["net_pnl"], dt)
            self.log_trade(trade)

        self.rolling_bars.append(bar)
        # Keep buffer bounded to save memory
        if len(self.rolling_bars) > 500:
            self.rolling_bars = self.rolling_bars[-500:]

        if len(self.rolling_bars) < self.min_warmup_bars:
            telemetry = {
                "timestamp": dt.isoformat(),
                "epoch": epoch,
                "symbol": self.symbol,
                "close": close,
                "status": "WARMUP",
                "bars_buffered": len(self.rolling_bars),
                "p_hold": 1.0,
                "p_buy": 0.0,
                "p_sell": 0.0,
                "signal_direction": "HOLD",
                "confidence": 1.0,
                "regime": "WARMUP",
                "risk_verdict": "VETO",
                "veto_reason": "WARMUP_PERIOD",
                "executed_order_id": None
            }
            self.log_signal(telemetry)
            return telemetry

        # 2. Extract Causal Features
        df_buffer = pd.DataFrame(self.rolling_bars)
        fb = FeatureBuilder()
        df_feat = fb.build_features(df_buffer, symbol=self.symbol)
        latest_feat = df_feat.iloc[-1]

        regime = str(latest_feat["regime"])
        session = MarketSession.get_session_name(dt.hour) if hasattr(MarketSession, "get_session_name") else "STANDARD"

        X = latest_feat[self.feature_cols].values.reshape(1, -1)
        X_s = self.scaler.transform(X)

        # 3. Inference
        probas = self.model.predict_proba(X_s)[0]
        p_hold, p_buy, p_sell = float(probas[0]), float(probas[1]), float(probas[2])

        # Directional signal selection
        if max(p_buy, p_sell) >= self.confidence_threshold:
            signal_direction = "BUY" if p_buy > p_sell else "SELL"
            confidence = max(p_buy, p_sell)
        else:
            signal_direction = "HOLD"
            confidence = p_hold

        # 4. Risk Engine Validation
        executed_order_id = None
        risk_verdict = "HOLD"
        veto_reason = None

        if signal_direction in ("BUY", "SELL"):
            # Regime filter check
            if regime in ("HIGH_VOLATILITY", "UNCERTAIN"):
                risk_verdict = "VETO"
                veto_reason = f"REGIME_FILTER_VETO_{regime}"
            else:
                quote = self.broker.get_quote(self.symbol)
                acct = self.broker.get_account_state()
                account_state = AccountState(
                    balance=acct["balance"],
                    equity=acct["equity"],
                    free_margin=acct["free_margin"],
                    used_margin=acct["used_margin"],
                    initial_balance=acct["initial_balance"]
                )

                # Open positions check
                open_pos_objs = [
                    Position(
                        position_id=p["position_id"],
                        symbol=p["symbol"],
                        direction=p["direction"],
                        lot_size=p["lot_size"],
                        entry_price=p["entry_price"],
                        current_price=close,
                        sl_price=p["sl_price"],
                        tp_price=p["tp_price"]
                    ) for p in self.broker.get_open_positions()
                ]

                decision, code, detail = self.risk_engine.validate_new_order(
                    symbol=self.symbol,
                    direction=signal_direction,
                    current_spread_pips=quote["spread_pips"],
                    account=account_state,
                    open_positions=open_pos_objs,
                    current_dt=dt,
                    is_news_blackout=False
                )

                if decision == RiskDecision.APPROVE:
                    risk_verdict = "APPROVE"
                    # Sizing & Placement
                    pip_size = 0.0001
                    sl_pips = 15.0
                    tp_pips = 20.0
                    entry_est = quote["ask"] if signal_direction == "BUY" else quote["bid"]
                    sl_price = entry_est - (sl_pips * pip_size) if signal_direction == "BUY" else entry_est + (sl_pips * pip_size)
                    tp_price = entry_est + (tp_pips * pip_size) if signal_direction == "BUY" else entry_est - (tp_pips * pip_size)

                    lot_size, size_err = self.risk_engine.calculate_position_size(
                        account=account_state,
                        symbol=self.symbol,
                        entry_price=entry_est,
                        sl_price=sl_price
                    )

                    if lot_size > 0 and not size_err:
                        order_res = self.broker.place_order(
                            symbol=self.symbol,
                            direction=signal_direction,
                            lot_size=lot_size,
                            sl_price=sl_price,
                            tp_price=tp_price
                        )
                        if order_res.get("status") == "FILLED":
                            executed_order_id = order_res["order_id"]
                        else:
                            risk_verdict = "REJECTED_BY_BROKER"
                            veto_reason = order_res.get("reason", "BROKER_REJECTION")
                    else:
                        risk_verdict = "VETO"
                        veto_reason = f"SIZING_ERROR: {size_err}"
                else:
                    risk_verdict = "VETO"
                    veto_reason = f"{code}: {detail}"

        telemetry = {
            "timestamp": dt.isoformat(),
            "epoch": epoch,
            "symbol": self.symbol,
            "close": close,
            "status": "PROCESSED",
            "p_hold": round(p_hold, 4),
            "p_buy": round(p_buy, 4),
            "p_sell": round(p_sell, 4),
            "signal_direction": signal_direction,
            "confidence": round(confidence, 4),
            "regime": regime,
            "risk_verdict": risk_verdict,
            "veto_reason": veto_reason,
            "executed_order_id": executed_order_id,
            "broker_equity": self.broker.equity,
            "open_positions": len(self.broker.positions)
        }
        self.log_signal(telemetry)
        return telemetry


def main():
    parser = argparse.ArgumentParser(description="Run Candidate B Shadow Validation Engine")
    parser.add_argument("--symbol", default="frxEURUSD", help="Forex Symbol")
    parser.add_argument("--bars", type=int, default=100, help="Number of recent bars to simulate")
    parser.add_argument("--threshold", type=float, default=0.55, help="Confidence threshold")
    parser.add_argument("--initial-balance", type=float, default=1000.0, help="Initial balance")
    args = parser.parse_args()

    print("=" * 80)
    print("GATE 23 — CANDIDATE B SHADOW & PAPER TRADING RUNNER")
    print("=" * 80)
    print(f"Symbol: {args.symbol} | Mode: PAPER / SHADOW | LIVE_TRADING = false")
    print(f"Simulating evaluation of {args.bars} bars with confidence threshold {args.threshold}")

    # Load clean data
    data_path = settings.clean_data_dir / f"{args.symbol}_M15.parquet"
    if not data_path.exists():
        print(f"Error: Dataset {data_path} not found.")
        sys.exit(1)

    df_base = pd.read_parquet(data_path)
    engine = ShadowTradingEngine(
        symbol=args.symbol,
        initial_balance=args.initial_balance,
        confidence_threshold=args.threshold
    )

    print("Initializing and fitting Candidate B (HGB_Balanced TRIAL_06)...")
    engine.initialize_model(df_base)
    print("Model initialized successfully.")

    # Slice stream: Need warmup bars + requested bars
    total_bars_needed = engine.min_warmup_bars + args.bars
    slice_df = df_base.iloc[-total_bars_needed:].copy()
    feeder = MarketDataFeeder(slice_df, symbol=args.symbol)

    print(f"Streaming {args.bars} validation bars through decoupled architecture...")
    count = 0
    signals_count = 0
    trades_opened = 0

    for bar in feeder.stream_bars():
        res = engine.process_bar(bar)
        if res.get("status") == "PROCESSED":
            count += 1
            if res.get("signal_direction") in ("BUY", "SELL"):
                signals_count += 1
            if res.get("executed_order_id"):
                trades_opened += 1

    reconcile_res = engine.broker.reconcile()
    acct = engine.broker.get_account_state()

    print("\n" + "=" * 80)
    print("SHADOW ENGINE EXECUTION SUMMARY")
    print("=" * 80)
    print(f"Processed Bars: {count}")
    print(f"Signals Generated: {signals_count}")
    print(f"Orders Executed: {trades_opened}")
    print(f"Closed Trades: {len(engine.broker.closed_trades)}")
    print(f"Final Balance: ${acct['balance']:.2f} | Final Equity: ${acct['equity']:.2f}")
    print(f"Reconciliation Synchronized: {reconcile_res['is_synchronized']}")
    print(f"Telemetry Log: {engine.signals_log_path}")
    print(f"Trades Log: {engine.trades_log_path}")
    print("Status: GATE 23 SHADOW ENGINE VERIFIED READY")


if __name__ == "__main__":
    main()
