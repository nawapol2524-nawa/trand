import os
import sys
import time
import subprocess
import signal
import threading
import json
import re
import shutil
from datetime import datetime, timedelta
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as _ef:
                for _line in _ef:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _v = _line.split("=", 1)
                        _k, _v = _k.strip(), _v.strip().strip("'\"")
                        if _k not in os.environ:
                            os.environ[_k] = _v
        except Exception:
            pass

# ==========================================
# 🔔 NOTIFICATION MODULE INTEGRATION
# ==========================================
try:
    import notifier
except ImportError:
    try:
        from trand import notifier
    except ImportError:
        notifier = None

# ==========================================
# ⚙️ SUPERVISOR CONFIGURATION & LOG PATHS
# ==========================================
BINANCE_SCRIPT = "main_binance.py"
FOREX_SCRIPT = "main_forex.py"
DASHBOARD_SCRIPT = "dashboard.py"
MT5_SCRIPT = "main_mt5.py"
SUPERVISOR_LOG = "supervisor_log.txt"
CONSOLE_LOG_FILE = "console_log.txt"
STATUS_LOG_FILE = "status_log.txt"
TRADE_LOG_FILE = "trade_log.txt"
TRADE_LOG_DERIV_FILE = "trade_log_deriv.txt"
DAILY_24H_LOG_FILE = "daily_24h_log.txt"
DAILY_CYCLE_STATE_FILE = ".daily_cycle.json"
ARCHIVE_DIR = os.path.join("archive", "logs")

ENABLE_DERIV = os.getenv("ENABLE_DERIV", "true").lower() in ("true", "1", "yes")
ENABLE_MT5 = os.getenv("ENABLE_MT5", "false").lower() in ("true", "1", "yes")

_log_lock = threading.Lock()
current_active_cycle = None

def get_thai_datetime():
    return datetime.utcnow() + timedelta(hours=7)

def get_thai_time():
    return get_thai_datetime().strftime('%Y-%m-%d %H:%M:%S')

def get_current_24h_cycle_info():
    """
    คำนวณช่วงเวลาของรอบ 24 ชั่วโมง (09:00 น. วันนี้ -> 09:00 น. วันพรุ่งนี้ ตามเวลาไทย)
    คืนค่า: (cycle_start_dt, cycle_end_dt, cycle_str)
    """
    now = get_thai_datetime()
    cycle_date = now.date() if now.hour >= 9 else (now - timedelta(days=1)).date()
    cycle_start = datetime(cycle_date.year, cycle_date.month, cycle_date.day, 9, 0, 0)
    cycle_end = cycle_start + timedelta(days=1)
    cycle_str = cycle_date.strftime("%Y%m%d")
    return cycle_start, cycle_end, cycle_str

