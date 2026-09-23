"""
UTC clock and candle timestamp utilities.
No broker imports. No side effects.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.models import Timeframe

# Seconds per timeframe
TIMEFRAME_SECONDS: dict[Timeframe, int] = {
    Timeframe.M1:  60,
    Timeframe.M5:  300,
    Timeframe.M15: 900,
    Timeframe.H1:  3600,
    Timeframe.H4:  14400,
    Timeframe.D1:  86400,
}


def utc_now() -> datetime:
    """Current UTC time, timezone-aware."""
    return datetime.now(tz=timezone.utc)


def candle_open_time(ts: datetime, tf: Timeframe) -> datetime:
    """
    Floor ts to the candle open time for the given timeframe.
    e.g. 09:37 UTC on M5 → 09:35 UTC
    """
    period = TIMEFRAME_SECONDS[tf]
    epoch = int(ts.timestamp())
    floored = (epoch // period) * period
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def candle_close_time(ts: datetime, tf: Timeframe) -> datetime:
    """
    Return the exclusive close time of the candle containing ts.
    A candle is CLOSED when current_time >= candle_close_time.
    """
    period = TIMEFRAME_SECONDS[tf]
    open_t = candle_open_time(ts, tf)
    return open_t + timedelta(seconds=period)


def is_candle_closed(candle_open: datetime, tf: Timeframe,
                     now: datetime | None = None) -> bool:
    """
    Return True if the candle that opened at candle_open is fully closed.
    Uses utc_now() if now is not provided.
    """
    if now is None:
        now = utc_now()
    return now >= candle_close_time(candle_open, tf)


def previous_candle_open(ts: datetime, tf: Timeframe) -> datetime:
    """Return open time of the candle immediately before the one containing ts."""
    current_open = candle_open_time(ts, tf)
    period = TIMEFRAME_SECONDS[tf]
    return current_open - timedelta(seconds=period)


def bars_are_monotonic(timestamps: list[datetime], tf: Timeframe) -> bool:
    """
    Return True if timestamps form a strictly increasing sequence
    with no gaps (consecutive candles exactly one period apart).
    """
    period = TIMEFRAME_SECONDS[tf]
    for i in range(1, len(timestamps)):
        diff = int((timestamps[i] - timestamps[i - 1]).total_seconds())
        if diff != period:
            return False
    return True
