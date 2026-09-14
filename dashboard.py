import http.server
import socketserver
import os
import sys
import time
import threading
import json
import urllib.parse
import subprocess
import socket
import signal
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
import warnings
warnings.filterwarnings("ignore")

# ==============================================================================
# ⚙️ CONFIGURATION & PATHS
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.getenv("PORT", 9848))

CONSOLE_LOG_FILE = os.path.join(BASE_DIR, "console_log.txt")
STATUS_LOG_FILE = os.path.join(BASE_DIR, "status_log.txt")
ENGINE_CONFIG_FILE = os.path.join(BASE_DIR, "engine_config.json")
RESTART_FLAG_FILE = os.path.join(BASE_DIR, "restart.flag")
RELOAD_ENGINES_FLAG_FILE = os.path.join(BASE_DIR, "reload_engines.flag")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Bot State Files (for fallback status detection)
ACTIVE_STATE_BINANCE = os.path.join(BASE_DIR, "active_state.json")
ACTIVE_STATE_DERIV = os.path.join(BASE_DIR, "active_state_deriv.json")
ACTIVE_STATE_SYNTHETIC = os.path.join(BASE_DIR, "active_state_synthetic.json")

# 🛡️ PIN Security Gate Configuration (Default PIN: 180444)
DEFAULT_PIN = "180444"
DASHBOARD_PIN = os.getenv("DASHBOARD_PIN", DEFAULT_PIN).strip() or DEFAULT_PIN
DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY") or hashlib.sha256(f"ag_classic_secret_{DASHBOARD_PIN}".encode()).hexdigest()

# Session Duration: 7 Days (604,800 Seconds)
SESSION_DURATION_DAYS = 7
SESSION_DURATION_SECS = SESSION_DURATION_DAYS * 86400

_sessions = {}
_sessions_lock = threading.RLock()

# ==============================================================================
# 🛡️ AUTHENTICATION & SESSION TOKEN MANAGEMENT
# ==============================================================================
def generate_session_token() -> str:
    """
    สร้าง Authenticated Session Token แบบ HMAC-SHA256
    รูปแบบ: {created_at}:{nonce}:{signature}
    มีอายุ 7 วัน และทนทานต่อการรีสตาร์ทเซิร์ฟเวอร์ (Stateless verification fallback)
    """
    created_at = int(time.time())
    nonce = secrets.token_hex(8)
    payload = f"{created_at}:{nonce}"
    sig = hmac.new(DASHBOARD_SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    token = f"{payload}:{sig}"
    with _sessions_lock:
        _sessions[token] = created_at + SESSION_DURATION_SECS
    return token

def verify_session_token(token: str) -> bool:
    """
    ตรวจสอบความถูกต้องของ Session Token:
    1. ตรวจสอบใน In-memory Cache เพื่อความเร็ว O(1)
    2. Fallback ตรวจสอบ HMAC signature หากเซิร์ฟเวอร์เพิ่งรีสตาร์ท
    3. ตรวจสอบอายุ 7 วัน ป้องกัน Token หมดอายุ
    """
    if not token or not isinstance(token, str):
        return False
    token = token.strip()
    now = int(time.time())

    with _sessions_lock:
        if token in _sessions:
            if _sessions[token] > now:
                return True
            else:
                del _sessions[token]
                return False

    try:
        parts = token.split(":")
        if len(parts) == 3:
            created_at_str, nonce, sig = parts
            created_at = int(created_at_str)
            if (now - created_at > SESSION_DURATION_SECS) or (created_at > now + 300):
                return False
            expected_payload = f"{created_at_str}:{nonce}"
            expected_sig = hmac.new(DASHBOARD_SECRET_KEY.encode(), expected_payload.encode(), hashlib.sha256).hexdigest()
            if hmac.compare_digest(sig, expected_sig):
                with _sessions_lock:
                    _sessions[token] = created_at + SESSION_DURATION_SECS
                return True
    except Exception:
        pass
    return False

# ==============================================================================
# ⏱️ TIME & LOG HELPERS
# ==============================================================================
def get_thai_datetime():
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=7)

def get_thai_time():
    return get_thai_datetime().strftime('%Y-%m-%d %H:%M:%S')

def is_forex_weekend(dt=None):
    """
    ตรวจสอบสถานะวันหยุดของตลาด Forex สากล (ปิด ส. 04:00 น. - จ. 04:00 น. ตามเวลาไทย)
    """
    if dt is None:
        dt = get_thai_datetime()
    wd = dt.weekday()  # Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
    hour = dt.hour
    if wd == 5:  # วันเสาร์
        return hour >= 4
    elif wd == 6:  # วันอาทิตย์
        return True
    elif wd == 0:  # วันจันทร์
        return hour < 4
    else:  # วันอังคาร - วันศุกร์
        return False

def read_last_lines(filepath, num_lines=180, buffer_size=128 * 1024):
    """
    อ่าน N บรรทัดสุดท้ายจากไฟล์อย่างปลอดภัย รวดเร็วระดับ O(1)
    ไม่โหลดทั้งไฟล์เข้า RAM ปลอดภัยต่อ Race Condition
    """
    try:
        if not os.path.exists(filepath):
            return ""
        size = os.path.getsize(filepath)
        if size == 0:
            return ""

        with open(filepath, "rb") as f:
            if size <= buffer_size:
                data = f.read()
            else:
                f.seek(size - buffer_size)
                data = f.read()
                first_nl = data.find(b"\n")
                if first_nl != -1:
                    data = data[first_nl + 1:]

            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines(keepends=True)
            clean_lines = [l for l in lines if "DeprecationWarning" not in l and "timezone-aware objects" not in l and "dt_utc or datetime.utcnow" not in l and "now_th = datetime.utcnow" not in l and "is_cooling_down = s" not in l]
            if len(clean_lines) > num_lines:
                clean_lines = clean_lines[-num_lines:]
            return "".join(clean_lines)
    except Exception:
        return ""

def get_console_text(lines=180):
    """อ่านข้อความล่าสุดจาก console_log.txt หรือ status_log.txt อย่างปลอดภัย"""
    content = read_last_lines(CONSOLE_LOG_FILE, num_lines=lines)
    if not content.strip():
        content = read_last_lines(STATUS_LOG_FILE, num_lines=lines)
    if not content.strip():
        return "⏳ กำลังรอสัญญาณ Console Log จากระบบ Supervisor..."
    return content

