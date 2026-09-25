"""
Unit and integration tests for Google Drive Trading Evidence Archive.
Tests local durable writing, redaction, trade ledger, daily summary,
queue persistence, drive client hierarchy resolution, uploader retry/backoff,
and retention cleanup.
"""
import asyncio
import base64
import csv
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.services.evidence.collector import EvidenceCollector
from src.services.evidence.gdrive_client import DEFAULT_ROOT_FOLDER_ID, GoogleDriveClient
from src.services.evidence.models import DailySummary, EvidenceQueueItem, RuntimeEvent, TradeRecord
from src.services.evidence.uploader import EvidenceUploader


@pytest.fixture
def temp_evidence_dir():
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestEvidenceCollector:
    def test_directory_initialization(self, temp_evidence_dir):
        collector = EvidenceCollector(base_dir=str(temp_evidence_dir))
        assert collector.evidence_dir.exists()
        assert collector.queue_file == temp_evidence_dir / "upload_queue.json"

    def test_sanitize_secrets(self):
        dirty = {
            "api_key": "secret_key_12345",
            "access_token": "bearer eyJhbGciOi...",
            "password": "SuperSecretPassword!",
            "normal_field": "safe_value",
            "nested": {
                "client_secret": "my_client_secret",
                "price": 1.2345,
            },
            "array_field": [
                {"token": "tok_abc"},
                "Bearer secret_bearer_token",
                "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASC",
                "regular_string",
            ],
        }
        clean = EvidenceCollector.sanitize(dirty)
        assert clean["api_key"] == "[REDACTED]"
        assert clean["access_token"] == "[REDACTED]"
        assert clean["password"] == "[REDACTED]"
        assert clean["normal_field"] == "safe_value"
        assert clean["nested"]["client_secret"] == "[REDACTED]"
        assert clean["nested"]["price"] == 1.2345
        assert clean["array_field"][0]["token"] == "[REDACTED]"
        assert clean["array_field"][1] == "[REDACTED]"
        assert clean["array_field"][2] == "[REDACTED]"
        assert clean["array_field"][3] == "regular_string"

    def test_record_runtime_event(self, temp_evidence_dir):
        collector = EvidenceCollector(base_dir=str(temp_evidence_dir))
        ev = collector.record_runtime_event(
            event_type="ORDER_SUBMITTED",
            symbol="EURUSD",
            direction="BUY",
            strategy_version="FOREX_TREND_BREAKOUT_V1",
            order_id="ORD123",
            position_id="POS456",
            trade_id="TRD789",
            status="SUBMITTED",
            payload={"volume": 0.05, "secret_key": "topsecret"},
            timestamp_utc="2026-09-25T10:00:00+00:00",
        )

        assert ev.event_type == "ORDER_SUBMITTED"
        assert ev.payload["secret_key"] == "[REDACTED]"

        date_str = "2026-09-25"
        expected_file = temp_evidence_dir / "runtime_logs" / date_str / f"runtime_{date_str}.jsonl"
        assert expected_file.exists()

        lines = expected_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["symbol"] == "EURUSD"
        assert record["order_id"] == "ORD123"

        # Check queue
        queue = collector._load_queue()
        rel_path = f"runtime_logs/{date_str}/runtime_{date_str}.jsonl"
        assert rel_path in queue
        assert queue[rel_path]["status"] == "PENDING"

    def test_record_trade_and_update_exit(self, temp_evidence_dir):
        collector = EvidenceCollector(base_dir=str(temp_evidence_dir))
        now_utc = "2026-09-25T12:00:00+00:00"

        trade = TradeRecord(
            trade_id="TRD_001",
            symbol="GBPUSD",
            direction="SELL",
            signal_time_utc=now_utc,
            order_time_utc=now_utc,
            entry_time_utc=now_utc,
            entry_price=1.3245,
            volume=0.1,
            stop_loss=1.3280,
            take_profit=1.3175,
            risk_amount=35.0,
            order_id="ORD_999",
            position_id="POS_888",
            strategy_version="FOREX_TREND_BREAKOUT_V1",
            ai_decision="APPROVE",
            ai_confidence=0.88,
            gate_result="PASSED",
            risk_result="APPROVED",
        )

        collector.record_trade(trade)

        date_str = "2026-09-25"
        jsonl_file = temp_evidence_dir / "trades" / date_str / f"trade_ledger_{date_str}.jsonl"
        csv_file = temp_evidence_dir / "trades" / date_str / f"trade_ledger_{date_str}.csv"

        assert jsonl_file.exists()
        assert csv_file.exists()

        # Verify CSV has correct header and values
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["trade_id"] == "TRD_001"
            assert rows[0]["symbol"] == "GBPUSD"
            assert float(rows[0]["entry_price"]) == 1.3245

        # Update trade exit
        exit_time = "2026-09-25T13:30:00+00:00"
        updated = collector.update_trade_exit(
            position_id="POS_888",
            exit_price=1.3200,
            exit_time=exit_time,
            close_reason="TAKE_PROFIT",
            gross_pnl=45.0,
            net_pnl=43.5,
            commission=-1.5,
            swap=0.0,
        )

        assert updated is not None
        assert updated.exit_price == 1.3200
        assert updated.close_reason == "TAKE_PROFIT"
        assert updated.net_pnl == 43.5
        assert updated.R_multiple == round(43.5 / 35.0, 2)

        # Check ledger files updated
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["close_reason"] == "TAKE_PROFIT"
            assert float(rows[0]["net_pnl"]) == 43.5
            assert float(rows[0]["R_multiple"]) == 1.24

    def test_generate_daily_summary(self, temp_evidence_dir):
        collector = EvidenceCollector(base_dir=str(temp_evidence_dir))
        date_str = "2026-09-25"

        collector.record_runtime_event("MARKET_DATA", symbol="EURUSD", timestamp_utc=f"{date_str}T08:00:00+00:00")
        collector.record_runtime_event("STRATEGY_SIGNAL", symbol="EURUSD", direction="LONG", timestamp_utc=f"{date_str}T08:05:00+00:00")
        collector.record_runtime_event("AI_DECISION", status="PROPOSAL_GENERATED", timestamp_utc=f"{date_str}T08:05:01+00:00")
        collector.record_runtime_event("DETERMINISTIC_GATE", status="APPROVED", timestamp_utc=f"{date_str}T08:05:02+00:00")
        collector.record_runtime_event("RISK_DECISION", status="APPROVED", timestamp_utc=f"{date_str}T08:05:03+00:00")
        collector.record_runtime_event("ORDER_SUBMITTED", status="SUBMITTED", timestamp_utc=f"{date_str}T08:05:04+00:00")

        # Win trade
        t1 = TradeRecord(
            trade_id="T1", symbol="EURUSD", direction="LONG",
            order_time_utc=f"{date_str}T08:05:04+00:00",
            exit_time_utc=f"{date_str}T09:00:00+00:00",
            gross_pnl=50.0, net_pnl=48.0, commission=-2.0, risk_amount=25.0, R_multiple=1.92,
        )
        collector.record_trade(t1)

        # Loss trade
        t2 = TradeRecord(
            trade_id="T2", symbol="GBPUSD", direction="SHORT",
            order_time_utc=f"{date_str}T10:00:00+00:00",
            exit_time_utc=f"{date_str}T11:00:00+00:00",
            gross_pnl=-25.0, net_pnl=-26.0, commission=-1.0, risk_amount=25.0, R_multiple=-1.04,
        )
        collector.record_trade(t2)

        summary = collector.generate_daily_summary(date_str=date_str)
        assert summary.date_utc == date_str
        assert summary.market_data_events == 1
        assert summary.strategy_signals == 1
        assert summary.orders_submitted == 1
        assert summary.positions_opened == 2
        assert summary.positions_closed == 2
        assert summary.wins == 1
        assert summary.losses == 1
        assert summary.win_rate == 0.5
        assert summary.net_pnl == 22.0
        assert summary.gross_pnl == 25.0
        assert summary.profit_factor == 2.0  # 50.0 / 25.0
        assert summary.average_R == round((1.92 - 1.04) / 2, 2)

        summary_file = temp_evidence_dir / "daily_reports" / date_str / f"daily_summary_{date_str}.json"
        assert summary_file.exists()


