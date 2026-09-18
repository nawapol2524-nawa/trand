#!/usr/bin/env python3
import sys
import argparse

def main():
    parser = argparse.ArgumentParser(description="AI Forex Autonomous Trading System CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("inspect-env", help="Inspect environment variables")
    subparsers.add_parser("prepare-data", help="Run historical data pipeline")
    subparsers.add_parser("run-leakage-audit", help="Run automated leakage audit")
    
    train_p = subparsers.add_parser("train", help="Train baseline model")
    train_p.add_argument("--symbol", default="frxEURUSD")
    train_p.add_argument("--timeframe", default="M15")
    train_p.add_argument("--model", default="hist_gradient_boosting")

    wf_p = subparsers.add_parser("walk-forward", help="Run walk-forward validation")
    wf_p.add_argument("--symbol", default="frxEURUSD")
    wf_p.add_argument("--timeframe", default="M15")
    wf_p.add_argument("--splits", type=int, default=3)

    args = parser.parse_args()

    if args.command == "inspect-env":
        from scripts import inspect_env
        inspect_env.main()
    elif args.command == "prepare-data":
        from scripts import prepare_data
        prepare_data.main()
    elif args.command == "run-leakage-audit":
        from scripts import run_leakage_audit
        run_leakage_audit.main()
    elif args.command == "train":
        from ai_forex_bot.ai.training.trainer import TrainingPipeline
        trainer = TrainingPipeline(symbol=args.symbol, timeframe=args.timeframe, model_type=args.model)
        res = trainer.train()
        print(f"Model trained! Run ID: {res['run_id']}")
    elif args.command == "walk-forward":
        from scripts import walk_forward
        sys.argv = ["walk_forward.py", "--symbol", args.symbol, "--timeframe", args.timeframe, "--splits", str(args.splits)]
        walk_forward.main()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
