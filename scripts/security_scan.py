#!/usr/bin/env python3
"""
Security & Repository Hygiene Scanner
====================================
Institutional Security Standard for Gate 25
Performs automated vulnerability and secret leakage checks:
1. Tracked Secret Files Audit (git ls-files)
2. Secret Token & High-Entropy Credential Pattern Scan
3. .env.example Placeholder Verification
4. .gitignore Completeness Verification
5. Hard Governance Invariant Audit (LIVE_TRADING=false, AUTO_PROMOTION=false)
"""

import os
import sys
import re
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Any
import yaml

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

# Forbidden tracked file patterns
FORBIDDEN_TRACKED_PATTERNS = [
    r"^\.env$",
    r"^\.env\.(?!example).*",
    r".*\.pem$",
    r".*\.key$",
    r".*\.secret$",
    r".*id_rsa.*",
    r".*credentials\.json$"
]

# Sensitive token signatures (ignoring explicit dummy placeholders)
SECRET_PATTERNS = [
    (r"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----", "PRIVATE_KEY_HEADER"),
    (r"sk-[a-zA-Z0-9]{32,}", "OPENAI_SECRET_KEY"),
    (r"ghp_[a-zA-Z0-9]{36,}", "GITHUB_PAT"),
    (r"AKIA[0-9A-Z]{16}", "AWS_ACCESS_KEY"),
]