def append_to_console_log(text):
    """บันทึกคำสั่งและผลลัพธ์ลง console_log.txt"""
    try:
        with open(CONSOLE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass

# ==============================================================================
# ⚙️ ENGINE CONFIG & PROCESS SUPERVISION HELPERS
# ==============================================================================
_engine_lock = threading.RLock()

def load_engine_config():
    """โหลดคอนฟิกโหมดเครื่องยนต์จาก engine_config.json"""
    default_cfg = {
        "mode": "synthetic",
        "binance": True,
        "synthetic": True,
        "forex": False,
        "updated_at": get_thai_time()
    }
    with _engine_lock:
        if not os.path.exists(ENGINE_CONFIG_FILE):
            save_engine_config(default_cfg)
            return default_cfg
        try:
            with open(ENGINE_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in default_cfg.items():
                        if k not in data:
                            data[k] = v
                    return data
                return default_cfg
        except Exception:
            return default_cfg

def save_engine_config(cfg):
    """บันทึกคอนฟิกลง engine_config.json อย่างปลอดภัย"""
    try:
        cfg["updated_at"] = get_thai_time()
        with open(ENGINE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False

def trigger_supervisor_update(reason="System restart"):
    """สร้างหรืออัปเดตไฟล์ restart.flag เพื่อแจ้งเตือน Supervisor ให้ Full Restart (ใช้เฉพาะคำสั่ง restart จริงๆ เท่านั้น)"""
    try:
        with open(RESTART_FLAG_FILE, "w", encoding="utf-8") as f:
            f.write(f"{reason} at {get_thai_time()}")
    except Exception:
        pass

def trigger_engine_reload(reason="Engine hot reload"):
    """สร้างหรืออัปเดตไฟล์ reload_engines.flag เพื่อให้ Supervisor สลับ Worker ทันทีแบบ Hot-swap ไร้รอยต่อ โดยไม่รีสตาร์ททั้งระบบและไม่เกิด CPU Spike"""
    try:
        with open(RELOAD_ENGINES_FLAG_FILE, "w", encoding="utf-8") as f:
            f.write(f"{reason} at {get_thai_time()}")
    except Exception:
        pass

def set_engine_mode_config(mode: str):
    """
    ตั้งค่าโหมดเครื่องยนต์: 'synthetic' | 'all' | 'forex' | 'auto'
    บันทึกลง engine_config.json และส่งสัญญาณ reload_engines.flag ให้ Supervisor สลับ Worker ทันที
    """
    mode = str(mode).lower().strip()
    if mode not in ("synthetic", "all", "forex", "auto"):
        return False, f"Invalid mode '{mode}'. Choose: synthetic, all, forex, auto"

    with _engine_lock:
        cfg = load_engine_config()
        cfg["mode"] = mode

        if mode == "synthetic":
            cfg["binance"] = True
            cfg["synthetic"] = True
            cfg["forex"] = False
        elif mode == "all":
            cfg["binance"] = True
            cfg["synthetic"] = True
            cfg["forex"] = True
        elif mode == "forex":
            cfg["binance"] = True
            cfg["synthetic"] = False
            cfg["forex"] = True
        elif mode == "auto":
            cfg["binance"] = True
            weekend = is_forex_weekend()
            cfg["synthetic"] = weekend
            cfg["forex"] = not weekend

        save_engine_config(cfg)

    trigger_engine_reload(f"Engine mode set to {mode}")
    return True, cfg

def toggle_engine_config(engine_name: str):
    """สลับเปิด/ปิดเครื่องยนต์เดี่ยว (binance, forex, synthetic) แบบ Hot-swap"""
    engine_name = str(engine_name).lower().strip()
    with _engine_lock:
        cfg = load_engine_config()
        if engine_name == "binance":
            cfg["binance"] = not cfg.get("binance", True)
            val = cfg["binance"]
        elif engine_name in ("forex", "deriv_forex"):
            cfg["forex"] = not cfg.get("forex", False)
            val = cfg["forex"]
            if cfg["forex"] and cfg.get("synthetic"):
                cfg["mode"] = "all"
            elif cfg["forex"]:
                cfg["mode"] = "forex"
            else:
                cfg["mode"] = "synthetic"
        elif engine_name in ("synthetic", "deriv_synthetic"):
            cfg["synthetic"] = not cfg.get("synthetic", True)
            val = cfg["synthetic"]
            if cfg["synthetic"] and cfg.get("forex"):
                cfg["mode"] = "all"
            elif cfg["synthetic"]:
                cfg["mode"] = "synthetic"
            else:
                cfg["mode"] = "forex"
        else:
            return False, f"Unknown engine '{engine_name}'"

        save_engine_config(cfg)

    trigger_engine_reload(f"Toggled {engine_name} to {val}")
    return True, val

def detect_active_engines():
    """
    ตรวจสอบโปรเซสเครื่องยนต์ที่กำลังรันอยู่จริงบนระบบปฏิบัติการ
    1. ตรวจผ่าน pgrep (ปลอดภัย ไม่ใช้ shell=True)
    2. ตรวจผ่าน /proc (สำหรับ Linux container ไร้ subprocess)
    3. Fallback ตรวจความสดใหม่ของไฟล์ active_state (< 300s)
    """
    active = []

    # 1. pgrep
    try:
        res = subprocess.run(["pgrep", "-fl", "python"], capture_output=True, text=True, timeout=2)
        out = res.stdout or ""
        if "main_binance.py" in out:
            active.append("BinanceEngine")
        if "main_deriv_synthetic.py" in out:
            active.append("DerivSyntheticEngine")
        if "main_forex.py" in out:
            active.append("DerivForexEngine")
    except Exception:
        pass

    # 2. Linux /proc inspection (รวดเร็ว ปลอดภัยระดับ Native)
    if not active and os.path.exists("/proc"):
        try:
            for pid in os.listdir("/proc"):
                if pid.isdigit():
                    cmdline_path = os.path.join("/proc", pid, "cmdline")
                    if os.path.exists(cmdline_path):
                        with open(cmdline_path, "rb") as f:
                            cmdline = f.read().decode("utf-8", errors="ignore")
                            if "main_binance.py" in cmdline and "BinanceEngine" not in active:
                                active.append("BinanceEngine")
                            if "main_deriv_synthetic.py" in cmdline and "DerivSyntheticEngine" not in active:
                                active.append("DerivSyntheticEngine")
                            if "main_forex.py" in cmdline and "DerivForexEngine" not in active:
                                active.append("DerivForexEngine")
        except Exception:
            pass

    # 3. State file modification check fallback (< 300s)
    now = time.time()
    if not active:
        try:
            if os.path.exists(ACTIVE_STATE_BINANCE) and (now - os.path.getmtime(ACTIVE_STATE_BINANCE) < 300):
                active.append("BinanceEngine")
            if os.path.exists(ACTIVE_STATE_SYNTHETIC) and (now - os.path.getmtime(ACTIVE_STATE_SYNTHETIC) < 300):
                active.append("DerivSyntheticEngine")
            if os.path.exists(ACTIVE_STATE_DERIV) and (now - os.path.getmtime(ACTIVE_STATE_DERIV) < 300):
                active.append("DerivForexEngine")
        except Exception:
            pass

    return active

def get_engine_status():
    """
    สร้างข้อมูลสถานะเครื่องยนต์ส่งให้ API และ Dashboard
    คืนค่า JSON:
    {
      "mode": "synthetic",
      "binance": true,
      "synthetic": true,
      "forex": false,
      "active_engines": ["BinanceEngine", "DerivSyntheticEngine"]
    }
    """
    cfg = load_engine_config()
    mode = cfg.get("mode", "synthetic")
    active_engines = detect_active_engines()

    if active_engines:
        binance_active = "BinanceEngine" in active_engines
        synthetic_active = "DerivSyntheticEngine" in active_engines
        forex_active = "DerivForexEngine" in active_engines
    else:
        # หากยังไม่มี Process รันจริง ให้แสดงสถานะตามเป้าหมายของ Config
        binance_active = cfg.get("binance", True)
        if mode == "synthetic":
            synthetic_active = cfg.get("synthetic", True)
            forex_active = False
        elif mode == "all":
            synthetic_active = cfg.get("synthetic", True)
            forex_active = cfg.get("forex", True)
        elif mode == "forex":
            synthetic_active = False
            forex_active = cfg.get("forex", True)
        elif mode == "auto":
            weekend = is_forex_weekend()
            synthetic_active = cfg.get("synthetic", weekend)
            forex_active = cfg.get("forex", not weekend)
        else:
            synthetic_active = cfg.get("synthetic", True)
            forex_active = cfg.get("forex", False)

    return {
        "mode": mode,
        "binance": bool(binance_active),
        "synthetic": bool(synthetic_active),
        "forex": bool(forex_active),
        "active_engines": active_engines
    }

# ==============================================================================
# 🌐 HTML & CLIENT APPLICATION (UPGRADED CLASSIC DASHBOARD)
# ==============================================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AG 2.0 Live Quant Terminal</title>
    <style>
        /* Base / PowerShell Dark Theme (ขาว-ดำ / Charcoal) - ค่าเริ่มต้น */
        :root {
            --bg-color: #0c0c0c;
            --panel-bg: #161b22;
            --terminal-bg: #0d1117;
            --border-color: #30363d;
            --text-primary: #58a6ff;
            --text-terminal: #f0f6fc;
            --prompt-symbol-color: #58a6ff;
            --text-dim: #8b949e;
            --accent-btn: #238636;
            --accent-btn-hover: #2ea043;
            --input-bg: #010409;
            --input-text: #ffffff;
            --danger: #f85149;
            --mode-active-glow: rgba(63, 185, 80, 0.4);
            --mode-active-border: #3fb950;
            --mode-active-bg: rgba(46, 160, 67, 0.18);
            --mode-active-color: #3fb950;
        }

        /* ธีม: PowerShell Classic (น้ำเงินเข้ม-ขาว) */
        body.theme-powershell-blue {
            --bg-color: #011638;
            --panel-bg: #011e4d;
            --terminal-bg: #012456;
            --border-color: #1a3c74;
            --text-primary: #90caf9;
            --text-terminal: #ffffff;
            --prompt-symbol-color: #e5c07b;
            --text-dim: #90a4ae;
            --accent-btn: #0969da;
            --accent-btn-hover: #1f6feb;
            --input-bg: #011a3d;
            --input-text: #ffffff;
            --mode-active-glow: rgba(144, 202, 249, 0.4);
            --mode-active-border: #90caf9;
            --mode-active-bg: rgba(9, 105, 218, 0.25);
            --mode-active-color: #90caf9;
        }

        /* ธีม: Pure Black & White (ดำสนิท-ขาว เรียบหรู) */
        body.theme-true-black {
            --bg-color: #000000;
            --panel-bg: #111111;
            --terminal-bg: #000000;
            --border-color: #262626;
            --text-primary: #ffffff;
            --text-terminal: #ffffff;
            --prompt-symbol-color: #ffffff;
            --text-dim: #777777;
            --accent-btn: #2b2b2b;
            --accent-btn-hover: #444444;
            --input-bg: #0a0a0a;
            --input-text: #ffffff;
            --mode-active-glow: rgba(255, 255, 255, 0.3);
            --mode-active-border: #ffffff;
            --mode-active-bg: #222222;
            --mode-active-color: #ffffff;
        }

        /* ธีม: Matrix Green (เขียวเดิม) */
        body.theme-matrix {
            --bg-color: #0d1117;
            --panel-bg: #161b22;
            --terminal-bg: #010409;
            --border-color: #30363d;
            --text-primary: #58a6ff;
            --text-terminal: #39ff14;
            --prompt-symbol-color: #39ff14;
            --text-dim: #8b949e;
            --accent-btn: #238636;
            --accent-btn-hover: #2ea043;
            --input-bg: #010409;
            --input-text: #ffffff;
            --mode-active-glow: rgba(57, 255, 20, 0.4);
            --mode-active-border: #39ff14;
            --mode-active-bg: rgba(46, 160, 67, 0.22);
            --mode-active-color: #39ff14;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-color);
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            padding: 12px;
            transition: background-color 0.2s;
        }

        /* Top Header */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 16px;
            background: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px 8px 0 0;
        }

        .header-title {
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 700;
            font-size: 1.05em;
            letter-spacing: 0.5px;
            color: var(--text-primary);
            font-family: 'SF Mono', Monaco, Consolas, 'Courier New', monospace;
        }

        .header-status {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 0.85em;
        }

        .badge {
            padding: 3px 8px;
            border-radius: 12px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }

        .badge-live {
            background: rgba(46, 160, 67, 0.2);
            color: #3fb950;
            border: 1px solid rgba(46, 160, 67, 0.4);
        }

        .badge-warning {
            background: rgba(227, 179, 65, 0.2);
            color: #e3b341;
            border: 1px solid rgba(227, 179, 65, 0.4);
        }

        .badge-error {
            background: rgba(248, 81, 73, 0.2);
            color: #f85149;
            border: 1px solid rgba(248, 81, 73, 0.4);
        }

        .pulse-dot {
            width: 8px;
            height: 8px;
            background-color: #3fb950;
            border-radius: 50%;
            animation: pulse 1.8s infinite;
        }

        .pulse-dot.warning {
            background-color: #e3b341;
            animation: pulse-warn 1.4s infinite;
        }

        .pulse-dot.error {
            background-color: #f85149;
            animation: none;
            box-shadow: 0 0 6px #f85149;
        }

        @keyframes pulse {
            0% { transform: scale(0.9); opacity: 0.7; }
            50% { transform: scale(1.3); opacity: 1; box-shadow: 0 0 8px #3fb950; }
            100% { transform: scale(0.9); opacity: 0.7; }
        }

        @keyframes pulse-warn {
            0% { transform: scale(0.9); opacity: 0.7; }
            50% { transform: scale(1.3); opacity: 1; box-shadow: 0 0 8px #e3b341; }
            100% { transform: scale(0.9); opacity: 0.7; }
        }

        /* ⚡ Engine Mode Selector Bar (ใต้ Header) */
        .engine-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 16px;
            background: var(--panel-bg);
            border-left: 1px solid var(--border-color);
            border-right: 1px solid var(--border-color);
            border-bottom: 1px solid var(--border-color);
            font-size: 0.85em;
            flex-wrap: wrap;
            gap: 10px;
        }

        .mode-buttons-group {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .engine-bar-label {
            font-weight: 600;
            color: var(--text-dim);
            margin-right: 2px;
        }

        .btn-mode {
            padding: 5px 12px;
            font-size: 0.85em;
            font-weight: 600;
            border-radius: 6px;
            border: 1px solid var(--border-color);
            background: var(--input-bg);
            color: var(--text-dim);
            cursor: pointer;
            transition: all 0.2s ease;
            outline: none;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            user-select: none;
        }

        .btn-mode:hover {
            background: #21262d;
            color: #ffffff;
            border-color: #8b949e;
        }

        .btn-mode.active {
            background: var(--mode-active-bg);
            color: var(--mode-active-color);
            border-color: var(--mode-active-border);
            box-shadow: 0 0 10px var(--mode-active-glow);
            font-weight: 700;
        }

        .engine-indicators-group {
            display: flex;
            align-items: center;
            gap: 10px;
            font-family: 'SF Mono', Monaco, Consolas, monospace;
            font-size: 0.83em;
            color: var(--text-terminal);
            background: var(--terminal-bg);
            padding: 4px 12px;
            border-radius: 6px;
            border: 1px solid var(--border-color);
            user-select: none;
        }

        .ind-item {
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }

        .ind-dot {
            font-size: 0.9em;
            display: inline-block;
        }

        .ind-sep {
            color: var(--border-color);
        }

        /* Controls Bar (Theme + Scroll) */
        .controls-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 7px 14px;
            background: var(--panel-bg);
            border-left: 1px solid var(--border-color);
            border-right: 1px solid var(--border-color);
            border-bottom: 1px solid var(--border-color);
            font-size: 0.82em;
            color: var(--text-dim);
            flex-wrap: wrap;
            gap: 8px;
        }

        .controls-bar label {
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
            user-select: none;
        }

        .theme-selector {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .theme-selector select {
            background: var(--input-bg);
            color: var(--text-terminal);
            border: 1px solid var(--border-color);
            border-radius: 5px;
            padding: 3px 8px;
            font-size: 0.9em;
            font-family: inherit;
            cursor: pointer;
            outline: none;
        }

        /* Live Console Screen */
        .console-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-height: 520px;
            background: var(--terminal-bg);
            border-left: 1px solid var(--border-color);
            border-right: 1px solid var(--border-color);
            position: relative;
        }

        pre#consoleOutput {
            flex: 1;
            padding: 16px;
            color: var(--text-terminal);
            background: var(--terminal-bg);
            font-family: 'SF Mono', 'Cascadia Code', Consolas, 'Courier New', Menlo, Monaco, monospace;
            font-size: 0.9em;
            line-height: 1.48;
            white-space: pre-wrap;
            word-break: break-all;
            overflow-y: auto;
            max-height: calc(100vh - 220px);
        }

        /* Custom Scrollbar */
        pre#consoleOutput::-webkit-scrollbar {
            width: 8px;
        }
        pre#consoleOutput::-webkit-scrollbar-track {
            background: var(--terminal-bg);
        }
        pre#consoleOutput::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 4px;
        }
        pre#consoleOutput::-webkit-scrollbar-thumb:hover {
            background: var(--text-primary);
        }

        /* Command Input Section */
        .command-wrapper {
            background: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 0 0 8px 8px;
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        form#cmdForm {
            display: flex;
            align-items: center;
            gap: 8px;
            width: 100%;
        }

        .prompt-symbol {
            color: var(--prompt-symbol-color);
            font-family: 'SF Mono', Monaco, Consolas, monospace;
            font-size: 1.05em;
            font-weight: bold;
            padding-left: 4px;
            white-space: nowrap;
        }

        input#cmdInput {
            flex: 1;
            padding: 10px 14px;
            background: var(--input-bg);
            color: var(--input-text);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            font-family: 'SF Mono', Monaco, Consolas, monospace;
            font-size: 0.95em;
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
        }

        input#cmdInput:focus {
            border-color: var(--text-primary);
            box-shadow: 0 0 6px rgba(88, 166, 255, 0.3);
        }

        .btn {
            padding: 10px 18px;
            font-size: 0.9em;
            font-weight: 600;
            border-radius: 6px;
            border: none;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .btn-run {
            background: var(--accent-btn);
            color: #ffffff;
        }

        .btn-run:hover {
            opacity: 0.9;
        }

        .btn-clear {
            background: #21262d;
            color: #c9d1d9;
            border: 1px solid var(--border-color);
        }

        .btn-clear:hover {
            background: #30363d;
            color: #ffffff;
        }

        .cmd-status {
            font-size: 0.8em;
            color: var(--text-dim);
            padding-left: 6px;
            min-height: 18px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .cmd-status.running {
            color: #e3b341;
        }

        .cmd-status.success {
            color: #3fb950;
        }

        .cmd-status.error {
            color: var(--danger);
        }
    </style>
</head>
<body>
    <!-- Header -->
    <header>
        <div class="header-title">
            <span>⚡ AG 2.0 QUANT TERMINAL</span>
            <span style="color: var(--border-color);">|</span>
            <span style="color: var(--text-dim); font-size: 0.85em;">Wispbyte Live Stream</span>
        </div>
        <div class="header-status">
            <span class="badge badge-live" id="streamBadge">
                <span class="pulse-dot" id="pulseDot"></span>
                <span id="badgeText">STREAMING</span>
            </span>
            <span style="color: var(--text-dim); font-size: 0.8em;" id="lastSyncTime">Sync: ...</span>
        </div>
    </header>

    <!-- ⚡ Engine Mode Selector Bar -->
    <div class="engine-bar">
        <div class="mode-buttons-group">
            <span class="engine-bar-label">⚙️ โหมด:</span>
            <button type="button" class="btn-mode" id="btnModeSynthetic" data-mode="synthetic" onclick="setEngineMode('synthetic')">⚡ Synthetic 24/7</button>
            <button type="button" class="btn-mode" id="btnModeAll" data-mode="all" onclick="setEngineMode('all')">🤖 All (3 Engines)</button>
            <button type="button" class="btn-mode" id="btnModeForex" data-mode="forex" onclick="setEngineMode('forex')">📈 Forex Only</button>
            <button type="button" class="btn-mode" id="btnModeAuto" data-mode="auto" onclick="setEngineMode('auto')">🔄 Auto-Switch</button>
        </div>
        <div class="engine-indicators-group">
            <span class="ind-item">Binance: <span id="indBinance" class="ind-dot">⚪</span></span>
            <span class="ind-sep">|</span>
            <span class="ind-item">Synthetic: <span id="indSynthetic" class="ind-dot">⚪</span></span>
            <span class="ind-sep">|</span>
            <span class="ind-item">Forex: <span id="indForex" class="ind-dot">⚪</span></span>
        </div>
    </div>

    <!-- Controls Bar -->
    <div class="controls-bar">
        <div class="theme-selector">
            <span>🎨 ธีมสี:</span>
            <select id="themeSelect" onchange="applyTheme(this.value)">
                <option value="powershell-dark">⚪ PowerShell Dark (ขาว-ดำ / Charcoal)</option>
                <option value="powershell-blue">🔷 PowerShell Classic (น้ำเงินเข้ม-ขาว)</option>
                <option value="true-black">⬛ Pure Black & White (ดำสนิท-ขาวโอโม)</option>
                <option value="matrix">🟢 Matrix Green (เขียวเดิม)</option>
            </select>
        </div>
        <div style="display: flex; gap: 16px; align-items: center;">
            <label>
                <input type="checkbox" id="chkAutoScroll" checked>
                <span>Auto-Scroll ด้านล่างสุด</span>
            </label>
            <button class="btn btn-clear" style="padding: 2px 8px; font-size: 0.8em;" onclick="manualScrollBottom()">⬇️ ล่างสุด</button>
        </div>
    </div>

    <!-- Console Output Screen -->
    <div class="console-container">
        <pre id="consoleOutput">กำลังโหลดข้อมูล Console Log ล่าสุด...</pre>
    </div>

    <!-- Command Input Bar -->
    <div class="command-wrapper">
        <form id="cmdForm" onsubmit="handleCommandSubmit(event)">
            <span class="prompt-symbol" id="promptText">PS &gt;</span>
            <input type="text" id="cmdInput" placeholder="พิมพ์คำสั่ง เช่น mode synthetic, restart, help, ps aux (กด Enter)..." autocomplete="off" spellcheck="false">
            <button type="submit" class="btn btn-run" id="btnRun">Execute</button>
            <button type="button" class="btn btn-clear" onclick="clearConsole()">Clear Screen</button>
        </form>
        <div class="cmd-status" id="cmdStatus">
            <span>พร้อมรับคำสั่ง (พิมพ์ <b>restart</b> เพื่อรีสตาร์ทบอททั้งหมด, พิมพ์ <b>help</b> เพื่อดูคำสั่งทั้งหมด)</span>
        </div>
    </div>

    <script>
        const consoleEl = document.getElementById('consoleOutput');
        const cmdInput = document.getElementById('cmdInput');
        const cmdStatus = document.getElementById('cmdStatus');
        const chkAutoScroll = document.getElementById('chkAutoScroll');
        const lastSyncTimeEl = document.getElementById('lastSyncTime');
        const btnRun = document.getElementById('btnRun');
        const themeSelect = document.getElementById('themeSelect');
        const promptText = document.getElementById('promptText');
        const streamBadge = document.getElementById('streamBadge');
        const pulseDot = document.getElementById('pulseDot');
        const badgeText = document.getElementById('badgeText');

        // Elements for Engine Mode & Indicators
        const indBinance = document.getElementById('indBinance');
        const indSynthetic = document.getElementById('indSynthetic');
        const indForex = document.getElementById('indForex');

        let isFirstLoad = true;
        let isUserScrolling = false;
        let cmdHistory = [];
        let historyIndex = -1;
        let consecutiveErrors = 0;

        // =====================================================================
        // ⚡ ENGINE MODE & REAL-TIME STATUS CONTROLLER
        // =====================================================================
        function updateEngineStatusUI(data) {
            if (!data) return;

            const activeMode = data.mode || 'synthetic';
            document.querySelectorAll('.btn-mode').forEach(btn => {
                if (btn.getAttribute('data-mode') === activeMode) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            });

            if (indBinance) indBinance.textContent = data.binance ? '🟢' : '⚪';
            if (indSynthetic) indSynthetic.textContent = data.synthetic ? '🟢' : '⚪';
            if (indForex) indForex.textContent = data.forex ? '🟢' : '⚪';
        }

        async function fetchEngineStatus() {
            try {
                const res = await fetch('/api/engine_status?t=' + Date.now());
                if (res.ok) {
                    const data = await res.json();
                    updateEngineStatusUI(data);
                }
            } catch (err) {}
        }

        let isSwitchingMode = false;
        async function setEngineMode(mode) {
            if (isSwitchingMode) return;
            isSwitchingMode = true;
            cmdStatus.className = 'cmd-status running';
            cmdStatus.textContent = '⏳ กำลังสลับโหมดเป็น ' + mode + ' (Hot-swap)...';

            try {
                const res = await fetch('/api/set_engine_mode', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ mode: mode })
                });

                const data = await res.json();
                if (res.ok && (data.status === 'success' || data.mode)) {
                    updateEngineStatusUI(data);
                    cmdStatus.className = 'cmd-status success';
                    cmdStatus.textContent = '✅ สลับโหมดเป็น [' + mode.toUpperCase() + '] สำเร็จ! (Hot-swap ไร้รอยต่อ ไม่รีสตาร์ทเซิร์ฟเวอร์)';
                    consoleEl.textContent += `\\n[WEB-TERMINAL] ⚡ สลับโหมดเครื่องยนต์เป็น '${mode}' สำเร็จ (Hot-swap ไร้รอยต่อ)\\n`;
                    if (chkAutoScroll.checked) consoleEl.scrollTop = consoleEl.scrollHeight;
                } else {
                    cmdStatus.className = 'cmd-status error';
                    cmdStatus.textContent = '❌ ผิดพลาด: ' + (data.error || 'Unknown error');
                }
            } catch (err) {
                cmdStatus.className = 'cmd-status error';
                cmdStatus.textContent = '❌ ไม่สามารถเชื่อมต่อได้: ' + err.message;
            } finally {
                isSwitchingMode = false;
            }
        }

        // =====================================================================
        // 🎨 THEME & STREAMING CONTROLLER
        // =====================================================================
        function updateStreamStatus(state, msg) {
            if (state === 'live') {
                consecutiveErrors = 0;
                if (streamBadge) streamBadge.className = 'badge badge-live';
                if (pulseDot) pulseDot.className = 'pulse-dot';
                if (badgeText) badgeText.textContent = 'STREAMING';
                if (lastSyncTimeEl) lastSyncTimeEl.textContent = 'Sync: ' + msg;
            } else if (state === 'reconnecting') {
                consecutiveErrors++;
                if (consecutiveErrors >= 3) {
                    if (streamBadge) streamBadge.className = 'badge badge-error';
                    if (pulseDot) pulseDot.className = 'pulse-dot error';
                    if (badgeText) badgeText.textContent = 'OFFLINE';
                } else {
                    if (streamBadge) streamBadge.className = 'badge badge-warning';
                    if (pulseDot) pulseDot.className = 'pulse-dot warning';
                    if (badgeText) badgeText.textContent = 'RECONNECTING';
                }
                if (lastSyncTimeEl) lastSyncTimeEl.textContent = 'Sync: ' + msg;
            }
        }

        function applyTheme(theme) {
            document.body.className = '';
            if (theme === 'powershell-blue') {
                document.body.classList.add('theme-powershell-blue');
                promptText.textContent = 'PS C:\\\\> ';
            } else if (theme === 'true-black') {
                document.body.classList.add('theme-true-black');
                promptText.textContent = '$ ';
            } else if (theme === 'matrix') {
                document.body.classList.add('theme-matrix');
                promptText.textContent = '$ ';
            } else {
                promptText.textContent = 'PS > ';
            }
            themeSelect.value = theme;
            localStorage.setItem('ag_terminal_theme', theme);
        }

        const savedTheme = localStorage.getItem('ag_terminal_theme') || 'powershell-dark';
        applyTheme(savedTheme);

        consoleEl.addEventListener('scroll', () => {
            const isNearBottom = consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 60;
            if (!isNearBottom && chkAutoScroll.checked) {
                isUserScrolling = true;
            } else if (isNearBottom) {
                isUserScrolling = false;
            }
        });

        function manualScrollBottom() {
            chkAutoScroll.checked = true;
            isUserScrolling = false;
            consoleEl.scrollTop = consoleEl.scrollHeight;
        }

        let isFetching = false;
        async function fetchConsoleLogs() {
            if (isFetching) return;
            isFetching = true;
            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 4000);
                const res = await fetch('/api/console?t=' + Date.now(), {
                    signal: controller.signal
                });
                clearTimeout(timeoutId);

                if (res.ok) {
                    const text = await res.text();
                    if (text && text.trim().length > 0) {
                        if (consoleEl.textContent !== text) {
                            consoleEl.textContent = text;
                            if (isFirstLoad || (chkAutoScroll.checked && !isUserScrolling)) {
                                consoleEl.scrollTop = consoleEl.scrollHeight;
                                isFirstLoad = false;
                            }
                        }
                    } else if (isFirstLoad) {
                        consoleEl.textContent = "⏳ กำลังรอสัญญาณ Console Log จากระบบ Supervisor...";
                    }
                    const now = new Date();
                    updateStreamStatus('live', now.toLocaleTimeString('th-TH'));
                } else {
                    updateStreamStatus('reconnecting', 'HTTP ' + res.status);
                }
            } catch (err) {
                const errLabel = err.name === 'AbortError' ? 'Timeout' : 'Reconnecting...';
                updateStreamStatus('reconnecting', errLabel);
            } finally {
                isFetching = false;
            }
        }

        // =====================================================================
        // ⌨️ COMMAND EXECUTION & CLI CONTROLLER
        // =====================================================================
        async function handleCommandSubmit(e) {
            e.preventDefault();
            const cmd = cmdInput.value.trim();
            if (!cmd) return;

            cmdHistory.push(cmd);
            historyIndex = cmdHistory.length;

            cmdStatus.className = 'cmd-status running';
            cmdStatus.textContent = '⏳ กำลังส่งและรันคำสั่ง: ' + cmd + '...';
            btnRun.disabled = true;

            consoleEl.textContent += `\n[WEB-TERMINAL] $ ${cmd}\n`;
            if (chkAutoScroll.checked) consoleEl.scrollTop = consoleEl.scrollHeight;

            try {
                const res = await fetch('/api/run', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ cmd: cmd })
                });

                const data = await res.json();
                if (data.status === 'success') {
                    cmdStatus.className = 'cmd-status success';
                    cmdStatus.textContent = '✅ คำสั่งทำงานสำเร็จ (' + new Date().toLocaleTimeString('th-TH') + ')';
                    if (data.output) {
                        consoleEl.textContent += data.output + '\\n';
                        if (chkAutoScroll.checked) consoleEl.scrollTop = consoleEl.scrollHeight;
                    }
                    const cmdLower = cmd.toLowerCase();
                    if (cmdLower.startsWith('mode') || cmdLower.startsWith('toggle') || cmdLower.includes('restart')) {
                        setTimeout(fetchEngineStatus, 400);
                    }
                } else {
                    cmdStatus.className = 'cmd-status error';
                    cmdStatus.textContent = '❌ ผิดพลาด: ' + (data.error || 'Unknown error');
                }
            } catch (err) {
                const isRestart = cmd.toLowerCase().startsWith('restart') || cmd.toLowerCase() === 'reboot';
                if (isRestart) {
                    cmdStatus.className = 'cmd-status success';
                    cmdStatus.textContent = '🔄 กำลังรีสตาร์ทระบบและดึงโค้ดล่าสุด... สตรีมสดจะกลับมาใน 3-5 วินาที';
                    consoleEl.textContent += '\\n[WEB-TERMINAL] 🔄 ส่งสัญญาณรีสตาร์ทระบบสำเร็จ กำลังเชื่อมต่อใหม่อัตโนมัติ...\\n';
                    setTimeout(fetchEngineStatus, 1500);
                } else {
                    cmdStatus.className = 'cmd-status error';
                    cmdStatus.textContent = '❌ ไม่สามารถส่งคำสั่งได้: ' + err.message;
                }
            } finally {
                btnRun.disabled = false;
                cmdInput.value = '';
                cmdInput.focus();
            }
        }

        cmdInput.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowUp') {
                if (cmdHistory.length > 0 && historyIndex > 0) {
                    historyIndex--;
                    cmdInput.value = cmdHistory[historyIndex];
                }
                e.preventDefault();
            } else if (e.key === 'ArrowDown') {
                if (historyIndex < cmdHistory.length - 1) {
                    historyIndex++;
                    cmdInput.value = cmdHistory[historyIndex];
                } else {
                    historyIndex = cmdHistory.length;
                    cmdInput.value = '';
                }
                e.preventDefault();
            }
        });

        function clearConsole() {
            consoleEl.textContent = '--- Screen Cleared (Waiting next log stream) ---\\n';
        }

        // =====================================================================
        // 🚀 BOOTSTRAP TIMERS & WISPBYTE LOW-CPU POLLING
        // =====================================================================
        let logIntervalId = null;
        let statusIntervalId = null;

        function startPolling(logMs = 3500, statusMs = 5000) {
            if (logIntervalId) clearInterval(logIntervalId);
            if (statusIntervalId) clearInterval(statusIntervalId);
            logIntervalId = setInterval(fetchConsoleLogs, logMs);
            statusIntervalId = setInterval(fetchEngineStatus, statusMs);
        }

        // เมื่อสลับแท็บไปหน้าอื่น ชะลอความถี่เพื่อประหยัด CPU เซิร์ฟเวอร์สูงสุด
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                // แท็บอยู่เบื้องหลัง: ดึงทุก 12 วินาที / 15 วินาที
                startPolling(12000, 15000);
            } else {
                // แท็บกลับมาโฟกัส: ดึงทันทีและคืนรอบปกติ
                fetchConsoleLogs();
                fetchEngineStatus();
                startPolling(3500, 5000);
            }
        });

        fetchConsoleLogs();
        fetchEngineStatus();
        startPolling(3500, 5000);
        if (cmdInput) cmdInput.focus();
    </script>
