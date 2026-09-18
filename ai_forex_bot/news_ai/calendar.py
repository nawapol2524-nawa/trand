"""
Economic Calendar Engine & Policy Framework
===========================================
Enforces strict temporal event causality:
- Separates scheduled_time from publication_time.
- Prevents actual release figures from leaking prior to publication_time.
- Computes time_to_event, time_since_event, and economic surprise metrics.
- Manages trading blackout policies (NORMAL, CAUTION, BLACKOUT, EVENT_MODE).
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any
import numpy as np
import pandas as pd


class CalendarPolicy(str, Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    BLACKOUT = "BLACKOUT"
    EVENT_MODE = "EVENT_MODE"


@dataclass
class EconomicEvent:
    event_id: str
    event_name: str
    currency: str
    country: str
    scheduled_epoch: int
    publication_epoch: int
    importance: str  # LOW, MEDIUM, HIGH
    forecast: Optional[float] = None
    previous: Optional[float] = None
    actual: Optional[float] = None
    source: str = "forexfactory"

    @property
    def importance_weight(self) -> int:
        mapping = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
        return mapping.get(self.importance.upper(), 1)


class EconomicCalendarEngine:
    def __init__(self, blackout_pre_seconds: int = 900, blackout_post_seconds: int = 900):
        self.blackout_pre_seconds = blackout_pre_seconds
        self.blackout_post_seconds = blackout_post_seconds
        self.events: List[EconomicEvent] = []

    def load_events(self, events: List[EconomicEvent]):
        # Sort chronologically by scheduled epoch
        self.events = sorted(events, key=lambda e: e.scheduled_epoch)

    def get_context_at_epoch(self, epoch: int, currency: Optional[str] = None) -> Dict[str, Any]:
        """
        Queries economic calendar state at exact timestamp `epoch`.
        Guarantees:
        - `actual` is visible ONLY if epoch >= publication_epoch.
        - Computes time_to_next_event and time_since_last_event.
        - Determines current CalendarPolicy.
        """
        relevant_events = [
            e for e in self.events 
            if (currency is None or e.currency.upper() == currency.upper() or e.currency.upper() == "USD")
            and e.importance.upper() in {"HIGH", "MEDIUM"}
        ]

        if not relevant_events:
            return {
                "policy": CalendarPolicy.NORMAL.value,
                "time_to_event_sec": 86400,
                "time_since_event_sec": 86400,
                "event_importance": 0,
                "surprise": 0.0,
                "active_event_id": None
            }

        past_events = [e for e in relevant_events if e.scheduled_epoch <= epoch]
        future_events = [e for e in relevant_events if e.scheduled_epoch > epoch]

        last_event = past_events[-1] if past_events else None
        next_event = future_events[0] if future_events else None

        time_since = (epoch - last_event.scheduled_epoch) if last_event else 86400
        time_to = (next_event.scheduled_epoch - epoch) if next_event else 86400

        policy = CalendarPolicy.NORMAL
        active_event = None

        # Check upcoming blackout
        if next_event and time_to <= self.blackout_pre_seconds:
            policy = CalendarPolicy.BLACKOUT if next_event.importance.upper() == "HIGH" else CalendarPolicy.CAUTION
            active_event = next_event
        # Check post-event stabilization
        elif last_event and time_since <= self.blackout_post_seconds:
            policy = CalendarPolicy.BLACKOUT if last_event.importance.upper() == "HIGH" else CalendarPolicy.EVENT_MODE
            active_event = last_event
        elif (next_event and time_to <= self.blackout_pre_seconds * 2) or (last_event and time_since <= self.blackout_post_seconds * 2):
            policy = CalendarPolicy.CAUTION
            active_event = next_event or last_event

        # Compute surprise only if actual is published
        surprise = 0.0
        if last_event and epoch >= last_event.publication_epoch:
            if last_event.actual is not None and last_event.forecast is not None:
                surprise = float(last_event.actual - last_event.forecast)

        return {
            "policy": policy.value,
            "time_to_event_sec": int(time_to),
            "time_since_event_sec": int(time_since),
            "event_importance": active_event.importance_weight if active_event else 0,
            "surprise": float(surprise),
            "active_event_id": active_event.event_id if active_event else None
        }

    def add_calendar_features(self, df: pd.DataFrame, currency: Optional[str] = None) -> pd.DataFrame:
        """
        Vectorized/batch feature enrichment for historical time series.
        """
        policies = []
        time_tos = []
        time_sinces = []
        importances = []
        surprises = []

        for epoch in df["epoch"]:
            ctx = self.get_context_at_epoch(int(epoch), currency=currency)
            policies.append(ctx["policy"])
            time_tos.append(ctx["time_to_event_sec"])
            time_sinces.append(ctx["time_since_event_sec"])
            importances.append(ctx["event_importance"])
            surprises.append(ctx["surprise"])

        df["econ_policy"] = policies
        df["econ_is_blackout"] = (df["econ_policy"] == CalendarPolicy.BLACKOUT.value).astype(int)
        df["econ_time_to_event_sec"] = time_tos
        df["econ_time_since_event_sec"] = time_sinces
        df["econ_importance"] = importances
        df["econ_surprise"] = surprises
        return df
