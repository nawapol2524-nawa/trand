"""
Unit Tests for Unified Webboard, Data Aggregator, and News Service.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from webboard.news_service import NewsService
from webboard.data_aggregator import DataAggregator


class TestNewsService:
    def test_news_service_events(self):
        service = NewsService()
        events = service.get_upcoming_events()
        assert len(events) > 0
        for e in events:
            assert e.currency in ("USD", "EUR", "GBP")
            assert e.impact in ("HIGH", "MEDIUM", "LOW")
            assert e.title != ""

    def test_news_state_evaluation(self):
        service = NewsService()
        state = service.evaluate_news_state()
        assert "high_impact_soon" in state
        assert "blackout_active" in state
        assert "upcoming_events" in state
        assert isinstance(state["upcoming_events"], list)
        assert len(state["upcoming_events"]) > 0


class TestDataAggregator:
    def test_data_aggregator_snapshot(self):
        workspace_root = str(Path(__file__).resolve().parent.parent)
        aggregator = DataAggregator(workspace_root=workspace_root)
        snapshot = aggregator.get_full_snapshot()

        assert "portfolio" in snapshot
        assert "forex_gold" in snapshot
        assert "deriv_synthetic" in snapshot
        assert "ai_brain" in snapshot
        assert "news" in snapshot

        port = snapshot["portfolio"]
        assert port["total_balance_usd"] > 0
        assert "total_daily_pnl_usd" in port

        forex = snapshot["forex_gold"]
        assert forex["symbol"] == "XAUUSD"
        assert forex["capital"]["current_balance"] > 0
        assert forex["market_status"]["spot_price"] > 0

        deriv = snapshot["deriv_synthetic"]
        assert deriv["symbol"] == "1HZ90V"
        assert deriv["capital"]["current_balance"] > 0
        assert deriv["capital"]["stake_usd"] == 10.0


class TestWebboardServer:
    def test_handler_api_status(self):
        import io
        from unittest.mock import MagicMock
        from webboard.server import WebboardRequestHandler

        handler = WebboardRequestHandler.__new__(WebboardRequestHandler)
        workspace_root = str(Path(__file__).resolve().parent.parent)
        handler.aggregator = DataAggregator(workspace_root=workspace_root)
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler._handle_api_status()
        handler.wfile.seek(0)
        data = json.loads(handler.wfile.read().decode())
        assert "portfolio" in data
        assert "forex_gold" in data
        assert "news" in data

    def test_handler_api_news(self):
        import io
        from unittest.mock import MagicMock
        from webboard.server import WebboardRequestHandler

        handler = WebboardRequestHandler.__new__(WebboardRequestHandler)
        workspace_root = str(Path(__file__).resolve().parent.parent)
        handler.aggregator = DataAggregator(workspace_root=workspace_root)
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler._handle_api_news()
        handler.wfile.seek(0)
        data = json.loads(handler.wfile.read().decode())
        assert "upcoming_events" in data
        assert "blackout_active" in data

    def test_get_weekly_report(self):
        workspace_root = str(Path(__file__).resolve().parent.parent)
        aggregator = DataAggregator(workspace_root=workspace_root)
        report = aggregator.get_weekly_report()

        assert "weekly_performance" in report
        assert "cumulative_stats" in report
        assert "execution_audit" in report
        assert "market_context" in report
        assert "formatted_markdown" in report

        wp = report["weekly_performance"]
        assert wp["trades_count"] > 0
        assert "win_rate_pct" in wp
        assert "net_pnl_usd" in wp

        cs = report["cumulative_stats"]
        assert cs["trades_count"] > 0
        assert cs["profit_factor"] > 0

        ea = report["execution_audit"]
        assert ea["sl_tp_integrity"]["status"] == "PASS"
        assert ea["cooldown_check"]["status"] == "PASS"

    def test_handler_api_weekly_report(self):
        import io
        from unittest.mock import MagicMock
        from webboard.server import WebboardRequestHandler

        handler = WebboardRequestHandler.__new__(WebboardRequestHandler)
        workspace_root = str(Path(__file__).resolve().parent.parent)
        handler.aggregator = DataAggregator(workspace_root=workspace_root)
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler._handle_api_weekly_report()
        handler.wfile.seek(0)
        data = json.loads(handler.wfile.read().decode())
        assert "weekly_performance" in data
        assert "formatted_markdown" in data


