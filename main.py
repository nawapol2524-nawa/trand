import os
import sys
import time
import subprocess
import signal
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# ⚙️ SUPERVISOR CONFIGURATION
# ==========================================
BINANCE_SCRIPT = "main_binance.py"
FOREX_SCRIPT = "main_forex.py"
DASHBOARD_SCRIPT = "dashboard.py"
MT5_SCRIPT = "main_mt5.py"
SUPERVISOR_LOG = "supervisor_log.txt"
ENABLE_DERIV = os.getenv("ENABLE_DERIV", "true").lower() in ("true", "1", "yes")
ENABLE_MT5 = os.getenv("ENABLE_MT5", "false").lower() in ("true", "1", "yes")


def get_thai_time():
    return (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')

def log_supervisor(text):
    now = get_thai_time()
    msg = f"[{now}] [SUPERVISOR] {text}"
    print(msg, flush=True)
    try:
        with open(SUPERVISOR_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

# ==========================================
# 🔄 AUTO-PATCH SYSTEM (GIT SYNC)
# ==========================================
last_update_check = 0

# บังคับอัปเดตไฟล์ทุกครั้งที่รัน (แก้ปัญหา git reset ค้าง)
try:
    subprocess.run(["git", "fetch", "origin", "main"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "reset", "--hard", "origin/main"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
except:
    pass

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
            core_files = ["main.py", "main_binance.py", "main_forex.py", "dashboard.py", "requirements.txt"]
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
                # หยุด worker เก่าทั้งหมด และปล่อยให้ Pterodactyl รีสตาร์ทคอนเทนเนอร์ใหม่แทน
                stop_all_workers()
            else:
                subprocess.run(["git", "reset", "origin/main"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        log_supervisor(f"⚠️ [AUTO-PATCH ERROR] ตรวจสอบอัปเดตไม่สำเร็จ: {e}")

# ==========================================
# 📂 GOOGLE DRIVE LIVE DASHBOARD SYNC
# ==========================================
GDRIVE_WEBHOOK_URL = os.getenv("GDRIVE_WEBHOOK_URL")
last_gdrive_sync = 0

def sync_to_gdrive():
    global last_gdrive_sync
    if not GDRIVE_WEBHOOK_URL or "your_" in GDRIVE_WEBHOOK_URL:
        return
    now = time.time()
    if now - last_gdrive_sync < 60:
        return
    last_gdrive_sync = now
    
    try:
        import requests
        thai_now = get_thai_time()
        dashboard = []
        dashboard.append("=" * 65)
        dashboard.append("🏛️ AG 2.0 DUAL-ENGINE LIVE MONITOR (BINANCE + DERIV FOREX)")
        dashboard.append(f"🕒 อัปเดตล่าสุด: {thai_now} (เวลาไทย)")
        dashboard.append("=" * 65)
        
        # 1. ข้อมูล Binance
        dashboard.append("\n🪙 [BINANCE SPOT - งบ ~200 บาท]")
        dashboard.append("-" * 50)
        if os.path.exists("status_log.txt"):
            with open("status_log.txt", "r", encoding="utf-8") as f:
                lines = f.readlines()
                dashboard.append("".join(lines[-15:]).strip())
        else:
            dashboard.append("ยังไม่มีข้อมูล status_log.txt")
            
        # 2. ข้อมูล Deriv Forex (100% Free Cloud API)
        dashboard.append("\n\n📈 [DERIV FOREX & CFD - 24/7 Cloud]")
        dashboard.append("-" * 50)
        if ENABLE_DERIV:
            if os.path.exists("status_log_deriv.txt"):
                with open("status_log_deriv.txt", "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    dashboard.append("".join(lines[-15:]).strip())
            else:
                dashboard.append("รอ Deriv Engine โหลดข้อมูลสถานะ...")
        else:
            dashboard.append("⏸️ สแตนด์บายชั่วคราว (ENABLE_DERIV=false)")
            
        dashboard.append("\n" + "=" * 65)
        full_content = "\n".join(dashboard)
        
        resp = requests.post(
            GDRIVE_WEBHOOK_URL,
            json={"filename": "status_log.txt", "content": full_content},
            timeout=15
        )
        if resp.status_code == 200 and resp.json().get("status") == "success":
            log_supervisor("☁️ [GDRIVE-SYNC] อัปเดตสถานะสดขึ้น Google Drive สำเร็จ!")
    except Exception as e:
        log_supervisor(f"⚠️ [GDRIVE-SYNC ERROR] อัปเดตสถานะขึ้น Google Drive ไม่สำเร็จ: {e}")

# ==========================================
# 🚀 PROCESS MANAGEMENT (DUAL-ENGINE)
# ==========================================
processes = {}

def start_worker(name, script_path):
    log_supervisor(f"🚀 กำลังเปิดการทำงาน: {name} ({script_path})...")
    try:
        # เปิด process ลูกโดยใช้ Python ตัวเดียวกัน
        proc = subprocess.Popen([sys.executable, script_path])
        processes[name] = {
            'proc': proc,
            'script': script_path,
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

# ดักจับสัญญาณปิดโปรแกรม (Ctrl+C หรือ Docker stop)
signal.signal(signal.SIGINT, stop_all_workers)
signal.signal(signal.SIGTERM, stop_all_workers)

def monitor_workers():
    for name, item in list(processes.items()):
        proc = item.get('proc')
        if proc is None or proc.poll() is not None:
            exit_code = proc.poll() if proc else 'N/A'
            now = time.time()
            log_supervisor(f"🚨 [ALERT] {name} หยุดทำงานผิดปกติ! (Exit Code: {exit_code})")
            
            # ตรวจสอบความถี่ในการรีสตาร์ท (กันลูปแครชรัวๆ)
            if now - item['last_restart'] < 10:
                log_supervisor(f"⏳ {name} แครชไวเกินไป พัก 10 วินาทีก่อนเปิดใหม่...")
                time.sleep(10)
            
            item['restarts'] += 1
            item['last_restart'] = time.time()
            log_supervisor(f"🔄 กำลังรีสตาร์ท {name} (ครั้งที่ {item['restarts']})...")
            new_proc = subprocess.Popen([sys.executable, item['script']])
            processes[name]['proc'] = new_proc
            log_supervisor(f"✅ {name} รีสตาร์ทสำเร็จ (New PID: {new_proc.pid})")

# ==========================================
# 👑 MAIN ENTRY POINT
# ==========================================
if __name__ == '__main__':
    log_supervisor("=" * 60)
    log_supervisor("🏛️ AG 2.0 DUAL-ENGINE SUPERVISOR STARTING")
    log_supervisor("=" * 60)
    log_supervisor(f"📂 ไดเรกทอรีทำงาน: {os.getcwd()}")
    
    # 1. เริ่มต้น Binance Engine
    if os.path.exists(BINANCE_SCRIPT):
        start_worker("BinanceEngine", BINANCE_SCRIPT)
    else:
        log_supervisor(f"❌ ไม่พบไฟล์ {BINANCE_SCRIPT}!")

    # 2. เริ่มต้น Deriv Forex Engine (100% Free Cloud API)
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

    # 3. ลูปเฝ้าระวัง (Watchdog Loop)
        # 2.5 เริ่มต้น Web Dashboard
    if os.path.exists(DASHBOARD_SCRIPT):
        start_worker("WebDashboard", DASHBOARD_SCRIPT)
    else:
        log_supervisor(f"❌ ไม่พบไฟล์ {DASHBOARD_SCRIPT}!")

    log_supervisor("👀 Supervisor เข้าสู่โหมดเฝ้าระวัง Workers และตรวจจับ Auto-Patch...")
    while True:
        try:
            check_for_updates()
            sync_to_gdrive()
            monitor_workers()
            time.sleep(15)
        except (KeyboardInterrupt, SystemExit):
            stop_all_workers()
        except Exception as e:
            log_supervisor(f"⚠️ เกิดข้อผิดพลาดใน Supervisor Loop: {e}")
            time.sleep(15)