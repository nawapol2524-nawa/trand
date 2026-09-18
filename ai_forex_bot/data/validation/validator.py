"""
Market Data Validation Engine
=============================
Validates OHLC data against strict financial time-series integrity constraints:
- Non-negative, non-zero prices
- Strict OHLC inequality rules (high >= low, high >= open, high >= close, low <= open, low <= close)
- Monotonic UTC timestamp sequence
- Duplicate timestamp detection
- Weekday abnormal gap detection vs legitimate weekend closures
- Return spike / bad tick anomalies
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd


@dataclass
class ValidationReport:
    symbol: str
    timeframe: str
    total_rows: int
    is_valid: bool
    duplicate_timestamps: int = 0
    out_of_order_count: int = 0
    invalid_ohlc_inequalities: int = 0
    non_positive_prices: int = 0
    nan_or_inf_count: int = 0
    extreme_price_spikes: int = 0
    weekday_gaps: int = 0
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "total_rows": self.total_rows,
            "is_valid": self.is_valid,
            "duplicate_timestamps": self.duplicate_timestamps,
            "out_of_order_count": self.out_of_order_count,
            "invalid_ohlc_inequalities": self.invalid_ohlc_inequalities,
            "non_positive_prices": self.non_positive_prices,
            "nan_or_inf_count": self.nan_or_inf_count,
            "extreme_price_spikes": self.extreme_price_spikes,
            "weekday_gaps": self.weekday_gaps,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "errors": self.errors
        }


class DataValidator:
    def __init__(self, spike_threshold_pct: float = 8.0, max_weekday_gap_seconds: int = 900):
        self.spike_threshold_pct = spike_threshold_pct
        self.max_weekday_gap_seconds = max_weekday_gap_seconds

    def validate(self, df: pd.DataFrame, symbol: str, timeframe: str = "M1") -> ValidationReport:
        errors: List[str] = []
        total_rows = len(df)
        
        if total_rows == 0:
            return ValidationReport(
                symbol=symbol,
                timeframe=timeframe,
                total_rows=0,
                is_valid=False,
                errors=["DataFrame is empty."]
            )

        # Ensure required columns exist
        required_cols = {"epoch", "open", "high", "low", "close"}
        missing_cols = required_cols - set(df.columns)
        if missing_cols:
            return ValidationReport(
                symbol=symbol,
                timeframe=timeframe,
                total_rows=total_rows,
                is_valid=False,
                errors=[f"Missing required columns: {missing_cols}"]
            )

        # 1. NaN and Inf checks
        nan_inf_mask = df[["epoch", "open", "high", "low", "close"]].isna().any(axis=1) | np.isinf(df[["open", "high", "low", "close"]]).any(axis=1)
        nan_inf_count = int(nan_inf_mask.sum())
        if nan_inf_count > 0:
            errors.append(f"Found {nan_inf_count} rows with NaN or Infinite values.")

        # 2. Timestamp monotonicity and duplicates
        duplicates = int(df["epoch"].duplicated().sum())
        if duplicates > 0:
            errors.append(f"Found {duplicates} duplicate timestamps.")

        diffs = df["epoch"].diff()
        out_of_order = int((diffs < 0).sum())
        if out_of_order > 0:
            errors.append(f"Found {out_of_order} out-of-order timestamps (non-monotonic).")

        # 3. Non-positive prices
        non_pos = int(((df["open"] <= 0) | (df["high"] <= 0) | (df["low"] <= 0) | (df["close"] <= 0)).sum())
        if non_pos > 0:
            errors.append(f"Found {non_pos} non-positive prices.")

        # 4. OHLC inequality violations
        invalid_inequalities = int((
            (df["high"] < df["low"]) |
            (df["high"] < df["open"]) |
            (df["high"] < df["close"]) |
            (df["low"] > df["open"]) |
            (df["low"] > df["close"])
        ).sum())
        if invalid_inequalities > 0:
            errors.append(f"Found {invalid_inequalities} OHLC inequality violations (e.g. high < low).")

        # 5. Extreme price spike check (> threshold on single bar)
        ret = (df["high"] - df["low"]) / df["open"] * 100.0
        spikes = int((ret > self.spike_threshold_pct).sum())
        if spikes > 0:
            errors.append(f"Found {spikes} extreme price range spikes (> {self.spike_threshold_pct}% of open).")

        # 6. Gap analysis (excluding weekend closures)
        weekday_gaps = 0
        if "epoch" in df.columns and len(df) > 1:
            step = diffs.dropna()
            large_steps = step[step > self.max_weekday_gap_seconds]
            if len(large_steps) > 0:
                for idx in large_steps.index:
                    t_before = pd.to_datetime(df.loc[idx - 1, "epoch"], unit="s", utc=True)
                    # Friday close (day of week 4) to Sunday open (day of week 6) is legitimate weekend gap
                    if not (t_before.dayofweek == 4 and t_before.hour >= 20):
                        weekday_gaps += 1

        is_valid = (
            nan_inf_count == 0 and
            duplicates == 0 and
            out_of_order == 0 and
            non_pos == 0 and
            invalid_inequalities == 0 and
            spikes == 0
        )

        start_time = str(pd.to_datetime(df["epoch"].iloc[0], unit="s", utc=True)) if total_rows > 0 else None
        end_time = str(pd.to_datetime(df["epoch"].iloc[-1], unit="s", utc=True)) if total_rows > 0 else None

        return ValidationReport(
            symbol=symbol,
            timeframe=timeframe,
            total_rows=total_rows,
            is_valid=is_valid,
            duplicate_timestamps=duplicates,
            out_of_order_count=out_of_order,
            invalid_ohlc_inequalities=invalid_inequalities,
            non_positive_prices=non_pos,
            nan_or_inf_count=nan_inf_count,
            extreme_price_spikes=spikes,
            weekday_gaps=weekday_gaps,
            start_time=start_time,
            end_time=end_time,
            errors=errors
        )