</body>
</html>
"""

# ==============================================================================
# 🌐 HTTP SERVER & REQUEST HANDLER
# ==============================================================================
class QuantTerminalHandler(http.server.BaseHTTPRequestHandler):
    timeout = 10
    protocol_version = "HTTP/1.1"

    def get_token_from_request(self):
        return ""

    def is_authenticated(self):
        return True

    def send_unauthorized(self, msg="Unauthorized"):
        self._send_json({"status": "ok", "authenticated": True}, 200)

    def _send_auth_success(self, token):
        try:
            self.close_connection = True
            data = {"status": "ok", "authenticated": True, "token": token}
            encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Set-Cookie", f"token={token}; Path=/; Max-Age={SESSION_DURATION_SECS}; SameSite=Lax")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)
            try:
                self.wfile.flush()
            except Exception:
                pass
        except (BrokenPipeError, ConnectionResetError, socket.error):
            pass

    def _send_json(self, data, status=200):
        try:
            self.close_connection = True
            encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)
            try:
                self.wfile.flush()
            except Exception:
                pass
        except (BrokenPipeError, ConnectionResetError, socket.error):
            pass

    def do_OPTIONS(self):
        try:
            self.close_connection = True
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, socket.error):
            pass

    def do_GET(self):
        self.close_connection = True
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            # 1. API: ตรวจสอบสถานะ Authentication & Health Check (Render, Cloud, Docker)
            if path in ("/api/auth", "/api/auth/verify", "/healthz", "/ping"):
                self._send_json({"status": "ok", "healthy": True}, 200)
                return

            # 2. API: Engine Status (อ่าน engine_config.json และ active processes)
            if path == "/api/engine_status":
                status = get_engine_status()
                self._send_json(status, 200)
                return

            # 3. API: Console Log Stream
            if path.startswith("/api/console"):
                log_content = get_console_text(lines=180)
                encoded = log_content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)
                try:
                    self.wfile.flush()
                except Exception:
                    pass
                return

            # 4. Static Files (หากมี)
            if path.startswith("/static/"):
                rel_path = path[len("/static/"):].lstrip("/")
                safe_path = os.path.normpath(os.path.join(STATIC_DIR, rel_path))
                if safe_path.startswith(STATIC_DIR) and os.path.isfile(safe_path):
                    with open(safe_path, "rb") as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return

            # 5. Web Page: หน้าจอเดี่ยว Pure Classic Terminal
            if path == "/" or path.startswith("/?"):
                encoded = HTML_PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)
                try:
                    self.wfile.flush()
                except Exception:
                    pass
                return

            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, socket.error):
            pass

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 1. API Auth: เข้าถึงได้ทันที (Direct Access)
        if path == "/api/auth":
            self._send_json({"status": "ok", "authenticated": True}, 200)
            return

        # 2. API: ตั้งค่า Engine Mode (POST /api/set_engine_mode)
        if path == "/api/set_engine_mode":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length).decode('utf-8')
                mode = ""
                try:
                    data = json.loads(post_data)
                    mode = data.get("mode", "")
                except Exception:
                    params = urllib.parse.parse_qs(post_data)
                    mode = params.get("mode", [""])[0]

                mode = str(mode).strip().lower()
                success, res_val = set_engine_mode_config(mode)
                if not success:
                    self._send_json({"status": "error", "error": res_val}, 400)
                    return

                append_to_console_log(f"\n[{get_thai_time()}] [API-SET-MODE] ⚙️ ผู้ใช้งานสลับโหมดเครื่องยนต์เป็น '{mode}' ผ่าน Web UI\n")
                status_data = get_engine_status()
                status_data["status"] = "success"
                status_data["message"] = f"โหมดถูกเปลี่ยนเป็น {mode} เรียบร้อยแล้ว"
                self._send_json(status_data, 200)
                return
            except Exception as e:
                self._send_json({"status": "error", "error": str(e)}, 500)
                return

        # 3. API: รับคำสั่ง Execute Command บน Server (POST /api/run)
        if path in ("/api/run", "/run"):

            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length).decode('utf-8')
                cmd = ""
                try:
                    data = json.loads(post_data)
                    cmd = data.get('cmd', '').strip()
                except Exception:
                    params = urllib.parse.parse_qs(post_data)
                    cmd = params.get('cmd', [''])[0].strip()

                if not cmd:
                    self._send_json({"status": "error", "error": "ไม่มีคำสั่งถูกส่งมา"}, 400)
                    return

                cmd_lower = cmd.lower().strip()

                # ⚡ คำสั่งพิเศษ: Engine Mode CLI (mode synthetic | mode all | mode forex | mode auto)
                if cmd_lower in ("mode synthetic", "mode:synthetic", "/mode synthetic"):
                    success, cfg = set_engine_mode_config("synthetic")
                    output = (
                        "⚡ [ENGINE MODE CHANGED]\n"
                        "โหมดถูกเปลี่ยนเป็น: Synthetic 24/7 (Deriv Volatility Indices 24 ชม.)\n"
                        f"สถานะคอนฟิก: Binance={'ON 🟢' if cfg.get('binance') else 'OFF ⚪'} | Synthetic=ON 🟢 | Forex=OFF ⚪\n"
                        "บันทึกลง engine_config.json และส่งสัญญาณ reload_engines.flag ให้ Supervisor เรียบร้อย (Hot-swap ไร้รอยต่อ ไม่รีสตาร์ทเซิร์ฟเวอร์)"
                    )
                    append_to_console_log(f"\n[{get_thai_time()}] [MODE-SWITCH] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.05})
                    return

                elif cmd_lower in ("mode all", "mode:all", "/mode all"):
                    success, cfg = set_engine_mode_config("all")
                    output = (
                        "🤖 [ENGINE MODE CHANGED]\n"
                        "โหมดถูกเปลี่ยนเป็น: All (3 Engines: Binance Spot + Deriv Forex + Deriv Synthetic)\n"
                        "สถานะคอนฟิก: รันพร้อมกันทุกเครื่องยนต์ (Binance=ON 🟢 | Synthetic=ON 🟢 | Forex=ON 🟢)\n"
                        "บันทึกลง engine_config.json และส่งสัญญาณ reload_engines.flag ให้ Supervisor เรียบร้อย (Hot-swap ไร้รอยต่อ ไม่รีสตาร์ทเซิร์ฟเวอร์)"
                    )
                    append_to_console_log(f"\n[{get_thai_time()}] [MODE-SWITCH] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.05})
                    return

                elif cmd_lower in ("mode forex", "mode:forex", "/mode forex"):
                    success, cfg = set_engine_mode_config("forex")
                    output = (
                        "📈 [ENGINE MODE CHANGED]\n"
                        "โหมดถูกเปลี่ยนเป็น: Forex Only (EURUSD, GBPUSD, USDJPY)\n"
                        f"สถานะคอนฟิก: Binance={'ON 🟢' if cfg.get('binance') else 'OFF ⚪'} | Synthetic=OFF ⚪ | Forex=ON 🟢\n"
                        "บันทึกลง engine_config.json และส่งสัญญาณ reload_engines.flag ให้ Supervisor เรียบร้อย (Hot-swap ไร้รอยต่อ ไม่รีสตาร์ทเซิร์ฟเวอร์)"
                    )
                    append_to_console_log(f"\n[{get_thai_time()}] [MODE-SWITCH] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.05})
                    return

                elif cmd_lower in ("mode auto", "mode:auto", "/mode auto"):
                    success, cfg = set_engine_mode_config("auto")
                    weekend = is_forex_weekend()
                    target_now = "Synthetic (วันหยุดสุดสัปดาห์)" if weekend else "Forex (วันทำการปกติ)"
                    output = (
                        "🔄 [ENGINE MODE CHANGED]\n"
                        f"โหมดถูกเปลี่ยนเป็น: Auto-Switch (ปัจจุบันคือ: {target_now})\n"
                        "ระบบจะสลับระหว่าง Forex (จันทร์-ศุกร์) และ Synthetic (เสาร์-อาทิตย์) อัตโนมัติ 100%\n"
                        "บันทึกลง engine_config.json และส่งสัญญาณ reload_engines.flag ให้ Supervisor เรียบร้อย (Hot-swap ไร้รอยต่อ ไม่รีสตาร์ทเซิร์ฟเวอร์)"
                    )
                    append_to_console_log(f"\n[{get_thai_time()}] [MODE-SWITCH] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.05})
                    return

                # ⚡ คำสั่งพิเศษ: Toggle Engines CLI (toggle binance | toggle forex | toggle synthetic)
                elif cmd_lower in ("toggle binance", "toggle:binance", "/toggle binance"):
                    success, val = toggle_engine_config("binance")
                    state_str = "เปิดทำงาน 🟢 (ON)" if val else "ปิดทำงาน ⚪ (OFF)"
                    output = f"🔄 [TOGGLE ENGINE]\nBinance Engine: {state_str}\nบันทึก engine_config.json และส่งสัญญาณ reload_engines.flag เรียบร้อย (Hot-swap ไม่รีสตาร์ทเซิร์ฟเวอร์)"
                    append_to_console_log(f"\n[{get_thai_time()}] [TOGGLE] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.05})
                    return

                elif cmd_lower in ("toggle forex", "toggle:forex", "/toggle forex"):
                    success, val = toggle_engine_config("forex")
                    state_str = "เปิดทำงาน 🟢 (ON)" if val else "ปิดทำงาน ⚪ (OFF)"
                    output = f"🔄 [TOGGLE ENGINE]\nDeriv Forex Engine: {state_str}\nบันทึก engine_config.json และส่งสัญญาณ reload_engines.flag เรียบร้อย (Hot-swap ไม่รีสตาร์ทเซิร์ฟเวอร์)"
                    append_to_console_log(f"\n[{get_thai_time()}] [TOGGLE] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.05})
                    return

                elif cmd_lower in ("toggle synthetic", "toggle:synthetic", "/toggle synthetic"):
                    success, val = toggle_engine_config("synthetic")
                    state_str = "เปิดทำงาน 🟢 (ON)" if val else "ปิดทำงาน ⚪ (OFF)"
                    output = f"🔄 [TOGGLE ENGINE]\nDeriv Synthetic Engine: {state_str}\nบันทึก engine_config.json และส่งสัญญาณ reload_engines.flag เรียบร้อย (Hot-swap ไม่รีสตาร์ทเซิร์ฟเวอร์)"
                    append_to_console_log(f"\n[{get_thai_time()}] [TOGGLE] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.05})
                    return

                # ⚡ คำสั่งพิเศษ: แสดงสถานะเครื่องยนต์ปัจจุบัน
                elif cmd_lower in ("status", "engine", "engines", "mode", "engine_status"):
                    st = get_engine_status()
                    active_str = ", ".join(st["active_engines"]) if st["active_engines"] else "ไม่มี (รันเดี่ยวหรือกำลังเริ่ม)"
                    output = (
                        f"📊 [ENGINE STATUS REPORT]\n"
                        f"  • Current Mode   : {st['mode'].upper()}\n"
                        f"  • Binance Engine : {'🟢 RUNNING (ON)' if st['binance'] else '⚪ STOPPED (OFF)'}\n"
                        f"  • Synthetic 24/7 : {'🟢 RUNNING (ON)' if st['synthetic'] else '⚪ STOPPED (OFF)'}\n"
                        f"  • Forex Engine   : {'🟢 RUNNING (ON)' if st['forex'] else '⚪ STOPPED (OFF)'}\n"
                        f"  • Active Engines : {active_str}\n"
                        f"  • Forex Weekend  : {'YES (Closed)' if is_forex_weekend() else 'NO (Open)'}"
                    )
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.01})
                    return

                # ⚡ คำสั่งพิเศษ: Restart ระบบทั้งหมด (main.py + Binance + Deriv)
                elif cmd_lower in ("restart", "restart bot", "restart all", "/restart", "reboot"):
                    git_msg = ""
                    try:
                        git_res = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True, timeout=10)
                        if git_res.stdout.strip():
                            git_msg = f"\n[GIT] {git_res.stdout.strip()}"
                    except Exception as ge:
                        git_msg = f"\n[GIT NOTE] {ge}"

                    def schedule_restart_flag():
                        time.sleep(0.8)
                        trigger_supervisor_update("Full restart requested")

                    threading.Thread(target=schedule_restart_flag, daemon=True).start()

                    output = (
                        "🔄 [COMMAND RESTART ACCEPTED]\n"
                        f"ได้รับคำสั่งรีสตาร์ทระบบเรียบร้อยแล้ว!{git_msg}\n"
                        "⏳ กำลังส่งสัญญาณให้ Supervisor ปิด Workers และ Re-execute main.py ตัวใหม่ทันที...\n"
                        "📡 หน้าจอ Console จะกลับมาสตรีมสดอัตโนมัติใน 3-5 วินาที ไร้การหลุดจากคอนเทนเนอร์"
                    )
                    append_to_console_log(f"\n[{get_thai_time()}] [WEB-TERMINAL-RESTART] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.5})
                    return

                # ⚡ คำสั่งพิเศษ: AI Offline Retraining
                elif cmd_lower in ("train", "retrain", "train ai", "ai train"):
                    def run_bg_train():
                        try:
                            append_to_console_log(f"\n[{get_thai_time()}] [AI-TRAIN] 🧠 เริ่มต้น Offline Retraining ใน Background...\n")
                            proc = subprocess.Popen(
                                [sys.executable, "-u", "train_offline.py"],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True,
                                bufsize=1
                            )
                            for line in iter(proc.stdout.readline, ''):
                                if not line:
                                    break
                                append_to_console_log(line.rstrip())
                            proc.stdout.close()
                            proc.wait()
                            append_to_console_log(f"\n[{get_thai_time()}] [AI-TRAIN] 🎯 เสร็จสมบูรณ์ (Code: {proc.returncode})\n")
                        except Exception as e:
                            append_to_console_log(f"\n[{get_thai_time()}] [AI-TRAIN ERROR] ❌ {e}\n")

                    threading.Thread(target=run_bg_train, daemon=True).start()
                    output = (
                        "🧠 [AI RETRAINING INITIATED]\n"
                        "คำสั่งฝึกฝนโมเดล AI RL ถูกส่งไปยัง Background Process เรียบร้อยแล้ว!\n"
                        "⚡ กำลังเริ่มรัน train_offline.py (Brad Goh SMC + Grid Search)...\n"
                        "📡 ติดตามความคืบหน้าสดได้บนหน้าจอ Console นี้แบบ Real-Time"
                    )
                    append_to_console_log(f"\n[{get_thai_time()}] [WEB-TERMINAL-TRAIN] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.1})
                    return

                # ⚡ คำสั่งพิเศษ: รีสตาร์ทเฉพาะ Binance
                elif cmd_lower in ("restart binance", "restart btc", "restart crypto"):
                    subprocess.run(["pkill", "-f", "main_binance.py"])
                    output = "🔄 กำลังสั่งรีสตาร์ทเฉพาะ Binance Spot Engine... (Supervisor จะเปิดขึ้นมาใหม่ใน 2 วินาที)"
                    append_to_console_log(f"\n[{get_thai_time()}] [WEB-TERMINAL-RESTART] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.2})
                    return

                # ⚡ คำสั่งพิเศษ: รีสตาร์ทเฉพาะ Deriv (Forex / Synthetic)
                elif cmd_lower in ("restart deriv", "restart forex", "restart synthetic"):
                    subprocess.run(["pkill", "-f", "main_forex.py"])
                    subprocess.run(["pkill", "-f", "main_deriv_synthetic.py"])
                    output = "🔄 กำลังสั่งรีสตาร์ท Deriv Engine... (Supervisor จะเปิดขึ้นมาใหม่ตามโหมดวันทำการใน 2 วินาที)"
                    append_to_console_log(f"\n[{get_thai_time()}] [WEB-TERMINAL-RESTART] $ {cmd}\n{output}\n")
                    self._send_json({"status": "success", "cmd": cmd, "output": output, "elapsed_sec": 0.2})
                    return

                # ⚡ คำสั่งพิเศษ: Help เมนูแนะนำคำสั่ง
                elif cmd_lower in ("help", "/help", "?"):
                    help_text = (
                        "📖 [AVAILABLE BOT COMMANDS]\n"
                        "  ⚙️ Engine Control:\n"
                        "    • mode synthetic   : สลับโหมดเทรด Synthetic Indices 24/7\n"
                        "    • mode all         : รันพร้อมกันทุกเครื่องยนต์ (Binance + Forex + Synthetic)\n"
                        "    • mode forex       : สลับโหมดเทรดเฉพาะ Forex (EURUSD, GBPUSD, USDJPY)\n"
                        "    • mode auto        : สลับอัตโนมัติตามวันเปิดทำการ (Forex จ.-ศ. / Synthetic ส.-อา.)\n"
                        "    • toggle binance   : เปิด/ปิด Binance Spot Engine\n"
                        "    • toggle forex     : เปิด/ปิด Deriv Forex Engine\n"
                        "    • toggle synthetic : เปิด/ปิด Deriv Synthetic Engine\n"
                        "    • status / engines : ตรวจสอบสถานะโหมดและเครื่องยนต์ที่กำลังรันอยู่\n\n"
                        "  🔄 Supervisor & System:\n"
                        "    • restart          : ดึงโค้ดล่าสุดจาก GitHub และรีสตาร์ทระบบทั้งหมด\n"
                        "    • restart binance  : รีสตาร์ทเฉพาะ Binance Spot Engine\n"
                        "    • restart deriv    : รีสตาร์ทเฉพาะ Deriv Engine\n"
                        "    • train / retrain  : สั่งรัน AI Retraining ใน Background ทันที\n"
                        "    • git pull         : ดึงโค้ดอัปเดตจาก GitHub ทันที\n"
                        "    • git status       : เช็คสถานะไฟล์ Git Commit ล่าสุด\n"
                        "    • ls -la / ps aux  : ดูรายชื่อไฟล์ / ตรวจสอบ PID โปรเซส Linux"
                    )
                    self._send_json({"status": "success", "cmd": cmd, "output": help_text, "elapsed_sec": 0.01})
                    return

                # รันคำสั่งทั่วไปบนระบบ
                start_time = time.time()
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=20
                )
                elapsed = time.time() - start_time

                output = result.stdout
                if result.stderr:
                    output += ("\n" if output else "") + "[STDERR]: " + result.stderr

                if not output.strip():
                    output = "(คำสั่งทำงานสำเร็จ รหัส Exit Code: 0)"

                formatted_log = (
                    f"\n[{get_thai_time()}] [WEB-TERMINAL-EXEC] $ {cmd} (ใช้เวลา {elapsed:.2f}s)\n"
                    f"{output.strip()}\n"
                )
                append_to_console_log(formatted_log)

                self._send_json({
                    "status": "success",
                    "cmd": cmd,
                    "output": output.strip(),
                    "elapsed_sec": round(elapsed, 2)
                })

            except subprocess.TimeoutExpired:
                err_msg = "⏳ หมดเวลา (Timeout 20 วินาที): คำสั่งใช้เวลานานเกินไป"
                append_to_console_log(f"\n[{get_thai_time()}] [WEB-TERMINAL-TIMEOUT] $ {cmd}\n")
                self._send_json({"status": "error", "error": err_msg}, 408)
            except Exception as e:
                self._send_json({"status": "error", "error": str(e)}, 500)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

# ==============================================================================
# 🚀 SERVER RUNNER & LIFECYCLE
# ==============================================================================
class RobustThreadingHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass
        super().server_bind()

    def handle_error(self, request, client_address):
        exc_type, exc_val, _ = sys.exc_info()
        if exc_type in (BrokenPipeError, ConnectionResetError, socket.timeout):
            return
        super().handle_error(request, client_address)

_shutdown_event = threading.Event()

def signal_handler(signum, frame):
    print(f"\n🛑 ได้รับสัญญาณ ({signum}) กำลังปิด Terminal Server อย่างปลอดภัย...")
    _shutdown_event.set()

def run_server():
    load_engine_config()

    print(f"🚀 เริ่มต้นระบบ AG 2.0 Live Quant Terminal Server ที่พอร์ต {PORT}...")
    print(f"🌐 ใช้งานผ่าน URL: http://0.0.0.0:{PORT}")
    print(f"🔓 โหมดความปลอดภัย: เข้าถึงได้ทันที (Direct Access - No PIN Required)")

    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except ValueError:
        pass

    httpd = None
    for attempt in range(1, 11):
        try:
            httpd = RobustThreadingHTTPServer(("0.0.0.0", PORT), QuantTerminalHandler)
            break
        except OSError as e:
            if attempt == 10:
                print(f"❌ ไม่สามารถเปิดพอร์ต {PORT} ได้หลังพยายาม 10 ครั้ง: {e}")
                sys.exit(1)
            print(f"⏳ พอร์ต {PORT} กำลังรอเคลียร์ (ความพยายาม {attempt}/10)...")
            time.sleep(1)

    srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    srv_thread.start()

    while not _shutdown_event.is_set():
        _shutdown_event.wait(0.5)

    print("🛑 กำลังหยุดการทำงานของ HTTP Server...")
    httpd.shutdown()
    httpd.server_close()
    print("👋 ปิด Terminal Server เรียบร้อยสมบูรณ์")

if __name__ == "__main__":
    run_server()
