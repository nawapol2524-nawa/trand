from ai_forex_bot.data.market.pipeline import HistoricalDataPipeline

def main():
    print("Starting historical data pipeline (Ingestion ➔ Validation ➔ Resampling)...")
    pipeline = HistoricalDataPipeline()
    manifest = pipeline.process_all()
    print("Historical data pipeline complete. Manifest saved at data/clean/dataset_manifest.json")

if __name__ == "__main__":
    main()
