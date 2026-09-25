"""
Asynchronous Evidence Uploader Service.
Runs as a decoupled background worker. Processes local evidence queue in batches,
uploads to Google Drive, handles retries with exponential backoff, and ensures
that network/drive errors never impact the trading execution pipeline.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.services.evidence.collector import EvidenceCollector
from src.services.evidence.gdrive_client import GoogleDriveClient

logger = logging.getLogger("EvidenceUploader")


class EvidenceUploader:
    """Decoupled background worker for Google Drive Evidence Archival."""

    def __init__(
        self,
        collector: EvidenceCollector,
        gdrive_client: Optional[GoogleDriveClient] = None,
        batch_interval_seconds: float = 30.0,
        max_batch_size: int = 20,
        local_retention_days: int = 30,
    ):
        self.collector = collector
        self.client = gdrive_client or GoogleDriveClient()
        self.batch_interval = float(os.environ.get("GDRIVE_UPLOAD_INTERVAL_SECONDS", batch_interval_seconds))
        self.max_batch_size = int(os.environ.get("GDRIVE_BATCH_SIZE", max_batch_size))
        self.local_retention_days = int(os.environ.get("LOCAL_EVIDENCE_RETENTION_DAYS", local_retention_days))

        self._shutdown_event: Optional[asyncio.Event] = None
        self._backoff_delay = 5.0
        self._max_backoff = 300.0

        # Telemetry metrics
        self.last_successful_upload_utc: Optional[str] = None
        self.last_upload_error: Optional[str] = None
        self.pending_upload_count: int = 0
        self.total_uploads_success: int = 0
        self.total_uploads_failed: int = 0

    @property
    def shutdown_event(self) -> asyncio.Event:
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()
        return self._shutdown_event

    def get_telemetry(self) -> Dict[str, Any]:
        """Return non-sensitive observability metrics for health monitoring."""
        return {
            "google_drive_enabled": self.client.enabled,
            "auth_status": self.client.auth_status,
            "last_successful_upload_utc": self.last_successful_upload_utc,
            "pending_upload_count": self.pending_upload_count,
            "last_upload_error": self.last_upload_error,
            "total_uploads_success": self.total_uploads_success,
            "total_uploads_failed": self.total_uploads_failed,
        }

    async def start(self) -> None:
        """Run upload loop in background until stopped."""
        logger.info(
            "EvidenceUploader worker started (enabled=%s, interval=%.1fs, retention=%dd)",
            self.client.enabled,
            self.batch_interval,
            self.local_retention_days,
        )

        while not self.shutdown_event.is_set():
            try:
                await self.process_batch()
            except Exception as e:
                logger.error("Unexpected error in EvidenceUploader worker: %s", e)

            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=self.batch_interval)
            except asyncio.TimeoutError:
                pass

        logger.info("EvidenceUploader worker stopped.")

    def stop(self) -> None:
        self.shutdown_event.set()

    async def process_batch(self) -> int:
        """Process one batch of pending uploads."""
        queue = self.collector._load_queue()
        pending_items = [
            (path, item)
            for path, item in queue.items()
            if item.get("status") in ("PENDING", "FAILED")
        ]
        self.pending_upload_count = len(pending_items)

        if not self.client.enabled:
            return 0

        if not self.client.is_operational():
            if self.client.auth_status == "NOT_CONFIGURED":
                # Try re-authenticating once in case credentials were added
                self.client._authenticate()
            if not self.client.is_operational():
                return 0

        if not pending_items:
            return 0

        logger.info(
            json.dumps({
                "event": "GDRIVE_QUEUE_PENDING",
                "pending_count": len(pending_items),
                "batch_size": min(len(pending_items), self.max_batch_size),
            })
        )

        uploaded_in_batch = 0
        batch_slice = pending_items[: self.max_batch_size]

        for rel_path, item in batch_slice:
            if self.shutdown_event.is_set():
                break

            local_file = self.collector.evidence_dir / rel_path
            if not local_file.exists():
                logger.warning("Local evidence file missing: %s. Removing from queue.", rel_path)
                queue.pop(rel_path, None)
                continue

            category = item.get("category", "runtime_logs")
            date_str = item.get("date_str", datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"))
            folder_hierarchy = f"TradingBot/{category}/{date_str}"
            mime_type = "text/csv" if local_file.suffix == ".csv" else "application/json"

            logger.info(
                json.dumps({
                    "event": "GDRIVE_UPLOAD_START",
                    "file": local_file.name,
                    "target_folder": folder_hierarchy,
                })
            )

            try:
                # Offload blocking synchronous Drive API call to executor
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    self.client.upload_file,
                    local_file,
                    folder_hierarchy,
                    mime_type,
                )

                now_iso = datetime.now(tz=timezone.utc).isoformat()
                item["status"] = "UPLOADED"
                item["last_upload_time"] = now_iso
                item["retry_count"] = 0
                item["last_error"] = None

                self.last_successful_upload_utc = now_iso
                self.total_uploads_success += 1
                uploaded_in_batch += 1
                self._backoff_delay = 5.0  # Reset backoff on success

                logger.info(
                    json.dumps({
                        "event": "GDRIVE_UPLOAD_SUCCESS",
                        "file": local_file.name,
                        "action": result.get("action"),
                        "file_id": result.get("file_id"),
                    })
                )
            except Exception as e:
                err_msg = str(e)
                item["status"] = "FAILED"
                item["retry_count"] = item.get("retry_count", 0) + 1
                item["last_error"] = err_msg

                self.last_upload_error = err_msg
                self.total_uploads_failed += 1

                logger.warning(
                    json.dumps({
                        "event": "GDRIVE_UPLOAD_FAILED",
                        "file": local_file.name,
                        "retry_count": item["retry_count"],
                        "error": err_msg,
                    })
                )

                # Exponential backoff on failure
                await asyncio.sleep(self._backoff_delay)
                self._backoff_delay = min(self._backoff_delay * 2.0, self._max_backoff)

        self.collector._save_queue(queue)
        self.pending_upload_count = sum(1 for q in queue.values() if q.get("status") != "UPLOADED")

        # Periodically apply local retention policy
        self.apply_retention()

        return uploaded_in_batch

    def apply_retention(self) -> int:
        """
        Enforce local file retention.
        Removes files older than LOCAL_EVIDENCE_RETENTION_DAYS only if they are UPLOADED.
        NEVER deletes unsent evidence!
        """
        if self.local_retention_days <= 0:
            return 0

        queue = self.collector._load_queue()
        cutoff_date = (datetime.now(tz=timezone.utc) - timedelta(days=self.local_retention_days)).strftime("%Y-%m-%d")
        deleted_count = 0

        for rel_path, item in list(queue.items()):
            date_str = item.get("date_str", "")
            # Only remove if older than cutoff AND upload status is UPLOADED
            if date_str and date_str < cutoff_date and item.get("status") == "UPLOADED":
                local_file = self.collector.evidence_dir / rel_path
                if local_file.exists():
                    try:
                        local_file.unlink()
                        deleted_count += 1
                        logger.info("Retained/deleted local uploaded evidence file: %s", rel_path)
                    except Exception as e:
                        logger.warning("Failed to delete expired evidence file %s: %s", rel_path, e)
                queue.pop(rel_path, None)

        if deleted_count > 0:
            self.collector._save_queue(queue)

        return deleted_count
