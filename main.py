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
from ai_forex_bot.monitoring.console import ConsoleUI
from scripts.run_production_daemon import ProductionDaemonSupervisor


def print_banner(symbol: str, timeframe: str, strategy: str, single_cycle: bool, heartbeat_interval: float = 60.0):
    symbols_list = [s.strip() for s in symbol.split(",") if s.strip()]
    ConsoleUI.print_startup_banner(
        symbols=symbols_list,
        timeframe=timeframe,
        strategy=strategy,
        single_cycle=single_cycle,
        live_trading=settings.live_trading,
        auto_promotion=settings.auto_promotion,
        model_id=os.getenv("MODEL_ID", "candidate_r75_M15"),
        heartbeat_interval=heartbeat_interval
    )
def clean_system_disk_cache():
    """Frees up disk space on constrained VPS containers (bot-hosting.net) by removing caches."""
    import shutil
    cleaned_bytes = 0
    # Clean ~/.cache (pip wheel cache can consume 150-250MB)
    cache_dir = Path.home() / ".cache"
    if cache_dir.exists():
        try:
            for f in cache_dir.glob("**/*"):
                if f.is_file():
                    cleaned_bytes += f.stat().st_size
            shutil.rmtree(cache_dir, ignore_errors=True)
        except Exception:
            pass
    # Clean temporary pip and test caches in /tmp
    tmp_dir = Path("/tmp")
    if tmp_dir.exists():
        for p in tmp_dir.glob("pip*"):
            try:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
            except Exception:
                pass
    if cleaned_bytes > 500_000:
        print(f"[DISK-CLEANER] Auto-purged {cleaned_bytes / (1024 * 1024):.1f} MB of temporary build caches.")


def auto_git_pull():
    """Auto-sync latest updates from git on startup if in git repo."""
    try:
        import subprocess
        res = subprocess.run(["git", "pull", "--ff-only"], capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            if "Already up to date" not in res.stdout:
                print(f"[AUTO-UPDATE] Pulled latest updates from GitHub:\n{res.stdout.strip()}")
            else:
                print("[AUTO-UPDATE] Verified: Codebase is up-to-date with GitHub.")
    except Exception:
        pass


def main():
    # Automatically pull latest updates on boot
    auto_git_pull()

    # Automatically ensure disk cleanliness on constrained environments
    clean_system_disk_cache()

    # Read environment variables with fallback
    env_symbol = os.getenv("SYMBOL", "R_25,R_10,R_75")
    env_timeframe = os.getenv("TIMEFRAME", "M1")
    env_strategy = os.getenv("STRATEGY", "double_barrel")
    env_heartbeat = float(os.getenv("HEARTBEAT_INTERVAL", "60.0"))
    env_retrain = float(os.getenv("RETRAIN_INTERVAL", "3600.0"))
    env_balance = float(os.getenv("INITIAL_BALANCE", "4.92"))
    env_leverage = float(os.getenv("LEVERAGE", "1000.0"))

    parser = argparse.ArgumentParser(
        description="AI Forex Autonomous Trading System — Production Entrypoint"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=env_symbol,
        help="Trading Symbol(s) (e.g. R_25, R_75, R_10, frxEURUSD, or comma-separated 'R_25,R_10,R_75', or 'ALL')"
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default=env_timeframe,
        help="Timeframe (e.g. M15)"
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default=env_strategy,
        help="Execution Strategy (e.g. double_barrel)"
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=env_heartbeat,
        help="Heartbeat interval in seconds"
    )
    parser.add_argument(
        "--retrain-interval",
        type=float,
        default=env_retrain,
        help="Retrain check interval in seconds"
    )
    parser.add_argument(
        "--single-cycle",
        action="store_true",
        help="Execute one single supervision cycle and exit (test mode)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify configuration and exit without running loops"
    )
    parser.add_argument(
        "--balance",
        type=float,
        default=env_balance,
        help="Initial wallet balance in USDT (default: 4.92)"
    )
    parser.add_argument(
        "--leverage",
        type=float,
        default=env_leverage,
        help="Broker leverage ratio (default: 1000.0)"
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        default=os.getenv("RESET_STATE", "false").lower() in ("true", "1", "yes"),
        help="Reset portfolio state to clean initial balance"
    )

    args = parser.parse_args()

    print_banner(args.symbol, args.timeframe, args.strategy, args.single_cycle, args.heartbeat_interval)

    if args.dry_run:
        print("[MAIN] Dry-run completed. System is ready for execution.")
        sys.exit(0)

    # Initialize Daemon Supervisor
    supervisor = ProductionDaemonSupervisor(
        symbol=args.symbol,
        timeframe=args.timeframe,
        strategy=args.strategy,
        heartbeat_interval=args.heartbeat_interval,
        retrain_interval=args.retrain_interval,
        restore_state=not args.reset_state,
        initial_balance=args.balance,
        leverage=args.leverage,
        reset_state=args.reset_state
    )

    # Signal handlers for container lifecycle
    def _term_handler(signum, frame):
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\n[MAIN] Received {sig_name} from host. Stopping daemon cleanly...")
        sys.stdout.flush()
        supervisor.shutdown(reason=f"HOST_{sig_name}")
        sys.exit(0)

    signal.signal(signal.SIGINT, _term_handler)
    signal.signal(signal.SIGTERM, _term_handler)

    exit_code = supervisor.run(single_cycle=args.single_cycle, show_banner=False)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
