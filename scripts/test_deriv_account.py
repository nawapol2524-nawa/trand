import json
import os
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("DERIV_API_TOKEN")
app_id = "1089"

print("Checking Deriv Token:", token[:10] if token else "None")

try:
    from websockets.sync.client import connect
    uri = f"wss://ws.derivws.com/websockets/v3?app_id={app_id}"
    with connect(uri, open_timeout=5.0) as ws:
        ws.send(json.dumps({"authorize": token}))
        res = json.loads(ws.recv(timeout=5.0))
        if "authorize" in res:
            auth = res["authorize"]
            fn = auth.get("fullname")
            em = auth.get("email")
            lid = auth.get("loginid")
            bal = auth.get("balance")
            cur = auth.get("currency")
            is_v = auth.get("is_virtual")
            print("==========================================")
            print(f"DERIV CONNECTION SUCCESSFUL!")
            print(f"User: {fn} ({em})")
            print(f"Active Account: {lid}")
            print(f"Balance: {bal} {cur}")
            print(f"Is Demo / Virtual: {bool(is_v)}")
            print("==========================================")
            print("Account List:")
            for a in auth.get("account_list", []):
                a_id = a.get("loginid")
                a_v = "DEMO" if a.get("is_virtual") else "REAL"
                a_cur = a.get("currency")
                print(f"  * {a_id} [{a_v}] ({a_cur})")
        else:
            err = res.get("error", {})
            print("Deriv Auth Failed:", err.get("message"), err.get("code"))
except Exception as e:
    print("Connection error:", e)
