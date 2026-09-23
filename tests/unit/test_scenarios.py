"""
Unit tests for Scenario Engine (Phase H).
Tests: scenario creation, activation, invalidation, completion.
"""
from datetime import datetime, timezone
import pytest

from src.core.scenarios import (
    Scenario,
    ScenarioEngine,
    ScenarioStatus,
    ScenarioType,
)

UTC = timezone.utc


class TestScenarioEngine:

    def test_create_scenario(self):
        engine = ScenarioEngine()
        sc = engine.create_scenario(
            symbol="EURUSD",
            scenario_type=ScenarioType.BULLISH_CONTINUATION,
            time_horizon="M5",
            activation_conditions={"min_price": 1.1450},
            invalidation_conditions={"stop_price": 1.1400},
            notes="Breakout continuation thesis",
        )
        assert sc.symbol == "EURUSD"
        assert sc.status == ScenarioStatus.PLANNED
        assert len(engine.get_active_scenarios("EURUSD")) == 1

    def test_scenario_activation_on_price(self):
        engine = ScenarioEngine()
        sc = engine.create_scenario(
            symbol="EURUSD",
            scenario_type=ScenarioType.BULLISH_CONTINUATION,
            time_horizon="M5",
            activation_conditions={"min_price": 1.1450, "target_price": 1.1500},
            invalidation_conditions={"stop_price": 1.1400},
        )

        # Price below activation -> stays PLANNED
        changed = engine.update_price("EURUSD", 1.1440)
        assert len(changed) == 0
        assert sc.status == ScenarioStatus.PLANNED

        # Price hits min_price -> activates
        changed = engine.update_price("EURUSD", 1.1451)
        assert len(changed) == 1
        assert sc.status == ScenarioStatus.ACTIVE
        assert sc.activated_at is not None

    def test_scenario_invalidation_on_stop(self):
        engine = ScenarioEngine()
        sc = engine.create_scenario(
            symbol="EURUSD",
            scenario_type=ScenarioType.BULLISH_CONTINUATION,
            time_horizon="M5",
            activation_conditions={"min_price": 1.1450},
            invalidation_conditions={"stop_price": 1.1400},
        )
        engine.update_price("EURUSD", 1.1455)  # Activate
        assert sc.status == ScenarioStatus.ACTIVE

        # Price drops below stop -> invalidated
        changed = engine.update_price("EURUSD", 1.1395)
        assert len(changed) == 1
        assert sc.status == ScenarioStatus.INVALIDATED
        assert sc.invalidated_at is not None
        assert "stop level" in sc.invalidation_reason

    def test_scenario_completion_on_target(self):
        engine = ScenarioEngine()
        sc = engine.create_scenario(
            symbol="EURUSD",
            scenario_type=ScenarioType.BULLISH_CONTINUATION,
            time_horizon="M5",
            activation_conditions={"min_price": 1.1450, "target_price": 1.1500},
            invalidation_conditions={"stop_price": 1.1400},
        )
        engine.update_price("EURUSD", 1.1455)  # Activate

        # Price reaches target -> completed
        changed = engine.update_price("EURUSD", 1.1505)
        assert len(changed) == 1
        assert sc.status == ScenarioStatus.COMPLETED
        assert sc.completed_at is not None
