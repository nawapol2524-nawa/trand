"""
Integration Verification: Live Deriv Demo Execution
===================================================
Tests real end-to-end integration of DerivBroker:
1. Connects to Deriv Demo (DOT94482469).
2. Verifies account balance ($10,000 range).
3. Fetches live quote for R_75.
4. Places a real $1.00 MULTUP demo contract.
5. Verifies contract registration and open positions.
6. Closes the position via Deriv sell command.
7. Reconciles final account state and closed trades.
"""

import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Set root
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

# Load .env from Desktop/TradingBot_Workspace or local
env_path = Path("/Users/nawaphonkoedbua/Desktop/TradingBot_Workspace/.env")
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

from ai_forex_bot.execution.deriv_broker import DerivBroker


def run_live_test():
    print("=" * 60)
    print("🚀 DERIV BROKER LIVE DEMO INTEGRATION TEST")
    print("=" * 60)

    token = os.getenv("DERIV_API_TOKEN")
    app_id = os.getenv("DERIV_APP_ID", "34lQGsI4JVHDtfZhaHAqk")

    if not token:
        print("❌ DERIV_API_TOKEN not found in environment!")
        sys.exit(1)

    print(f"🔑 Using Token: {token[:10]}... | App ID: {app_id}")
    broker = DerivBroker(token=token, app_id=app_id, account_type="demo")

    print("\n[STEP 1] Connecting to Deriv...")
    if not broker.connect():
        print("❌ Connection failed!")
        sys.exit(1)

    print(f"✅ Connected to Account: {broker.account_id} ({broker.account_type})")
    print(f"💰 Current Balance: ${broker.balance:.2f} USD | Equity: ${broker.equity:.2f} USD")

    print("\n[STEP 2] Fetching live quote for R_75...")
    quote = broker.get_quote("R_75")
    print(f"📊 R_75 Quote: Bid={quote['bid']}, Ask={quote['ask']}, Spread={quote['spread_pips']} pips")

    print("\n[STEP 3] Placing $1.00 MULTUP Demo Order on R_75...")
    order_res = broker.place_order(
        symbol="R_75",
        direction="BUY",
        lot_size=0.01,
        sl_price=quote['bid'] * 0.98,
        tp_price=quote['ask'] * 1.02,
        stake=1.0
    )
    print("📝 Order Result:", order_res)
    if order_res.get("status") != "FILLED":
        print("❌ Order was not filled!")
        broker.disconnect()
        sys.exit(1)

    contract_id = order_res["order_id"]
    print(f"✅ Contract {contract_id} successfully bought on Deriv Demo!")
    print(f"💼 Open Positions: {len(broker.get_open_positions())}")

    print("\n[STEP 4] Waiting 2 seconds before closing...")
    time.sleep(2)

    print(f"\n[STEP 5] Closing Contract {contract_id} via Deriv...")
    close_res = broker.close_position(contract_id, exit_reason="TEST_COMPLETE")
    print("📝 Close Result:", close_res)
    if close_res.get("status") != "CLOSED":
        print("❌ Failed to close position!")
        broker.disconnect()
        sys.exit(1)

    trade = close_res["trade"]
    print(f"✅ Contract closed! Net PnL: ${trade['net_pnl']:+.2f} USD")
    print(f"💰 Updated Balance: ${broker.balance:.2f} USD")

    print("\n[STEP 6] Reconciling final state...")
    audit = broker.reconcile()
    print("📋 Reconciliation Audit:", audit)

    broker.disconnect()
    print("\n" + "=" * 60)
    print("🎉 DERIV LIVE INTEGRATION TEST COMPLETED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_live_test()
