"""
Broker Abstraction Interface
============================
Unified execution interface decoupled from specific broker protocol implementations.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class BaseBroker(ABC):
    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_account_state(self) -> Dict[str, float]:
        """Returns balance, equity, free_margin, used_margin."""
        pass

    @abstractmethod
    def get_quote(self, symbol: str) -> Dict[str, float]:
        """Returns bid, ask, spread_pips, timestamp."""
        pass

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        direction: str,
        lot_size: float,
        sl_price: float,
        tp_price: float,
        order_type: str = "MARKET"
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def close_position(self, position_id: str) -> Dict[str, Any]:
        pass

    def partial_close_position(
        self,
        position_id: str,
        fraction: float = 0.5,
        exit_price: Optional[float] = None,
        exit_reason: str = "PARTIAL_TP",
        exit_epoch: Optional[int] = None
    ) -> Dict[str, Any]:
        """Partially closes a position."""
        raise NotImplementedError

    def modify_position(
        self,
        position_id: str,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None
    ) -> bool:
        """Modifies SL and/or TP of an open position."""
        raise NotImplementedError

    @abstractmethod
    def get_open_positions(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def reconcile(self) -> Dict[str, Any]:
        pass

