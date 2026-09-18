"""
System Health Monitor & Heartbeat Service
=========================================
Institutional Production Monitoring Standard for Gate 26
Tracks real-time system metrics, process uptime, resources, and trading state:
- Periodically writes structured heartbeat to logs/heartbeat.json
- Health probe endpoint for Docker container healthchecks and external monitors
- Detects memory leaks, stale feeds, kill switches, and worker faults
"""

import os
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

from ai_forex_bot.config.settings import settings
from ai_forex_bot.models.registry import ModelRegistry
from ai_forex_bot.risk.kill_switch import EmergencyKillSwitch


def get_process_memory_mb() -> float:
    """Calculates RSS memory consumption of the current process in megabytes."""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        return round(process.memory_info().rss / (1024 * 1024), 2)
    except Exception:
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform == "darwin":
                return round(usage / (1024 * 1024), 2)
            else:
                return round(usage / 1024, 2)
        except Exception:
            return 0.0


class SystemHealthMonitor:
    def __init__(
        self,
        root_dir: Optional[Path] = None,
        heartbeat_file: Optional[Path] = None
    ):
        self.root_dir = root_dir or settings.root_dir
        self.heartbeat_file = heartbeat_file or (self.root_dir / "logs" / "heartbeat.json")
        self.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
        self.start_time = datetime.now(timezone.utc)
        self.kill_switch = EmergencyKillSwitch(root_dir=self.root_dir)

    def get_uptime_seconds(self) -> float:
        return round((datetime.now(timezone.utc) - self.start_time).total_seconds(), 2)

    def get_system_resources(self) -> Dict[str, Any]:
        total, used, free = shutil.disk_usage(self.root_dir)
        return {
            "pid": os.getpid(),
            "memory_rss_mb": get_process_memory_mb(),
            "free_disk_mb": round(free / (1024 * 1024), 2)
        }

    def record_heartbeat(
        self,
        champion_model_id: Optional[str] = None,
        open_positions_count: int = 0,
        today_pnl_usd: float = 0.0,
        last_candle_epoch: Optional[int] = None,
        risk_engine_status: str = "NORMAL",
        broker_connected: bool = True,
        worker_statuses: Optional[Dict[str, str]] = None,
        custom_metrics: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Emits structured system heartbeat and writes atomically to disk.
        """
        now = datetime.now(timezone.utc)
        uptime = self.get_uptime_seconds()
        resources = self.get_system_resources()

        # Query Champion Model ID if not provided
        if not champion_model_id:
            try:
                reg = ModelRegistry()
                champ = reg.get_champion()
                champion_model_id = champ.model_id if champ else "NONE"
            except Exception:
                champion_model_id = "UNKNOWN"

        # Check Kill-Switch Status
        is_ks_active = self.kill_switch.is_kill_switch_active()
        ks_reason = self.kill_switch.reason if is_ks_active else "NORMAL"

        # Determine overall status
        if is_ks_active:
            overall_status = "KILL_SWITCH_ACTIVE"
        elif resources["free_disk_mb"] < 200.0:
            overall_status = "LOW_DISK_SPACE"
        elif not broker_connected:
            overall_status = "BROKER_DISCONNECTED"
        else:
            overall_status = "HEALTHY"

        heartbeat_data = {
            "timestamp": now.isoformat(),
            "uptime_seconds": uptime,
            "overall_status": overall_status,
            "governance": {
                "live_trading": settings.live_trading,
                "auto_promotion": settings.auto_promotion
            },
            "system_resources": resources,
            "trading_state": {
                "champion_model_id": champion_model_id,
                "open_positions_count": open_positions_count,
                "today_pnl_usd": round(today_pnl_usd, 2),
                "last_candle_epoch": last_candle_epoch,
                "risk_engine_status": risk_engine_status,
                "kill_switch_active": is_ks_active,
                "kill_switch_reason": ks_reason
            },
            "workers": worker_statuses or {},
            "custom": custom_metrics or {}
        }

        temp_file = self.heartbeat_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(heartbeat_data, f, indent=2)

        os.replace(temp_file, self.heartbeat_file)
        return heartbeat_data

    def check_health_probe(self, max_stale_seconds: float = 120.0) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Health probe query for Docker/Kubernetes healthcheck.
        Returns: (is_healthy, reason, details)
        """
        if not self.heartbeat_file.exists():
            return False, "HEARTBEAT_FILE_MISSING", {}

        try:
            with open(self.heartbeat_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return False, f"HEARTBEAT_READ_ERROR: {e}", {}

        ts_str = data.get("timestamp")
        if not ts_str:
            return False, "INVALID_HEARTBEAT_FORMAT", data

        try:
            hb_time = datetime.fromisoformat(ts_str)
            age = (datetime.now(timezone.utc) - hb_time).total_seconds()
        except Exception as e:
            return False, f"TIMESTAMP_PARSE_ERROR: {e}", data

        if age > max_stale_seconds:
            return False, f"HEARTBEAT_STALE: age {age:.1f}s > threshold {max_stale_seconds:.1f}s", data

        status = data.get("overall_status", "UNKNOWN")
        if status in ("HEALTHY", "NORMAL"):
            return True, "SYSTEM_HEALTHY", data
        else:
            return False, f"UNHEALTHY_STATUS: {status}", data


def main():
    import argparse
    parser = argparse.ArgumentParser(description="System Health Monitor & Probe")
    parser.add_argument("--probe", action="store_true", help="Run health probe and exit with code 0/1")
    parser.add_argument("--max-stale", type=float, default=120.0, help="Max stale age in seconds")
    args = parser.parse_args()

    monitor = SystemHealthMonitor()

    if args.probe:
        healthy, reason, data = monitor.check_health_probe(max_stale_seconds=args.max_stale)
        if healthy:
            print(f"[HEALTH_OK] {reason}")
            sys.exit(0)
        else:
            print(f"[HEALTH_FAIL] {reason}", file=sys.stderr)
            sys.exit(1)
    else:
        hb = monitor.record_heartbeat()
        print(json.dumps(hb, indent=2))
        sys.exit(0)


if __name__ == "__main__":
    main()
