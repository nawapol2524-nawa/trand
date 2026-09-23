"""
Scenario Engine & Scenario Book — Phase H requirement.
Enables structured forward-looking scenario tracking (bullish/bearish continuation,
reversal, range, breakout failure) without requiring multi-LLM bloat.
Deterministic engine validates activation, invalidation, and completion.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class ScenarioType(str, Enum):
    BULLISH_CONTINUATION = "BULLISH_CONTINUATION"
    BEARISH_CONTINUATION = "BEARISH_CONTINUATION"
    REVERSAL             = "REVERSAL"
    RANGE                = "RANGE"
    BREAKOUT_FAILURE     = "BREAKOUT_FAILURE"
    NO_TRADE             = "NO_TRADE"
    INVALIDATED          = "INVALIDATED"


class ScenarioStatus(str, Enum):
    PLANNED     = "PLANNED"
    ACTIVE      = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    COMPLETED   = "COMPLETED"


@dataclass
class Scenario:
    scenario_id:             str
    scenario_type:           ScenarioType
    symbol:                  str
    created_at:              datetime
    time_horizon:            str              # e.g., 'M5', 'H1', 'H4'
    activation_conditions:   dict[str, Any]   # e.g., {'min_price': 1.1450, 'require_bos': True}
    invalidation_conditions: dict[str, Any]   # e.g., {'stop_price': 1.1380}
    status:                  ScenarioStatus = ScenarioStatus.PLANNED
    activated_at:            Optional[datetime] = None
    invalidated_at:          Optional[datetime] = None
    completed_at:            Optional[datetime] = None
    invalidation_reason:     Optional[str] = None
    notes:                   str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id":             self.scenario_id,
            "scenario_type":           self.scenario_type.value,
            "symbol":                  self.symbol,
            "created_at":              self.created_at.isoformat(),
            "time_horizon":            self.time_horizon,
            "activation_conditions":   self.activation_conditions,
            "invalidation_conditions": self.invalidation_conditions,
            "status":                  self.status.value,
            "activated_at":            self.activated_at.isoformat() if self.activated_at else None,
            "invalidated_at":          self.invalidated_at.isoformat() if self.invalidated_at else None,
            "completed_at":            self.completed_at.isoformat() if self.completed_at else None,
            "invalidation_reason":     self.invalidation_reason,
            "notes":                   self.notes,
        }


class ScenarioEngine:
    """
    Manages the lifecycle of scenarios per instrument.
    Deterministic engine validates status changes.
    """

    def __init__(self):
        self._scenarios: dict[str, list[Scenario]] = {}  # symbol -> list of scenarios

    def create_scenario(
        self,
        symbol: str,
        scenario_type: ScenarioType,
        time_horizon: str,
        activation_conditions: dict[str, Any],
        invalidation_conditions: dict[str, Any],
        notes: str = "",
        scenario_id: Optional[str] = None,
    ) -> Scenario:
        sid = scenario_id or f"scen_{uuid.uuid4().hex[:8]}"
        sc = Scenario(
            scenario_id=sid,
            scenario_type=scenario_type,
            symbol=symbol,
            created_at=datetime.now(tz=timezone.utc),
            time_horizon=time_horizon,
            activation_conditions=activation_conditions,
            invalidation_conditions=invalidation_conditions,
            status=ScenarioStatus.PLANNED,
            notes=notes,
        )
        if symbol not in self._scenarios:
            self._scenarios[symbol] = []
        self._scenarios[symbol].append(sc)
        return sc

    def get_active_scenarios(self, symbol: str) -> list[Scenario]:
        return [
            s for s in self._scenarios.get(symbol, [])
            if s.status in (ScenarioStatus.ACTIVE, ScenarioStatus.PLANNED)
        ]

    def update_price(self, symbol: str, current_price: float, now: Optional[datetime] = None) -> list[Scenario]:
        """
        Evaluate market price against active/planned scenarios.
        Returns list of scenarios that changed state.
        """
        now_utc = now or datetime.now(tz=timezone.utc)
        changed: list[Scenario] = []

        for sc in self._scenarios.get(symbol, []):
            if sc.status == ScenarioStatus.PLANNED:
                # Check activation
                min_p = sc.activation_conditions.get("min_price")
                max_p = sc.activation_conditions.get("max_price")
                should_activate = False

                if min_p is not None and current_price >= min_p:
                    should_activate = True
                elif max_p is not None and current_price <= max_p:
                    should_activate = True

                if should_activate:
                    sc.status = ScenarioStatus.ACTIVE
                    sc.activated_at = now_utc
                    changed.append(sc)

            elif sc.status == ScenarioStatus.ACTIVE:
                # Check invalidation
                stop_p = sc.invalidation_conditions.get("stop_price")
                if stop_p is not None:
                    if sc.scenario_type in (ScenarioType.BULLISH_CONTINUATION, ScenarioType.REVERSAL):
                        if current_price <= stop_p:
                            sc.status = ScenarioStatus.INVALIDATED
                            sc.invalidated_at = now_utc
                            sc.invalidation_reason = f"Price breached stop level {stop_p}"
                            changed.append(sc)
                    elif sc.scenario_type == ScenarioType.BEARISH_CONTINUATION:
                        if current_price >= stop_p:
                            sc.status = ScenarioStatus.INVALIDATED
                            sc.invalidated_at = now_utc
                            sc.invalidation_reason = f"Price breached stop level {stop_p}"
                            changed.append(sc)

                # Check completion
                target_p = sc.activation_conditions.get("target_price")
                if target_p is not None:
                    if sc.scenario_type == ScenarioType.BULLISH_CONTINUATION and current_price >= target_p:
                        sc.status = ScenarioStatus.COMPLETED
                        sc.completed_at = now_utc
                        changed.append(sc)
                    elif sc.scenario_type == ScenarioType.BEARISH_CONTINUATION and current_price <= target_p:
                        sc.status = ScenarioStatus.COMPLETED
                        sc.completed_at = now_utc
                        changed.append(sc)

        return changed
