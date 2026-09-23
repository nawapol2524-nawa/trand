"""
Railway & Container Healthcheck Verification Service.
Evaluates state/health.json and state/bot_state.json for container readiness and liveness.

Exit codes:
  0: HEALTHY (ready and advancing, or recoverable transient degradation)
  1: UNHEALTHY (stale heartbeat, dead app, unrecoverable disconnect, corrupted state)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def run_healthcheck(
    state_dir: str | None = None,
    max_stale_seconds: float = 60.0,
    max_disconnect_seconds: float = 180.0,
) -> int:
    state_path = Path(state_dir or os.environ.get("STATE_DIR", "./state"))
    health_file = state_path / "health.json"
    bot_state_file = state_path / "bot_state.json"

    # 1. Application dead or health state not created
    if not health_file.exists():
        sys.stderr.write("HEALTHCHECK_FAIL: health.json does not exist (daemon not initialized)\n")
        return 1

    try:
        health_data = json.loads(health_file.read_text(encoding="utf-8"))
    except Exception as e:
        sys.stderr.write(f"HEALTHCHECK_FAIL: health.json malformed: {e}\n")
        return 1

    # 2. Application explicitly stopped or dead
    if not health_data.get("alive", False):
        sys.stderr.write("HEALTHCHECK_FAIL: Application marked alive=False\n")
        return 1

    status = str(health_data.get("status", "UNKNOWN"))
    if status in ("STOPPED", "CRITICAL", "FATAL"):
        sys.stderr.write(f"HEALTHCHECK_FAIL: Fatal status reported: {status}\n")
        return 1

    # 3. Heartbeat staleness check (detects frozen/deadlocked event loop)
    last_hb_str = health_data.get("last_heartbeat")
    if not last_hb_str:
        sys.stderr.write("HEALTHCHECK_FAIL: Missing last_heartbeat timestamp\n")
        return 1

    try:
        last_hb = datetime.fromisoformat(last_hb_str)
        now_utc = datetime.now(tz=timezone.utc)
        delta_seconds = (now_utc - last_hb).total_seconds()
        if delta_seconds > max_stale_seconds:
            sys.stderr.write(f"HEALTHCHECK_FAIL: Stale heartbeat ({delta_seconds:.1f}s > {max_stale_seconds}s)\n")
            return 1
    except Exception as e:
        sys.stderr.write(f"HEALTHCHECK_FAIL: Invalid timestamp format in heartbeat: {e}\n")
        return 1

    # 4. Unrecoverable broker disconnect check
    broker_connected = health_data.get("broker_connected", False)
    if not broker_connected:
        uptime = float(health_data.get("uptime_seconds", 0.0))
        # If disconnected and past initial grace period, report unhealthy
        if uptime > max_disconnect_seconds:
            sys.stderr.write(
                f"HEALTHCHECK_FAIL: Broker disconnected unrecoverably (uptime={uptime:.1f}s > {max_disconnect_seconds}s)\n"
            )
            return 1

    # 5. Persistent state consistency check
    if bot_state_file.exists():
        try:
            bot_state = json.loads(bot_state_file.read_text(encoding="utf-8"))
            if not isinstance(bot_state.get("open_positions"), dict):
                sys.stderr.write("HEALTHCHECK_FAIL: bot_state.json corrupted: open_positions is not a dict\n")
                return 1
            if float(bot_state.get("daily_starting_balance", 0.0)) <= 0:
                sys.stderr.write("HEALTHCHECK_FAIL: bot_state.json corrupted: daily_starting_balance <= 0\n")
                return 1
        except Exception as e:
            sys.stderr.write(f"HEALTHCHECK_FAIL: bot_state.json corrupted: {e}\n")
            return 1

    return 0


if __name__ == "__main__":
    stale_sec = float(os.environ.get("HEALTHCHECK_MAX_STALE_SECONDS", "60.0"))
    disconnect_sec = float(os.environ.get("HEALTHCHECK_MAX_DISCONNECT_SECONDS", "180.0"))
    sys.exit(run_healthcheck(max_stale_seconds=stale_sec, max_disconnect_seconds=disconnect_sec))
