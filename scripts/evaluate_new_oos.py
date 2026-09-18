#!/usr/bin/env python3
"""
Single-Pass Out-of-Sample (OOS) Evaluator
=========================================
Institutional Governance & Audit Standard for Gate 22R
Executes candidate evaluation against genuine OOS holdout sets under cryptographic access control.
"""

import os
import sys
import argparse
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import pandas as pd

# Add workspace root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ai_forex_bot.config.settings import settings
from ai_forex_bot.data.oos_guard import (
    OOSGuard,
    OOSDataset,
    OOSManifest,
    CandidateManifest,
    OOSEvaluationSession,
    OOSAccessPolicy,
    OOSAccessViolation
)


def evaluate_oos_gate(
    session_id: str,
    token: str,
    candidate_manifest_path: Path,
    oos_manifest_path: Path,
    data_path: Optional[Path] = None
) -> int:
    print("=" * 80)
    print("GATE 22R — CRYPTOGRAPHIC OOS EVALUATION GATE")
    print("=" * 80)

    # 1. Live Trading Invariant Check
    if os.getenv("LIVE_TRADING", "false").lower() == "true":
        OOSAccessPolicy.log_access(
            session_id=session_id,
            operation="EVALUATE_OOS",
            purpose="LIVE_TRADING_CHECK",
            allowed=False,
            reason="LIVE_TRADING_ACTIVE_CANNOT_EVALUATE_RESEARCH_OOS"
        )
        raise OOSAccessViolation("LIVE_TRADING_ACTIVE: Cannot execute research OOS evaluation while live trading is active")

    # 2. Manifest Verification
    if not candidate_manifest_path.exists():
        raise OOSAccessViolation(f"Candidate manifest not found at: {candidate_manifest_path}")

    if not oos_manifest_path.exists():
        raise OOSAccessViolation(f"OOS manifest not found at: {oos_manifest_path}")

    cand_manifest = CandidateManifest.load(candidate_manifest_path)
    oos_manifest = OOSManifest.load(oos_manifest_path)

    # 3. Check if already consumed
    if oos_manifest.consumed:
        OOSAccessPolicy.log_access(
            session_id=session_id,
            operation="EVALUATE_OOS",
            purpose="VERIFY_CONSUMED",
            allowed=False,
            reason="BLOCKED_OOS_ALREADY_CONSUMED"
        )
        raise OOSAccessViolation("BLOCKED: OOS_ALREADY_CONSUMED: The target OOS holdout has already been consumed")

    # 4. Check candidate hash binding
    if cand_manifest.compute_hash() != oos_manifest.candidate_manifest_hash:
        OOSAccessPolicy.log_access(
            session_id=session_id,
            operation="EVALUATE_OOS",
            purpose="VERIFY_CANDIDATE_HASH",
            allowed=False,
            reason="CANDIDATE_MANIFEST_HASH_MISMATCH"
        )
        raise OOSAccessViolation("CANDIDATE_MANIFEST_HASH_MISMATCH: Candidates have been modified after manifest freeze")

    # 5. Check real data availability
    if oos_manifest.row_count == 0 or data_path is None or not data_path.exists():
        print("Status: NEW_OOS_STATUS = WAITING_FOR_REAL_POST_BOUNDARY_DATA")
        print("Notice: No genuine post-boundary real market data (post 2026-09-18 03:15:00 UTC) has been ingested.")
        print("Synthetic candles and resampled data are strictly prohibited.")
        OOSAccessPolicy.log_access(
            session_id=session_id,
            operation="EVALUATE_OOS",
            purpose="CHECK_DATA_AVAILABILITY",
            allowed=True,
            reason="WAITING_FOR_REAL_POST_BOUNDARY_DATA"
        )
        return 0

    # 6. Initialize Session
    session = OOSEvaluationSession(
        session_id=session_id,
        token=token,
        candidate_manifest_path=candidate_manifest_path,
        oos_manifest_path=oos_manifest_path,
        git_commit=oos_manifest.git_commit_before_unlock
    )
    session.open_session()

    # 7. Ingest and Validate OOS Data
    print(f"Loading OOS data from: {data_path}")
    df_oos = OOSDataset.load_oos_data(
        df_or_path=data_path,
        session=session,
        oos_manifest=oos_manifest,
        candidate_manifest=cand_manifest
    )
    print(f"OOS Dataset validated: {len(df_oos)} bars, hash: {oos_manifest.dataset_sha256}")

    # 8. Close and Consume Session
    session.close_and_consume()
    print("Evaluation completed successfully. Session consumed and permanently locked.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Cryptographically Guarded OOS Evaluator")
    parser.add_argument("--session-id", default="SESSION_TEST_GATE22R")
    parser.add_argument("--token", default="TOKEN_VALID_GATE22R")
    parser.add_argument("--candidate-manifest", default="GATE_22R_CANDIDATE_MANIFEST.json")
    parser.add_argument("--oos-manifest", default="GATE_22R_OOS_MANIFEST.json")
    parser.add_argument("--data-path", default=None)

    args = parser.parse_args()
    data_path = Path(args.data_path) if args.data_path else None

    try:
        ret = evaluate_oos_gate(
            session_id=args.session_id,
            token=args.token,
            candidate_manifest_path=Path(args.candidate_manifest),
            oos_manifest_path=Path(args.oos_manifest),
            data_path=data_path
        )
        sys.exit(ret)
    except OOSAccessViolation as e:
        print(f"OOS ACCESS VIOLATION: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