def append_console_log(text):
    """
    บันทึกทุกบรรทัดคอนโซลลงทั้ง:
    1. console_log.txt (สำหรับ Web Terminal)
    2. daily_24h_log.txt (เก็บบันทึก 100% ตลอดรอบ 24 ชม. เพื่อ Gemini Spark โดยห้าม Trim เด็ดขาด)
    แบบ Thread-Safe
    """
    with _log_lock:
        try:
            with open(CONSOLE_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass
        try:
            with open(DAILY_24H_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass

def trim_console_log():
    """
    จำกัดขนาดเฉพาะ console_log.txt สำหรับ Web Terminal ให้คงประวัติไว้ 5,000 - 10,000 บรรทัดล่าสุด
    (daily_24h_log.txt ห้ามตัดทิ้งเด็ดขาดระหว่างรอบ 24 ชม. เพื่อให้ Gemini Spark อ่านได้ครบถ้วน 100%)
    """
    with _log_lock:
        try:
            if os.path.exists(CONSOLE_LOG_FILE) and os.path.getsize(CONSOLE_LOG_FILE) > 2_000_000:
                with open(CONSOLE_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                if len(lines) > 10000:
                    with open(CONSOLE_LOG_FILE, "w", encoding="utf-8") as f:
                        f.writelines(lines[-7500:])
        except Exception:
            pass

def clean_old_daily_archives(max_days=3):
    """ลบไฟล์สำรอง daily_archive_YYYYMMDD.txt ที่เก่าเกิน 3 วัน เพื่อประหยัดพื้นที่ดิสก์"""
    try:
        if not os.path.exists(ARCHIVE_DIR):
            return
        now_ts = time.time()
        now_thai = get_thai_datetime()
        for fname in os.listdir(ARCHIVE_DIR):
            if fname.startswith("daily_archive_") and fname.endswith(".txt"):
                fpath = os.path.join(ARCHIVE_DIR, fname)
                is_old = False
                try:
                    # 1. ตรวจสอบจาก modification time
                    file_mtime = os.path.getmtime(fpath)
                    if (now_ts - file_mtime) > (max_days * 86400):
                        is_old = True
                    else:
                        # 2. ตรวจสอบจากวันที่ YYYYMMDD ในชื่อไฟล์
                        date_part = fname.replace("daily_archive_", "").replace(".txt", "")
                        if len(date_part) == 8 and date_part.isdigit():
                            f_date = datetime.strptime(date_part, "%Y%m%d").date()
                            if (now_thai.date() - f_date).days > max_days:
                                is_old = True
                except Exception:
                    pass

                if is_old:
                    try:
                        os.remove(fpath)
                        log_supervisor(f"🧹 [LOG-CLEANUP] ลบไฟล์ Archive เก่าเกิน {max_days} วัน: {fname}")
                    except Exception as e:
                        log_supervisor(f"⚠️ [LOG-CLEANUP ERROR] ไม่สามารถลบ {fname}: {e}")
    except Exception as e:
        log_supervisor(f"⚠️ [LOG-CLEANUP ERROR] ผิดพลาดขณะล้างไฟล์เก่า: {e}")

def init_daily_24h_log():
    """
    เริ่มต้นระบบบันทึก 24 ชั่วโมง:
    - ตรวจสอบรอบเวลาปัจจุบัน (09:00 -> 09:00 วันถัดไป)
    - หากพบค้างจากรอบเก่า ทำการ archive และเริ่มรอบใหม่
    - ดูแลให้ daily_24h_log.txt พร้อมบันทึกตลอด 24 ชม. เต็มโดยไม่ Trim
    """
    global current_active_cycle
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    c_start, c_end, c_str = get_current_24h_cycle_info()
    current_active_cycle = c_str

    saved_cycle = None
    if os.path.exists(DAILY_CYCLE_STATE_FILE):
        try:
            with open(DAILY_CYCLE_STATE_FILE, "r", encoding="utf-8") as f:
                state_data = json.load(f)
                saved_cycle = state_data.get("cycle_id")
        except Exception:
            pass

    # ตรวจสอบว่าต้องหมุนเวียนรอบเก่าหรือไม่
    if saved_cycle and saved_cycle != c_str:
        if os.path.exists(DAILY_24H_LOG_FILE) and os.path.getsize(DAILY_24H_LOG_FILE) > 0:
            archive_path = os.path.join(ARCHIVE_DIR, f"daily_archive_{saved_cycle}.txt")
            try:
                shutil.move(DAILY_24H_LOG_FILE, archive_path)
                log_supervisor(f"📦 [24H INIT] ย้าย Log รอบก่อนหน้า ({saved_cycle}) เข้า Archive: {archive_path}")
            except Exception as e:
                log_supervisor(f"⚠️ [24H INIT ARCHIVE ERROR] {e}")

    # หากยังไม่มี daily_24h_log.txt ให้สร้างใหม่พร้อม Header
    if not os.path.exists(DAILY_24H_LOG_FILE) or os.path.getsize(DAILY_24H_LOG_FILE) == 0:
        with _log_lock:
            try:
                with open(DAILY_24H_LOG_FILE, "w", encoding="utf-8") as f:
                    header = (
                        f"╔══════════════════════════════════════════════════════════════════════════════════╗\n"
                        f"║  🏛️ AG 2.0 QUANT TERMINAL | DAILY 24H AUDIT CONSOLE STREAM                        ║\n"
                        f"║  🕒 รอบเวลา 24 ชม. : {c_start.strftime('%Y-%m-%d %H:%M:%S')} -> {c_end.strftime('%Y-%m-%d %H:%M:%S')} (เวลาไทย UTC+7) ║\n"
                        f"║  🔒 บันทึกครบถ้วน 100% ห้าม Trim เด็ดขาดเพื่อรองรับการวิเคราะห์ของ Gemini Spark        ║\n"
                        f"╚══════════════════════════════════════════════════════════════════════════════════╝\n\n"
                    )
                    f.write(header)
                    # รวมประวัติ console จาก status_log.txt เดิมในรอบนี้หากมี
                    if os.path.exists(STATUS_LOG_FILE):
                        try:
                            with open(STATUS_LOG_FILE, "r", encoding="utf-8", errors="replace") as sf:
                                s_content = sf.read()
                            if "CONSOLE OUTPUT" in s_content:
                                c_part = s_content.split("CONSOLE OUTPUT", 1)[-1]
                                c_part_lines = c_part.splitlines()
                                if len(c_part_lines) > 2:
                                    f.write("\n".join(c_part_lines[2:]) + "\n")
                        except Exception:
                            pass
            except Exception:
                pass

    # บันทึกสถานะรอบปัจจุบัน
    try:
        with open(DAILY_CYCLE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "cycle_id": c_str,
                "cycle_start": c_start.strftime("%Y-%m-%d %H:%M:%S"),
                "cycle_end": c_end.strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": get_thai_time()
            }, f, indent=2)
    except Exception:
        pass

    clean_old_daily_archives(max_days=3)
    log_supervisor(f"📋 [24H LOG SYSTEM] ประจำการรอบ 24 ชม.: {c_start.strftime('%Y-%m-%d %H:%M')} -> {c_end.strftime('%Y-%m-%d %H:%M')} (รอบ ID: {c_str})")

def check_and_rotate_24h_log():
    """
    ตรวจสอบการเปลี่ยนรอบ 24 ชม. ทุกครั้งที่ผ่าน 09:00 น. เวลาไทย:
    - หมุนเวียน daily_24h_log.txt ไปเป็น archive/logs/daily_archive_YYYYMMDD.txt
    - ลบไฟล์เก่าเกิน 3 วัน
    - เริ่มบันทึกรอบ 24 ชม. ใหม่สะอาดๆ
    """
    global current_active_cycle
    c_start, c_end, c_str = get_current_24h_cycle_info()
    if current_active_cycle is None:
        current_active_cycle = c_str
        return

    if c_str != current_active_cycle:
        log_supervisor(f"🔄 [24H ROLLOVER] ถึงเวลา 09:00 น. (เวลาไทย) สิ้นสุดรอบ 24 ชม. เก่า ({current_active_cycle}) กำลัง Rollover...")
        
        # ส่งข้อมูลปิดท้ายรอบเก่าขึ้น Google Drive ก่อน Rollover
        try:
            sync_to_gdrive(force=True)
        except Exception as e:
            log_supervisor(f"⚠️ [24H ROLLOVER SYNC ERROR] {e}")

        # ย้าย daily_24h_log.txt ไปยัง archive/logs/daily_archive_YYYYMMDD.txt
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        archive_path = os.path.join(ARCHIVE_DIR, f"daily_archive_{current_active_cycle}.txt")
        with _log_lock:
            try:
                if os.path.exists(DAILY_24H_LOG_FILE):
                    shutil.move(DAILY_24H_LOG_FILE, archive_path)
                    log_supervisor(f"💾 [24H ROLLOVER] สำรอง Log รอบ 24 ชม. สำเร็จ: {archive_path}")
            except Exception as e:
                log_supervisor(f"⚠️ [24H ROLLOVER ARCHIVE ERROR] {e}")

            # เริ่มต้นไฟล์ daily_24h_log.txt รอบใหม่สะอาดๆ
            try:
                with open(DAILY_24H_LOG_FILE, "w", encoding="utf-8") as f:
                    header = (
                        f"╔══════════════════════════════════════════════════════════════════════════════════╗\n"
                        f"║  🏛️ AG 2.0 QUANT TERMINAL | DAILY 24H AUDIT CONSOLE STREAM                        ║\n"
                        f"║  🕒 รอบเวลา 24 ชม. : {c_start.strftime('%Y-%m-%d %H:%M:%S')} -> {c_end.strftime('%Y-%m-%d %H:%M:%S')} (เวลาไทย UTC+7) ║\n"
                        f"║  🔒 บันทึกครบถ้วน 100% ห้าม Trim เด็ดขาดเพื่อรองรับการวิเคราะห์ของ Gemini Spark        ║\n"
                        f"╚══════════════════════════════════════════════════════════════════════════════════╝\n\n"
                    )
                    f.write(header)
            except Exception:
                pass

        # อัปเดตรอบและบันทึก State
        current_active_cycle = c_str
        try:
            with open(DAILY_CYCLE_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "cycle_id": c_str,
                    "cycle_start": c_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "cycle_end": c_end.strftime("%Y-%m-%d %H:%M:%S"),
                    "updated_at": get_thai_time()
                }, f, indent=2)
        except Exception:
            pass

        # ลบไฟล์เก่าเกิน 3 วัน
        clean_old_daily_archives(max_days=3)
        log_supervisor(f"✅ [24H ROLLOVER] เริ่มต้นรอบ 24 ชม. ใหม่สะอาดๆ เรียบร้อย ({c_start.strftime('%Y-%m-%d %H:%M')} -> {c_end.strftime('%Y-%m-%d %H:%M')})")

def log_supervisor(text):
    now = get_thai_time()
    msg = f"[{now}] [SUPERVISOR] {text}\n"
    sys.stdout.write(msg)
    sys.stdout.flush()
    try:
        with open(SUPERVISOR_LOG, "a", encoding="utf-8") as f:
            f.write(msg)
    except Exception:
        pass
    append_console_log(msg)

# ==========================================
# 🔄 AUTO-PATCH SYSTEM (GIT SYNC)
# ==========================================
last_update_check = 0

def check_for_updates():
    global last_update_check
    now = time.time()
    if now - last_update_check < 300:
        return
    last_update_check = now
    
    try:
        subprocess.run(["git", "fetch", "origin", "main"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        status = subprocess.run(["git", "status", "-uno"], capture_output=True, text=True)
        if "Your branch is behind" in status.stdout:
            diff = subprocess.run(["git", "diff", "--name-only", "HEAD", "origin/main"], capture_output=True, text=True)
            core_files = ["main.py", "main_binance.py", "main_forex.py", "dashboard.py", "requirements.txt", "notifier.py"]
            if any(cf in diff.stdout for cf in core_files):
                log_supervisor("🔄 [AUTO-PATCH] พบการอัปเดตโค้ดหลักใน GitHub! กำลังอัปเดตและรีสตาร์ทระบบ...")
                req_changed = "requirements.txt" in diff.stdout
                subprocess.run(["git", "reset", "--hard", "origin/main"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if req_changed:
                    log_supervisor("📦 [AUTO-PATCH] ตรวจพบแพ็กเกจใหม่ กำลังรัน pip install -r requirements.txt...")
                    pip_cmd = [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
                    if os.path.exists(".local"):
                        pip_cmd = [sys.executable, "-m", "pip", "install", "-U", "--prefix", ".local", "-r", "requirements.txt"]
                    subprocess.run(pip_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                time.sleep(2)
                restart_entire_system()
            else:
                subprocess.run(["git", "reset", "origin/main"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        log_supervisor(f"⚠️ [AUTO-PATCH ERROR] ตรวจสอบอัปเดตไม่สำเร็จ: {e}")

# ==========================================
# 📂 GOOGLE DRIVE 24H AI REPORT SYNC
# ==========================================
GDRIVE_WEBHOOK_URL = os.getenv("GDRIVE_WEBHOOK_URL")
last_gdrive_sync = 0

def build_ai_analysis_report(cycle_start, cycle_end, thai_now):
    """
    สร้างเอกสารรายงาน AI-Ready 24H ครบทั้ง 4 ส่วน สำหรับ Gemini Spark:
    1. 📊 [24H DAILY EXECUTIVE RECAP]: รอบเวลา, PnL รวม, จำนวนไม้ Win/Loss, สถานะปัจจุบัน
    2. 🚨 [24H SYSTEM HEALTH & ERRORS]: รวมทุกบรรทัดเตือน (⚠️, ❌, Error, Timeout, Reconnect) ในรอบ 24 ชม.
    3. 📋 [24H TRADE LEDGER]: ประวัติการเปิด-ปิดไม้ทุกไม้ในรอบวันจาก trade_log.txt
    4. 📜 [FULL 24H CONSOLE STREAM]: เนื้อหาคอนโซลทั้งหมดตลอดรอบ 24 ชม. แบบครบถ้วน 100%
    """
    # -------------------------------------------------------------
    # 1. รวบรวมสถิติการเทรด และ PnL ในรอบ 24 ชม. ปัจจุบัน
    # -------------------------------------------------------------
    wins = 0
    losses = 0
    be_count = 0
    total_pnl_usdt = 0.0
    total_pnl_thb = 0.0
    total_pnl_usd = 0.0

    # 1.1 อ่านสถิติจาก agent_memory_multi.json (Binance Spot)
    if os.path.exists("agent_memory_multi.json"):
        try:
            with open("agent_memory_multi.json", "r", encoding="utf-8") as f:
                mem = json.load(f)
            for sym, data in mem.items():
                for ref in data.get("reflections", []):
                    try:
                        rdt = datetime.strptime(ref.get("date", ""), "%Y-%m-%d %H:%M:%S")
                        if cycle_start <= rdt < cycle_end:
                            if ref.get("type") == "WIN":
                                wins += 1
                            elif ref.get("type") == "LOSS":
                                losses += 1
                    except Exception:
                        pass
        except Exception:
            pass

    # 1.2 อ่านสถิติจาก agent_memory_deriv.json (Deriv Forex)
    if os.path.exists("agent_memory_deriv.json"):
        try:
            with open("agent_memory_deriv.json", "r", encoding="utf-8") as f:
                d_mem = json.load(f)
            for h in d_mem.get("history", []):
                try:
                    hdt = datetime.strptime(h.get("time", ""), "%Y-%m-%d %H:%M:%S")
                    if cycle_start <= hdt < cycle_end:
                        p_usd = float(h.get("profit_usd", 0))
                        p_thb = float(h.get("profit_thb", 0))
                        if p_usd >= 0:
                            wins += 1
                        else:
                            losses += 1
                        total_pnl_usd += p_usd
                        total_pnl_thb += p_thb
                except Exception:
                    pass
        except Exception:
            pass

    # -------------------------------------------------------------
    # 2. สกัด Trade Ledger ในรอบ 24 ชม. จาก trade_log.txt & trade_log_deriv.txt
    # -------------------------------------------------------------
    ledger_lines = []
    if os.path.exists(TRADE_LOG_FILE):
        try:
            with open(TRADE_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                t_lines = f.readlines()
            current_dt = None
            for line in t_lines:
                m = re.match(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
                if m:
                    try:
                        current_dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass
                if current_dt and cycle_start <= current_dt < cycle_end:
                    ledger_lines.append(line)
                    # คำนวณ PnL ตัวเลขจริงจาก Log
                    p_match = re.search(r"Net Profit\s*:\s*([+-]?[\d.]+)\s*USDT(?:\s*\(([+-]?[\d.]+)\s*บาท\))?", line)
                    if p_match:
                        try:
                            total_pnl_usdt += float(p_match.group(1))
                            if p_match.group(2):
                                total_pnl_thb += float(p_match.group(2))
                        except Exception:
                            pass
                    l_match = re.search(r"Net Loss\s*:\s*-?\$?([+-]?[\d.]+)\s*USDT(?:\s*\(([+-]?[\d.]+)\s*บาท\))?", line)
                    if l_match:
                        try:
                            total_pnl_usdt -= float(l_match.group(1))
                            if l_match.group(2):
                                total_pnl_thb += float(l_match.group(2))
                        except Exception:
                            pass
                    if "SL-BREAKEVEN CLOSED" in line:
                        be_count += 1
        except Exception:
            pass

    if os.path.exists(TRADE_LOG_DERIV_FILE):
        try:
            with open(TRADE_LOG_DERIV_FILE, "r", encoding="utf-8", errors="replace") as f:
                d_lines = f.readlines()
            current_d_dt = None
            d_ledger = []
            for line in d_lines:
                m = re.match(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
                if m:
                    try:
                        current_d_dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass
                if current_d_dt and cycle_start <= current_d_dt < cycle_end:
                    d_ledger.append(line)
            if d_ledger:
                ledger_lines.append("\n--- DERIV FOREX TRADES (24H) ---\n" + "".join(d_ledger))
        except Exception:
            pass

    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    trade_ledger_text = "".join(ledger_lines).strip()
    if not trade_ledger_text:
        trade_ledger_text = "(ยังไม่มีประวัติการเปิด-ปิดไม้ในรอบ 24 ชม. นี้ - บอทสแตนด์บายตรวจจับสัญญาณตามกลยุทธ์)"

    # -------------------------------------------------------------
    # 3. สถานะพอร์ตและเครื่องยนต์ปัจจุบัน
    # -------------------------------------------------------------
    active_positions = []
    if os.path.exists("active_state.json"):
        try:
            with open("active_state.json", "r", encoding="utf-8") as f:
                a_data = json.load(f)
            for sym, s in a_data.items():
                if s.get("in_position", False):
                    ep = s.get("entry_price", 0)
                    ps = s.get("position_size", 0)
                    active_positions.append(f"{sym} (Entry: ${ep:.4f}, Size: {ps})")
        except Exception:
            pass

    if os.path.exists("active_state_deriv.json"):
        try:
            with open("active_state_deriv.json", "r", encoding="utf-8") as f:
                d_data = json.load(f)
            at = d_data.get("active_trade")
            if at:
                sym_d = at.get("symbol")
                ep_d = at.get("entry_price")
                active_positions.append(f"{sym_d} [Deriv] (Entry: {ep_d})")
        except Exception:
            pass

    pos_status = ", ".join(active_positions) if active_positions else "⚪ FLAT ทุกเหรียญ (ไม่มีออเดอร์ค้าง สแตนด์บายรอสัญญาณใหม่)"

    engines_active = []
    for pname, pdata in processes.items():
        proc = pdata.get('proc')
        if proc and proc.poll() is None:
            engines_active.append(f"{pname} (🟢 ONLINE)")
        else:
            engines_active.append(f"{pname} (🔴 OFFLINE)")
    engine_status_summary = " | ".join(engines_active) if engines_active else "⚡ Supervisor Active"

    # -------------------------------------------------------------
    # 4. ดึงเนื้อหาคอนโซลเต็ม 100% จาก daily_24h_log.txt
    # -------------------------------------------------------------
    console_stream = ""
    if os.path.exists(DAILY_24H_LOG_FILE):
        with _log_lock:
            try:
                with open(DAILY_24H_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    console_stream = f.read()
            except Exception:
                pass
    if not console_stream.strip() and os.path.exists(CONSOLE_LOG_FILE):
        with _log_lock:
            try:
                with open(CONSOLE_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    console_stream = f.read()
            except Exception:
                pass
    if not console_stream.strip():
        console_stream = "(กำลังรวบรวมข้อมูล Console Stream ตลอดรอบ 24 ชม...)"

    # -------------------------------------------------------------
    # 5. สกัด Alert / Error ในรอบ 24 ชม. จาก daily_24h_log.txt
    # -------------------------------------------------------------
    alert_keywords = ["⚠️", "❌", "error", "timeout", "reconnect", "traceback", "circuit breaker", "exception", "failed", "crash"]
    alert_lines = []
    seen_alerts = set()
    for raw_line in console_stream.splitlines():
        line = raw_line.strip()
        # กรองข้ามเส้นตารางข้อมูลสรุปปกติ
        if line.count("║") >= 3 or line.startswith("╠") or line.startswith("╔") or line.startswith("╚") or line.startswith("─"):
            continue
        l_low = line.lower()
        if any(k in l_low for k in alert_keywords):
            if line not in seen_alerts:
                seen_alerts.add(line)
                alert_lines.append(line)

    if alert_lines:
        alert_preview = "\n".join([f"  • {a}" for a in alert_lines[-50:]])
        total_alerts = len(alert_lines)
        system_health_text = (
            f"🚨 ตรวจพบสัญญาณแจ้งเตือนทั้งหมด {total_alerts} รายการในรอบ 24 ชม.:\n"
            f"{alert_preview}"
        )
    else:
        system_health_text = "✅ 100% HEALTHY - ไม่พบ Error, Timeout หรือข้อผิดพลาดใดๆ ตลอดรอบ 24 ชม. ระบบทำงานราบรื่นสมบูรณ์แบบ"

    # -------------------------------------------------------------
    # 6. ประกอบเอกสาร AI-Ready
    # -------------------------------------------------------------
    cycle_start_str = cycle_start.strftime("%Y-%m-%d %H:%M:%S")
    cycle_end_str = cycle_end.strftime("%Y-%m-%d %H:%M:%S")

    # คำนวณสถานะความเสี่ยงข่าว CPI (ตามแผนกลยุทธ์ Gemini Spark)
    now_th = datetime.utcnow() + timedelta(hours=7)
    if now_th.year == 2026 and now_th.month == 9 and now_th.day == 11:
        if (19, 0) <= (now_th.hour, now_th.minute) < (20, 30):
            cpi_status_note = "🔴 ACTIVE (19:00 - 20:30 น.) - งดเปิดไม้ใหม่ทุกตลาดเพื่อเลี่ยงพายุ CPI & Whipsaw"
        elif (18, 30) <= (now_th.hour, now_th.minute) < (19, 0):
            cpi_status_note = "⚠️ PRE-NEWS WINDOW (18:30 - 19:00 น.) - เตรียมปิดไม้เสี่ยงก่อนข่าว CPI 19:30 น."
        elif (now_th.hour, now_th.minute) < (18, 30):
            cpi_status_note = "⏳ SCHEDULED - เตรียมล็อกระบบ 19:00 - 20:30 น. คืนนี้ (US CPI 19:30 น.)"
        else:
            cpi_status_note = "🟢 COMPLETED - พ้นช่วงอันตรายข่าว CPI เรียบร้อยแล้ว ระบบปลดล็อก 100%"
    else:
        cpi_status_note = "⚪ NORMAL - ไม่มีมาตรการ Red Folder Freeze เฉพาะกิจในวันนี้"

    header_block = (
        f"╔══════════════════════════════════════════════════════════════════════════════════╗\n"
        f"║  🏛️ AG 2.0 QUANT SYSTEM | DAILY 24H EXECUTIVE AI REPORT (GEMINI SPARK AUDIT)   ║\n"
        f"║  🕒 รอบเวลาการวิเคราะห์: {cycle_start_str} -> {cycle_end_str} (เวลาไทย UTC+7) ║\n"
        f"║  📡 สถานะการซิงค์: LIVE 100% UNTRIMMED STREAM (อัปเดตทุก 1 นาที)                   ║\n"
        f"╚══════════════════════════════════════════════════════════════════════════════════╝\n\n"
        f"📊 [24H DAILY EXECUTIVE RECAP]\n"
        f"{'─' * 82}\n"
        f"• 🕒 รอบเวลาวิเคราะห์ (24H Cycle) : {cycle_start_str} -> {cycle_end_str} (เวลาไทย UTC+7)\n"
        f"• 🕒 อัปเดตข้อมูลล่าสุด (Last Sync) : {thai_now} (เวลาไทย)\n"
        f"• 💰 ยอด PnL รวมรอบ 24 ชม.        : {total_pnl_usdt:+.4f} USDT | {total_pnl_usd:+.2f} USD (≈ {total_pnl_thb:+.2f} บาท)\n"
        f"• 🎯 สถิติการเทรดรอบวัน (Stats)     : ทั้งหมด {total_trades} ไม้ (ชนะ {wins} | แพ้ {losses} | Breakeven {be_count}) | Win Rate: {win_rate:.1f}%\n"
        f"• ⚡ สถานะเครื่องยนต์ (Engines)    : {engine_status_summary}\n"
        f"• 🪙 สถานะพอร์ตปัจจุบัน (Positions) : {pos_status}\n"
        f"• 🔴 มาตรการความเสี่ยงข่าว CPI (Risk Window) : {cpi_status_note}\n"
        f"{'═' * 82}\n\n"
        f"🚨 [24H SYSTEM HEALTH & ERRORS]\n"
        f"{'─' * 82}\n"
        f"{system_health_text}\n"
        f"{'═' * 82}\n\n"
        f"📋 [24H TRADE LEDGER]\n"
        f"{'─' * 82}\n"
        f"{trade_ledger_text}\n"
        f"{'═' * 82}\n\n"
        f"📜 [FULL 24H CONSOLE STREAM]\n"
        f"{'─' * 82}\n"
        f"{console_stream}\n"
    )

    return header_block, trade_ledger_text

def sync_to_gdrive(force=False):
    """
    ส่ง Console Log สด 100% พร้อม AI Analysis Header ขึ้น Google Drive ทุก 1 นาที
    โดยอ่านและส่งเนื้อหาทั้งหมดของรอบ 24 ชม. (daily_24h_log.txt) ไปยัง status_log.txt และ console_log.txt
    """
    global last_gdrive_sync
    if not GDRIVE_WEBHOOK_URL or "your_" in GDRIVE_WEBHOOK_URL:
        return
    now = time.time()
    if not force and (now - last_gdrive_sync < 60):
        return
    last_gdrive_sync = now
    
    try:
        import requests
        c_start, c_end, c_str = get_current_24h_cycle_info()
        thai_now = get_thai_time()

        full_content, trade_ledger_text = build_ai_analysis_report(c_start, c_end, thai_now)

        # 1. บันทึกทับ status_log.txt บนเครื่องท้องถิ่น
        try:
            with open(STATUS_LOG_FILE, "w", encoding="utf-8") as f:
                f.write(full_content)
        except Exception:
            pass

        # 2. ส่ง console_log.txt ไปยัง Google Drive Webhook (บรรจุ 24H AI Stream เต็ม 100%)
        resp = requests.post(
            GDRIVE_WEBHOOK_URL,
            json={"filename": "console_log.txt", "content": full_content},
            timeout=30
        )

        # 3. ส่งทับ status_log.txt บน Google Drive เพื่อให้ไฟล์เดิมอัปเดตสดทันที
        try:
            requests.post(
                GDRIVE_WEBHOOK_URL,
                json={"filename": "status_log.txt", "content": full_content},
                timeout=30
            )
        except Exception:
            pass

        # 4. ส่ง trade_log.txt (24H Trade Ledger) ไปยัง Google Drive
        if trade_ledger_text.strip():
            try:
                requests.post(
                    GDRIVE_WEBHOOK_URL,
                    json={"filename": "trade_log.txt", "content": trade_ledger_text},
                    timeout=30
                )
            except Exception:
                pass

        if resp.status_code == 200:
            log_supervisor("☁️ [GDRIVE-SYNC] อัปเดต Full 24H AI Stream (console_log / status_log / trade_log) ขึ้น Google Drive สำเร็จ!")
    except Exception as e:
        log_supervisor(f"⚠️ [GDRIVE-SYNC ERROR] อัปเดตสถานะขึ้น Google Drive ไม่สำเร็จ: {e}")

# ==========================================
# 🚀 PROCESS MANAGEMENT (DUAL-ENGINE + CONSOLE STREAM)
# ==========================================
processes = {}

def stream_worker_output(name, proc):
    """อ่าน output จาก process ลูกแบบเรียลไทม์: พิมพ์ออกหน้าจอ + บันทึกใส่ console_log.txt"""
    try:
        for line in iter(proc.stdout.readline, ''):
            if not line:
                break
            sys.stdout.write(line)
            sys.stdout.flush()
            append_console_log(line)
    except Exception:
        pass
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass

def start_worker(name, script_path):
    log_supervisor(f"🚀 กำลังเปิดการทำงาน: {name} ({script_path})...")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        t = threading.Thread(target=stream_worker_output, args=(name, proc), daemon=True)
        t.start()

        processes[name] = {
            'proc': proc,
            'script': script_path,
            'thread': t,
            'restarts': 0,
            'last_restart': time.time()
        }
        log_supervisor(f"✅ {name} ทำงานสำเร็จ (PID: {proc.pid})")
        return proc
    except Exception as e:
        log_supervisor(f"❌ ไม่สามารถเปิด {name} ได้: {e}")
        return None

def stop_all_workers(signum=None, frame=None):
    log_supervisor("🛑 ได้รับสัญญาณหยุดระบบ! กำลังปิด Workers ทั้งหมดอย่างปลอดภัย...")
    for name, item in processes.items():
        proc = item.get('proc')
        if proc and proc.poll() is None:
            try:
                log_supervisor(f"⏳ กำลังส่งคำสั่งปิด {name} (PID: {proc.pid})...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                log_supervisor(f"✅ {name} ปิดเรียบร้อยแล้ว")
            except Exception as e:
                log_supervisor(f"⚠️ ผิดพลาดขณะปิด {name}: {e}")
    log_supervisor("👋 ระบบ Supervisor ปิดตัวเองเรียบร้อย")
    sys.exit(0)

def restart_entire_system():
    """ปิด Workers ทั้งหมด และ Re-execute main.py ตัวใหม่ทันทีโดยไม่หลุดออกจาก Container"""
    log_supervisor("🛑 กำลังปิด Workers ทั้งหมดอย่างปลอดภัยเพื่อเตรียม Restart ระบบ...")
    for name, item in list(processes.items()):
        proc = item.get('proc')
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                log_supervisor(f"✅ {name} ปิดเรียบร้อย")
            except Exception:
                pass
    log_supervisor("🚀 กำลัง Re-executing main.py เพื่อเริ่มระบบใหม่อย่างสมบูรณ์...")
    time.sleep(1)
    os.execv(sys.executable, [sys.executable, "main.py"])

signal.signal(signal.SIGINT, stop_all_workers)
signal.signal(signal.SIGTERM, stop_all_workers)

def monitor_workers():
    for name, item in list(processes.items()):
        proc = item.get('proc')
        if proc is None or proc.poll() is not None:
            exit_code = proc.poll() if proc else 'N/A'
            now = time.time()
            log_supervisor(f"🚨 [ALERT] {name} หยุดทำงานผิดปกติ! (Exit Code: {exit_code})")
            
            if now - item['last_restart'] < 10:
                log_supervisor(f"⏳ {name} แครชไวเกินไป พัก 10 วินาทีก่อนเปิดใหม่...")
                time.sleep(10)
            
            item['restarts'] += 1
            item['last_restart'] = time.time()
            log_supervisor(f"🔄 กำลังรีสตาร์ท {name} (ครั้งที่ {item['restarts']})...")
            new_proc = subprocess.Popen(
                [sys.executable, "-u", item['script']],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            t = threading.Thread(target=stream_worker_output, args=(name, new_proc), daemon=True)
            t.start()
            processes[name]['proc'] = new_proc
            processes[name]['thread'] = t
            log_supervisor(f"✅ {name} รีสตาร์ทสำเร็จ (New PID: {new_proc.pid})")

# ==========================================
# 👑 MAIN ENTRY POINT
# ==========================================
if __name__ == '__main__':
    banner_lines = [
        "╔══════════════════════════════════════════════════════════════════════════════════╗",
        "║  🏛️ AG 2.0 QUANT TERMINAL | DUAL-ENGINE SUPERVISOR (QUANT SHIELD)                 ║",
        "║  ⚡ Binance Engine : Spot Sandbox Testnet (100% Demo / Training)                 ║",
        "║  ⚡ Deriv Engine   : Forex Demo Account (DOT94482469 - 100% No Real Money)       ║",
        "║  📡 Console Logger : Streamed to console_log.txt & synced as status_log.txt      ║",
        "║  🔔 LINE Notify    : Active for BUY, TP, SL, Breakeven & Trailing Run             ║",
        "╚══════════════════════════════════════════════════════════════════════════════════╝"
    ]
    for b in banner_lines:
        log_supervisor(b)
    log_supervisor(f"📂 ไดเรกทอรีทำงาน: {os.getcwd()}")
    
    # เริ่มต้นระบบ 24H Daily Log และตั้งค่า Rollover 09:00 น.
    init_daily_24h_log()

    # ส่งแจ้งเตือนเริ่มต้นระบบ
    if notifier:
        try:
            notifier.notify_system("AG 2.0 Supervisor", "🚀 เริ่มต้นระบบ Dual-Engine (Binance Testnet Sandbox + Deriv Demo DOT94482469)")
        except Exception:
            pass

    # 1. เริ่มต้น Binance Engine
    if os.path.exists(BINANCE_SCRIPT):
        start_worker("BinanceEngine", BINANCE_SCRIPT)
    else:
        log_supervisor(f"❌ ไม่พบไฟล์ {BINANCE_SCRIPT}!")

    # 2. เริ่มต้น Deriv Forex Engine (Demo DOT94482469)
    if ENABLE_DERIV:
        if os.path.exists(FOREX_SCRIPT):
            start_worker("DerivForexEngine", FOREX_SCRIPT)
        else:
            log_supervisor(f"❌ ไม่พบไฟล์ {FOREX_SCRIPT}!")
    elif ENABLE_MT5:
        if os.path.exists(MT5_SCRIPT):
            start_worker("MT5Engine", MT5_SCRIPT)
        else:
            log_supervisor(f"❌ ไม่พบไฟล์ {MT5_SCRIPT}!")
    else:
        log_supervisor("⏸️ [MODE] รันเฉพาะ Binance Spot 100%")

    # 3. เริ่มต้น Web Dashboard
    if os.path.exists(DASHBOARD_SCRIPT):
        start_worker("WebDashboard", DASHBOARD_SCRIPT)
    else:
        log_supervisor(f"❌ ไม่พบไฟล์ {DASHBOARD_SCRIPT}!")

    # 4. ลูปเฝ้าระวัง (Watchdog Loop)
    log_supervisor("👀 Supervisor เข้าสู่โหมดเฝ้าระวัง Workers และตรวจจับ Auto-Patch...")
    while True:
        try:
            # 1. ตรวจสอบว่ามีคำสั่ง Restart จาก Web Terminal หรือไม่ (ตอบสนองใน 1-2 วินาที)
            if os.path.exists("restart.flag"):
                log_supervisor("🔄 [COMMAND RESTART] ตรวจพบคำสั่ง Restart จาก Web Terminal!")
                try:
                    os.remove("restart.flag")
                except Exception:
                    pass
                restart_entire_system()

            check_for_updates()
            check_and_rotate_24h_log()
            sync_to_gdrive()
            trim_console_log()
            monitor_workers()

            # วนลูปพัก 20 วินาที โดยตรวจ restart.flag ทุกๆ 1 วินาที เพื่อให้ตอบสนองคำสั่งทันที
            for _ in range(20):
                if os.path.exists("restart.flag"):
                    break
                time.sleep(1)

        except (KeyboardInterrupt, SystemExit):
            stop_all_workers()
        except Exception as e:
            log_supervisor(f"⚠️ เกิดข้อผิดพลาดใน Supervisor Loop: {e}")
            time.sleep(5)
