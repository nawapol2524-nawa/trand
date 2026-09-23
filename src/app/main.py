"""
Trading Bot entry point.
Usage: python -m src.app.main

SAFETY RULE: Default mode is PAPER.
LIVE requires BOTH:
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

    # Phase 0 HARD GATE — broker not yet verified
    if mode in ("LIVE", "DEMO"):
        _log("BROKER_GATE", {
            "status": "BLOCKED",
            "reason": "Phase 0 broker verification not yet complete",
            "action": "Running in PAPER mode until credentials verified",
        }, level="warning")
        mode = "PAPER"

    # Write health file (checked by Docker HEALTHCHECK)
    state_dir = Path(os.environ.get("STATE_DIR", "./state"))
    state_dir.mkdir(parents=True, exist_ok=True)
    health_path = state_dir / "health.json"
    health_path.write_text(json.dumps({
        "alive": True,
        "mode": mode,
        "started": datetime.now(tz=timezone.utc).isoformat(),
        "status": "SCAFFOLD_ONLY",
    }))

    _log("BOT_RUNNING", {
        "mode": mode,
        "status": "SCAFFOLD — strategies and broker not yet wired",
    })

    # Main loop (placeholder — will be replaced with full event loop)
    while not _shutdown.is_set():
        await asyncio.sleep(1)

    _log("BOT_STOPPED", {"mode": mode})
    health_path.write_text(json.dumps({"alive": False}))


if __name__ == "__main__":
    asyncio.run(main())
