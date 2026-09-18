"""
Financial News & NLP Context Engine
===================================
Maintains causal timestamp alignment for incoming macro and pair news:
- Strictly filters articles where publication_epoch > current_epoch.
- Computes aggregate rolling sentiment scores, uncertainty index, and event severity.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import numpy as np
import pandas as pd


@dataclass
class NewsArticle:
    news_id: str
    headline: str
    source: str
    publication_epoch: int
    currency: str
    sentiment_score: float  # -1.0 (bearish) to +1.0 (bullish)
    uncertainty_score: float  # 0.0 (certain) to 1.0 (highly uncertain)
    severity_score: float  # 0.0 (minor) to 1.0 (breaking shock)


class NewsContextEngine:
    def __init__(self, memory_window_seconds: int = 21600):  # 6 hours decay window
        self.memory_window_seconds = memory_window_seconds
        self.articles: List[NewsArticle] = []

    def load_articles(self, articles: List[NewsArticle]):
        self.articles = sorted(articles, key=lambda a: a.publication_epoch)

    def get_sentiment_at_epoch(self, epoch: int, currency: Optional[str] = None) -> Dict[str, float]:
        """
        Retrieves exponentially decayed sentiment prior to epoch.
        Articles published strictly AFTER epoch are rejected (leakage prevention).
        """
        valid_articles = [
            a for a in self.articles 
            if a.publication_epoch <= epoch and (epoch - a.publication_epoch) <= self.memory_window_seconds
            and (currency is None or a.currency.upper() == currency.upper() or a.currency.upper() == "USD")
        ]

        if not valid_articles:
            return {
                "news_sentiment": 0.0,
                "news_uncertainty": 0.0,
                "news_severity": 0.0,
                "news_article_count": 0
            }

        # Weight by recency (exponential decay)
        weights = []
        sentiments = []
        uncertainties = []
        severities = []

        for a in valid_articles:
            dt = epoch - a.publication_epoch
            w = np.exp(-dt / (self.memory_window_seconds / 2.0))
            weights.append(w)
            sentiments.append(a.sentiment_score * w)
            uncertainties.append(a.uncertainty_score * w)
            severities.append(a.severity_score * w)

        sum_w = sum(weights) + 1e-9
        return {
            "news_sentiment": float(np.clip(sum(sentiments) / sum_w, -1.0, 1.0)),
            "news_uncertainty": float(np.clip(sum(uncertainties) / sum_w, 0.0, 1.0)),
            "news_severity": float(np.clip(sum(severities) / sum_w, 0.0, 1.0)),
            "news_article_count": len(valid_articles)
        }

    def add_news_features(self, df: pd.DataFrame, currency: Optional[str] = None) -> pd.DataFrame:
        sentiments = []
        uncertainties = []
        severities = []
        counts = []

        for epoch in df["epoch"]:
            ctx = self.get_sentiment_at_epoch(int(epoch), currency=currency)
            sentiments.append(ctx["news_sentiment"])
            uncertainties.append(ctx["news_uncertainty"])
            severities.append(ctx["news_severity"])
            counts.append(ctx["news_article_count"])

        df["news_sentiment"] = sentiments
        df["news_uncertainty"] = uncertainties
        df["news_severity"] = severities
        df["news_article_count"] = counts
        return df
