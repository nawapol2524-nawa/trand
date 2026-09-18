import os
from pathlib import Path
from dotenv import load_dotenv

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(WORKSPACE_ROOT / ".env", override=False)

def main():
    print("=== ENVIRONMENT VARIABLE AUDIT ===")
    vars_to_check = [
        "DERIV_API_TOKEN", "DERIV_APP_ID", "ENABLE_DERIV",
        "METAAPI_TOKEN", "METAAPI_ACCOUNT_ID",
        "TESTNET_API_KEY", "TESTNET_SECRET_KEY",
        "GROQ_API_KEY", "OPENAI_API_KEY", "ALPHA_VANTAGE_KEY",
        "LINE_CHANNEL_ACCESS_TOKEN", "LINE_USER_ID", "DASHBOARD_PIN"
    ]
    for v in vars_to_check:
        val = os.getenv(v)
        status = "PRESENT (PROTECTED)" if (val and len(val.strip()) > 0) else "NOT SET"
        print(f"  {v:<28}: {status}")
    print("=== AUDIT COMPLETE: ZERO SECRETS EXPOSED ===")

if __name__ == "__main__":
    main()
