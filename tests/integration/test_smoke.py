import unittest
from ai_forex_bot.ai.training.trainer import TrainingPipeline

class TestSystemSmoke(unittest.TestCase):
    def test_training_smoke_workflow(self):
        trainer = TrainingPipeline(symbol="frxEURUSD", timeframe="M15", model_type="logistic_regression")
        res = trainer.train()
        self.assertIn("run_id", res)
        self.assertIn("validation", res["metrics"])
        self.assertIn("test_oos", res["metrics"])
        self.assertGreater(res["dataset_meta"]["train_rows"], 1000)

if __name__ == "__main__":
    unittest.main()
