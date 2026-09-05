import os
import sys
import time
import json
import subprocess
import ccxt
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
SYMBOLS = ['SOL/USDT', 'BTC/USDT', 'GALA/USDT', 'VET/USDT', 'PAXG/USDT']
TIMEFRAME = '15m'
HTF_TIMEFRAME = '1h'
TRADE_AMOUNT_USDT = 15.0 # จำนวนเงินที่ใช้ซื้อต่อ 1 ไม้ (Binance ขั้นต่ำ $10)

MEMORY_FILE = "agent_memory_multi.json"
LOG_FILE = "trade_log.txt"

exchange = ccxt.binance({
    'apiKey': os.getenv('TESTNET_API_KEY'),
    'secret': os.getenv('TESTNET_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})
exchange.set_sandbox_mode(True)

try:
    bal = exchange.fetch_balance()
    start_usdt = bal['total'].get('USDT', 0.0)
    print(f"✅ เชื่อมต่อ Testnet สำเร็จ! ยอดเงิน: {start_usdt:.2f} USDT", flush=True)
except Exception as e:
    print(f"❌ เชื่อมต่อ Testnet ไม่สำเร็จ: {e}", flush=True)
    exit()

# ==========================================
# 🧠 MEMORY & STATE MANAGEMENT
# ==========================================
# เก็บสถานะการเทรดของแต่ละเหรียญแบบแยกอิสระ
state = {}
for sym in SYMBOLS:
    state[sym] = {
        'in_position': False,
        'entry_price': 0.0,
        'position_size': 0.0,
        'tp': 0.0,
        'sl': 0.0,
        'be_set': False,
        'consecutive_losses': 0,
        'cooldown_until': None
    }

def get_default_memory():
    return {
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "learned_params": {
            "min_volume_ratio": 1.30,
            "min_adx": 14.0
        },
        "reflections": []
    }

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # ตรวจสอบว่ามีครบทุกเหรียญไหม ถ้าเหรียญใหม่มาเพิ่มให้สร้างใหม่
                for sym in SYMBOLS:
                    if sym not in data:
                        data[sym] = get_default_memory()
                return data
        except Exception:
            pass
    
    # ถ้าไม่มีไฟล์ ให้สร้างใหม่
    data = {}
    for sym in SYMBOLS:
        data[sym] = get_default_memory()
    return data

memory = load_memory()

def save_memory(mem):
    try:
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ==========================================
# 🔄 AUTO-PATCH SYSTEM
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
            log_trade("🔄 [AUTO-PATCH] พบอัปเดตใหม่บน GitHub! กำลังดาวน์โหลดและรีสตาร์ทตัวเอง...")
            # ใช้ reset --hard เพื่อบังคับทับโค้ดใหม่ลงไป 100% (แก้ปัญหา Conflict)
            subprocess.run(["git", "reset", "--hard", "origin/main"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(2)
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        log_trade(f"⚠️ [AUTO-PATCH ERROR] อัปเดตไม่สำเร็จ: {e}")

def get_thai_time():
    return (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')

def log_trade(text):
    now = get_thai_time()
    log_msg = f"[{now}] {text}"
    print(log_msg, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_msg + "\n")

# ==========================================
# 📊 INDICATORS & LOGIC
# ==========================================
def calculate_indicators(df):
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['close'].shift(1))
    df['tr3'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    df['atr'] = df['tr'].rolling(14).mean()

    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))

    upMove = df['high'] - df['high'].shift(1)
    downMove = df['low'].shift(1) - df['low']
    plusDM = pd.Series(0.0, index=df.index)
    minusDM = pd.Series(0.0, index=df.index)
    plusDM[(upMove > downMove) & (upMove > 0)] = upMove
    minusDM[(downMove > upMove) & (downMove > 0)] = downMove

    df['+di'] = 100 * (plusDM.ewm(alpha=1/14, adjust=False).mean() / df['atr'])
    df['-di'] = 100 * (minusDM.ewm(alpha=1/14, adjust=False).mean() / df['atr'])
    dx = 100 * abs(df['+di'] - df['-di']) / (df['+di'] + df['-di'])
    df['adx'] = dx.ewm(alpha=1/14, adjust=False).mean()

    # คำนวณ Bollinger Bands สำหรับท่า Pullback
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['bb_lower'] = df['sma20'] - (2 * df['std20'])

    return df

def ag_evaluate_market(sym, current_price, prev_high, avg_volume, current_volume, ema_200_1h, rsi, adx, atr, bb_lower, wyckoff_valid):
    learned = memory[sym]["learned_params"]
    min_vol = learned.get("min_volume_ratio", 1.30)
    min_adx = learned.get("min_adx", 14.0)
    min_adx = min(min_adx, 14.0)
    
    vol_ratio = (current_volume / avg_volume) if avg_volume > 0 else 1.0

    is_htf_bull = current_price > ema_200_1h
    is_breakout = current_price > prev_high
    vol_confirmed = vol_ratio >= min_vol
    rsi_valid = 50 <= rsi <= 75
    adx_valid = adx >= min_adx

    decision = "WAIT"
    reason = f"ยังไม่ทะลุ Swing High ${prev_high:.6f} และยังไม่แตะขอบล่าง BB"

    # --- Strategy 1: Breakout ---
    is_strat1 = is_htf_bull and is_breakout and vol_confirmed and rsi_valid and adx_valid and wyckoff_valid
    # --- Strategy 2: Pullback Sniper ---
    is_strat2 = is_htf_bull and (current_price <= bb_lower) and (rsi < 40)

    if is_strat1:
        decision = "BUY"
        reason = f"Breakout! ยืนยันครบ | RSI:{rsi:.1f} ADX:{adx:.1f} Vol:{vol_ratio:.2f}x"
    elif is_strat2:
        decision = "BUY"
        reason = f"Pullback Sniper! ช้อนของถูก | RSI:{rsi:.1f} แตะ BB Lower: ${bb_lower:.4f}"
    elif not is_htf_bull: 
        reason = f"ราคาใต้ 1h EMA200"

    return {
        "decision": decision,
        "suggested_tp_price": current_price + (2.5 * atr),
        "suggested_sl_price": current_price - (1.5 * atr),
        "reason": reason,
        "rsi": rsi, "adx": adx
    }

def sync_data_to_github():
    try:
        subprocess.run(["git", "config", "user.name", "Wispbyte-Bot"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.email", "bot@wispbyte.com"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # เพิ่มการอัปโหลด LOG_FILE ไปพร้อมกับ MEMORY_FILE
        subprocess.run(["git", "add", MEMORY_FILE, LOG_FILE], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if MEMORY_FILE in status.stdout or LOG_FILE in status.stdout:
            subprocess.run(["git", "commit", "-m", "Auto-Sync Data [bot]"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "pull", "--rebase"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "push"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log_trade("☁️ [AUTO-SYNC] อัปโหลดความจำและ Log ขึ้น GitHub สำเร็จ!")
    except Exception as e:
        log_trade(f"⚠️ [AUTO-SYNC ERROR] ไม่สามารถอัปโหลดข้อมูลได้: {e}")

def ag_learn_from_trade(sym, trade_type, pnl_pct):
    learned = memory[sym]["learned_params"]
    current_min_vol = learned.get("min_volume_ratio", 1.30)
    current_min_adx = learned.get("min_adx", 14.0)

    if trade_type == "WIN":
        new_min_vol = max(1.10, round(current_min_vol - 0.05, 2))
        new_min_adx = max(10.0, round(current_min_adx - 0.5, 1))
        lesson = f"Win (+{pnl_pct:.2f}%): ลดเกณฑ์ Vol->{new_min_vol}x, ADX->{new_min_adx}"
    else:
        new_min_vol = min(1.80, round(current_min_vol + 0.10, 2))
        new_min_adx = min(25.0, round(current_min_adx + 1.0, 1))
        lesson = f"Loss (False Break): เพิ่มเกณฑ์ Vol->{new_min_vol}x, ADX->{new_min_adx}"

    learned["min_volume_ratio"] = new_min_vol
    learned["min_adx"] = new_min_adx
    memory[sym]["reflections"].append({
        "date": get_thai_time(),
        "type": trade_type,
        "pnl": f"{pnl_pct:+.2f}%",
        "lesson": lesson
    })
    save_memory(memory)
    sync_data_to_github()
    return lesson

def process_symbol(sym):
    try:
        # 1. ดึงข้อมูล
        bars_15m = exchange.fetch_ohlcv(sym, timeframe=TIMEFRAME, limit=100)
        df_15m = pd.DataFrame(bars_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_15m = calculate_indicators(df_15m)
        
        current_row = df_15m.iloc[-1]
        current_price = float(current_row['close'])
        current_high = float(current_row['high'])
        current_low = float(current_row['low'])
        
        wyckoff_valid = False
        if (current_high - current_low) > 0:
            wyckoff_valid = ((current_price - current_low) / (current_high - current_low)) >= 0.70
            
        rsi_14 = float(current_row['rsi'])
        adx_14 = float(current_row['adx'])
        atr_14 = float(current_row['atr'])
        
        prev_high = float(df_15m['high'].iloc[-11:-1].max())
        avg_volume = float(df_15m['volume'].iloc[-11:-1].mean())
        current_volume = float(current_row['volume'])

        bars_1h = exchange.fetch_ohlcv(sym, timeframe=HTF_TIMEFRAME, limit=210)
        df_1h = pd.DataFrame(bars_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_1h['ema200'] = df_1h['close'].ewm(span=200, adjust=False).mean()
        ema_200_1h = float(df_1h['ema200'].iloc[-1])
        
        rsi_14 = float(current_row['rsi'])
        adx_14 = float(current_row['adx'])
        atr_14 = float(current_row['atr'])
        bb_lower = float(current_row['bb_lower'])

        wyckoff_valid = True
        candle_body = abs(float(current_row['close']) - float(current_row['open']))
        upper_wick = float(current_row['high']) - max(float(current_row['close']), float(current_row['open']))
        if upper_wick > candle_body * 1.5:
            wyckoff_valid = False

        # 2. ประเมิน
        eval_result = ag_evaluate_market(sym, current_price, prev_high, avg_volume, current_volume, ema_200_1h, rsi_14, adx_14, atr_14, bb_lower, wyckoff_valid)
        
        s = state[sym]
        is_cooling_down = s['cooldown_until'] and datetime.utcnow() < s['cooldown_until']

        status_text = ""
        if is_cooling_down:
            status_text = "🛑 COOLDOWN"
        elif s['in_position']:
            pnl = ((current_price - s['entry_price']) / s['entry_price']) * 100
            status_text = f"🟢 LIVE LONG | PnL: {pnl:+.2f}%"
        else:
            status_text = f"WAITING ({eval_result['reason']})"

        print(f"[{sym}] {current_price:.6f} | {status_text}", flush=True)

        # 3. ตัดสินใจซื้อ
        if not s['in_position'] and not is_cooling_down:
            if eval_result["decision"] == "BUY":
                ticker = exchange.fetch_ticker(sym)
                real_entry = float(ticker['last'])
                raw_size = TRADE_AMOUNT_USDT / real_entry
                
                if real_entry < 0.1: size = round(raw_size)
                elif real_entry < 10: size = round(raw_size, 1)
                elif real_entry < 1000: size = round(raw_size, 2)
                else: size = round(raw_size, 4)

                try:
                    order = exchange.create_market_buy_order(sym, size)
                    avg_price = order.get('average')
                    if avg_price is None: avg_price = order.get('price')
                    if avg_price is None: avg_price = real_entry
                    s['entry_price'] = float(avg_price)
                    s['position_size'] = size
                    s['in_position'] = True
                    s['be_set'] = False
                    s['tp'] = eval_result["suggested_tp_price"]
                    s['sl'] = eval_result["suggested_sl_price"]
                    log_trade(f"🟢 [BUY {sym}] ซื้อ {size} @ ${s['entry_price']:.6f} | TP: ${s['tp']:.6f} | SL: ${s['sl']:.6f}")
                except Exception as e:
                    log_trade(f"❌ [BUY ERROR {sym}] {e}")

        # 4. จัดการ Trailing Stop / TP / SL
        elif s['in_position']:
            pnl_percent = (current_price - s['entry_price']) / s['entry_price']

            # Trailing Stop
            if pnl_percent >= 0.015:
                trailing_sl = current_price * 0.99
                if trailing_sl > s['sl']:
                    s['sl'] = trailing_sl
                    s['be_set'] = True
                    log_trade(f"🛡️ [TRAILING STOP {sym}] ขยับ SL ตามกำไรไปที่ ${s['sl']:.6f}")

            if current_price >= s['tp']:
                try:
                    base_coin = sym.split('/')[0]
                    free_bal = exchange.fetch_free_balance().get(base_coin, 0)
                    sell_size = min(s['position_size'], free_bal) if free_bal > 0 else s['position_size']
                    
                    order = exchange.create_market_sell_order(sym, sell_size)
                    avg_price = order.get('average')
                    if avg_price is None: avg_price = order.get('price')
                    if avg_price is None: avg_price = current_price
                    exit_price = float(avg_price)
                    real_pnl_pct = (exit_price - s['entry_price']) / s['entry_price']
                    
                    s['in_position'] = False
                    s['consecutive_losses'] = 0
                    memory[sym]["total_trades"] += 1
                    memory[sym]["wins"] += 1

                    lesson = ag_learn_from_trade(sym, "WIN", real_pnl_pct * 100)
                    log_trade(f"🎯 [TP SUCCESS {sym}] ปิดกำไรที่ ${exit_price:.6f} (+{real_pnl_pct*100:.2f}%) | {lesson}")
                except Exception as e:
                    log_trade(f"❌ [TP ERROR {sym}] {e}")

            elif current_price <= s['sl']:
                try:
                    base_coin = sym.split('/')[0]
                    free_bal = exchange.fetch_free_balance().get(base_coin, 0)
                    sell_size = min(s['position_size'], free_bal) if free_bal > 0 else s['position_size']
                    
                    order = exchange.create_market_sell_order(sym, sell_size)
                    avg_price = order.get('average')
                    if avg_price is None: avg_price = order.get('price')
                    if avg_price is None: avg_price = current_price
                    exit_price = float(avg_price)
                    real_pnl_pct = (exit_price - s['entry_price']) / s['entry_price']
                    
                    s['in_position'] = False
                    memory[sym]["total_trades"] += 1

                    if s['be_set'] and real_pnl_pct >= 0:
                        log_trade(f"🛡️ [SL-BREAKEVEN {sym}] ปิดเสมอตัวที่ ${exit_price:.6f} (+{real_pnl_pct*100:.2f}%)")
                    else:
                        memory[sym]["losses"] += 1
                        s['consecutive_losses'] += 1

                        if s['consecutive_losses'] >= 2:
                            s['cooldown_until'] = datetime.utcnow() + timedelta(hours=4)
                            log_trade(f"🚨 [CIRCUIT BREAKER {sym}] ขาดทุนติด 2 ครั้ง พัก 4 ชม.")

                        lesson = ag_learn_from_trade(sym, "LOSS", real_pnl_pct * 100)
                        log_trade(f"🛑 [SL SUCCESS {sym}] คัทลอสที่ ${exit_price:.6f} ({real_pnl_pct*100:.2f}%) | {lesson}")
                except Exception as e:
                    log_trade(f"❌ [SL ERROR {sym}] {e}")

    except Exception as e:
        log_trade(f"⚠️ Error {sym}: {e}")

# ==========================================
# 🚀 MAIN LOOP
# ==========================================
if __name__ == '__main__':
    log_trade("🚀 เริ่มรันระบบ AG 2.0 MULTI-COIN บน Binance Testnet")
    log_trade(f"🪙 เหรียญที่เฝ้าเทรด: {', '.join(SYMBOLS)}")

    while True:
        check_for_updates()
        
        print("\n" + "="*50)
        print(f"🕒 สแกนตลาดเวลา: {get_thai_time()}")
        
        for sym in SYMBOLS:
            process_symbol(sym)
            time.sleep(2) # กันโดนแบน API Rate Limit ระหว่างดึงเหรียญ
            
        print("="*50)
        time.sleep(60) # พัก 1 นาทีก่อนสแกนรอบถัดไป