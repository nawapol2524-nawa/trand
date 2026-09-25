"""
System Version & Lineage Tracking.
Provides single source of truth for runtime version, git commit SHA, and schema version.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any, Dict

SYSTEM_VERSION = "1.3.0"
SCHEMA_VERSION = "1.3"


def get_git_commit_sha() -> str:
    """
    Retrieve current git commit SHA (7 chars).
    Checks Railway / CI environment variables first, then falls back to git cli.
    """
    # Railway environment variables
    env_sha = (
        os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        or os.environ.get("GIT_COMMIT_SHA")
        or os.environ.get("GITHUB_SHA")
    )
    if env_sha:
        return env_sha[:7]

    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=2.0,
        )
        return out.decode("utf-8").strip()
    except Exception:
        return "unknown"


def get_version_info() -> Dict[str, Any]:
    """Return dictionary of system version metadata."""
    return {
        "version": SYSTEM_VERSION,
        "system_version": SYSTEM_VERSION,
        "schema_version": SCHEMA_VERSION,
        "git_commit": get_git_commit_sha(),
    }
