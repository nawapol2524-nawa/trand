"""
High-Performance Zero-Dependency Webboard Server.
Serves static assets, JSON REST API, and Server-Sent Events (SSE) live stream
with zero UI flicker and instant real-time synchronization.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Optional

from webboard.data_aggregator import DataAggregator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("webboard_server")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class WebboardRequestHandler(SimpleHTTPRequestHandler):
    """Handles static web assets, REST endpoints, and SSE stream."""

    aggregator: DataAggregator = None
    static_dir: Path = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.static_dir), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy GET log spam for streaming endpoints
        if "/api/status" in args[0] or "/api/stream" in args[0]:
            return
        logger.info("%s - %s", self.address_string(), format % args)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")

        if path in ("", "/"):
            self.path = "/index.html"
            return super().do_GET()

        # REST API Routes
        if path == "/api/status":
            self._handle_api_status()
            return

        if path == "/api/news":
            self._handle_api_news()
            return

        if path == "/api/trades":
            self._handle_api_trades()
            return

        if path == "/api/weekly-report":
            self._handle_api_weekly_report()
            return

        # Server-Sent Events (SSE) Live Real-Time Stream
        if path == "/api/stream":
            self._handle_sse_stream()
            return

        # Fallback to static file handler (app.js, styles.css, etc.)
        return super().do_GET()

    def _handle_api_status(self) -> None:
        try:
            snapshot = self.aggregator.get_full_snapshot()
            body = json.dumps(snapshot, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            logger.exception("Error generating status API response")
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

    def _handle_api_news(self) -> None:
        try:
            news = self.aggregator.news_service.evaluate_news_state()
            body = json.dumps(news, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

    def _handle_api_trades(self) -> None:
        try:
            snapshot = self.aggregator.get_full_snapshot()
            forex_trades = snapshot["forex_gold"].get("closed_trades_history", [])
            deriv_trades = snapshot["deriv_synthetic"].get("recent_trades", [])
            body = json.dumps({"forex_gold": forex_trades, "deriv_synthetic": deriv_trades}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

    def _handle_api_weekly_report(self) -> None:
        try:
            report = self.aggregator.get_weekly_report()
            body = json.dumps(report, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            logger.exception("Error generating weekly report")
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

    def _handle_sse_stream(self) -> None:
        """Streams live SSE updates with zero client polling jitter."""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            while True:
                snapshot = self.aggregator.get_full_snapshot()
                data_str = json.dumps(snapshot)
                msg = f"data: {data_str}\n\n".encode("utf-8")
                self.wfile.write(msg)
                self.wfile.flush()
                time.sleep(1.5)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            logger.debug(f"SSE stream closed: {e}")


def run_server(port: int = 8080, host: str = "0.0.0.0", workspace_root: Optional[str] = None):
    root_path = Path(workspace_root or os.getcwd())
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)

    aggregator = DataAggregator(workspace_root=str(root_path))
    WebboardRequestHandler.aggregator = aggregator
    WebboardRequestHandler.static_dir = static_dir

    server = ThreadedHTTPServer((host, port), WebboardRequestHandler)
    print(f"\n=================================================================")
    print(f"🚀 TRADING BOT UNIFIED WEBBOARD IS ONLINE")
    print(f"   URL: http://localhost:{port} (or http://127.0.0.1:{port})")
    print(f"   Forex & Gold (XAUUSD) + Deriv Multipliers (1HZ90V)")
    print(f"   Zero-Flicker Real-Time Streaming Active")
    print(f"=================================================================\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Webboard server gracefully...")
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port=port_arg)
