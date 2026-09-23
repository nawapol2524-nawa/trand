"""
cTrader OAuth2 Access Token Helper
===================================
Run this script ONCE locally to get your cTrader Access Token.
The token will be saved to .env automatically.

Usage:
    python3 scripts/get_ctrader_token.py

Requirements:
    pip install requests python-dotenv

Steps:
1. Script opens browser to Spotware authorization URL
2. You authorize your cTrader account (2565611)
3. Browser redirects to localhost:8080/callback with a code
4. Script exchanges code for access token
5. Token is saved to .env — never printed to terminal

SECURITY: Never share the access token.
Tokens expire — check cTrader docs for refresh token procedure.
"""
from __future__ import annotations

import http.server
import json
import os
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# Load credentials from .env (never hardcode here)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Manual .env parser fallback
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

CLIENT_ID     = os.environ.get("CTRADER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CTRADER_CLIENT_SECRET", "")
REDIRECT_URI  = "http://localhost:8080/callback"
SCOPE         = "trading"

# Spotware OAuth endpoints
AUTH_URL  = "https://connect.spotware.com/apps/auth"
TOKEN_URL = "https://connect.spotware.com/apps/token"

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_config() -> bool:
    if not CLIENT_ID or CLIENT_ID.startswith("YOUR_") or CLIENT_ID.startswith("PENDING"):
        print("[FAIL] CTRADER_CLIENT_ID not set in .env")
        return False
    if not CLIENT_SECRET or CLIENT_SECRET.startswith("YOUR_") or CLIENT_SECRET.startswith("PENDING"):
        print("[FAIL] CTRADER_CLIENT_SECRET not set in .env")
        return False
    # Never print the actual values
    print(f"[OK] CLIENT_ID  : {CLIENT_ID[:10]}...{CLIENT_ID[-4:]}")
    print(f"[OK] SECRET     : {'*' * 20}")
    return True


# ---------------------------------------------------------------------------
# Local HTTP server to catch the OAuth callback
# ---------------------------------------------------------------------------
_auth_code: list[str] = []

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # type: ignore[override]
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            _auth_code.append(params["code"][0])
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body>
                <h2>Authorization successful!</h2>
                <p>You can close this window and return to the terminal.</p>
                </body></html>
            """)
        elif "error" in params:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body><h2>Error: {error}</h2></body></html>".encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args) -> None:
        pass  # Suppress request logs


def _run_callback_server() -> None:
    server = http.server.HTTPServer(("localhost", 8080), _CallbackHandler)
    server.timeout = 120
    server.handle_request()  # Wait for exactly one request


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------
def exchange_code_for_token(code: str) -> dict:
    data = urllib.parse.urlencode({
        "grant_type":    "authorization_code",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
    }).encode()

    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Save token to .env
# ---------------------------------------------------------------------------
def save_token_to_env(token_data: dict) -> None:
    env_path = Path(__file__).parent.parent / ".env"
    content = env_path.read_text() if env_path.exists() else ""

    access_token  = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in    = token_data.get("expires_in", "unknown")

    import re
    # Update or append CTRADER_ACCESS_TOKEN
    if "CTRADER_ACCESS_TOKEN=" in content:
        content = re.sub(r"CTRADER_ACCESS_TOKEN=.*", f"CTRADER_ACCESS_TOKEN={access_token}", content)
    else:
        content += f"\nCTRADER_ACCESS_TOKEN={access_token}\n"

    if "CTRADER_REFRESH_TOKEN=" in content:
        content = re.sub(r"CTRADER_REFRESH_TOKEN=.*", f"CTRADER_REFRESH_TOKEN={refresh_token}", content)
    else:
        content += f"CTRADER_REFRESH_TOKEN={refresh_token}\n"

    env_path.write_text(content)

    # Log confirmation WITHOUT printing the token value
    print(f"[OK] Access token saved to .env (expires in {expires_in}s)")
    print(f"[OK] Refresh token saved to .env")
    print(f"[OK] Token type: {token_data.get('tokenType', token_data.get('token_type', 'unknown'))}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("cTrader Open API — OAuth2 Token Acquisition")
    print("=" * 60)

    if not validate_config():
        sys.exit(1)

    # Build authorization URL
    params = urllib.parse.urlencode({
        "client_id":     CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPE,
        "response_type": "code",
    })
    auth_url = f"{AUTH_URL}?{params}"

    print(f"\n[INFO] Starting local callback server on port 8080...")
    server_thread = threading.Thread(target=_run_callback_server, daemon=True)
    server_thread.start()

    print(f"[INFO] Opening browser for authorization...")
    print(f"[INFO] If browser doesn't open, visit this URL manually:")
    print(f"\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("[INFO] Waiting for authorization callback (timeout: 120s)...")
    server_thread.join(timeout=125)

    if not _auth_code:
        print("[FAIL] No authorization code received. Did you authorize?")
        sys.exit(1)

    code = _auth_code[0]
    print(f"[OK] Authorization code received")

    print("[INFO] Exchanging code for access token...")
    try:
        token_data = exchange_code_for_token(code)
    except Exception as e:
        print(f"[FAIL] Token exchange failed: {e}")
        sys.exit(1)

    if "access_token" not in token_data and "accessToken" not in token_data:
        print(f"[FAIL] Unexpected response: {list(token_data.keys())}")
        sys.exit(1)

    # Normalize key names (cTrader API may use camelCase)
    if "accessToken" in token_data and "access_token" not in token_data:
        token_data["access_token"] = token_data["accessToken"]
    if "refreshToken" in token_data and "refresh_token" not in token_data:
        token_data["refresh_token"] = token_data["refreshToken"]
    if "expiresIn" in token_data and "expires_in" not in token_data:
        token_data["expires_in"] = token_data["expiresIn"]

    save_token_to_env(token_data)

    print("\n[DONE] Access token obtained and saved to .env")
    print("[NEXT] Run: python3 scripts/verify_ctrader_connection.py")


if __name__ == "__main__":
    main()
