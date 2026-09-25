"""
Data models for the Google Drive Trading Evidence Archive.
Defines schemas for runtime log events, trade ledger, and daily summaries.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class RuntimeEvent:
    timestamp_utc: str
    event_type: str
    symbol: Optional[str] = None
    direction: Optional[str] = None
    strategy_version: Optional[str] = None
    bot_git_sha: Optional[str] = None
    order_id: Optional[str] = None
    position_id: Optional[str] = None
    trade_id: Optional[str] = None
    status: Optional[str] = None
    reason: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    reconciliation_state: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))


@dataclass
class TradeRecord:
    trade_id: str
    symbol: str
    direction: str
    signal_time_utc: Optional[str] = None
    order_time_utc: Optional[str] = None
    entry_time_utc: Optional[str] = None
    entry_price: Optional[float] = None
    volume: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    exit_time_utc: Optional[str] = None
    exit_price: Optional[float] = None
    close_reason: Optional[str] = None
    gross_pnl: Optional[float] = None
    commission: Optional[float] = 0.0
    swap: Optional[float] = 0.0
    net_pnl: Optional[float] = None
    risk_amount: Optional[float] = None
    R_multiple: Optional[float] = None
    order_id: Optional[str] = None
    position_id: Optional[str] = None
    strategy_version: Optional[str] = None
    bot_git_sha: Optional[str] = None
    ai_decision: Optional[str] = None
    ai_confidence: Optional[float] = None
    gate_result: Optional[str] = None
    risk_result: Optional[str] = None
    source: str = "BOT_EVENT"  # BOT_EVENT, BROKER_RECONCILIATION, BROKER_HISTORY, DERIVED

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def csv_fieldnames(cls) -> List[str]:
        return [
            "trade_id",
            "symbol",
            "direction",
            "signal_time_utc",
            "order_time_utc",
            "entry_time_utc",
            "entry_price",
            "volume",
            "stop_loss",
            "take_profit",
            "exit_time_utc",
            "exit_price",
            "close_reason",
            "gross_pnl",
            "commission",
            "swap",
            "net_pnl",
            "risk_amount",
            "R_multiple",
            "order_id",
            "position_id",
            "strategy_version",
            "bot_git_sha",
            "ai_decision",
            "ai_confidence",
            "gate_result",
            "risk_result",
            "source",
        ]


@dataclass
class DailySummary:
    date_utc: str
    bot_git_sha: str
    runtime_duration: Optional[float] = None
    cycles: int = 0
    market_data_events: int = 0
    strategy_signals: int = 0
    ai_approved: int = 0
    ai_rejected: int = 0
    gate_rejected: int = 0
    risk_approved: int = 0
    risk_rejected: int = 0
    orders_submitted: int = 0
    orders_accepted: int = 0
    orders_rejected: int = 0
    positions_opened: int = 0
    positions_closed: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: Optional[float] = None
    gross_pnl: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    net_pnl: float = 0.0
    profit_factor: Optional[float] = None
    average_R: Optional[float] = None
    max_drawdown_if_existing_source_supports_it: Optional[float] = None
    broker_disconnects: int = 0
    broker_reconnects: int = 0
    errors: int = 0
    reconciliation_count: int = 0
    reconciliation_mismatches: int = 0
    google_drive_upload_success: int = 0
    google_drive_upload_failures: int = 0
    unsent_evidence_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class EvidenceQueueItem:
    rel_path: str               # e.g. "runtime_logs/2026-09-25/runtime_2026-09-25.jsonl"
    category: str               # "runtime_logs", "decisions", "trades", "daily_reports", "reconciliation", "health"
    date_str: str               # "2026-09-25"
    file_name: str              # "runtime_2026-09-25.jsonl"
    last_modified: str          # ISO timestamp
    last_uploaded_offset: int = 0  # For incremental/append tracking
    status: str = "PENDING"     # PENDING, UPLOADING, UPLOADED, FAILED
    retry_count: int = 0
    last_error: Optional[str] = None
    last_upload_time: Optional[str] = None
