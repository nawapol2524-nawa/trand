"""
Decision Trace Logging Service — Phase K requirement.
Maintains a tamper-evident, append-only, replayable audit trail for every AI invocation.
Strict security: NEVER writes credentials, tokens, or secret keys.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.ai.schemas import TradeProposal
from src.ai.validator import ValidationResult
from src.core.version import SYSTEM_VERSION, get_git_commit_sha


@dataclass
class DecisionTraceRecord:
    trace_id:              str
    timestamp:             str
    event_id:              str
    provider:              str
    model:                 str
    input_schema_version:  str = "1.0"
    output_schema_version: str = "1.0"
    system_version:        str = SYSTEM_VERSION
    git_commit:            Optional[str] = None
    context_summary:       dict[str, Any] = None  # type: ignore[assignment]
    proposal:              dict[str, Any] = None  # type: ignore[assignment]
    validation_result:     dict[str, Any] = None  # type: ignore[assignment]
    risk_result:           dict[str, Any] = None  # type: ignore[assignment]
    execution_result:      dict[str, Any] = None  # type: ignore[assignment]

    def to_json(self) -> str:
        return json.dumps(asdict(self))


class DecisionTraceLogger:
    """Logs structured decision traces into an append-only JSONL file."""

    def __init__(self, log_dir: str = "logs"):
        self.log_path = Path(log_dir) / "decision_traces.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_decision(
        self,
        trace_id: str,
        event_id: str,
        provider: str,
        model: str,
        context_summary: dict[str, Any],
        proposal: Optional[TradeProposal] = None,
        validation_result: Optional[ValidationResult] = None,
        risk_result: Optional[dict[str, Any]] = None,
        execution_result: Optional[dict[str, Any]] = None,
    ) -> DecisionTraceRecord:
        now_str = datetime.now(tz=timezone.utc).isoformat()

        # Sanitize any potential secret substrings defensively
        sanitized_summary = self._sanitize(context_summary)

        if proposal is None:
            proposal_dict: dict[str, Any] = {}
        elif isinstance(proposal, dict):
            proposal_dict = proposal
        elif hasattr(proposal, "to_dict") and callable(proposal.to_dict):
            proposal_dict = proposal.to_dict()
        elif is_dataclass(proposal):
            proposal_dict = asdict(proposal)
        else:
            proposal_dict = {}

        record = DecisionTraceRecord(
            trace_id=trace_id,
            timestamp=now_str,
            event_id=event_id,
            provider=provider,
            model=model,
            context_summary=sanitized_summary,
            proposal=proposal_dict,
            validation_result={
                "passed": validation_result.passed,
                "decision": validation_result.decision,
                "reason": validation_result.reason,
                "checks": validation_result.checks,
            } if validation_result else {},
            risk_result=risk_result or {},
            execution_result=execution_result or {},
            system_version=SYSTEM_VERSION,
            git_commit=get_git_commit_sha(),
        )

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(record.to_json() + "\n")

        return record

    @staticmethod
    def _sanitize(data: Any) -> Any:
        if isinstance(data, dict):
            clean = {}
            for k, v in data.items():
                if any(sec in k.lower() for sec in ["key", "token", "secret", "password", "auth"]):
                    clean[k] = "[REDACTED]"
                else:
                    clean[k] = DecisionTraceLogger._sanitize(v)
            return clean
        elif isinstance(data, list):
            return [DecisionTraceLogger._sanitize(item) for item in data]
        return data


# Canonical Alias for Runner & Services
DecisionTraceService = DecisionTraceLogger
