"""
cTrader Remote MCP Broker Adapter.
Authoritative execution and market data interface for Deriv cTrader.
Communicates via JSON-RPC 2.0 / SSE with https://mcp.ctrader.com/trading/mcp.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger("CTraderMCPBroker")


class CTraderMCPBroker:
    """Production broker adapter for cTrader Remote MCP Server."""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        bearer_token: Optional[str] = None,
        timeout_seconds: float = 15.0,
    ):
        # Auto-load .env if present
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            try:
                from dotenv import load_dotenv
                load_dotenv(env_path)
            except ImportError:
                with open(env_path, "r", encoding="utf-8") as fp:
                    for line in fp:
                        if "=" in line and not line.strip().startswith("#"):
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip())

        self.endpoint_url = endpoint_url or os.environ.get("CTRADER_MCP_URL", "https://mcp.ctrader.com/trading/mcp")
        self.bearer_token = bearer_token or os.environ.get("CTRADER_MCP_TOKEN", "")
        self.timeout = timeout_seconds
        self.session_id: Optional[str] = None
        self._ssl_context: Optional[Any] = None

    def _urlopen(self, req: urllib.request.Request):
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self._ssl_context is not None:
            kwargs["context"] = self._ssl_context
        return urllib.request.urlopen(req, **kwargs)

    def connect(self) -> str:
        """Perform MCP initialize handshake and obtain session ID."""
        if not self.bearer_token or self.bearer_token.startswith("YOUR_"):
            raise ValueError("cTrader MCP Bearer Token is not configured in .env")

        rpc_init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "trading-bot-broker", "version": "1.0.0"},
            },
        }

        req = urllib.request.Request(
            self.endpoint_url,
            data=json.dumps(rpc_init).encode("utf-8"),
            headers={
                "Authorization": self.bearer_token,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )

        with self._urlopen(req) as resp:
            self.session_id = resp.headers.get("mcp-session-id")
            if not self.session_id:
                raise ConnectionError("cTrader MCP server did not return mcp-session-id header")

        # Send initialized notification
        rpc_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        req_notif = urllib.request.Request(
            self.endpoint_url,
            data=json.dumps(rpc_notif).encode("utf-8"),
            headers={
                "Authorization": self.bearer_token,
                "mcp-session-id": self.session_id,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        try:
            with self._urlopen(req_notif):
                pass
        except Exception:
            pass

        return self.session_id

    def call_tool(self, tool_name: str, arguments: dict[str, Any], _retry: bool = False) -> dict[str, Any]:
        """Execute a tool on the remote cTrader MCP server."""
        if not self.session_id:
            self.connect()

        rpc_call = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 1000000,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        req = urllib.request.Request(
            self.endpoint_url,
            data=json.dumps(rpc_call).encode("utf-8"),
            headers={
                "Authorization": self.bearer_token,
                "mcp-session-id": self.session_id,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )

        try:
            with self._urlopen(req) as resp:
                raw_text = resp.read().decode("utf-8", errors="ignore")
                for line in raw_text.splitlines():
                    if line.startswith("data:"):
                        payload = json.loads(line[5:].strip())
                        if "error" in payload:
                            raise RuntimeError(f"cTrader MCP Error: {payload['error']}")
                        content = payload.get("result", {}).get("content", [{}])[0].get("text", "")
                        try:
                            return json.loads(content)
                        except json.JSONDecodeError:
                            return {"raw": content}
                return {"raw": raw_text}
        except urllib.error.HTTPError as e:
            if e.code in (400, 404) and not _retry:
                # Session expired or not found, re-connect once
                logger.warning(
                    "cTrader MCP tool '%s' encountered HTTP %d (session=%s). Re-authenticating and retrying...",
                    tool_name,
                    e.code,
                    self.session_id,
                )
                self.connect()
                return self.call_tool(tool_name, arguments, _retry=True)
            raise

    def get_balance(self) -> dict[str, Any]:
        """Get account balance, equity, and free margin."""
        res = self.call_tool("get_balance", {})
        money_digits = res.get("moneyDigits", 2)
        factor = 10**money_digits
        return {
            "balance": res.get("balance", 0) / factor,
            "equity": res.get("equity", 0) / factor,
            "free_margin": res.get("freeMargin", 0) / factor,
            "raw": res,
        }

    def get_positions(self) -> list[dict[str, Any]]:
        """Get open positions."""
        res = self.call_tool("get_positions", {})
        return res.get("positions", [])

    def get_spot_prices(self, symbol_ids: list[int]) -> list[dict[str, Any]]:
        """Get live spot prices for symbol IDs."""
        res = self.call_tool("get_spot_prices", {"symbolId": symbol_ids})
        return res.get("prices", [])

    def get_trendbars(
        self,
        symbol_id: int,
        period: str = "M_5",
        count: int = 250,
        from_timestamp: Optional[int] = None,
        to_timestamp: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        Get historical/live OHLCV trendbars for symbol.
        period: M_1, M_5, M_15, M_30, H_1, H_4, D_1, W_1, MN_1
        Returns list of trendbar dicts: [{timestamp, open, high, low, close, volume}, ...]
        """
        now_ms = to_timestamp or int(time.time() * 1000)
        if from_timestamp is None:
            period_seconds = 3600 if period == "H_1" else 300
            window_ms = count * period_seconds * 4 * 1000
            max_range_ms = 719 * 3600 * 1000
            from_timestamp = now_ms - min(window_ms, max_range_ms)

        args: dict[str, Any] = {
            "symbolId": symbol_id,
            "period": period,
            "fromTimestamp": str(from_timestamp),
            "toTimestamp": str(now_ms),
            "count": count,
        }
        res = self.call_tool("get_trendbars", args)
        if isinstance(res, dict):
            return res.get("trendbars", [])
        return []

    def create_market_order(
        self,
        symbol_id: int,
        trade_side: str,
        volume: int,
        relative_sl: int,
        relative_tp: int,
        comment: str = "",
        label: str = "",
    ) -> dict[str, Any]:
        """Submit a market order."""
        args = {
            "symbolId": symbol_id,
            "orderType": "MARKET",
            "tradeSide": trade_side.upper(),
            "volume": volume,
            "relativeStopLoss": relative_sl,
            "relativeTakeProfit": relative_tp,
            "comment": comment,
            "label": label,
        }
        return self.call_tool("create_order", args)

    def amend_position(self, position_id: int, stop_loss: float, take_profit: Optional[float] = None) -> dict[str, Any]:
        """Amend position Stop Loss and Take Profit."""
        args: dict[str, Any] = {"positionId": position_id, "stopLoss": stop_loss}
        if take_profit is not None:
            args["takeProfit"] = take_profit
        return self.call_tool("amend_position", args)

    def close_position(self, position_id: int, volume: int) -> dict[str, Any]:
        """Close an open position."""
        return self.call_tool("close_position", {"positionId": position_id, "volume": volume})
