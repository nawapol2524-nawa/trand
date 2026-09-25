"""
Operational Monitoring & Observability Service — Phase 5 & 6 requirements.
Maintains live heartbeats, system telemetry, and Docker-compatible health.json.
Hardened with version lineage tracking and thread-safe atomic writes.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.version import SYSTEM_VERSION, get_git_commit_sha

logger = logging.getLogger("OperationalMonitor")


@dataclass
class HealthTelemetry:
    alive: bool = True
    status: str = "INITIALIZING"        # HEALTHY, DEGRADED, HALTED, STOPPED
    mode: str = "DEMO"
    system_version: str = f"v{SYSTEM_VERSION}"
    git_commit: str = ""
    started_at: str = ""
    last_heartbeat: str = ""
    uptime_seconds: float = 0.0
    broker_connected: bool = False
    broker_latency_ms: float = 0.0
    ai_status: str = "UNKNOWN"          # HEALTHY, OFFLINE_FALLBACK, ERROR
    open_positions: int = 0
    trade_count_today: int = 0
    daily_pnl_usd: float = 0.0
    daily_pnl_pct: float = 0.0
    consecutive_losses: int = 0
    kill_switch_active: bool = False
    data_freshness_seconds: float = 0.0
    reconnect_count: int = 0
    uncaught_exceptions: int = 0
    restart_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class OperationalMonitor:
    """Manages system health, heartbeats, and metrics for 24/7 operations."""

    def __init__(self, state_dir: Optional[str] = None):
        self.state_dir = Path(state_dir or os.environ.get("STATE_DIR", "./state"))
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.health_file = self.state_dir / "health.json"
        self._lock = threading.Lock()
        self._start_time = time.time()
        self.telemetry = HealthTelemetry(
            system_version=f"v{SYSTEM_VERSION}",
            git_commit=get_git_commit_sha(),
            started_at=datetime.now(tz=timezone.utc).isoformat(),
            last_heartbeat=datetime.now(tz=timezone.utc).isoformat(),
        )
        self.update_health()

    def record_heartbeat(
        self,
        broker_connected: bool,
        open_positions: int,
        daily_pnl: float,
        daily_pnl_pct: float,
        consecutive_losses: int,
        kill_switch_active: bool,
        ai_status: str = "HEALTHY",
        broker_latency_ms: float = 0.0,
        data_freshness_seconds: float = 0.0,
    ) -> None:
        """Update live telemetry metrics on each execution cycle."""
        now_utc = datetime.now(tz=timezone.utc)
        self.telemetry.last_heartbeat = now_utc.isoformat()
        self.telemetry.uptime_seconds = round(time.time() - self._start_time, 1)
        self.telemetry.broker_connected = broker_connected
        self.telemetry.broker_latency_ms = round(broker_latency_ms, 2)
        self.telemetry.ai_status = ai_status
        self.telemetry.open_positions = open_positions
        self.telemetry.daily_pnl_usd = round(daily_pnl, 2)
        self.telemetry.daily_pnl_pct = round(daily_pnl_pct, 4)
        self.telemetry.consecutive_losses = consecutive_losses
        self.telemetry.kill_switch_active = kill_switch_active
        self.telemetry.data_freshness_seconds = round(data_freshness_seconds, 1)
        if not self.telemetry.git_commit or self.telemetry.git_commit == "unknown":
            self.telemetry.git_commit = get_git_commit_sha()

        # Determine overall status
        if kill_switch_active:
            self.telemetry.status = "HALTED_KILL_SWITCH"
        elif consecutive_losses >= 5:
            self.telemetry.status = "HALTED_CONSECUTIVE_LOSSES"
        elif not broker_connected:
            self.telemetry.status = "DEGRADED_BROKER_DISCONNECTED"
        elif ai_status == "ERROR":
            self.telemetry.status = "DEGRADED_AI_ERROR"
        else:
            self.telemetry.status = "HEALTHY"

        self.update_health()

    def record_reconnect(self) -> None:
        self.telemetry.reconnect_count += 1
        self.update_health()

    def record_exception(self) -> None:
        self.telemetry.uncaught_exceptions += 1
        self.update_health()

    def update_health(self) -> None:
        """Thread-safe atomic write to health.json using unique temporary file."""
        with self._lock:
            unique_tmp = self.health_file.with_name(f"health_{uuid.uuid4().hex[:8]}.tmp")
            try:
                unique_tmp.write_text(json.dumps(asdict(self.telemetry), indent=2), encoding="utf-8")
                unique_tmp.replace(self.health_file)
            except Exception as e:
                logger.warning("Failed to update health file: %s", e)
            finally:
                if unique_tmp.exists():
                    try:
                        unique_tmp.unlink(missing_ok=True)
                    except Exception:
                        pass

    def shutdown(self) -> None:
        self.telemetry.alive = False
        self.telemetry.status = "STOPPED"
        self.update_health()
