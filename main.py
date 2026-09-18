#!/usr/bin/env python3
"""
AI Forex Autonomous Trading System — Universal Production Entrypoint
===================================================================
Optimized for 24/7 Cloud VPS & Pterodactyl Hosting (bot-hosting.net):
- Seamless startup via standard `python3 main.py`
- Instantiates and supervises ProductionDaemonSupervisor
- Handles process lifecycle & SIGINT / SIGTERM graceful shutdown
- Enforces strict safety rules: LIVE_TRADING = false by default
"""

import os
import sys
import signal
import argparse
from pathlib import Path

# Set workspace root into sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(WORKSPACE_ROOT))

from ai_forex_bot.config.settings import settings
from scripts.run_production_daemon import ProductionDaemonSupervisor


def print_banner(symbol: str, timeframe: str, single_cycle: bool):
    print("=" * 80)
    print("  🚀 AI FOREX AUTONOMOUS TRADING BOT — PRODUCTION ENTRYPOINT")
    print("=" * 80)
    print(f"  Target Symbol       : {symbol}")
    print(f"  Execution Timeframe : {timeframe}")
    print(f"  Trading Mode        : PAPER / SHADOW SIMULATION")
    print(f"  Live Trading Gate   : LIVE_TRADING = {str(settings.live_trading).lower()} (STRICT FINANCIAL SAFETY)")
    print(f"  Auto Promotion Gate : AUTO_PROMOTION = {str(settings.auto_promotion).lower()}")
    print(f"  Supervisor Mode     : {'SINGLE-CYCLE TEST' if single_cycle else '24/7 CONTINUOUS DAEMON'}")
    print("=" * 80)
    sys.stdout.flush()


def main():
    # Read environment variables with fallback
    env_symbol = os.getenv("SYMBOL", "frxEURUSD")
    env_timeframe = os.getenv("TIMEFRAME", "M15")
    env_heartbeat = float(os.getenv("HEARTBEAT_INTERVAL", "60.0"))
    env_retrain = float(os.getenv("RETRAIN_INTERVAL", "3600.0"))

    parser = argparse.ArgumentParser(
        description="AI Forex Autonomous Trading System — Production Entrypoint"
    )
    parser.add_argument("--symbol", type=str, default=env_symbol, help="Trading Symbol (e.g. frxEURUSD)")
    parser.add_argument("--timeframe", type=str, default=env_timeframe, help="Timeframe (e.g. M15)")
    parser.add_argument("--heartbeat-interval", type=float, default=env_heartbeat, help="Heartbeat interval in seconds")
    parser.add_argument("--retrain-interval", type=float, default=env_retrain, help="Retrain check interval in seconds")
    parser.add_argument("--single-cycle", action="store_true", help="Execute one single supervision cycle and exit (test mode)")
    parser.add_argument("--dry-run", action="store_true", help="Verify configuration and exit without running loops")

    args = parser.parse_args()

    print_banner(args.symbol, args.timeframe, args.single_cycle)

    if args.dry_run:
        print("[MAIN] Dry-run completed. System is ready for execution.")
        sys.exit(0)

    # Initialize Daemon Supervisor
    supervisor = ProductionDaemonSupervisor(
        symbol=args.symbol,
        timeframe=args.timeframe,
        heartbeat_interval=args.heartbeat_interval,
        retrain_interval=args.retrain_interval,
        restore_state=True
    )

    # Signal handlers for Pterodactyl container lifecycle
    def _term_handler(signum, frame):
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\n[MAIN] Received {sig_name} from host. Stopping daemon cleanly...")
        sys.stdout.flush()
        supervisor.shutdown(reason=f"HOST_{sig_name}")
        sys.exit(0)

    signal.signal(signal.SIGINT, _term_handler)
    signal.signal(signal.SIGTERM, _term_handler)

    exit_code = supervisor.run(single_cycle=args.single_cycle)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
