"""
Google Drive Client Adapter.
Handles authentication, folder structure navigation/creation, and file upload/update.
Supports Google Service Account (file or env JSON/base64) and OAuth2 Refresh Token.
Degrades gracefully if Google Drive is disabled or unauthorized.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("GoogleDriveClient")

DEFAULT_ROOT_FOLDER_ID = "1pEn5CK-qeXuPQYbbVc6KMNjbjTGwvn5I"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]


class GoogleDriveClient:
    """Production client for Google Drive Evidence Archival."""

    def __init__(
        self,
        folder_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        credentials: Optional[Any] = None,
        drive_service: Optional[Any] = None,
    ):
        self.root_folder_id = folder_id or os.environ.get("GOOGLE_DRIVE_FOLDER_ID", DEFAULT_ROOT_FOLDER_ID)
        self.enabled = (
            enabled
            if enabled is not None
            else os.environ.get("GOOGLE_DRIVE_ENABLED", "false").strip().lower() in ("true", "1", "yes", "on")
        )
        self.service = drive_service
        self.credentials = credentials
        self._folder_cache: Dict[str, str] = {}
        self.auth_status = "NOT_CONFIGURED"
        self.last_error: Optional[str] = None

        if self.enabled and not self.service:
            self._authenticate()

    def _authenticate(self) -> bool:
        """Authenticate via Service Account JSON or OAuth2 Refresh Token."""
        if not self.enabled:
            self.auth_status = "DISABLED"
            return False

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError:
            self.auth_status = "MISSING_DEPENDENCY"
            self.last_error = "google-auth or google-api-python-client is not installed"
            logger.warning("Google Drive client disabled: %s", self.last_error)
            return False

        # 1. Service Account from Environment Variable (raw JSON or base64)
        sa_json_env = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if sa_json_env:
            try:
                # Try decoding base64 if it does not start with '{'
                clean_env = sa_json_env.strip()
                if not clean_env.startswith("{"):
                    clean_env = base64.b64decode(clean_env).decode("utf-8")
                info = json.loads(clean_env)
                self.credentials = service_account.Credentials.from_service_account_info(
                    info, scopes=DRIVE_SCOPES
                )
                self.service = build("drive", "v3", credentials=self.credentials, cache_discovery=False)
                self.auth_status = "CONFIGURED"
                logger.info("Authenticated Google Drive via GOOGLE_SERVICE_ACCOUNT_JSON")
                return True
            except Exception as e:
                self.auth_status = "AUTH_FAILED"
                self.last_error = f"Invalid GOOGLE_SERVICE_ACCOUNT_JSON: {e}"
                logger.error(self.last_error)
                return False

        # 2. Service Account from File Path
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if creds_path and os.path.exists(creds_path):
            try:
                self.credentials = service_account.Credentials.from_service_account_file(
                    creds_path, scopes=DRIVE_SCOPES
                )
                self.service = build("drive", "v3", credentials=self.credentials, cache_discovery=False)
                self.auth_status = "CONFIGURED"
                logger.info("Authenticated Google Drive via credentials file: %s", creds_path)
                return True
            except Exception as e:
                self.auth_status = "AUTH_FAILED"
                self.last_error = f"Failed to load credentials file: {e}"
                logger.error(self.last_error)
                return False

        # 3. OAuth2 Refresh Token
        refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        if refresh_token and client_id and client_secret:
            try:
                from google.oauth2.credentials import Credentials
                self.credentials = Credentials(
                    token=None,
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=DRIVE_SCOPES,
                )
                self.service = build("drive", "v3", credentials=self.credentials, cache_discovery=False)
                self.auth_status = "CONFIGURED"
                logger.info("Authenticated Google Drive via OAuth2 refresh token")
                return True
            except Exception as e:
                self.auth_status = "AUTH_FAILED"
                self.last_error = f"Failed to build OAuth2 credentials: {e}"
                logger.error(self.last_error)
                return False

        self.auth_status = "NOT_CONFIGURED"
        self.last_error = "No Google Drive credentials configured (requires GOOGLE_SERVICE_ACCOUNT_JSON or credentials file)"
        logger.info("Google Drive is enabled but credentials are not yet configured.")
        return False

    def is_operational(self) -> bool:
        """Check if Drive client is enabled and authenticated."""
        return self.enabled and self.service is not None

    def get_or_create_subfolder(self, folder_name: str, parent_id: str) -> str:
        """Find or create a subfolder inside parent_id."""
        cache_key = f"{parent_id}/{folder_name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        query = (
            f"'{parent_id}' in parents and name = '{folder_name}' and "
            f"mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        response = self.service.files().list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        files = response.get("files", [])
        if files:
            fid = files[0]["id"]
            self._folder_cache[cache_key] = fid
            return fid

        # Create folder
        meta = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        folder = self.service.files().create(
            body=meta,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        fid = folder.get("id")
        self._folder_cache[cache_key] = fid
        return fid

    def resolve_folder_path(self, relative_folder_path: str) -> str:
        """
        Resolve path hierarchy under root_folder_id.
        e.g. 'TradingBot/runtime_logs/2026-09-25' -> target folder ID.
        """
        parts = [p for p in relative_folder_path.strip("/").split("/") if p]
        current_parent = self.root_folder_id

        path_acc = ""
        for part in parts:
            path_acc = f"{path_acc}/{part}" if path_acc else part
            current_parent = self.get_or_create_subfolder(part, current_parent)

        return current_parent

    def upload_file(
        self,
        local_file_path: Path,
        relative_folder_path: str,
        mime_type: str = "text/plain",
    ) -> Dict[str, Any]:
        """
        Upload or update a file in the target Google Drive folder.
        Uses MediaFileUpload for chunked/resumable upload.
        """
        if not self.is_operational():
            raise RuntimeError(f"Google Drive client not operational (status: {self.auth_status})")

        from googleapiclient.http import MediaFileUpload

        target_folder_id = self.resolve_folder_path(relative_folder_path)
        file_name = local_file_path.name

        # Check if file already exists in target folder
        query = (
            f"'{target_folder_id}' in parents and name = '{file_name}' and trashed = false"
        )
        response = self.service.files().list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        existing_files = response.get("files", [])
        media = MediaFileUpload(str(local_file_path), mimetype=mime_type, resumable=True)

        if existing_files:
            file_id = existing_files[0]["id"]
            updated = self.service.files().update(
                fileId=file_id,
                media_body=media,
                fields="id, name, modifiedTime, size",
                supportsAllDrives=True,
            ).execute()
            return {"action": "UPDATED", "file_id": updated.get("id"), "details": updated}
        else:
            meta = {
                "name": file_name,
                "parents": [target_folder_id],
            }
            created = self.service.files().create(
                body=meta,
                media_body=media,
                fields="id, name, createdTime, size",
                supportsAllDrives=True,
            ).execute()
            return {"action": "CREATED", "file_id": created.get("id"), "details": created}
