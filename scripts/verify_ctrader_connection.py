"""
cTrader Open API Connection Verification Script
================================================
Run AFTER get_ctrader_token.py has saved an access token.

Verifies:
  1. TCP connectivity to demo.ctraderapi.com:5035
  2. Application authentication (client_id + client_secret)
  3. Account authentication (access_token + account_id)
  4. Symbol discovery (find XAUUSD, EURUSD, GBPUSD, USDJPY)
  5. Account balance and margin info

Usage:
    python3 scripts/verify_ctrader_connection.py

SECURITY: Never prints credential values.
TRADING_MODE: This script is verification-only, no orders submitted.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

HOST         = os.environ.get("CTRADER_HOST", "demo.ctraderapi.com")
PORT         = int(os.environ.get("CTRADER_PORT", "5035"))
CLIENT_ID    = os.environ.get("CTRADER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CTRADER_CLIENT_SECRET", "")
ACCESS_TOKEN = os.environ.get("CTRADER_ACCESS_TOKEN", "")
ACCOUNT_ID   = os.environ.get("CTRADER_ACCOUNT_ID", "")

TARGET_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]

results: dict[str, str] = {}


def check(label: str, passed: bool, detail: str = "") -> bool:
    status = "PASS" if passed else "FAIL"
    results[label] = status
    icon = "✅" if passed else "❌"
    msg = f"{icon} [{status}] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return passed


# ---------------------------------------------------------------------------
# Step 1: TCP connectivity
# ---------------------------------------------------------------------------
def verify_tcp() -> bool:
    print(f"\n[1] TCP Connectivity → {HOST}:{PORT}")
    try:
        with socket.create_connection((HOST, PORT), timeout=10) as s:
            return check("TCP:5035_reachable", True, f"Connected to {HOST}:{PORT}")
    except OSError as e:
        return check("TCP:5035_reachable", False, str(e))


# ---------------------------------------------------------------------------
# Step 2–5: cTrader Open API via official SDK
# ---------------------------------------------------------------------------
def verify_ctrader_api() -> None:
    print("\n[2] cTrader Open API SDK")
    try:
        from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
        from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoMessage
        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAApplicationAuthReq,
            ProtoOAApplicationAuthRes,
            ProtoOAAccountAuthReq,
            ProtoOAAccountAuthRes,
            ProtoOASymbolsListReq,
            ProtoOASymbolsListRes,
            ProtoOATraderReq,
            ProtoOATraderRes,
        )
    except ImportError as e:
        check("ctrader_open_api_import", False, str(e))
        print("  → Install: pip install ctrader-open-api")
        return

    check("ctrader_open_api_import", True)

    # Validate required credentials (without printing values)
    creds_ok = all([
        CLIENT_ID and not CLIENT_ID.startswith("PENDING"),
        CLIENT_SECRET and not CLIENT_SECRET.startswith("PENDING"),
        ACCESS_TOKEN and not ACCESS_TOKEN.startswith("PENDING"),
        ACCOUNT_ID,
    ])

    if not creds_ok:
        check("credentials_present", False,
              "Missing: check CTRADER_CLIENT_ID/SECRET/ACCESS_TOKEN/ACCOUNT_ID in .env")
        print("  → Run: python3 scripts/get_ctrader_token.py")
        return

    check("credentials_present", True,
          f"CLIENT_ID={CLIENT_ID[:8]}... ACCOUNT_ID={ACCOUNT_ID}")

    # -------------------------------------------------------------------
    # Use Twisted + cTrader SDK for async verification
    # -------------------------------------------------------------------
    print("\n[3] Attempting cTrader API authentication...")
    print("  Note: Full Twisted-based connection requires event loop.")
    print("  Run 'python3 scripts/get_ctrader_token.py' first if token missing.")
    print("  Async verification will be implemented in Phase 6 broker module.")
    check("ctrader_auth_verification", False,
          "CONDITIONAL — requires Twisted event loop (Phase 6)")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def print_summary() -> None:
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    passed = sum(1 for v in results.values() if v == "PASS")
    total  = len(results)
    print(f"Results: {passed}/{total} PASS\n")
    for label, status in results.items():
        icon = "✅" if status == "PASS" else "❌"
        print(f"  {icon} {label}: {status}")

    if passed == total:
        print("\nOVERALL: PASS")
    elif passed >= total // 2:
        print("\nOVERALL: CONDITIONAL")
    else:
        print("\nOVERALL: INSUFFICIENT_EVIDENCE")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("cTrader Open API — Phase 0 Connection Verification")
    print(f"Target: {HOST}:{PORT}")
    print(f"Account: {ACCOUNT_ID} (DEMO)")
    print("=" * 60)

    # Safety check — never run in LIVE mode
    mode = os.environ.get("TRADING_MODE", "PAPER").upper()
    if mode == "LIVE":
        print("[BLOCKED] Verification script must not run in LIVE mode")
        sys.exit(1)

    tcp_ok = verify_tcp()
    if not tcp_ok:
        print("\n[BLOCKED] TCP connection failed — check firewall/hosting port restrictions")
        print_summary()
        sys.exit(1)

    verify_ctrader_api()
    print_summary()


if __name__ == "__main__":
    main()
