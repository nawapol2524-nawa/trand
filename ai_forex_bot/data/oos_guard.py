"""
Hard OOS Access-Control Mechanism & Machine-Checkable Lock
=========================================================
Institutional Governance & Audit Standard for Gate 22R
Prevents unauthorized access, post-hoc optimization, and leakage into out-of-sample holdout sets.
"""

import os
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import pandas as pd

from ai_forex_bot.config.settings import settings


class OOSAccessViolation(Exception):
    """Raised whenever an unauthorized, unverified, or policy-violating OOS access is attempted."""
    pass


@dataclass
class OOSManifest:
    symbol: str
    timeframe: str
    oos_start: str
    oos_end: Optional[str]
    row_count: int
    dataset_sha256: str
    feature_pipeline_sha256: str
    label_pipeline_sha256: str
    splitter_sha256: str
    config_sha256: str
    git_commit_before_unlock: str
    candidate_manifest_hash: str
    creation_timestamp: str
    evaluation_session_id: Optional[str] = None
    consumed: bool = False
    status: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OOSManifest":
        known_fields = {
            "symbol", "timeframe", "oos_start", "oos_end", "row_count",
            "dataset_sha256", "feature_pipeline_sha256", "label_pipeline_sha256",
            "splitter_sha256", "config_sha256", "git_commit_before_unlock",
            "candidate_manifest_hash", "creation_timestamp", "evaluation_session_id",
            "consumed", "status"
        }
        init_args = {k: v for k, v in data.items() if k in known_fields}
        extra = {k: v for k, v in data.items() if k not in known_fields}
        return cls(**init_args, metadata=extra)


    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "OOSManifest":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def validate_dataframe(self, df: pd.DataFrame) -> None:
        """Validates dataframe integrity against cryptographic manifest constraints."""
        if len(df) != self.row_count:
            raise OOSAccessViolation(
                f"Row count mismatch: manifest expects {self.row_count}, got {len(df)}"
            )

        # Compute SHA256 of parquet bytes
        df_bytes = df.to_parquet()
        actual_hash = hashlib.sha256(df_bytes).hexdigest()
        if actual_hash != self.dataset_sha256:
            raise OOSAccessViolation(
                f"Dataset SHA-256 hash mismatch! Expected {self.dataset_sha256}, got {actual_hash}"
            )

        # Integrity check: Monotonic epochs & No duplicates
        epochs = df["epoch"].values
        if not (np_monotonic := (pd.Series(epochs).is_monotonic_increasing)):
            raise OOSAccessViolation("OOS data epochs are not strictly monotonically increasing")

        if len(epochs) != len(set(epochs)):
            raise OOSAccessViolation("Duplicate timestamp / overlapping OOS rows detected in dataset")

        # Synthetic check: Verify no synthetic flags or impossible test markers
        if "is_synthetic" in df.columns or "synthetic" in df.columns:
            raise OOSAccessViolation("Synthetic data detected! OOS evaluation strictly requires real market data")


@dataclass
class CandidateManifest:
    candidates: List[Dict[str, Any]]
    created_at: str
    git_commit: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def compute_hash(self) -> str:
        canonical_str = json.dumps(self.candidates, sort_keys=True)
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "candidates": self.candidates,
            "created_at": self.created_at,
            "git_commit": self.git_commit,
            "candidate_manifest_hash": self.compute_hash(),
            "metadata": self.metadata
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "CandidateManifest":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        inst = cls(
            candidates=data["candidates"],
            created_at=data["created_at"],
            git_commit=data["git_commit"],
            metadata=data.get("metadata", {})
        )
        # Verify tamper resistance
        recorded_hash = data.get("candidate_manifest_hash")
        actual_hash = inst.compute_hash()
        if recorded_hash and recorded_hash != actual_hash:
            raise OOSAccessViolation(
                f"Candidate manifest hash mismatch! File has been tampered with. Recorded: {recorded_hash}, Computed: {actual_hash}"
            )
        return inst


