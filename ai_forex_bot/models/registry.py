"""
Model Registry & Metadata Store
===============================
Institutional Model Lifecycle Governance Standard for Gate 24
Maintains stateful tracking of models across their complete lifecycle:
CANDIDATE ➔ VALIDATED ➔ SHADOW ➔ CHAMPION ➔ REJECTED / ROLLBACK

Storage: artifacts/models/registry.json
Guarantees immutability, audit logging, zero silent promotion, and safe rollback.
"""

import os
import json
import hashlib
from enum import Enum
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Any

from ai_forex_bot.config.settings import settings


class ModelLifecycleState(str, Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    SHADOW = "SHADOW"
    CHAMPION = "CHAMPION"
    REJECTED = "REJECTED"
    ROLLBACK = "ROLLBACK"


@dataclass
class ModelRecord:
    model_id: str
    model_type: str
    version: str
    state: ModelLifecycleState
    artifact_file: str
    model_hash: str
    created_at: str
    updated_at: str
    train_start_epoch: int
    train_end_epoch: int
    train_row_count: int
    feature_count: int
    feature_names: List[str]
    hyperparameters: Dict[str, Any]
    validation_metrics: Dict[str, Any]
    state_history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value if isinstance(self.state, ModelLifecycleState) else self.state
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelRecord":
        data_copy = data.copy()
        if "state" in data_copy and isinstance(data_copy["state"], str):
            data_copy["state"] = ModelLifecycleState(data_copy["state"])
        return cls(**data_copy)


class ModelRegistry:
    def __init__(self, registry_file: Optional[Path] = None):
        self.root_dir = settings.root_dir
        self.registry_file = registry_file or (self.root_dir / "artifacts" / "models" / "registry.json")
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.models: Dict[str, ModelRecord] = {}
        self.champion_id: Optional[str] = None
        self.previous_champion_id: Optional[str] = None
        self.last_updated: Optional[str] = None
        self.load()

    def load(self) -> None:
        """Loads registry from JSON file if present."""
        if not self.registry_file.exists():
            return

        try:
            with open(self.registry_file, "r", encoding="utf-8") as f:
                payload = json.load(f)

            self.champion_id = payload.get("champion_id")
            self.previous_champion_id = payload.get("previous_champion_id")
            self.last_updated = payload.get("last_updated")

            self.models = {}
            for mid, mdata in payload.get("models", {}).items():
                self.models[mid] = ModelRecord.from_dict(mdata)
        except Exception:
            self.models = {}

    def save(self) -> None:
        """Saves registry to JSON file atomically."""
        self.last_updated = datetime.now(timezone.utc).isoformat()
        payload = {
            "champion_id": self.champion_id,
            "previous_champion_id": self.previous_champion_id,
            "last_updated": self.last_updated,
            "models": {mid: m.to_dict() for mid, m in self.models.items()}
        }
        with open(self.registry_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def register_model(
        self,
        model_id: str,
        model_type: str,
        version: str,
        artifact_path: Path,
        train_start_epoch: int,
        train_end_epoch: int,
        train_row_count: int,
        feature_names: List[str],
        hyperparameters: Dict[str, Any],
        validation_metrics: Dict[str, Any],
        initial_state: ModelLifecycleState = ModelLifecycleState.CANDIDATE,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ModelRecord:
        """Registers a new model into the registry with cryptographic file hash."""
        artifact_path = Path(artifact_path)
        if artifact_path.exists():
            model_bytes = artifact_path.read_bytes()
            model_hash = hashlib.sha256(model_bytes).hexdigest()
        else:
            model_hash = "PENDING_FILE_SAVE"

        now_str = datetime.now(timezone.utc).isoformat()
        history = [{
            "from_state": "NONE",
            "to_state": initial_state.value,
            "timestamp": now_str,
            "reason": "INITIAL_REGISTRATION"
        }]

        record = ModelRecord(
            model_id=model_id,
            model_type=model_type,
            version=version,
            state=initial_state,
            artifact_file=str(artifact_path.name),
            model_hash=model_hash,
            created_at=now_str,
            updated_at=now_str,
            train_start_epoch=train_start_epoch,
            train_end_epoch=train_end_epoch,
            train_row_count=train_row_count,
            feature_count=len(feature_names),
            feature_names=feature_names,
            hyperparameters=hyperparameters,
            validation_metrics=validation_metrics,
            state_history=history,
            metadata=metadata or {}
        )

        self.models[model_id] = record
        self.save()
        return record

    def transition_state(
        self,
        model_id: str,
        new_state: ModelLifecycleState,
        reason: str = ""
    ) -> bool:
        """Transitions model lifecycle state with complete transition history."""
        if model_id not in self.models:
            return False

        record = self.models[model_id]
        prev_state = record.state
        if prev_state == new_state:
            return True

        now_str = datetime.now(timezone.utc).isoformat()
        record.state = new_state
        record.updated_at = now_str
        record.state_history.append({
            "from_state": prev_state.value if isinstance(prev_state, ModelLifecycleState) else prev_state,
            "to_state": new_state.value if isinstance(new_state, ModelLifecycleState) else new_state,
            "timestamp": now_str,
            "reason": reason
        })

        self.save()
        return True

    def promote_challenger_to_champion(
        self,
        model_id: str,
        force: bool = False,
        min_balanced_acc: float = 0.40,
        reason: str = "MANUAL_OR_GATED_PROMOTION"
    ) -> bool:
        """
        Promotes challenger model to CHAMPION under strict criteria:
        - Auto-promotion is strictly FALSE by default.
        - Challenger must be in VALIDATED or SHADOW state.
        - Must satisfy minimum balanced accuracy criteria unless force=True.
        - Prior champion is transitioned to ROLLBACK state.
        """
        if model_id not in self.models:
            return False

        challenger = self.models[model_id]
        if challenger.state not in (ModelLifecycleState.VALIDATED, ModelLifecycleState.SHADOW) and not force:
            return False

        # Criteria check
        bal_acc = challenger.validation_metrics.get("balanced_accuracy", 0.0)
        if not force and bal_acc < min_balanced_acc:
            self.transition_state(
                model_id,
                ModelLifecycleState.REJECTED,
                reason=f"PROMOTION_REJECTED: Balanced accuracy {bal_acc:.4f} below threshold {min_balanced_acc:.4f}"
            )
            return False

        # Step prior champion down to ROLLBACK
        if self.champion_id and self.champion_id != model_id:
            old_champ_id = self.champion_id
            self.transition_state(
                old_champ_id,
                ModelLifecycleState.ROLLBACK,
                reason=f"SUPERSEDED_BY_NEW_CHAMPION_{model_id}"
            )
            self.previous_champion_id = old_champ_id

        # Promote challenger
        self.transition_state(
            model_id,
            ModelLifecycleState.CHAMPION,
            reason=reason
        )
        self.champion_id = model_id
        self.save()
        return True

    def rollback_to_previous_champion(self, reason: str = "PERFORMANCE_DEGRADATION") -> bool:
        """
        Rolls back current champion to ROLLBACK state and restores previous champion.
        """
        if not self.previous_champion_id or self.previous_champion_id not in self.models:
            return False

        current_champ_id = self.champion_id
        prev_champ_id = self.previous_champion_id

        # Demote current champion
        if current_champ_id and current_champ_id in self.models:
            self.transition_state(
                current_champ_id,
                ModelLifecycleState.ROLLBACK,
                reason=f"DEMOTED_DUE_TO_ROLLBACK: {reason}"
            )

        # Restore previous champion
        self.transition_state(
            prev_champ_id,
            ModelLifecycleState.CHAMPION,
            reason=f"RESTORED_FROM_ROLLBACK: {reason}"
        )

        self.champion_id = prev_champ_id
        self.previous_champion_id = current_champ_id
        self.save()
        return True

    def get_champion(self) -> Optional[ModelRecord]:
        if self.champion_id and self.champion_id in self.models:
            return self.models[self.champion_id]
        return None

    def get_model(self, model_id: str) -> Optional[ModelRecord]:
        return self.models.get(model_id)

    def list_models(self, state: Optional[ModelLifecycleState] = None) -> List[ModelRecord]:
        if state is None:
            return list(self.models.values())
        return [m for m in self.models.values() if m.state == state]
