# ENVIRONMENT_VERIFICATION.md
# STATUS: PARTIAL — Local verified, Hosting BLOCKED
# Generated: 2026-09-23

---

## A. LOCAL DEVELOPMENT ENVIRONMENT

### Verified

| Item | Value | Status |
|------|-------|--------|
| OS | macOS 27.0 | ✅ VERIFIED |
| Architecture | arm64 (Apple Silicon) | ✅ VERIFIED |
| Python (system) | 3.9.6 | ⚠️ EOL — DO NOT USE FOR PRODUCTION |
| Python (venv) | 3.9.6 | ⚠️ Existing venv — rebuild needed with 3.11 |
| Python (target) | 3.11+ | 🔄 Required — install via `brew install python@3.11` |
| Docker | Not available | ⚠️ Not installed locally |
| Git | Available | ✅ VERIFIED |
| venv | .venv/ (py 3.9.6) | ⚠️ Needs rebuild with 3.11 |

### Actions Required (Local)

```bash
# Install Python 3.11 (macOS arm64)
brew install python@3.11

# Rebuild venv with 3.11
rm -rf .venv
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

---

## B. BOT HOSTING ENVIRONMENT

### Hosting Provider: bot-hosting.net (Free Plan)

| Item | Value | Status |
|------|-------|--------|
| Provider | bot-hosting.net | 🔴 CRITICAL ISSUE — see below |
| Plan | Free | ❌ |
| Primary Purpose | Discord Bot Hosting | 🔴 NOT suitable for trading bot |
| Docker | UNKNOWN (free plan) | ❓ UNVERIFIED |
| 24/7 uptime | Advertised | ❓ UNVERIFIED for non-Discord bots |
| Python version | UNKNOWN | ❓ UNVERIFIED |
| Outbound TCP (port 5035) | UNKNOWN | ❓ CRITICAL — cTrader needs this |
| Persistent storage | UNKNOWN on free plan | ❓ UNVERIFIED |
| RAM | UNKNOWN (free plan) | ❓ UNVERIFIED |
| Custom process startup | UNKNOWN | ❓ UNVERIFIED |

### 🔴 CRITICAL: bot-hosting.net is designed for Discord bots

Based on documentation review:
- Marketed as "A Free Host For Discord Bots"
- Free plan limitations are unknown for Python trading bots
- **cTrader Open API requires outbound TCP connection to port 5035** (demo.ctraderapi.com:5035)
- Free hosting plans often block non-HTTP outbound ports
- May have sleep/inactivity timeouts that break 24/7 operation
- Docker support on free plan: UNKNOWN

### HOSTING STATUS: ❌ NOT VERIFIED — HIGH RISK

**RECOMMENDATION**: bot-hosting.net free plan is NOT verified for trading bot use.

Better alternatives to verify:
1. **Railway.app** (free tier) — general Linux, Python, persistent processes
2. **Render.com** (free tier) — supports background workers
3. **Oracle Cloud Free Tier** — free VPS (AMD/ARM), full root access, no restrictions
4. **DigitalOcean** — \$4/mo droplet, full Linux
5. **Contabo** — cheap VPS with full control

### Required Verification Before Deployment

To verify bot-hosting.net:
1. SSH/Console access: check `uname -a`, `python3 --version`
2. Test outbound TCP to `demo.ctraderapi.com:5035`
3. Check if persistent processes stay alive (no idle timeout)
4. Check RAM available (`free -h`)
5. Check disk (`df -h`)

```bash
# Run this on bot-hosting.net console to verify:
python3 -c "
import socket, sys
try:
    s = socket.create_connection(('demo.ctraderapi.com', 5035), timeout=10)
    s.close()
    print('PASS: Port 5035 reachable')
except Exception as e:
    print(f'FAIL: {e}')
"
```

---

## ENVIRONMENT VERIFICATION SUMMARY

| Environment | Status |
|-------------|--------|
| macOS Local (dev) | ✅ VERIFIED (Python upgrade required) |
| bot-hosting.net (prod) | ❌ NOT VERIFIED — wrong hosting type |
| Docker (local) | ❌ Not installed |
| Docker (hosting) | ❓ UNKNOWN |

**OVERALL ENVIRONMENT STATUS: CONDITIONAL**
Development can proceed locally. Production deployment is BLOCKED until hosting is verified.
