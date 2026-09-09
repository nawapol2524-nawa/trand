#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
🤖 AG 2.0 - MetaTrader 5 Cent Account Trading Bot (Pullback Sniper 15m)
=============================================================================
ระบบเทรดอัตโนมัติสำหรับบัญชี Cent บนแพลตฟอร์ม MetaTrader 5 ผ่าน MetaApi Cloud SDK
ออกแบบมาสำหรับงบประมาณขนาดเล็ก (เริ่มต้น 100 บาท ~ 280 USC)

คุณสมบัติหลัก:
- การเชื่อมต่อผ่าน metaapi-cloud-sdk พร้อมระบบตรวจจับคีย์และรออย่างปลอดภัย
- ค้นหาและเลือก Cent Symbol อัตโนมัติ (เช่น EURUSDm, EURUSDc, EURUSD)
- ขนาดไม้มาตรฐาน 0.01 Cent Lot รองรับการบริหารความเสี่ยงระดับไมโคร
- กลยุทธ์ Pullback Sniper บนกราฟ 15m (RSI Oversold + Price <= Lower Bollinger Band)
- ระบบบริหารความเสี่ยงฝั่ง Server: SL/TP แนบในคำสั่ง, Auto-Breakeven ที่ +15 pips, Trailing Stop
- ตัวกรองวันหยุด (Weekend Filter): ตรวจสอบ datetime.utcnow().weekday() < 5 เข้าโหมด Standby
- State Persistence: บันทึกสถานะไม้ลง active_state_mt5.json แบบ Atomic Write ป้องกันไฟล์เสียหาย
- Logs: บันทึกสถานะลง status_log_mt5.txt และ trade_log_mt5.txt พร้อมแสดงเวลาไทย
=============================================================================
"""

import os
import sys
import time
import json
import signal
import asyncio
from datetime import datetime, timedelta
import pandas as pd
from dotenv import load_dotenv

try:
    from metaapi_cloud_sdk import MetaApi
except ImportError:
    print("❌ [IMPORT ERROR] ไม่พบแพ็กเกจ metaapi-cloud-sdk")
    print("👉 กรุณาติดตั้งด้วยคำสั่ง: pip install metaapi-cloud-sdk")
    sys.exit(1)

# =============================================================================
# ⚙️ CONFIGURATION & CONSTANTS
# =============================================================================
load_dotenv()

# ไฟล์บันทึกข้อมูล
STATE_FILE = "active_state_mt5.json"
STATUS_FILE = "status_log_mt5.txt"
LOG_FILE = "trade_log_mt5.txt"

# การตั้งค่าสินทรัพย์และบัญชี Cent
# ลำดับสัญลักษณ์ที่บอทจะค้นหาตามประเภทบัญชี Cent ของแต่ละโบรกเกอร์ (Exness, XM, FBS, etc.)
CANDIDATE_SYMBOLS = [
    os.getenv("MT5_SYMBOL", "").strip(),
    "EURUSDc",     # Standard Cent (เช่น Exness Cent, XM Micro/Cent)
    "EURUSDm",     # Micro / Cent Symbol
    "EURUSD_c",    # Raw Cent
    "EURUSDmicro", # Micro Symbol
    "EURUSD"       # Standard Fallback
]
# กรองค่าว่างออก
CANDIDATE_SYMBOLS = [s for s in CANDIDATE_SYMBOLS if s]

DEFAULT_LOT_SIZE = float(os.getenv("MT5_LOT_SIZE", "0.01"))  # 0.01 Cent Lot สำหรับทุน ~100 บาท (~280 USC)
TIMEFRAME = os.getenv("MT5_TIMEFRAME", "15m")                # ไทม์เฟรม 15 นาทีตามกลยุทธ์

# พารามิเตอร์กลยุทธ์ Pullback Sniper
RSI_PERIOD = 14
RSI_OVERSOLD_THRESHOLD = 30.0    # RSI <= 30 ถือเป็นภาวะ Oversold สุดขีด
BB_PERIOD = 20                   # Bollinger Bands 20
BB_STD = 2.0                     # ค่าเบี่ยงเบน 2.0 Standard Deviations
ATR_PERIOD = 14

# การบริหารความเสี่ยง (Risk Management)
BREAKEVEN_TRIGGER_PIPS = 15.0    # กำไรแตะ +15 pips เลื่อน SL บังหน้าทุน (Auto-Breakeven)
BREAKEVEN_BUFFER_PIPS = 1.0      # เลื่อน SL เหนือทุน +1 pip เผื่อค่าคอมมิชชันและ Spread
TRAILING_TRIGGER_PIPS = 25.0     # กำไรแตะ +25 pips เริ่มต้นเปิดระบบ Trailing Stop
TRAILING_DISTANCE_PIPS = 15.0    # ลาก SL ตามหลังจุดสูงสุด 15 pips
DEFAULT_SL_PIPS = 25.0           # Server-side Stop Loss เริ่มต้น (25 pips)
DEFAULT_TP_PIPS = 45.0           # Server-side Take Profit เริ่มต้น (45 pips)

# รอบเวลาการสแกน (วินาที)
SCAN_INTERVAL_SECONDS = 30       # สแกนตลาดทุกๆ 30 วินาที
IN_POSITION_POLL_SECONDS = 10    # ตรวจสอบไม้ที่กำลังถือครองทุกๆ 10 วินาที

# =============================================================================
# 🕒 TIME & LOGGING UTILITIES
# =============================================================================
def get_thai_time() -> str:
    """คืนค่าเวลาปัจจุบันในประเทศไทย (UTC+7) รูปแบบ YYYY-MM-DD HH:MM:SS"""
    return (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')

def log_status(text: str):
    """บันทึกข้อความสถานะลง status_log_mt5.txt และแสดงบนคอนโซล"""
    print(text, flush=True)
    try:
        with open(STATUS_FILE, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass

def log_trade(text: str):
    """บันทึกประวัติและผลการเทรดลง trade_log_mt5.txt และ status_log_mt5.txt"""
    now = get_thai_time()
    log_msg = f"[{now}] {text}"
    print(log_msg, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")
        with open(STATUS_FILE, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")
    except Exception:
        pass

def trim_status_log_if_needed():
    """จำกัดขนาด status_log_mt5.txt ไม่ให้เกิน ~1.5 MB เพื่อประสิทธิภาพและความรวดเร็วในการ Sync"""
    try:
        if os.path.exists(STATUS_FILE) and os.path.getsize(STATUS_FILE) > 1_500_000:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > 7000:
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines[-5000:])
    except Exception:
        pass

# =============================================================================
# 💾 STATE PERSISTENCE (ATOMIC WRITE)
# =============================================================================
def get_default_state() -> dict:
    """โครงสร้างข้อมูลสถานะเริ่มต้นของบอท"""
    return {
        "symbol": None,
        "in_position": False,
        "position_id": None,
        "entry_price": 0.0,
        "position_size": DEFAULT_LOT_SIZE,
        "tp": 0.0,
        "sl": 0.0,
        "be_set": False,
        "highest_price": 0.0,
        "entry_time": None,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "last_update": None
    }

def save_state_atomic(state_dict: dict, file_path: str = STATE_FILE):
    """
    บันทึกสถานะการเทรดลงไฟล์ JSON แบบ Atomic Write
    โดยเขียนลงไฟล์ชั่วคราวแล้วเปลี่ยนชื่อ (os.replace) เพื่อป้องกันไฟล์เสียหายจากไฟดับหรือการหยุดทำงานกะทันหัน
    """
    state_dict["last_update"] = get_thai_time()
    temp_file = f"{file_path}.tmp_{os.getpid()}_{int(time.time() * 1000)}"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state_dict, f, indent=2, ensure_ascii=False, default=str)
            f.flush()
            os.fsync(f.fileno())  # ยืนยันการเขียนข้อมูลลงดิสก์โดยตรง
        os.replace(temp_file, file_path)  # Atomic rename
    except Exception as e:
        log_trade(f"⚠️ [STATE SAVE ERROR] บันทึกสถานะไม่สำเร็จ: {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

def load_state(file_path: str = STATE_FILE) -> dict:
    """กู้คืนสถานะการถือครองและเป้าหมาย TP/SL จาก active_state_mt5.json เมื่อเปิดเครื่องใหม่"""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                default = get_default_state()
                default.update(data)
                return default
        except Exception as e:
            log_trade(f"⚠️ [STATE LOAD ERROR] อ่านไฟล์สถานะไม่สำเร็จ: {e}")
    return get_default_state()

# =============================================================================
# 🔐 CREDENTIALS & SAFE STANDBY
# =============================================================================
def get_env_credentials():
    """ตรวจสอบว่ามี METAAPI_TOKEN และ METAAPI_ACCOUNT_ID ใน .env หรือไม่"""
    load_dotenv(override=True)
    token = os.getenv("METAAPI_TOKEN", "").strip()
    account_id = os.getenv("METAAPI_ACCOUNT_ID", "").strip()

    placeholders = {
        "", "your_token_here", "your_account_id_here", "your_metaapi_token",
        "your_metaapi_account_id", "your_metaapi_token_here", "your_metaapi_account_id_here",
        "xxx", "none", "null"
    }
    if not token or token.lower() in placeholders or not account_id or account_id.lower() in placeholders:
        return None, None
    return token, account_id

async def wait_for_credentials_safely() -> tuple:
    """
    หากยังไม่มีการตั้งค่า METAAPI_TOKEN หรือ METAAPI_ACCOUNT_ID
    จะแสดงข้อความเตือนอย่างสุภาพและหยุดรออย่างปลอดภัย (Safe Standby) โดยไม่ Crash
    """
    warned = False
    while True:
        token, account_id = get_env_credentials()
        if token and account_id:
            if warned:
                log_trade("✅ [CONFIG DETECTED] ตรวจพบ METAAPI_TOKEN และ METAAPI_ACCOUNT_ID เรียบร้อยแล้ว! กำลังเข้าสู่ขั้นตอนเชื่อมต่อ...")
            return token, account_id

        if not warned:
            msg = (
                "\n" + "=" * 65 + "\n"
                "📢 [คำแนะนำการตั้งค่า / Setup Instructions]\n"
                "ไม่พบค่า 'METAAPI_TOKEN' หรือ 'METAAPI_ACCOUNT_ID' ที่ถูกต้องในไฟล์ .env\n"
                "กรุณาเพิ่มการตั้งค่าสำหรับ MetaTrader 5 ในไฟล์ .env ดังตัวอย่างนี้:\n\n"
                "  METAAPI_TOKEN=your_token_from_metaapi\n"
                "  METAAPI_ACCOUNT_ID=your_account_id_from_metaapi\n"
                "  MT5_SYMBOL=EURUSDc    # (ระบุได้ตามต้องการ หรือปล่อยว่างเพื่อให้บอทตรวจจับ)\n"
                "  MT5_LOT_SIZE=0.01     # (ค่าเริ่มต้น 0.01 Cent Lot สำหรับทุน 100 บาท)\n\n"
                "💡 ระบบกำลังเข้าสู่โหมด Standby อย่างปลอดภัย (Safe Standby Mode)\n"
                "   และจะตรวจสอบไฟล์ .env ซ้ำอัตโนมัติทุกๆ 30 วินาที...\n"
                "=" * 65 + "\n"
            )
            log_status(msg)
            warned = True

        await asyncio.sleep(30)

# =============================================================================
# 📅 WEEKEND FILTER (ตัวกรองวันหยุดสุดสัปดาห์)
# =============================================================================
def is_forex_market_open() -> bool:
    """
    ตรวจสอบสถานะวันเปิดทำการของตลาด Forex:
    datetime.utcnow().weekday() < 5
    - จันทร์=0, อังคาร=1, พุธ=2, พฤหัส=3, ศุกร์=4 -> ตลาดเปิดทำการ (คืนค่า True)
    - เสาร์=5, อาทิตย์=6 -> สุดสัปดาห์ ตลาด Forex ปิดทำการ (คืนค่า False)
    """
    weekday = datetime.utcnow().weekday()
    return weekday < 5

# =============================================================================
# 📊 TECHNICAL ANALYSIS & PULLBACK SNIPER STRATEGY
# =============================================================================
def calculate_indicators(candles: list) -> pd.DataFrame:
    """
    คำนวณอินดิเคเตอร์เชิงเทคนิคบนกราฟ 15m สำหรับกลยุทธ์ Pullback Sniper
    - RSI (Relative Strength Index 14)
    - Bollinger Bands (SMA 20, 2 STD) -> Lower BB / Upper BB
    - ATR (Average True Range 14)
    """
    df = pd.DataFrame(candles)
    if df.empty or len(df) < BB_PERIOD:
        return df

    # จัดเรียงเวลาจากอดีตมาปัจจุบัน
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
        df = df.sort_values("time").reset_index(drop=True)

    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["open"] = df["open"].astype(float)

    # 1. Bollinger Bands (20, 2)
    df["sma20"] = df["close"].rolling(window=BB_PERIOD).mean()
    df["std20"] = df["close"].rolling(window=BB_PERIOD).std()
    df["bb_lower"] = df["sma20"] - (BB_STD * df["std20"])
    df["bb_upper"] = df["sma20"] + (BB_STD * df["std20"])

    # 2. RSI (14) - Wilder's smoothing
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))

    # 3. ATR (14)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    df["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(window=ATR_PERIOD).mean()

    return df

def evaluate_pullback_sniper(df: pd.DataFrame, current_price: float, pip_size: float, digits: int) -> dict:
    """
    ประเมินสัญญาณเทรดตามกลยุทธ์ Pullback Sniper 15m
    เงื่อนไข BUY:
    - RSI Oversold (RSI <= 30.0)
    - ราคาแตะหรือหลุดเส้น Lower Bollinger Band (Price <= Lower BB)
    """
    if df.empty or len(df) < BB_PERIOD or "rsi" not in df.columns:
        return {"decision": "WAIT", "reason": "ข้อมูลแท่งเทียนไม่เพียงพอสำหรับการวิเคราะห์"}

    latest = df.iloc[-1]
    rsi = float(latest["rsi"])
    bb_lower = float(latest["bb_lower"])
    bb_upper = float(latest["bb_upper"])
    atr = float(latest["atr"]) if pd.notna(latest["atr"]) else (20 * pip_size)

    # เงื่อนไขกลยุทธ์ Pullback Sniper
    is_rsi_oversold = rsi <= RSI_OVERSOLD_THRESHOLD
    # เผื่อความคลาดเคลื่อน 0.02% (2 pips) สำหรับการแตะขอบล่าง
    is_price_at_lower_bb = current_price <= (bb_lower + (2 * pip_size))

    decision = "WAIT"
    reason = f"RSI={rsi:.1f} (รอ <={RSI_OVERSOLD_THRESHOLD}) | ราคา {current_price:.{digits}f} vs BB_Lower {bb_lower:.{digits}f}"

    if is_rsi_oversold and is_price_at_lower_bb:
        decision = "BUY"
        reason = (
            f"🎯 [PULLBACK SNIPER BUY] ยืนยันครบถ้วน! "
            f"RSI Oversold ({rsi:.1f} <= {RSI_OVERSOLD_THRESHOLD}) & "
            f"ราคาแตะขอบล่าง BB ({current_price:.{digits}f} <= {bb_lower:.{digits}f})"
        )

    return {
        "decision": decision,
        "reason": reason,
        "rsi": rsi,
        "bb_lower": bb_lower,
        "bb_upper": bb_upper,
        "atr": atr
    }

# =============================================================================
# 🔍 SYMBOL RESOLUTION & SPECIFICATIONS
# =============================================================================
async def resolve_cent_symbol(connection) -> str:
    """
    ค้นหาสัญลักษณ์ Cent ที่พร้อมใช้งานบนบัญชี MT5 ของโบรกเกอร์
    หากพบคู่ Cent (เช่น EURUSDc, EURUSDm) จะเลือกใช้งานเป็นอันดับแรก
    """
    try:
        available_symbols = await connection.get_symbols()
    except Exception as e:
        log_trade(f"⚠️ ไม่สามารถดึงรายชื่อสัญลักษณ์ได้: {e}, ใช้ค่าเริ่มต้น EURUSD")
        return "EURUSD"

    # 1. ค้นหาจากรายการผู้สมัครที่กำหนดไว้
    for cand in CANDIDATE_SYMBOLS:
        if cand in available_symbols:
            log_trade(f"🔍 [SYMBOL DETECTED] ตรวจพบสัญลักษณ์คู่เงิน Cent: '{cand}'")
            return cand

    # 2. ค้นหาคู่เงินที่ขึ้นต้นด้วยหรือมี EURUSD
    for s in available_symbols:
        s_upper = s.upper()
        if "EURUSD" in s_upper and ("C" in s_upper or "M" in s_upper):
            log_trade(f"🔍 [SYMBOL DETECTED] พบสัญลักษณ์ประเภท Cent อัตโนมัติ: '{s}'")
            return s

    for s in available_symbols:
        if "EURUSD" in s.upper():
            log_trade(f"🔍 [SYMBOL DETECTED] พบสัญลักษณ์: '{s}'")
            return s

    log_trade("⚠️ ไม่พบคู่เงิน EURUSD แบบ Cent, ใช้ค่าเริ่มต้น EURUSD")
    return "EURUSD"

async def get_symbol_specs(connection, symbol: str) -> dict:
    """
    ดึงข้อมูลคุณสมบัติของสัญลักษณ์ (Specification)
    คำนวณ pip_size, point, digits และขนาดไม้ขั้นต่ำ
    """
    try:
        spec = await connection.get_symbol_specification(symbol)
        digits = int(spec.get("digits", 5))
        point = float(spec.get("point", 10 ** -digits))
        # ในฟอเร็กซ์ 5 หลัก: 1 pip = 10 points = 0.00010
        if spec.get("pipSize") and float(spec["pipSize"]) > 0:
            pip_size = float(spec["pipSize"])
        elif digits in (3, 5):
            pip_size = point * 10.0
        else:
            pip_size = point

        min_vol = float(spec.get("minVolume", DEFAULT_LOT_SIZE))
        step_vol = float(spec.get("volumeStep", 0.01))
        lot_size = max(DEFAULT_LOT_SIZE, min_vol)

        return {
            "digits": digits,
            "point": point,
            "pip_size": pip_size,
            "min_volume": min_vol,
            "volume_step": step_vol,
            "lot_size": lot_size,
            "contract_size": float(spec.get("contractSize", 100000.0))
        }
    except Exception as e:
        log_trade(f"⚠️ [SPEC ERROR] อ่านค่า Specification ไม่สำเร็จ: {e}, ใช้ค่าสากล")
        return {
            "digits": 5,
            "point": 0.00001,
            "pip_size": 0.00010,
            "min_volume": 0.01,
            "volume_step": 0.01,
            "lot_size": DEFAULT_LOT_SIZE,
            "contract_size": 100000.0
        }

# =============================================================================
# 🛡️ POSITION & RISK MANAGEMENT (SL / TP / BREAKEVEN / TRAILING)
# =============================================================================
async def manage_open_position(connection, symbol: str, specs: dict, state: dict):
    """
    ระบบบริหารความเสี่ยงสำหรับไม้ที่กำลังถือครอง:
    1. ตรวจสอบสถานะไม้บน Server MT5
    2. Auto-Breakeven: เมื่อกำไรแตะ +15 pips เลื่อน SL บังหน้าทุน (+1 pip buffer)
    3. Trailing Stop: เมื่อกำไรเติบโต ลาก SL ตามระยะ 15 pips
    4. ตรวจจับการปิดไม้โดย Server-side SL/TP
    """
    digits = specs["digits"]
    pip_size = specs["pip_size"]

    try:
        positions = await connection.get_positions()
    except Exception as e:
        log_status(f"⚠️ [POSITION POLL ERROR] ไม่สามารถตรวจสอบสถานะไม้ได้: {e}")
        return

    # ค้นหาตำแหน่งไม้ที่เปิดอยู่ของสัญลักษณ์นี้
    my_position = None
    target_pos_id = str(state.get("position_id") or "")
    for pos in positions:
        if str(pos.get("id")) == target_pos_id or pos.get("symbol") == symbol:
            my_position = pos
            break

    # กรณีไม้ถูกปิดไปแล้ว (โดย Server-side TP หรือ SL หรือปิดมือ)
    if not my_position:
        if state.get("in_position"):
            state["in_position"] = False
            state["total_trades"] = state.get("total_trades", 0) + 1
            last_pips = state.get("last_pips", 0.0)
            last_profit_usc = state.get("last_profit_usc", 0.0)
            last_profit_thb = (last_profit_usc / 100.0) * 34.0
            result_tag = "🎯 [TP / PROFIT]" if last_profit_usc >= 0 else "🛑 [SL / LOSS]"
            log_trade(
                f"{result_tag} [POSITION CLOSED {symbol}] ไม้ ID: {state.get('position_id')} ปิดเรียบร้อยแล้ว (โดย Server-side SL/TP) | "
                f"ผลลัพธ์สุทธิ: {last_profit_usc:+.2f} USC ({last_profit_thb:+.2f} บาท / {last_pips:+.1f} pips)"
            )
            state["position_id"] = None
            state["be_set"] = False
            state["highest_price"] = 0.0
            save_state_atomic(state)
        return

    # อัปเดตข้อมูลไม้ที่ถือครอง
    pos_id = str(my_position.get("id"))
    state["position_id"] = pos_id
    state["in_position"] = True
    entry_price = float(my_position.get("openPrice", state.get("entry_price", 0.0)))
    current_price = float(my_position.get("currentPrice", entry_price))
    current_sl = float(my_position.get("stopLoss") or 0.0)
    current_tp = float(my_position.get("takeProfit") or 0.0)
    unrealized_profit = float(my_position.get("unrealizedProfit") or my_position.get("profit") or 0.0)

    # คำนวณระยะกำไรเป็น Pips
    pnl_pips = (current_price - entry_price) / pip_size
    state["last_pips"] = pnl_pips
    state["last_profit_usc"] = unrealized_profit

    # บันทึกราคาสูงสุดที่เคยขึ้นไปถึง
    if current_price > state.get("highest_price", 0.0):
        state["highest_price"] = current_price

    # 1. 🛡️ AUTO-BREAKEVEN: เมื่อกำไรแตะ +15 pips เลื่อน SL ล็อกต้นทุน (+1 pip)
    if not state.get("be_set") and pnl_pips >= BREAKEVEN_TRIGGER_PIPS:
        be_sl = round(entry_price + (BREAKEVEN_BUFFER_PIPS * pip_size), digits)
        # ตรวจสอบให้แน่ใจว่าค่า SL ใหม่ดีกว่าค่าเดิม
        if be_sl > current_sl:
            try:
                log_trade(
                    f"🛡️ [AUTO-BREAKEVEN] {symbol} กำไรแตะ +{pnl_pips:.1f} pips (>= +{BREAKEVEN_TRIGGER_PIPS} pips)! "
                    f"กำลังเลื่อน Server SL ไปที่ {be_sl:.{digits}f}..."
                )
                await connection.modify_position(pos_id, stop_loss=be_sl, take_profit=current_tp)
                state["be_set"] = True
                state["sl"] = be_sl
                save_state_atomic(state)
                log_trade(f"✅ [AUTO-BREAKEVEN SUCCESS] ปรับ SL ล็อกต้นทุนสำเร็จ @ {be_sl:.{digits}f}")
                current_sl = be_sl
            except Exception as e:
                log_trade(f"❌ [BE MODIFY ERROR] ปรับ SL Breakeven ไม่สำเร็จ: {e}")

    # 2. 📈 TRAILING STOP: เมื่อกำไรก้อนใหญ่ (+25 pips ขึ้นไป) ลาก SL ตามราคา
    if pnl_pips >= TRAILING_TRIGGER_PIPS:
        trailing_sl = round(state["highest_price"] - (TRAILING_DISTANCE_PIPS * pip_size), digits)
        # ปรับเลื่อน SL ขึ้นเมื่อระยะใหม่อย่างน้อยห่างจาก SL เดิม 1.5 pips
        if trailing_sl > current_sl + (1.5 * pip_size):
            try:
                log_trade(
                    f"📈 [TRAILING STOP] {symbol} กำไร +{pnl_pips:.1f} pips | "
                    f"ขยับ Server SL ตามราคาขึ้นไปที่ {trailing_sl:.{digits}f}..."
                )
                await connection.modify_position(pos_id, stop_loss=trailing_sl, take_profit=current_tp)
                state["sl"] = trailing_sl
                save_state_atomic(state)
                log_trade(f"✅ [TRAILING STOP SUCCESS] ขยับ SL สำเร็จ @ {trailing_sl:.{digits}f}")
            except Exception as e:
                log_trade(f"❌ [TRAILING MODIFY ERROR] ปรับ Trailing SL ไม่สำเร็จ: {e}")

    # แสดงสถานะปัจจุบันบนหน้าจอ
    be_tag = " [BE ล็อกแล้ว]" if state.get("be_set") else ""
    pnl_thb = (unrealized_profit / 100.0) * 34.0
    log_status(
        f"📈 [MT5-CENT] [{symbol}] ราคา: {current_price:.{digits}f} | "
        f"🟢 ถือ BUY {state.get('position_size', 0.01)} Lot (PnL: {pnl_pips:+.1f} pips | {unrealized_profit:+.2f} USC / {pnl_thb:+.2f} บาท) | "
        f"SL: {state.get('sl', 0.0):.{digits}f} | TP: {state.get('tp', 0.0):.{digits}f}{be_tag}"
    )

async def execute_pullback_buy(connection, symbol: str, specs: dict, eval_result: dict, state: dict) -> bool:
    """
    เปิดไม้ BUY เมื่อกลยุทธ์ Pullback Sniper ยืนยันสัญญาณ
    แนบ Server-side SL และ TP ทันทีตั้งแต่ตอนส่งคำสั่ง
    """
    digits = specs["digits"]
    pip_size = specs["pip_size"]
    lot_size = specs["lot_size"]
    atr = eval_result["atr"]

    # ดึงราคาปัจจุบันจาก Broker
    try:
        quote = await connection.get_symbol_price(symbol)
        entry_price = float(quote.get("ask") or quote.get("bid"))
    except Exception:
        entry_price = float(eval_result.get("bb_lower", 1.0))

    # คำนวณ Server-side SL/TP
    # SL: อย่างน้อย 25 pips หรือ 1.5 * ATR
    # TP: อย่างน้อย 45 pips หรือ 2.5 * ATR
    sl_distance = max(DEFAULT_SL_PIPS * pip_size, 1.5 * atr)
    tp_distance = max(DEFAULT_TP_PIPS * pip_size, 2.5 * atr)

    sl_price = round(entry_price - sl_distance, digits)
    tp_price = round(entry_price + tp_distance, digits)

    log_trade(
        f"🚀 [ORDER SUBMIT] ยิงคำสั่ง BUY {symbol} {lot_size} Cent Lot "
        f"@ ~{entry_price:.{digits}f} | Server-SL: {sl_price:.{digits}f} | Server-TP: {tp_price:.{digits}f}"
    )

    try:
        trade_result = await connection.create_market_buy_order(
            symbol=symbol,
            volume=lot_size,
            stop_loss=sl_price,
            take_profit=tp_price,
            options={
                "comment": "PullbackSniper_MT5"
            }
        )

        pos_id = trade_result.get("positionId") or trade_result.get("orderId")
        string_code = trade_result.get("stringCode", "OK")

        margin_est_usc = (10.0 * entry_price) / 1000.0 * 100.0
        margin_est_thb = (margin_est_usc / 100.0) * 34.0
        log_trade(
            f"✅ [BUY SUCCESS {symbol}] เปิดไม้สำเร็จ! {lot_size} Cent Lot @ {entry_price:.{digits}f} | "
            f"ใช้เงินประกัน (Margin): ~{margin_est_usc:.2f} USC (~{margin_est_thb:.2f} บาท) | "
            f"Ticket: {pos_id} | Server-SL: {sl_price:.{digits}f} | Server-TP: {tp_price:.{digits}f}"
        )

        state["in_position"] = True
        state["position_id"] = str(pos_id)
        state["entry_price"] = entry_price
        state["position_size"] = lot_size
        state["sl"] = sl_price
        state["tp"] = tp_price
        state["be_set"] = False
        state["highest_price"] = entry_price
        state["entry_time"] = get_thai_time()
        save_state_atomic(state)
        return True

    except Exception as e:
        log_trade(f"❌ [ORDER ERROR] ยิงคำสั่งซื้อไม่สำเร็จ: {e}")
        return False

# =============================================================================
# 🔄 MAIN TRADING ENGINE & LIFECYCLE
# =============================================================================
async def run_bot():
    """แกนหลักของบอทเทรด MT5 Cent Account"""
    log_status("\n" + "=" * 65)
    log_status("🚀 เริ่มต้นระบบบอทเทรด MetaTrader 5 Cent Account (Pullback Sniper 15m)")
    log_status(f"🕒 เวลาเริ่มต้นระบบ: {get_thai_time()}")
    log_status(f"💰 แผนพอร์ต: ทุน 100 บาท (~280 USC) | ขนาดไม้: {DEFAULT_LOT_SIZE} Cent Lot")
    log_status("=" * 65)

    # 1. รอรับค่า Credential จาก .env อย่างปลอดภัย
    token, account_id = await wait_for_credentials_safely()

    # 2. เชื่อมต่อ MetaApi Cloud SDK
    log_status("📡 กำลังเตรียมเชื่อมต่อ MetaApi Cloud SDK...")
    api = MetaApi(token)

    account = None
    connection = None
    is_running = True

    def handle_exit_signal(sig, frame):
        nonlocal is_running
        log_trade("🛑 ได้รับสัญญาณหยุดการทำงาน (Shutdown Signal) กำลังปิดการเชื่อมต่ออย่างปลอดภัย...")
        is_running = False

    try:
        signal.signal(signal.SIGINT, handle_exit_signal)
        signal.signal(signal.SIGTERM, handle_exit_signal)
    except Exception:
        pass

    state = load_state()

    while is_running:
        try:
            # ตรวจสอบและเชื่อมต่อไปยัง MetaTrader Account
            if account is None:
                log_status(f"🔍 ค้นหาบัญชี MT5 ID: {account_id}...")
                account = await api.metatrader_account_api.get_account(account_id)

                if account.state != "DEPLOYED":
                    log_status("⏳ บัญชี MT5 ยังไม่ได้ Deploy กำลัง Deploy API Server...")
                    await account.deploy()

                log_status("⏳ กำลังรอเชื่อมต่อ MT5 Terminal Server...")
                await account.wait_connected()

                connection = account.get_rpc_connection()
                await connection.connect()
                log_status("🔄 กำลังซิงค์ Terminal State (wait_synchronized)...")
                await connection.wait_synchronized()

                # ตรวจสอบข้อมูลบัญชี
                account_info = await connection.get_account_information()
                log_status(
                    f"✅ เชื่อมต่อ MT5 สำเร็จ! โบรกเกอร์: {account_info.get('broker')} | "
                    f"ยอดบาลานซ์: {account_info.get('balance'):.2f} {account_info.get('currency')} | "
                    f"เลเวอเรจ: 1:{account_info.get('leverage')}"
                )

                # ตรวจจับสัญลักษณ์ Cent ที่เหมาะสมที่สุด
                active_symbol = await resolve_cent_symbol(connection)
                state["symbol"] = active_symbol
                specs = await get_symbol_specs(connection, active_symbol)
                log_status(
                    f"🎯 สัญลักษณ์ที่ใช้: {active_symbol} (Digits: {specs['digits']} | "
                    f"PipSize: {specs['pip_size']:.{specs['digits']}f} | LotSize: {specs['lot_size']})"
                )
                save_state_atomic(state)

            # =================================================================
            # 📅 ตัวกรองวันหยุดสุดสัปดาห์ (Weekend Filter)
            # =================================================================
            if not is_forex_market_open():
                log_status(
                    f"⏸️ [WEEKEND STANDBY] ตลาด Forex ปิดทำการช่วงสุดสัปดาห์ "
                    f"(วันเสาร์-อาทิตย์ UTC: {datetime.utcnow().strftime('%Y-%m-%d %A')}) | บอทเข้าสู่โหมด Standby..."
                )
                trim_status_log_if_needed()
                await asyncio.sleep(300)  # พัก 5 นาทีระหว่างสุดสัปดาห์
                continue

            # =================================================================
            # 🛡️ บริหารจัดการไม้ที่กำลังถือครองอยู่ (Active Position Management)
            # =================================================================
            await manage_open_position(connection, active_symbol, specs, state)

            # หากมีไม้ถือครองอยู่ ให้รอแล้ววนลูปสั้นเพื่อเฝ้าระวังกำไรและ SL
            if state.get("in_position"):
                await asyncio.sleep(IN_POSITION_POLL_SECONDS)
                trim_status_log_if_needed()
                continue

            # =================================================================
            # 📊 สแกนหาจังหวะเข้าทำกำไร (Pullback Sniper 15m)
            # =================================================================
            log_status(f"\n--- 🕒 สแกนตลาดเวลา: {get_thai_time()} [{active_symbol}] ---")

            candles = await account.get_historical_candles(active_symbol, timeframe=TIMEFRAME, limit=100)
            if not candles:
                log_status("⚠️ ไม่สามารถดึงแท่งเทียนได้ในรอบนี้ กำลังลองใหม่ในรอบหน้า...")
                await asyncio.sleep(SCAN_INTERVAL_SECONDS)
                continue

            df = calculate_indicators(candles)

            # ดึงราคาปัจจุบัน
            try:
                ticker = await connection.get_symbol_price(active_symbol)
                current_price = float(ticker.get("ask") or ticker.get("bid"))
            except Exception:
                current_price = float(df["close"].iloc[-1])

            # ประเมินกลยุทธ์ Pullback Sniper
            eval_result = evaluate_pullback_sniper(df, current_price, specs["pip_size"], specs["digits"])

            if eval_result["decision"] == "BUY":
                await execute_pullback_buy(connection, active_symbol, specs, eval_result, state)
            else:
                log_status(f"📈 [MT5-CENT] [{active_symbol}] {current_price:.{specs['digits']}f} | WAITING ({eval_result['reason']})")

            trim_status_log_if_needed()
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)

        except asyncio.CancelledError:
            log_trade("🛑 ได้รับคำสั่งยกเลิก Asynchronous Task")
            break
        except Exception as e:
            err_msg = str(e)
            if "top up" in err_msg.lower():
                log_status("⚠️ [METAAPI NOTICE] บัญชี MetaAPI Cloud รอการเปิดใช้งานแพ็กเกจ Terminal (Top up ใน app.metaapi.cloud) | ฝั่ง MT5 สแตนด์บายรออย่างปลอดภัย...")
                log_trade(f"⚠️ [METAAPI STANDBY] รอการเปิดใช้งานแพ็กเกจ MetaAPI Cloud: {err_msg}")
                connection = None
                account = None
                await asyncio.sleep(60)
            else:
                log_trade(f"⚠️ [LOOP WARNING] เกิดข้อผิดพลาดในการทำงาน: {e}")
                log_status("⏳ กำลังรีเซ็ตการเชื่อมต่อและลองใหม่อีกครั้งใน 15 วินาที...")
                connection = None
                account = None
                await asyncio.sleep(15)

    # ปิดการเชื่อมต่ออย่างปลอดภัยเมื่อจบการทำงาน
    if connection:
        try:
            await connection.close()
            log_status("🔌 ปิดการเชื่อมต่อ RPC Connection เรียบร้อยแล้ว")
        except Exception:
            pass

    save_state_atomic(state)
    log_status(f"👋 บอทปิดการทำงานสมบูรณ์ ณ เวลา: {get_thai_time()}")

def main():
    """จุดเริ่มต้นโปรแกรม"""
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        print("\n👋 สิ้นสุดการทำงานของบอทอย่างปลอดภัย")

if __name__ == "__main__":
    main()
