"""
Purged & Embargoed Time-Series Splitter
========================================
Implements Marcos López de Prado’s Purged K-Fold / Purged Temporal Split:
- Eliminates target look-ahead leakage across fold boundaries (target_end >= next_fold_start).
- Ensures no sample in fold A has forward label observations extending into fold B.
- Provides optional embargo buffer following fold transitions.
"""

from dataclasses import dataclass
from typing import Tuple, Dict, Any, List, Optional
import pandas as pd
import numpy as np


@dataclass
class SplitBoundaries:
    train_indices: np.ndarray
    val_indices: np.ndarray
    test_indices: np.ndarray
    purged_train_count: int
    purged_val_count: int
    train_start_epoch: int
    train_end_epoch: int
    val_start_epoch: int
    val_end_epoch: int
    test_start_epoch: int
    test_end_epoch: int
    train_target_max_epoch: int
    val_target_max_epoch: int
    train_val_leak_free: bool
    val_test_leak_free: bool


class PurgedTimeSeriesSplitter:
    def __init__(self, horizon_bars: int = 4, embargo_bars: int = 0):
        """
        :param horizon_bars: Maximum target observation horizon in bars (H).
        :param embargo_bars: Optional embargo buffer following fold transition.
        """
        self.horizon_bars = horizon_bars
        self.embargo_bars = embargo_bars

    def get_split_indices(
        self,
        df: pd.DataFrame,
        train_ratio: float = 0.70,
        val_ratio: float = 0.15
    ) -> SplitBoundaries:
        """
        Calculates split boundaries and purged indices for a time-ordered dataframe.
        """
        n = len(df)
        if n < (self.horizon_bars * 3):
            raise ValueError(f"Dataset length ({n}) too small for horizon ({self.horizon_bars})")

        raw_train_end = int(n * train_ratio)
        raw_val_end = int(n * (train_ratio + val_ratio))
        H = self.horizon_bars

        # 1. Purge Train boundary:
        # A sample at index i evaluates future returns up to index i + H.
        # If (i + H) >= raw_train_end, its evaluation window touches or crosses into validation.
        # Therefore, train samples must satisfy: i + H < raw_train_end => i <= raw_train_end - H - 1
        safe_train_end = max(0, raw_train_end - H)
        purged_train_count = raw_train_end - safe_train_end
        train_idx = np.arange(0, safe_train_end)

        # 2. Purge Validation boundary:
        val_start = raw_train_end + self.embargo_bars
        safe_val_end = max(val_start, raw_val_end - H)
        purged_val_count = raw_val_end - safe_val_end
        val_idx = np.arange(val_start, safe_val_end)

        # 3. Test fold:
        test_start = raw_val_end + self.embargo_bars
        test_idx = np.arange(test_start, n)

        # Timestamps / Epochs
        epochs = df["epoch"].values
        train_start_epoch = int(epochs[train_idx[0]])
        train_end_epoch = int(epochs[train_idx[-1]])
        val_start_epoch = int(epochs[val_idx[0]])
        val_end_epoch = int(epochs[val_idx[-1]])
        test_start_epoch = int(epochs[test_idx[0]])
        test_end_epoch = int(epochs[test_idx[-1]])

        # In df, sample i had future return computed up to row i + H
        train_target_max_index = train_idx[-1] + H
        val_target_max_index = val_idx[-1] + H

        train_target_max_epoch = int(epochs[train_target_max_index])
        val_target_max_epoch = int(epochs[val_target_max_index])

        # Strict causality assertions:
        train_val_leak_free = train_target_max_epoch < val_start_epoch
        val_test_leak_free = val_target_max_epoch < test_start_epoch

        return SplitBoundaries(
            train_indices=train_idx,
            val_indices=val_idx,
            test_indices=test_idx,
            purged_train_count=purged_train_count,
            purged_val_count=purged_val_count,
            train_start_epoch=train_start_epoch,
            train_end_epoch=train_end_epoch,
            val_start_epoch=val_start_epoch,
            val_end_epoch=val_end_epoch,
            test_start_epoch=test_start_epoch,
            test_end_epoch=test_end_epoch,
            train_target_max_epoch=train_target_max_epoch,
            val_target_max_epoch=val_target_max_epoch,
            train_val_leak_free=train_val_leak_free,
            val_test_leak_free=val_test_leak_free
        )