class TestGoogleDriveClient:
    def test_default_config(self):
        client = GoogleDriveClient(folder_id="custom_folder_id", enabled=False)
        assert client.root_folder_id == "custom_folder_id"
        assert not client.enabled
        assert not client.is_operational()

    def test_default_folder_id_fallback(self):
        client = GoogleDriveClient(enabled=False)
        assert client.root_folder_id == DEFAULT_ROOT_FOLDER_ID

    def test_subfolder_creation_and_caching(self):
        mock_service = MagicMock()
        mock_files = mock_service.files.return_value
        # First query returns empty (folder not found) -> create called -> returns {"id": "sub_123"}
        mock_files.list.return_value.execute.return_value = {"files": []}
        mock_files.create.return_value.execute.return_value = {"id": "sub_123"}

        client = GoogleDriveClient(folder_id="root_abc", enabled=True, drive_service=mock_service)
        fid = client.get_or_create_subfolder("runtime_logs", "root_abc")
        assert fid == "sub_123"

        # Second call should use cache without hitting API
        mock_files.list.reset_mock()
        mock_files.create.reset_mock()
        fid_cached = client.get_or_create_subfolder("runtime_logs", "root_abc")
        assert fid_cached == "sub_123"
        assert not mock_files.list.called
        assert not mock_files.create.called

    def test_resolve_folder_path_hierarchy(self):
        mock_service = MagicMock()
        mock_files = mock_service.files.return_value
        mock_files.list.return_value.execute.return_value = {"files": [{"id": "resolved_id"}]}

        client = GoogleDriveClient(folder_id="root_abc", enabled=True, drive_service=mock_service)
        final_id = client.resolve_folder_path("TradingBot/runtime_logs/2026-09-25")
        assert final_id == "resolved_id"

    def test_upload_file_new_and_update(self, temp_evidence_dir):
        dummy_file = temp_evidence_dir / "test.jsonl"
        dummy_file.write_text('{"event": "TEST"}\n', encoding="utf-8")

        mock_service = MagicMock()
        mock_files = mock_service.files.return_value

        # 1. New file scenario
        mock_files.list.return_value.execute.return_value = {"files": []}
        mock_files.create.return_value.execute.return_value = {"id": "drive_file_001"}

        client = GoogleDriveClient(folder_id="root_abc", enabled=True, drive_service=mock_service)
        res_create = client.upload_file(dummy_file, "TradingBot/test/2026-09-25", "application/json")
        assert res_create["action"] == "CREATED"
        assert res_create["file_id"] == "drive_file_001"

        # 2. Existing file scenario (update)
        mock_files.list.return_value.execute.return_value = {"files": [{"id": "drive_file_001"}]}
        mock_files.update.return_value.execute.return_value = {"id": "drive_file_001"}

        res_update = client.upload_file(dummy_file, "TradingBot/test/2026-09-25", "application/json")
        assert res_update["action"] == "UPDATED"
        assert res_update["file_id"] == "drive_file_001"