class OOSEvaluationSession:
    """One-time evaluation session token manager."""
    def __init__(
        self,
        session_id: str,
        token: str,
        candidate_manifest_path: Path,
        oos_manifest_path: Path,
        git_commit: str,
        created_at: Optional[str] = None
    ):
        self.session_id = session_id
        self.token = token
        self.candidate_manifest_path = Path(candidate_manifest_path)
        self.oos_manifest_path = Path(oos_manifest_path)
        self.git_commit = git_commit
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.is_open: bool = False
        self.consumed: bool = False

    def open_session(self) -> None:
        if self.consumed:
            raise OOSAccessViolation("OOS_ALREADY_CONSUMED: Cannot reopen an already consumed evaluation session")
        self.is_open = True

    def close_and_consume(self, log_path: Optional[Path] = None) -> None:
        self.is_open = False
        self.consumed = True
        # Mark manifest as consumed
        if self.oos_manifest_path.exists():
            manifest = OOSManifest.load(self.oos_manifest_path)
            manifest.consumed = True
            manifest.save(self.oos_manifest_path)

        OOSAccessPolicy.log_access(
            session_id=self.session_id,
            operation="CLOSE_AND_CONSUME",
            purpose="SESSION_COMPLETED",
            allowed=True,
            reason="Evaluation session consumed and locked permanently",
            log_path=log_path
        )


class OOSAccessPolicy:
    """Automated security gatekeeper enforcing zero unauthorized OOS reads."""
    LOG_FILE = settings.root_dir / "GATE_22R_OOS_ACCESS_LOG.jsonl"

    @classmethod
    def log_access(
        cls,
        session_id: Optional[str],
        operation: str,
        purpose: str,
        allowed: bool,
        reason: str,
        candidate_id: Optional[str] = None,
        process: str = "python",
        log_path: Optional[Path] = None
    ) -> None:
        target_path = log_path or cls.LOG_FILE
        target_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id or "NONE",
            "git_commit": os.getenv("GIT_COMMIT", "UNKNOWN"),
            "process": process,
            "operation": operation,
            "purpose": purpose,
            "candidate_id": candidate_id or "NONE",
            "allowed": allowed,
            "reason": reason
        }
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    @classmethod
    def verify_access(
        cls,
        session: Optional[OOSEvaluationSession],
        candidate_manifest: Optional[CandidateManifest] = None,
        oos_manifest: Optional[OOSManifest] = None,
        purpose: str = "INFERENCE",
        log_path: Optional[Path] = None
    ) -> bool:
        # Rule 1: Live trading check. Live trading must NOT access research OOS evaluator
        if os.getenv("LIVE_TRADING", "false").lower() == "true":
            cls.log_access(
                session_id=session.session_id if session else None,
                operation="READ_OOS",
                purpose=purpose,
                allowed=False,
                reason="LIVE_TRADING_ACTIVE: OOS access prohibited in live trading mode",
                log_path=log_path
            )
            raise OOSAccessViolation("LIVE_TRADING_ACTIVE: OOS access permitted only for final research evaluation with LIVE_TRADING=false")

        # Rule 2: Research lock verification
        if settings.oos_locked and (session is None or not session.is_open):
            cls.log_access(
                session_id=None,
                operation="READ_OOS",
                purpose=purpose,
                allowed=False,
                reason="OOS_ACCESS_LOCKED_RESEARCH_PHASE: Direct OOS read prohibited during research",
                log_path=log_path
            )
            raise OOSAccessViolation(
                "OOS_ACCESS_LOCKED_RESEARCH_PHASE: Research scripts are barred from reading OOS holdouts. "
                "Evaluation is only permitted through evaluate_frozen_oos with a valid one-time session."
            )

        # Rule 3: Session consumed verification
        if session.consumed:
            cls.log_access(
                session_id=session.session_id,
                operation="READ_OOS",
                purpose=purpose,
                allowed=False,
                reason="OOS_ALREADY_CONSUMED: Evaluation session has already been consumed",
                log_path=log_path
            )
            raise OOSAccessViolation("OOS_ALREADY_CONSUMED: One-time evaluation token has already been consumed")

        # Rule 4: Manifest checks
        if oos_manifest is not None and oos_manifest.consumed:
            cls.log_access(
                session_id=session.session_id,
                operation="READ_OOS",
                purpose=purpose,
                allowed=False,
                reason="OOS_MANIFEST_ALREADY_CONSUMED",
                log_path=log_path
            )
            raise OOSAccessViolation("OOS_MANIFEST_ALREADY_CONSUMED: Target OOS dataset has already been evaluated")

        if candidate_manifest is not None and oos_manifest is not None:
            if candidate_manifest.compute_hash() != oos_manifest.candidate_manifest_hash:
                cls.log_access(
                    session_id=session.session_id,
                    operation="READ_OOS",
                    purpose=purpose,
                    allowed=False,
                    reason="CANDIDATE_MANIFEST_MISMATCH: Candidates have been modified after freeze",
                    log_path=log_path
                )
                raise OOSAccessViolation(
                    "CANDIDATE_MANIFEST_MISMATCH: Candidates do not match the frozen candidate manifest hash"
                )

        cls.log_access(
            session_id=session.session_id,
            operation="READ_OOS",
            purpose=purpose,
            allowed=True,
            reason="AUTHORIZED_EVALUATION_SESSION",
            log_path=log_path
        )
        return True


