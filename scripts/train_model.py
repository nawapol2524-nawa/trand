import argparse
from ai_forex_bot.ai.training.trainer import TrainingPipeline

def main():
    parser = argparse.ArgumentParser(description="Train institutional AI Forex Model")
    parser.add_argument("--symbol", default="frxEURUSD", help="Symbol name (e.g. frxEURUSD, frxXAUUSD)")
    parser.add_argument("--timeframe", default="M15", help="Timeframe (e.g. M15, M5, H1)")
    parser.add_argument("--model", default="hist_gradient_boosting", help="Model type")
    args = parser.parse_args()

    print(f"Starting training pipeline for {args.symbol} {args.timeframe} using {args.model}...")
    trainer = TrainingPipeline(symbol=args.symbol, timeframe=args.timeframe, model_type=args.model)
    res = trainer.train()
    print(f"Training completed successfully! Run ID: {res['run_id']}")
    print(f"Model artifact saved to artifacts/models/{res['run_id']}.joblib")

if __name__ == "__main__":
    main()
