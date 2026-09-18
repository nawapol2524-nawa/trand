import argparse
import pandas as pd
from ai_forex_bot.features.builder import FeatureBuilder
from ai_forex_bot.labels.labeler import CostAwareLabeler
from ai_forex_bot.ai.training.walk_forward import WalkForwardValidator
from ai_forex_bot.config.settings import settings

def main():
    parser = argparse.ArgumentParser(description="Run Walk-Forward Time Series Validation")
    parser.add_argument("--symbol", default="frxEURUSD")
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--splits", type=int, default=3)
    args = parser.parse_args()

    df_base = pd.read_parquet(settings.clean_data_dir / f"{args.symbol}_{args.timeframe}.parquet")
    h1_path = settings.clean_data_dir / f"{args.symbol}_H1.parquet"
    df_h1 = pd.read_parquet(h1_path) if h1_path.exists() else None

    fb = FeatureBuilder()
    labeler = CostAwareLabeler()
    df_feat = fb.build_features(df_base, df_h1=df_h1, symbol=args.symbol)
    df_labeled = labeler.label_dataset(df_feat, symbol=args.symbol)

    wf = WalkForwardValidator(n_splits=args.splits)
    print(f"Running {args.splits} walk-forward splits on {args.symbol} {args.timeframe}...")
    results = wf.validate(df_labeled)
    for r in results:
        idx = r["split_index"]
        brier = r["metrics"]["brier_score"]
        f1 = r["metrics"]["f1_macro"]
        print(f"  Split {idx}: Brier Score={brier:.4f}, F1 Macro={f1:.4f}")

if __name__ == "__main__":
    main()