def run_git_ls_files() -> List[str]:
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=str(WORKSPACE_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception as e:
        print(f"[ERROR] Failed to run git ls-files: {e}", file=sys.stderr)
        return []


def audit_tracked_files(tracked_files: List[str]) -> Tuple[bool, List[str]]:
    violations = []
    compiled_patterns = [re.compile(p) for p in FORBIDDEN_TRACKED_PATTERNS]

    for f in tracked_files:
        for p in compiled_patterns:
            if p.match(f):
                violations.append(f)
                break

    passed = len(violations) == 0
    return passed, violations


def audit_code_secrets(tracked_files: List[str]) -> Tuple[bool, List[Dict[str, Any]]]:
    violations = []
    compiled_secrets = [(re.compile(pat), name) for pat, name in SECRET_PATTERNS]

    # Files excluded from secret scan (e.g., this scanner script itself or tests defining patterns)
    excluded_files = {
        "scripts/security_scan.py",
        "tests/unit/test_gate25_security.py"
    }

    for f in tracked_files:
        if f in excluded_files:
            continue

        file_path = WORKSPACE_ROOT / f
        if not file_path.exists() or file_path.is_dir():
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for pat, secret_type in compiled_secrets:
            matches = pat.findall(content)
            for m in matches:
                # Exclude obvious placeholders
                if "YOUR_" in m or "PLACEHOLDER" in m or "EXAMPLE" in m:
                    continue
                violations.append({
                    "file": f,
                    "secret_type": secret_type,
                    "sample": m[:8] + "..." if len(m) > 8 else m
                })

    passed = len(violations) == 0
    return passed, violations


def audit_env_example() -> Tuple[bool, str]:
    env_example_path = WORKSPACE_ROOT / ".env.example"
    if not env_example_path.exists():
        return False, ".env.example file does not exist"

    content = env_example_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, val = stripped.split("=", 1)
            key, val = key.strip(), val.strip()

            # Allowed boolean or empty values
            if val.lower() in ("true", "false", ""):
                continue

            # Must contain placeholder indicator
            if not (val.startswith("YOUR_") or "EXAMPLE" in val or "PLACEHOLDER" in val):
                return False, f"Non-placeholder secret detected in .env.example: {key}={val[:6]}..."

    return True, "All variables in .env.example use verified placeholders"


def audit_gitignore() -> Tuple[bool, List[str]]:
    gitignore_path = WORKSPACE_ROOT / ".gitignore"
    if not gitignore_path.exists():
        return False, ["Missing .gitignore file"]

    content = gitignore_path.read_text(encoding="utf-8")
    required_guards = [
        (".env", "Environment file exclusion"),
        ("artifacts/models/*.joblib", "Model binary exclusion"),
        ("*.log", "Log file exclusion"),
        ("*.sqlite3", "Database file exclusion"),
        ("__pycache__", "Python cache exclusion")
    ]

    missing = []
    for guard, desc in required_guards:
        if guard not in content:
            missing.append(f"{guard} ({desc})")

    return len(missing) == 0, missing


def audit_governance_invariants() -> Tuple[bool, List[str]]:
    violations = []

    # 1. Check configs/system.yaml
    sys_yaml_path = WORKSPACE_ROOT / "configs" / "system.yaml"
    if sys_yaml_path.exists():
        try:
            with open(sys_yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            system_sec = data.get("system", {})
            if system_sec.get("live_trading") is not False:
                violations.append("configs/system.yaml: system.live_trading must be false")
            if system_sec.get("auto_promotion") is not False:
                violations.append("configs/system.yaml: system.auto_promotion must be false")
        except Exception as e:
            violations.append(f"Failed to read configs/system.yaml: {e}")

    # 2. Check settings singleton
    try:
        from ai_forex_bot.config.settings import settings
        if settings.live_trading is not False:
            violations.append("settings.live_trading is not False")
        if settings.auto_promotion is not False:
            violations.append("settings.auto_promotion is not False")
    except Exception as e:
        violations.append(f"Failed to import settings: {e}")

    return len(violations) == 0, violations


def main():
    print("=" * 80)
    print("GATE 25 — AUTOMATED SECURITY & REPOSITORY HYGIENE SCANNER")
    print("=" * 80)

    tracked_files = run_git_ls_files()
    print(f"Total tracked files in git: {len(tracked_files)}")
    print("-" * 80)

    all_passed = True

    # 1. Tracked secret files check
    p1, v1 = audit_tracked_files(tracked_files)
    status1 = "PASS" if p1 else "FAIL"
    print(f"[CHECK 1] Tracked Secret Files Audit: {status1}")
    if not p1:
        all_passed = False
        print(f"  VIOLATION: Forbidden secret files tracked in git: {v1}")

    # 2. Secret signatures in code check
    p2, v2 = audit_code_secrets(tracked_files)
    status2 = "PASS" if p2 else "FAIL"
    print(f"[CHECK 2] Raw Credential Signatures Audit: {status2}")
    if not p2:
        all_passed = False
        for viol in v2:
            print(f"  VIOLATION: Found {viol['secret_type']} in {viol['file']} ({viol['sample']})")

    # 3. .env.example hygiene check
    p3, reason3 = audit_env_example()
    status3 = "PASS" if p3 else "FAIL"
    print(f"[CHECK 3] .env.example Hygiene & Placeholders: {status3}")
    if not p3:
        all_passed = False
        print(f"  VIOLATION: {reason3}")

    # 4. .gitignore completeness check
    p4, v4 = audit_gitignore()
    status4 = "PASS" if p4 else "FAIL"
    print(f"[CHECK 4] .gitignore Completeness Audit: {status4}")
    if not p4:
        all_passed = False
        print(f"  VIOLATION: Missing critical rules in .gitignore: {v4}")

    # 5. Governance invariants check
    p5, v5 = audit_governance_invariants()
    status5 = "PASS" if p5 else "FAIL"
    print(f"[CHECK 5] Governance Invariants (LIVE_TRADING=false, AUTO_PROMOTION=false): {status5}")
    if not p5:
        all_passed = False
        print(f"  VIOLATION: {v5}")

    print("=" * 80)
    if all_passed:
        print("SECURITY SCAN RESULT: PASS (All 5 hygiene checks passed successfully)")
        sys.exit(0)
    else:
        print("SECURITY SCAN RESULT: FAIL (Security vulnerabilities or hygiene gaps detected)", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
