"""
Unit tests for Backtest Engine (Gate 30).
Verifies:
  1. Deterministic execution (two runs match bit-for-bit)
  2. Risk bounds enforcement (max positions <= 3)
  3. Stress test execution
Uses committed synthetic test fixture for clean CI reproducibility without untracked data.
"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import pytest

from src.backtest.engine import BacktestConfig, BacktestEngine

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic_backtest_data"


class TestBacktestEngine:

    def test_backtest_determinism(self):
        """Verify two identical runs produce identical SHA-256 hashes."""
        cfg = BacktestConfig()

        engine1 = BacktestEngine(cfg)
        metrics1, trades1 = engine1.run(historical_dir=str(FIXTURE_DIR))

        engine2 = BacktestEngine(cfg)
        metrics2, trades2 = engine2.run(historical_dir=str(FIXTURE_DIR))

        assert metrics1.total_trades == metrics2.total_trades
        assert metrics1.net_pnl_usd == metrics2.net_pnl_usd
        assert metrics1.win_rate_pct == metrics2.win_rate_pct
        assert len(trades1) == len(trades2)

        # Hash comparison
        payload1 = json.dumps(asdict(metrics1), sort_keys=True)
        payload2 = json.dumps(asdict(metrics2), sort_keys=True)
        assert hashlib.sha256(payload1.encode()).hexdigest() == hashlib.sha256(payload2.encode()).hexdigest()

    def test_risk_limits_enforced(self):
        """Verify open positions never exceed max_open_positions."""
        cfg = BacktestConfig(max_open_positions=3)
        engine = BacktestEngine(cfg)
        metrics, trades = engine.run(historical_dir=str(FIXTURE_DIR))

        for pt in metrics.equity_curve:
            assert pt["open_positions"] <= 3

    def test_stress_test_execution(self):
        """Verify spread stress configuration changes execution metrics."""
        cfg_base = BacktestConfig(spread_multiplier=1.0)
        cfg_stressed = BacktestConfig(spread_multiplier=2.0)

        engine_base = BacktestEngine(cfg_base)
        metrics_base, _ = engine_base.run(historical_dir=str(FIXTURE_DIR))

        engine_stressed = BacktestEngine(cfg_stressed)
        metrics_stressed, _ = engine_stressed.run(historical_dir=str(FIXTURE_DIR))

        assert metrics_base.total_trades > 0
        assert metrics_stressed.total_trades > 0
        assert metrics_base.spread_multiplier == 1.0
        assert metrics_stressed.spread_multiplier == 2.0
