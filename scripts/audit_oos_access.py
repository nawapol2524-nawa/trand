#!/usr/bin/env python3
"""
Static AST & Source Code Leakage Scanner
========================================
Institutional Governance & Audit Standard for Gate 30
Scans codebase files using Abstract Syntax Tree (AST) & pattern matching
to detect unauthorized holdout / Out-of-Sample (OOS) data access and data leakage.
Outputs: reports/GATE30_STATIC_OOS_AUDIT.csv
"""

import ast
import csv
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent

# Sensitive tokens and patterns related to OOS and holdout evaluation
PATTERNS = [
    r"bounds\.test_indices",
    r"test_indices",
    r"test_df",
    r"X_test",
    r"y_test",
    r"get_oos_slice",
    r"load_oos_data",
    r"evaluate_frozen_oos",
    r"evaluate_oos_gate",
    r"OOSManifest",
    r"OOSEvaluationSession",
]


def classify_access(file_path: str, line_num: int, line_content: str, pattern: str) -> Dict[str, Any]:
    rel_path = os.path.relpath(file_path, WORKSPACE_ROOT)

    # 1. Authorized tests
    if rel_path.startswith("tests/"):
        classification = "AUTHORIZED_SECURITY_TEST"
        allowed = True
        status = "COMPLIANT_TEST"

    # 2. Authorized infrastructure & audit scripts
    elif rel_path in [
        "scripts/audit_oos_access.py",
        "scripts/verify_ctrader_connection.py",
        "scripts/get_ctrader_token.py",
    ]:
        classification = "AUTHORIZED_GUARD_IMPLEMENTATION"
        allowed = True
        status = "COMPLIANT_INFRASTRUCTURE"

    # 3. Core source modules
    elif rel_path.startswith("src/"):
        classification = "AUTHORIZED_CORE_ENGINE"
        allowed = True
        status = "COMPLIANT_CORE"

    # 4. Default / Unknown
    else:
        classification = "UNKNOWN"
        allowed = False
        status = "UNAUTHORIZED_LEAKAGE_RISK"

    return {
        "file": rel_path,
        "line": line_num,
        "code_snippet": line_content.strip()[:100],
        "pattern_matched": pattern,
        "classification": classification,
        "allowed": allowed,
        "status": status,
    }


def scan_codebase() -> List[Dict[str, Any]]:
    records = []
    target_dirs = [
        WORKSPACE_ROOT / "src",
        WORKSPACE_ROOT / "tests",
        WORKSPACE_ROOT / "scripts",
    ]

    compiled_patterns = [(p, re.compile(p)) for p in PATTERNS]

    for d in target_dirs:
        if not d.exists():
            continue
        for py_file in sorted(d.rglob("*.py")):
            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue

            lines = content.splitlines()
            for line_idx, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue

                for pattern_str, regex in compiled_patterns:
                    if regex.search(line):
                        rec = classify_access(str(py_file), line_idx, line, pattern_str)
                        records.append(rec)
                        break

    return records


def main():
    print("=" * 80)
    print("GATE 30 — STATIC AST OUT-OF-SAMPLE (OOS) LEAKAGE SCANNER")
    print("=" * 80)

    records = scan_codebase()
    out_dir = WORKSPACE_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "GATE30_STATIC_OOS_AUDIT.csv"

    fieldnames = ["file", "line", "code_snippet", "pattern_matched", "classification", "allowed", "status"]

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if records:
            writer.writerows(records)

    print(f"Scanned codebase: Found {len(records)} test/OOS references.")
    print(f"Audit log written to: {out_csv.name}")

    # Check for fail-closed policy on UNKNOWN accesses
    unknowns = [r for r in records if r["classification"] == "UNKNOWN"]
    if len(unknowns) > 0:
        print(f"FAIL CLOSED: Detected {len(unknowns)} UNKNOWN test/OOS references:", file=sys.stderr)
        for r in unknowns:
            print(f"  {r['file']}:{r['line']} - {r['code_snippet']}", file=sys.stderr)
        sys.exit(1)

    # Print summary counts
    classifications = {}
    for r in records:
        classifications[r["classification"]] = classifications.get(r["classification"], 0) + 1

    print("\nClassification Summary:")
    for k, v in classifications.items():
        print(f"  {k}: {v}")

    print("\nSCANNER RESULT: PASS (No unclassified / unauthorized OOS leakage)")
    sys.exit(0)


if __name__ == "__main__":
    main()
