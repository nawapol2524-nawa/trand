import unittest
import numpy as np
from ai_forex_bot.news_ai.calendar import EconomicCalendarEngine, EconomicEvent
from ai_forex_bot.news_ai.sentiment import NewsContextEngine, NewsArticle

class TestNewsAndCalendarCausality(unittest.TestCase):
    def test_future_news_injection_adversarial(self):
        """Injecting breaking news at T + 60 seconds must NOT alter sentiment or features at T."""
        engine = NewsContextEngine(memory_window_seconds=21600)
        
        # Historical news at T - 3600
        T = 1700000000
        article_past = NewsArticle(
            news_id="N1",
            headline="EUR GDP in line with estimates",
            source="reuters",
            publication_epoch=T - 3600,
            currency="EUR",
            sentiment_score=0.20,
            uncertainty_score=0.10,
            severity_score=0.30
        )
        engine.load_articles([article_past])
        
        ctx_before = engine.get_sentiment_at_epoch(T, currency="EUR")
        
        # Now inject an extreme breaking news shock at T + 60 (Future event relative to T)
        article_future = NewsArticle(
            news_id="N2",
            headline="CRITICAL: Unexpected emergency rate hike!",
            source="bloomberg",
            publication_epoch=T + 60,
            currency="EUR",
            sentiment_score=-0.95,
            uncertainty_score=0.90,
            severity_score=1.00
        )
        engine.load_articles([article_past, article_future])
        
        ctx_after = engine.get_sentiment_at_epoch(T, currency="EUR")
        
        # Sentiment and uncertainty at T must remain strictly identical
        self.assertEqual(ctx_before["news_sentiment"], ctx_after["news_sentiment"])
        self.assertEqual(ctx_before["news_uncertainty"], ctx_after["news_uncertainty"])
        self.assertEqual(ctx_before["news_severity"], ctx_after["news_severity"])
        self.assertEqual(ctx_before["news_article_count"], ctx_after["news_article_count"])

    def test_future_actual_data_invariance(self):
        """Actual economic release at T must NOT be visible at T - 1 second."""
        cal = EconomicCalendarEngine(blackout_pre_seconds=900, blackout_post_seconds=900)
        T_pub = 1700010000
        event = EconomicEvent(
            event_id="NFP_01",
            event_name="Non-Farm Payrolls",
            currency="USD",
            country="US",
            scheduled_epoch=T_pub,
            publication_epoch=T_pub,
            importance="HIGH",
            forecast=180.0,
            previous=150.0,
            actual=275.0
        )
        cal.load_events([event])
        
        # At T - 1 sec: surprise MUST be 0.0
        ctx_pre = cal.get_context_at_epoch(T_pub - 1, currency="USD")
        self.assertEqual(ctx_pre["surprise"], 0.0)
        
        # At T_pub: surprise is now visible (275 - 180 = 95)
        ctx_at = cal.get_context_at_epoch(T_pub, currency="USD")
        self.assertEqual(ctx_at["surprise"], 95.0)

if __name__ == "__main__":
    unittest.main()
