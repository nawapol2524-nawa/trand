"""
Trading Bot Entry Point — 24/7 Production Runner.
Usage: python -m src.app.main

SAFETY RULES:
- Default mode is PAPER.
- DEMO mode runs against Deriv cTrader Demo account.
- LIVE mode requires BOTH:
    TRADING_MODE=LIVE
    LIVE_TRADING_ENABLED=true
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.app.runner import TradingBotRunner
from src.brokers.ctrader_mcp import CTraderMCPBroker
from src.core.risk import RiskEngine
from src.services.monitor import OperationalMonitor
from src.services.state_manager import StateManager


def _check_trading_mode() -> str:
    """Enforce trading mode safety — LIVE requires explicit double-opt-in."""
    mode = os.environ.get("TRADING_MODE", "PAPER").upper().strip()
    if mode == "LIVE":
        live_enabled = os.environ.get("LIVE_TRADING_ENABLED", "false").strip().lower()
        if live_enabled != "true":
            _log("LIVE_BLOCKED", {
                "reason": "TRADING_MODE=LIVE but LIVE_TRADING_ENABLED is not 'true'",
                "action": "Forcing PAPER mode for safety",
            }, level="critical")
            return "PAPER"
    return mode


def _log(event: str, data: dict, level: str = "info") -> None:
    record = {"event": event, "ts": datetime.now(tz=timezone.utc).isoformat()}
    record.update(data)
    getattr(logging, level)(json.dumps(record))


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        stream=sys.stdout,
    )


_shutdown = asyncio.Event()


def _handle_signal(sig: int, _frame) -> None:  # type: ignore[type-arg]
    _log("SHUTDOWN_SIGNAL", {"signal": sig})
    _shutdown.set()


async def main() -> None:
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    mode = _check_trading_mode()

    _log("BOT_STARTING", {
        "trading_mode": mode,
        "python": sys.version,
    })

    # Register SIGTERM / SIGINT for graceful shutdown
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _handle_signal)

    # Initialize Core Services
    broker = CTraderMCPBroker()
    risk_engine = RiskEngine()
    state_mgr = StateManager()
    monitor = OperationalMonitor()

    runner = TradingBotRunner(
        broker=broker,
        risk_engine=risk_engine,
        state_manager=state_mgr,
        monitor=monitor,
    )

    # Wire runner shutdown with global signal
    async def monitor_shutdown():
        await _shutdown.wait()
        runner.stop()

    shutdown_task = asyncio.create_task(monitor_shutdown())

    try:
        if mode == "DEMO":
            _log("RUNNER_START", {"mode": "DEMO", "action": "Starting 24/7 cTrader Demo loop"})
            await runner.run_forever(cycle_interval_seconds=float(os.environ.get("CYCLE_INTERVAL", "5.0")))
        else:
            _log("RUNNER_START", {"mode": mode, "action": "Running in PAPER simulation loop"})
            # In paper mode, run simulation cycles
            while not _shutdown.is_set():
                await asyncio.sleep(1)
    finally:
        shutdown_task.cancel()
        _log("BOT_STOPPED", {"mode": mode})
        monitor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