class OOSDataset:
    """Safe container for loading and managing out-of-sample data."""

    # Cryptographic hash of the contaminated old test slice
    CONTAMINATED_TEST_SLICE_HASH = "6fd7ce632f4772b15cf85e4af36b05b6cf3f3dd0267c2895b87223614b9802ae"

    @classmethod
    def load_oos_data(
        cls,
        df_or_path: Any,
        session: OOSEvaluationSession,
        oos_manifest: OOSManifest,
        candidate_manifest: CandidateManifest,
        log_path: Optional[Path] = None
    ) -> pd.DataFrame:
        """Loads and validates OOS dataset under strict policy governance."""
        # 1. Verify policy access
        OOSAccessPolicy.verify_access(
            session=session,
            candidate_manifest=candidate_manifest,
            oos_manifest=oos_manifest,
            purpose="FINAL_OOS_EVALUATION",
            log_path=log_path
        )

        # 2. Ingest dataframe
        if isinstance(df_or_path, (str, Path)):
            df = pd.read_parquet(df_or_path)
        elif isinstance(df_or_path, pd.DataFrame):
            df = df_or_path.copy()
        else:
            raise ValueError("Unsupported data source")

        # 3. Contaminated test set rejection check (Test M)
        df_bytes = df.to_parquet()
        actual_hash = hashlib.sha256(df_bytes).hexdigest()
        if actual_hash == cls.CONTAMINATED_TEST_SLICE_HASH:
            OOSAccessPolicy.log_access(
                session_id=session.session_id,
                operation="LOAD_OOS",
                purpose="EVALUATION",
                allowed=False,
                reason="CONTAMINATED_HISTORICAL_SET_REJECTED",
                log_path=log_path
            )
            raise OOSAccessViolation(
                "CONTAMINATED_HISTORICAL_SET_REJECTED: The old test set (2026-07-27 to 2026-09-18) "
                "is permanently classified as CONTAMINATED_HISTORICAL_DIAGNOSTIC_SET and cannot be used as an unseen benchmark."
            )

        # 4. Manifest cryptographic validation (Test C, Test N, Test O)
        oos_manifest.validate_dataframe(df)

        return df


class OOSGuard:
    """Helper guard ensuring research pipelines cannot bypass OOS locks indirectly."""

    @classmethod
    def get_oos_slice(
        cls,
        df: pd.DataFrame,
        indices: Any,
        session: Optional[OOSEvaluationSession] = None,
        log_path: Optional[Path] = None
    ) -> pd.DataFrame:
        """Guarded slice extraction for test/OOS indices."""
        if session is None or not session.is_open:
            OOSAccessPolicy.log_access(
                session_id=None,
                operation="GET_OOS_SLICE",
                purpose="INDIRECT_HELPER_CALL",
                allowed=False,
                reason="INDIRECT_HELPER_CALL_BLOCKED",
                log_path=log_path
            )
            raise OOSAccessViolation(
                "INDIRECT_OOS_ACCESS_BLOCKED: Calling get_oos_slice without an active evaluation session is prohibited."
            )
        return df.iloc[indices].copy()
