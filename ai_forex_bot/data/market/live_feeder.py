"""
Live Market Feeder & Autonomous Synthetic Bar Engine
====================================================
Institutional Production Feed Standard for Gate 26:
1. Polls/streams live ticks and candles from Deriv WebSocket API when credentials
   and internet connectivity are active.
2. Provides an autonomous high-fidelity synthetic live bar generator (Offline/Paper mode)
   that generates continuous 1-minute / 15-minute bars matching symbol specifications
   (GBM stochastic volatility, pip sizes, and continuous 24/7 liquidity) if credentials
   or network are absent.
"""

import os
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd

from ai_forex_bot.config.settings import settings


class LiveMarketFeeder:
    """
    Dual-mode market data feeder:
    - Deriv WebSocket API streaming/polling
    - Autonomous high-fidelity synthetic bar generator
    """

    def __init__(
        self,
        symbol: str = "frxEURUSD",
        timeframe: str = "M15",
        api_token: Optional[str] = None,
        app_id: Optional[str] = None,
        offline_mode: bool = False,
        random_seed: Optional[int] = 42
    ):
        self.symbol = symbol
        self.timeframe = timeframe.upper()
        self.api_token = api_token or os.getenv("DERIV_API_TOKEN")
        self.app_id = app_id or os.getenv("DERIV_APP_ID", "1085")
        self.offline_mode = offline_mode
        self.rng = random.Random(random_seed)

        # Granularity mapping in seconds
        self.granularity_map = {
            "M1": 60,
            "M5": 300,
            "M15": 900,
            "H1": 3600,
            "H4": 14400,
            "D1": 86400
        }
        self.granularity_seconds = self.granularity_map.get(self.timeframe, 900)

        # Symbol specifications
        self.sym_cfg = settings.get_symbol_config(self.symbol)
        self.pip_size = self.sym_cfg.pip_size if self.sym_cfg else 0.0001
        self.decimals = max(0, int(-np.log10(self.pip_size))) if self.pip_size < 1 else 2

        # Volatility calibration
        if self.symbol == "R_75":
            self.annual_vol = 0.75
            self.initial_price = 250000.0
        elif self.symbol == "R_25":
            self.annual_vol = 0.25
            self.initial_price = 2500.0
        elif self.symbol == "R_10":
            self.annual_vol = 0.10
            self.initial_price = 6500.0
        elif "JPY" in self.symbol:
            self.annual_vol = 0.10
            self.initial_price = 155.0
        elif "XAU" in self.symbol:
            self.annual_vol = 0.18
            self.initial_price = 2400.0
        else:
            self.annual_vol = 0.09
            self.initial_price = 1.08500

        self.last_close: float = self.initial_price
        self.last_epoch: int = int(time.time() // self.granularity_seconds) * self.granularity_seconds
        self.mode: str = "INITIALIZING"
        self.connected: bool = False

        # Attempt to inspect clean historical parquet for realistic seed price & epoch
        self._seed_from_parquet_if_available()

    def _seed_from_parquet_if_available(self):
        """Seeds initial price and epoch from clean parquet if present on disk."""
        parquet_path = settings.clean_data_dir / f"{self.symbol}_{self.timeframe}.parquet"
        if not parquet_path.exists():
            # Try M15 or H1 fallback
            parquet_path = settings.clean_data_dir / f"{self.symbol}_M15.parquet"

        if parquet_path.exists():
            try:
                df = pd.read_parquet(parquet_path)
                if len(df) > 0:
                    last_row = df.iloc[-1]
                    self.last_close = round(float(last_row["close"]), self.decimals)
                    self.last_epoch = int(last_row["epoch"])
            except Exception:
                pass

    def get_warmup_bars(self, count: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieves warmup bars to prime rolling feature extraction buffer:
        - First checks local clean parquets.
        - If not available, generates realistic synthetic warmup sequence.
        """
        parquet_path = settings.clean_data_dir / f"{self.symbol}_{self.timeframe}.parquet"
        if not parquet_path.exists():
            parquet_path = settings.clean_data_dir / f"{self.symbol}_M15.parquet"

        if parquet_path.exists():
            try:
                df = pd.read_parquet(parquet_path)
                if len(df) >= count:
                    warmup_df = df.iloc[-count:].copy().sort_values("epoch").reset_index(drop=True)
                    bars = []
                    for _, row in warmup_df.iterrows():
                        bar = {
                            "epoch": int(row["epoch"]),
                            "open": round(float(row["open"]), self.decimals),
                            "high": round(float(row["high"]), self.decimals),
                            "low": round(float(row["low"]), self.decimals),
                            "close": round(float(row["close"]), self.decimals),
                            "symbol": self.symbol
                        }
                        bars.append(bar)
                    self.last_close = bars[-1]["close"]
                    self.last_epoch = bars[-1]["epoch"]
                    return bars
            except Exception:
                pass

        # Generate synthetic warmup sequence
        bars = []
        base_epoch = self.last_epoch - (count * self.granularity_seconds)
        price = self.last_close

        dt_year = self.granularity_seconds / (365.25 * 86400.0)
        vol_step = self.annual_vol * np.sqrt(dt_year)

        for i in range(count):
            bar_epoch = base_epoch + ((i + 1) * self.granularity_seconds)
            z = self.rng.gauss(0, 1)
            open_p = price
            ret = -0.5 * (vol_step ** 2) + vol_step * z
            close_p = round(max(self.pip_size, open_p * np.exp(ret)), self.decimals)

            wick_scale = abs(close_p - open_p) + (open_p * vol_step * 0.4)
            high_p = round(max(open_p, close_p) + (self.rng.uniform(0.1, 0.8) * wick_scale), self.decimals)
            low_p = round(max(self.pip_size, min(open_p, close_p) - (self.rng.uniform(0.1, 0.8) * wick_scale)), self.decimals)

            high_p = max(high_p, max(open_p, close_p))
            low_p = min(low_p, min(open_p, close_p))

            bar = {
                "epoch": bar_epoch,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "symbol": self.symbol
            }
            bars.append(bar)
            price = close_p

        self.last_close = price
        self.last_epoch = bars[-1]["epoch"]
        return bars

    def _poll_deriv_api(self) -> Optional[Dict[str, Any]]:
        """
        Attempts to fetch live candle from Deriv WebSocket API.
        Returns candle dict or None if offline/unavailable.
        """
        if self.offline_mode or not self.api_token:
            return None

        try:
            from websockets.sync.client import connect
            uri = f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}"
            with connect(uri, open_timeout=2.0, close_timeout=2.0) as ws:
                # Authorize if token present
                if self.api_token:
                    ws.send(json.dumps({"authorize": self.api_token}))
                    auth_raw = ws.recv(timeout=2.0)
                    auth_data = json.loads(auth_raw)
                    if "error" in auth_data:
                        return None

                # Query latest candle
                req = {
                    "ticks_history": self.symbol,
                    "end": "latest",
                    "count": 1,
                    "granularity": self.granularity_seconds,
                    "style": "candles"
                }
                ws.send(json.dumps(req))
                resp_raw = ws.recv(timeout=2.0)
                resp = json.loads(resp_raw)
                candles = resp.get("candles", [])
                if candles:
                    c = candles[-1]
                    self.connected = True
                    self.mode = "DERIV_WEBSOCKET"
                    return {
                        "epoch": int(c["epoch"]),
                        "open": round(float(c["open"]), self.decimals),
                        "high": round(float(c["high"]), self.decimals),
                        "low": round(float(c["low"]), self.decimals),
                        "close": round(float(c["close"]), self.decimals),
                        "symbol": self.symbol
                    }
        except Exception:
            self.connected = False
            return None

        return None

    def _generate_synthetic_bar(self) -> Dict[str, Any]:
        """
        Generates next continuous high-fidelity synthetic bar using
        calibrated Geometric Brownian Motion and symbol tick rules.
        """
        self.mode = "SYNTHETIC_OFFLINE"
        self.connected = True
        next_epoch = self.last_epoch + self.granularity_seconds
        dt_year = self.granularity_seconds / (365.25 * 86400.0)
        vol_step = self.annual_vol * np.sqrt(dt_year)

        open_p = self.last_close
        z = self.rng.gauss(0, 1)
        ret = -0.5 * (vol_step ** 2) + vol_step * z
        close_p = round(max(self.pip_size, open_p * np.exp(ret)), self.decimals)

        wick_scale = abs(close_p - open_p) + (open_p * vol_step * 0.4)
        high_p = round(max(open_p, close_p) + (self.rng.uniform(0.1, 0.8) * wick_scale), self.decimals)
        low_p = round(max(self.pip_size, min(open_p, close_p) - (self.rng.uniform(0.1, 0.8) * wick_scale)), self.decimals)

        high_p = max(high_p, max(open_p, close_p))
        low_p = min(low_p, min(open_p, close_p))

        self.last_close = close_p
        self.last_epoch = next_epoch

        return {
            "epoch": next_epoch,
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "symbol": self.symbol
        }

    def poll_next_bar(self) -> Dict[str, Any]:
        """
        Polls next live bar from Deriv WebSocket if possible,
        otherwise generates autonomous synthetic bar seamlessly.
        """
        deriv_bar = self._poll_deriv_api()
        if deriv_bar is not None and deriv_bar["epoch"] > self.last_epoch:
            self.last_close = deriv_bar["close"]
            self.last_epoch = deriv_bar["epoch"]
            return deriv_bar

        return self._generate_synthetic_bar()
