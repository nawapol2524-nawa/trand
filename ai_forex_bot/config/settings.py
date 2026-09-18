"""
System Configuration & Settings Manager
======================================
Loads declarative YAML configurations and environment variables securely.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List
import yaml
from dotenv import load_dotenv

# Load .env silently from workspace root
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(dotenv_path=WORKSPACE_ROOT / ".env", override=False)


class SymbolConfig:
    def __init__(self, name: str, data: Dict[str, Any]):
        self.name = name
        self.display_name: str = data.get("display_name", name)
        self.asset_class: str = data.get("asset_class", "forex")
        self.base_currency: str = data.get("base_currency", "")
        self.quote_currency: str = data.get("quote_currency", "")
        self.pip_size: float = float(data.get("pip_size", 0.0001))
        self.pip_value_usd: float = float(data.get("pip_value_usd", 10.0))
        self.lot_size: float = float(data.get("lot_size", 100000))
        self.min_lot: float = float(data.get("min_lot", 0.01))
        self.max_lot: float = float(data.get("max_lot", 10.0))
        self.lot_step: float = float(data.get("lot_step", 0.01))
        self.max_spread_pips: float = float(data.get("max_spread_pips", 2.0))
        self.typical_spread_pips: float = float(data.get("typical_spread_pips", 1.2))
        self.commission_per_lot_usd: float = float(data.get("commission_per_lot_usd", 6.0))
        self.swap_long_points: float = float(data.get("swap_long_points", 0.0))
        self.swap_short_points: float = float(data.get("swap_short_points", 0.0))


class Settings:
    def __init__(self, config_dir: Optional[Path] = None):
        self.root_dir = WORKSPACE_ROOT
        self.config_dir = config_dir or (WORKSPACE_ROOT / "configs")
        
        # Load YAML files
        self.symbols_file = self.config_dir / "symbols.yaml"
        self.system_file = self.config_dir / "system.yaml"
        
        self.raw_symbols: Dict[str, Any] = self._load_yaml(self.symbols_file).get("symbols", {})
        self.raw_system: Dict[str, Any] = self._load_yaml(self.system_file)
        
        self.symbols: Dict[str, SymbolConfig] = {
            k: SymbolConfig(k, v) for k, v in self.raw_symbols.items()
        }
        
        # System section
        sys_sec = self.raw_system.get("system", {})
        self.system_name: str = sys_sec.get("name", "AI Forex Bot")
        self.version: str = sys_sec.get("version", "2.0.0")
        self.random_seed: int = int(sys_sec.get("random_seed", 42))
        self.timezone: str = sys_sec.get("timezone", "UTC")
        self.live_trading: bool = bool(sys_sec.get("live_trading", False))
        self.auto_promotion: bool = bool(sys_sec.get("auto_promotion", False))
        
        # Risk section
        risk_sec = self.raw_system.get("risk", {})
        self.max_risk_per_trade_pct: float = float(risk_sec.get("max_risk_per_trade_pct", 1.0))
        self.max_daily_loss_usd: float = float(risk_sec.get("max_daily_loss_usd", 2.0))
        self.max_weekly_loss_usd: float = float(risk_sec.get("max_weekly_loss_usd", 6.0))
        self.max_drawdown_pct: float = float(risk_sec.get("max_drawdown_pct", 10.0))
        self.max_open_positions: int = int(risk_sec.get("max_open_positions", 2))
        
        # Data paths
        data_sec = self.raw_system.get("data", {})
        self.base_timeframe: str = data_sec.get("base_timeframe", "M1")
        self.resampled_timeframes: List[str] = data_sec.get("resampled_timeframes", ["M5", "M15", "H1", "H4", "D1"])
        self.raw_data_dir = self.root_dir / data_sec.get("raw_dir", "data/market/raw")
        self.clean_data_dir = self.root_dir / data_sec.get("clean_dir", "data/clean")
        self.features_dir = self.root_dir / data_sec.get("features_dir", "data/features")
        self.labels_dir = self.root_dir / data_sec.get("labels_dir", "data/labels")
        self.datasets_dir = self.root_dir / data_sec.get("datasets_dir", "data/datasets")
        
        # Economic Calendar section
        econ_sec = self.raw_system.get("economic_calendar", {})
        self.pre_event_blackout_minutes: int = int(econ_sec.get("pre_event_blackout_minutes", 15))
        self.post_event_stabilization_minutes: int = int(econ_sec.get("post_event_stabilization_minutes", 15))
        self.high_impact_only: bool = bool(econ_sec.get("high_impact_only", True))
        
        # AI section
        ai_sec = self.raw_system.get("ai", {})
        self.primary_model: str = ai_sec.get("primary_model", "hist_gradient_boosting")
        self.fallback_model: str = ai_sec.get("fallback_model", "random_forest")
        self.prediction_horizon_bars: int = int(ai_sec.get("prediction_horizon_bars", 15))
        self.confidence_threshold: float = float(ai_sec.get("confidence_threshold", 0.55))
        self.calibration_method: str = ai_sec.get("calibration_method", "isotonic")

        # Research & OOS Lock section
        res_sec = self.raw_system.get("research", {})
        self.oos_locked: bool = bool(res_sec.get("oos_locked", True))
        self.oos_evaluation_open: bool = bool(res_sec.get("oos_evaluation_open", False))
        self.oos_evaluation_session_id: Optional[str] = res_sec.get("oos_evaluation_session_id", None)
        self.oos_consumed: bool = bool(res_sec.get("oos_consumed", False))

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def get_symbol_config(self, symbol: str) -> Optional[SymbolConfig]:
        return self.symbols.get(symbol)

    def is_spread_acceptable(self, symbol: str, spread_pips: float) -> bool:
        cfg = self.get_symbol_config(symbol)
        if cfg is None:
            return False
        return spread_pips <= cfg.max_spread_pips


# Global singleton instance
settings = Settings()
