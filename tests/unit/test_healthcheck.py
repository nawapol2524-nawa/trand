"""
Unit tests for Railway & Container Healthcheck Verification Service.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from src.services.healthcheck import run_healthcheck


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    return tmp_path


def test_healthcheck_missing_file(tmp_state: Path):
    res = run_healthcheck(state_dir=str(tmp_state))
    assert res == 1


def test_healthcheck_healthy(tmp_state: Path):
    now_str = datetime.now(tz=timezone.utc).isoformat()
    health_payload = {
        "alive": True,
        "status": "HEALTHY",
        "last_heartbeat": now_str,
        "uptime_seconds": 120.0,
        "broker_connected": True,
    }
    (tmp_state / "health.json").write_text(json.dumps(health_payload), encoding="utf-8")
    bot_state_payload = {
        "open_positions": {},
        "daily_starting_balance": 10000.0,
    }
    (tmp_state / "bot_state.json").write_text(json.dumps(bot_state_payload), encoding="utf-8")

    res = run_healthcheck(state_dir=str(tmp_state))
    assert res == 0


def test_healthcheck_stale_heartbeat(tmp_state: Path):
    old_time = (datetime.now(tz=timezone.utc) - timedelta(seconds=120)).isoformat()
    health_payload = {
        "alive": True,
        "status": "HEALTHY",
        "last_heartbeat": old_time,
        "uptime_seconds": 300.0,
        "broker_connected": True,
    }
    (tmp_state / "health.json").write_text(json.dumps(health_payload), encoding="utf-8")

    res = run_healthcheck(state_dir=str(tmp_state), max_stale_seconds=60.0)
    assert res == 1


def test_healthcheck_not_alive(tmp_state: Path):
    now_str = datetime.now(tz=timezone.utc).isoformat()
    health_payload = {
        "alive": False,
        "status": "STOPPED",
        "last_heartbeat": now_str,
        "uptime_seconds": 10.0,
    }
    (tmp_state / "health.json").write_text(json.dumps(health_payload), encoding="utf-8")

    res = run_healthcheck(state_dir=str(tmp_state))
    assert res == 1


def test_healthcheck_unrecoverable_disconnect(tmp_state: Path):
    now_str = datetime.now(tz=timezone.utc).isoformat()
    health_payload = {
        "alive": True,
        "status": "DEGRADED_BROKER_DISCONNECTED",
        "last_heartbeat": now_str,
        "uptime_seconds": 300.0,
        "broker_connected": False,
    }
    (tmp_state / "health.json").write_text(json.dumps(health_payload), encoding="utf-8")

    res = run_healthcheck(state_dir=str(tmp_state), max_disconnect_seconds=180.0)
    assert res == 1


def test_healthcheck_transient_disconnect_allowed(tmp_state: Path):
    now_str = datetime.now(tz=timezone.utc).isoformat()
    health_payload = {
        "alive": True,
        "status": "DEGRADED_BROKER_DISCONNECTED",
        "last_heartbeat": now_str,
        "uptime_seconds": 30.0,  # Startup or transient < 180s
        "broker_connected": False,
    }
    (tmp_state / "health.json").write_text(json.dumps(health_payload), encoding="utf-8")

    res = run_healthcheck(state_dir=str(tmp_state), max_disconnect_seconds=180.0)
    assert res == 0
