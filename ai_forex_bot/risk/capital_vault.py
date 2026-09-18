"""
Capital Vault & Profit Sweep Engine
===================================
Automatically locks in trading profits into an isolated vault to protect principal:
- Periodically sweeps profits above high-water mark into protected capital vault.
- Vault funds are excluded from trading margin calculations.
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class VaultState:
    vault_balance_usd: float = 0.0
    total_swept_usd: float = 0.0
    high_water_mark: float = 1000.0


class CapitalVault:
    def __init__(self, sweep_threshold_usd: float = 10.0, sweep_fraction: float = 0.5):
        self.sweep_threshold_usd = sweep_threshold_usd
        self.sweep_fraction = sweep_fraction
        self.state = VaultState()

    def process_sweep(self, current_balance_usd: float) -> float:
        """
        If balance exceeds high-water mark by sweep_threshold, sweep a fraction to vault.
        """
        if current_balance_usd > (self.state.high_water_mark + self.sweep_threshold_usd):
            excess = current_balance_usd - self.state.high_water_mark
            sweep_amount = excess * self.sweep_fraction
            self.state.vault_balance_usd += sweep_amount
            self.state.total_swept_usd += sweep_amount
            self.state.high_water_mark = current_balance_usd - sweep_amount
            return sweep_amount
        return 0.0
