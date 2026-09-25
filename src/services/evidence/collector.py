"""
Evidence Collector Service.
Appends all trading runtime logs, decision traces, trade ledger entries,
reconciliation events, and health metrics locally before asynchronous upload.
Applies strict secret redaction and prevents duplicates.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.services.evidence.models import (
    DailySummary,
    EvidenceQueueItem,
    RuntimeEvent,
    TradeRecord,
)

logger = logging.getLogger("EvidenceCollector")


def get_git_sha() -> str:
    """Safely obtain current git commit SHA without failing."""
    sha = os.environ.get("GIT_SHA") or os.environ.get("RAILWAY_GIT_COMMIT_SHA")
    if sha:
        return sha[:40]
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
        return out[:40]
    except Exception:
        return "UNKNOWN"


class EvidenceCollector:
    """Collects and stores durable trading evidence locally with daily rotation."""

    def __init__(self, base_dir: Optional[str] = None):
        state_dir = os.environ.get("STATE_DIR", "./state")
        self.evidence_dir = Path(base_dir or (Path(state_dir) / "evidence"))
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.queue_file = self.evidence_dir / "upload_queue.json"
        self._git_sha = get_git_sha()

        # In-memory index of open trades by position_id/order_id for reconciliation updates
        self._active_trades: Dict[str, TradeRecord] = {}
        self._load_active_trades()

    def _load_active_trades(self) -> None:
        """Scan current day's trade ledger to recover active/open trades across restarts."""
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        trades_file = self.evidence_dir / "trades" / today / f"trade_ledger_{today}.jsonl"
        if trades_file.exists():
            try:
                for line in trades_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        data = json.loads(line)
                        trade = TradeRecord(**data)
                        if trade.position_id and not trade.exit_time_utc:
                            self._active_trades[trade.position_id] = trade
            except Exception as e:
                logger.warning("Failed to load active trade index: %s", e)

    @staticmethod
    def sanitize(data: Any) -> Any:
        """Recursively redact secrets, tokens, and passwords."""
        if isinstance(data, dict):
            clean = {}
            for k, v in data.items():
                k_lower = str(k).lower()
                if any(s in k_lower for s in ["token", "key", "secret", "password", "auth", "credential", "bearer"]):
                    clean[k] = "[REDACTED]"
                else:
                    clean[k] = EvidenceCollector.sanitize(v)
            return clean
        elif isinstance(data, list):
            return [EvidenceCollector.sanitize(x) for x in data]
        elif isinstance(data, str):
            if "bearer " in data.lower() or "-----BEGIN" in data:
                return "[REDACTED]"
            return data
        return data

    def _get_target_dir(self, category: str, date_str: str) -> Path:
        target = self.evidence_dir / category / date_str
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _enqueue_file(self, rel_path: str, category: str, date_str: str, file_name: str) -> None:
        """Track file in durable upload queue."""
        queue = self._load_queue()
        now_str = datetime.now(tz=timezone.utc).isoformat()
        if rel_path not in queue:
            queue[rel_path] = asdict(
                EvidenceQueueItem(
                    rel_path=rel_path,
                    category=category,
                    date_str=date_str,
                    file_name=file_name,
                    last_modified=now_str,
                    status="PENDING",
                )
            )
        else:
            queue[rel_path]["last_modified"] = now_str
            if queue[rel_path]["status"] == "UPLOADED":
                queue[rel_path]["status"] = "PENDING"
        self._save_queue(queue)

    def _load_queue(self) -> Dict[str, Dict[str, Any]]:
        if self.queue_file.exists():
            try:
                return json.loads(self.queue_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_queue(self, queue: Dict[str, Dict[str, Any]]) -> None:
        tmp = self.queue_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(queue, indent=2), encoding="utf-8")
        tmp.replace(self.queue_file)

    def record_runtime_event(
        self,
        event_type: str,
        symbol: Optional[str] = None,
        direction: Optional[str] = None,
        strategy_version: Optional[str] = None,
        order_id: Optional[str] = None,
        position_id: Optional[str] = None,
        trade_id: Optional[str] = None,
        status: Optional[str] = None,
        reason: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        reconciliation_state: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        timestamp_utc: Optional[str] = None,
        bot_git_sha: Optional[str] = None,
    ) -> RuntimeEvent:
        """Record structured runtime event into daily JSONL."""
        now = datetime.now(tz=timezone.utc)
        ts_str = timestamp_utc or now.isoformat()
        date_str = ts_str[:10]

        event = RuntimeEvent(
            timestamp_utc=ts_str,
            event_type=event_type,
            symbol=symbol,
            direction=direction,
            strategy_version=strategy_version,
            bot_git_sha=bot_git_sha or self._git_sha,
            order_id=order_id,
            position_id=position_id,
            trade_id=trade_id,
            status=status,
            reason=reason,
            error_code=error_code,
            error_message=error_message,
            reconciliation_state=reconciliation_state,
            payload=self.sanitize(payload or {}),
        )

        dir_path = self._get_target_dir("runtime_logs", date_str)
        file_name = f"runtime_{date_str}.jsonl"
        file_path = dir_path / file_name

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(event.to_json() + "\n")

        rel_path = f"runtime_logs/{date_str}/{file_name}"
        self._enqueue_file(rel_path, "runtime_logs", date_str, file_name)
        return event

    def record_decision(self, trace_record: Dict[str, Any]) -> None:
        """Append decision trace to daily decision JSONL."""
        ts_str = trace_record.get("timestamp") or datetime.now(tz=timezone.utc).isoformat()
        date_str = ts_str[:10]
        sanitized = self.sanitize(trace_record)

        dir_path = self._get_target_dir("decisions", date_str)
        file_name = f"decisions_{date_str}.jsonl"
        file_path = dir_path / file_name

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(sanitized) + "\n")

        rel_path = f"decisions/{date_str}/{file_name}"
        self._enqueue_file(rel_path, "decisions", date_str, file_name)

    def record_trade(self, trade: TradeRecord) -> None:
        """Add or update trade in daily ledger (both JSONL and CSV)."""
        date_str = (trade.order_time_utc or trade.signal_time_utc or datetime.now(tz=timezone.utc).isoformat())[:10]
        dir_path = self._get_target_dir("trades", date_str)

        jsonl_name = f"trade_ledger_{date_str}.jsonl"
        csv_name = f"trade_ledger_{date_str}.csv"
        jsonl_path = dir_path / jsonl_name
        csv_path = dir_path / csv_name

        trade.bot_git_sha = trade.bot_git_sha or self._git_sha
        if trade.position_id:
            self._active_trades[trade.position_id] = trade

        # Load all existing trades for today to update/deduplicate deterministically
        trades_map: Dict[str, TradeRecord] = {}
        if jsonl_path.exists():
            for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    t = TradeRecord(**item)
                    trades_map[t.trade_id] = t

        trades_map[trade.trade_id] = trade

        # Write atomic JSONL
        tmp_jsonl = jsonl_path.with_suffix(".tmp")
        with open(tmp_jsonl, "w", encoding="utf-8") as f:
            for t in trades_map.values():
                f.write(t.to_json() + "\n")
        tmp_jsonl.replace(jsonl_path)

        # Write atomic CSV
        tmp_csv = csv_path.with_suffix(".tmp")
        with open(tmp_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=TradeRecord.csv_fieldnames())
            writer.writeheader()
            for t in trades_map.values():
                writer.writerow(t.to_dict())
        tmp_csv.replace(csv_path)

        self._enqueue_file(f"trades/{date_str}/{jsonl_name}", "trades", date_str, jsonl_name)
        self._enqueue_file(f"trades/{date_str}/{csv_name}", "trades", date_str, csv_name)

    def update_trade_exit(
        self,
        position_id: str,
        exit_price: float,
        exit_time: str,
        close_reason: str,
        gross_pnl: float,
        net_pnl: float,
        commission: float = 0.0,
        swap: float = 0.0,
        source: str = "BROKER_RECONCILIATION",
    ) -> Optional[TradeRecord]:
        """Update existing trade record with broker-authoritative exit values."""
        trade = self._active_trades.get(position_id)
        if not trade:
            # Check if there is an existing trade in today's files
            today = exit_time[:10]
            jsonl_path = self.evidence_dir / "trades" / today / f"trade_ledger_{today}.jsonl"
            if jsonl_path.exists():
                for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        t_data = json.loads(line)
                        if str(t_data.get("position_id")) == str(position_id):
                            trade = TradeRecord(**t_data)
                            break

        if trade:
            trade.exit_price = exit_price
            trade.exit_time_utc = exit_time
            trade.close_reason = close_reason
            trade.gross_pnl = gross_pnl
            trade.net_pnl = net_pnl
            trade.commission = commission
            trade.swap = swap
            trade.source = source
            if trade.risk_amount and trade.risk_amount > 0:
                trade.R_multiple = round(net_pnl / trade.risk_amount, 2)
            self.record_trade(trade)
            if position_id in self._active_trades:
                del self._active_trades[position_id]
            return trade
        return None

    def record_reconciliation(self, recon_data: Dict[str, Any]) -> None:
        """Record reconciliation event to daily JSONL."""
        now = datetime.now(tz=timezone.utc)
        ts_str = recon_data.get("reconciliation_time") or now.isoformat()
        date_str = ts_str[:10]
        sanitized = self.sanitize(recon_data)

        dir_path = self._get_target_dir("reconciliation", date_str)
        file_name = f"reconciliation_{date_str}.jsonl"
        file_path = dir_path / file_name

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(sanitized) + "\n")

        rel_path = f"reconciliation/{date_str}/{file_name}"
        self._enqueue_file(rel_path, "reconciliation", date_str, file_name)

    def record_health(self, health_data: Dict[str, Any]) -> None:
        """Record health telemetry snapshot to daily JSONL."""
        now = datetime.now(tz=timezone.utc)
        ts_str = health_data.get("last_heartbeat") or now.isoformat()
        date_str = ts_str[:10]
        sanitized = self.sanitize(health_data)

        dir_path = self._get_target_dir("health", date_str)
        file_name = f"health_telemetry_{date_str}.jsonl"
        file_path = dir_path / file_name

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(sanitized) + "\n")

        rel_path = f"health/{date_str}/{file_name}"
        self._enqueue_file(rel_path, "health", date_str, file_name)

    def generate_daily_summary(self, date_str: Optional[str] = None) -> DailySummary:
        """Compute and persist authoritative daily summary JSON."""
        target_date = date_str or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = DailySummary(
            date_utc=target_date,
            bot_git_sha=self._git_sha,
        )

        # 1. Inspect runtime logs for event counts
        runtime_file = self.evidence_dir / "runtime_logs" / target_date / f"runtime_{target_date}.jsonl"
        if runtime_file.exists():
            for line in runtime_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                    ev_type = ev.get("event_type", "")
                    if ev_type == "MARKET_DATA":
                        summary.market_data_events += 1
                    elif ev_type == "STRATEGY_SIGNAL":
                        summary.strategy_signals += 1
                    elif ev_type == "AI_DECISION":
                        if ev.get("status") == "PROPOSAL_GENERATED":
                            summary.ai_approved += 1
                        else:
                            summary.ai_rejected += 1
                    elif ev_type == "DETERMINISTIC_GATE":
                        if ev.get("status") == "REJECTED":
                            summary.gate_rejected += 1
                    elif ev_type == "RISK_DECISION":
                        if ev.get("status") == "APPROVED":
                            summary.risk_approved += 1
                        else:
                            summary.risk_rejected += 1
                    elif ev_type == "ORDER_SUBMITTED":
                        summary.orders_submitted += 1
                    elif ev_type == "ORDER_ACCEPTED":
                        summary.orders_accepted += 1
                    elif ev_type == "ORDER_REJECTED":
                        summary.orders_rejected += 1
                    elif ev_type == "BROKER_DISCONNECTED":
                        summary.broker_disconnects += 1
                    elif ev_type == "BROKER_RECONNECT":
                        summary.broker_reconnects += 1
                    elif ev_type == "ERROR":
                        summary.errors += 1
                except Exception:
                    pass

        # 2. Inspect trade ledger for PnL & trade performance
        trades_file = self.evidence_dir / "trades" / target_date / f"trade_ledger_{target_date}.jsonl"
        r_multiples: List[float] = []
        gross_wins = 0.0
        gross_losses = 0.0

        if trades_file.exists():
            for line in trades_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    t = json.loads(line)
                    summary.positions_opened += 1
                    if t.get("exit_time_utc"):
                        summary.positions_closed += 1
                        net = float(t.get("net_pnl") or 0.0)
                        gross = float(t.get("gross_pnl") or 0.0)
                        comm = float(t.get("commission") or 0.0)
                        sw = float(t.get("swap") or 0.0)

                        summary.net_pnl += net
                        summary.gross_pnl += gross
                        summary.commission += comm
                        summary.swap += sw

                        if net > 0:
                            summary.wins += 1
                            gross_wins += gross
                        else:
                            summary.losses += 1
                            gross_losses += abs(gross)

                        if t.get("R_multiple") is not None:
                            r_multiples.append(float(t["R_multiple"]))
                except Exception:
                    pass

        # Calculations
        closed_total = summary.wins + summary.losses
        if closed_total > 0:
            summary.win_rate = round(summary.wins / closed_total, 4)
            summary.profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (999.0 if gross_wins > 0 else 0.0)
        if r_multiples:
            summary.average_R = round(sum(r_multiples) / len(r_multiples), 2)

        # 3. Inspect reconciliation events
        recon_file = self.evidence_dir / "reconciliation" / target_date / f"reconciliation_{target_date}.jsonl"
        if recon_file.exists():
            for line in recon_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                    summary.reconciliation_count += 1
                    if r.get("status") != "IN_SYNC":
                        summary.reconciliation_mismatches += 1
                except Exception:
                    pass

        # 4. Count unsent evidence
        queue = self._load_queue()
        summary.unsent_evidence_count = sum(1 for q in queue.values() if q.get("status") != "UPLOADED")

        # Persist daily summary JSON
        dir_path = self._get_target_dir("daily_reports", target_date)
        file_name = f"daily_summary_{target_date}.json"
        file_path = dir_path / file_name

        tmp_path = file_path.with_suffix(".tmp")
        tmp_path.write_text(summary.to_json(), encoding="utf-8")
        tmp_path.replace(file_path)

        rel_path = f"daily_reports/{target_date}/{file_name}"
        self._enqueue_file(rel_path, "daily_reports", target_date, file_name)

        return summary