class TestEvidenceUploader:
    def test_uploader_does_not_upload_when_disabled(self, temp_evidence_dir):
        collector = EvidenceCollector(base_dir=str(temp_evidence_dir))
        collector.record_runtime_event("MARKET_DATA", symbol="EURUSD")

        drive_client = GoogleDriveClient(enabled=False)
        uploader = EvidenceUploader(collector=collector, gdrive_client=drive_client)

        count = asyncio.run(uploader.process_batch())
        assert count == 0

        queue = collector._load_queue()
        assert any(item["status"] == "PENDING" for item in queue.values())

    def test_uploader_processes_batch_successfully(self, temp_evidence_dir):
        collector = EvidenceCollector(base_dir=str(temp_evidence_dir))
        collector.record_runtime_event("MARKET_DATA", symbol="EURUSD")

        mock_service = MagicMock()
        mock_files = mock_service.files.return_value
        mock_files.list.return_value.execute.return_value = {"files": []}
        mock_files.create.return_value.execute.return_value = {"id": "uploaded_123"}

        drive_client = GoogleDriveClient(folder_id="root_abc", enabled=True, drive_service=mock_service)
        uploader = EvidenceUploader(collector=collector, gdrive_client=drive_client)

        count = asyncio.run(uploader.process_batch())
        assert count > 0
        assert uploader.total_uploads_success == count

        queue = collector._load_queue()
        for item in queue.values():
            assert item["status"] == "UPLOADED"
            assert item["retry_count"] == 0

    def test_uploader_exponential_backoff_on_failure(self, temp_evidence_dir):
        collector = EvidenceCollector(base_dir=str(temp_evidence_dir))
        collector.record_runtime_event("MARKET_DATA", symbol="EURUSD")

        mock_service = MagicMock()
        mock_files = mock_service.files.return_value
        mock_files.list.side_effect = ConnectionError("Drive network unreachable")

        drive_client = GoogleDriveClient(folder_id="root_abc", enabled=True, drive_service=mock_service)
        uploader = EvidenceUploader(collector=collector, gdrive_client=drive_client)

        with patch("asyncio.sleep", return_value=None) as mock_sleep:
            count = asyncio.run(uploader.process_batch())
            assert count == 0
            assert uploader.total_uploads_failed >= 1
            assert mock_sleep.called

        queue = collector._load_queue()
        for item in queue.values():
            assert item["status"] == "FAILED"
            assert item["retry_count"] >= 1
            assert "Drive network unreachable" in item["last_error"]

    def test_retention_policy_preserves_unsent_files(self, temp_evidence_dir):
        collector = EvidenceCollector(base_dir=str(temp_evidence_dir))
        drive_client = GoogleDriveClient(enabled=False)
        uploader = EvidenceUploader(collector=collector, gdrive_client=drive_client, local_retention_days=30)

        # Create old file (40 days ago) that was NOT uploaded
        old_date = (datetime.now(tz=timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%d")
        old_dir = temp_evidence_dir / "runtime_logs" / old_date
        old_dir.mkdir(parents=True, exist_ok=True)
        old_file = old_dir / f"runtime_{old_date}.jsonl"
        old_file.write_text('{"event": "OLD_UNSENT"}\n', encoding="utf-8")

        collector._enqueue_file(f"runtime_logs/{old_date}/runtime_{old_date}.jsonl", "runtime_logs", old_date, old_file.name)

        # Retention run
        deleted = uploader.apply_retention()
        assert deleted == 0
        assert old_file.exists(), "Unsent evidence must NEVER be deleted by retention policy!"

        # Now mark as UPLOADED and verify retention deletes it
        queue = collector._load_queue()
        queue[f"runtime_logs/{old_date}/runtime_{old_date}.jsonl"]["status"] = "UPLOADED"
        collector._save_queue(queue)

        deleted_uploaded = uploader.apply_retention()
        assert deleted_uploaded == 1
        assert not old_file.exists()
