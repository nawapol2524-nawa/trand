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
# ⚙️ CONFIGURATION & ASSET SETTINGS
# ==========================================
SYMBOL = 'SOL/USDT'
TIMEFRAME = '15m'
HTF_TIMEFRAME = '1h'
TRADE_AMOUNT_USDT = 15.0 # ขั้นต่ำ Binance > $10

MEMORY_FILE = "agent_memory.json"
LOG_FILE = "trade_log.txt"

# เชื่อมต่อ Binance Testnet
exchange = ccxt.binance({
    'apiKey': os.getenv('TESTNET_API_KEY'),
    'secret': os.getenv('TESTNET_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})
exchange.set_sandbox_mode(True) # สำคัญ: เปิดโหมด Testnet

in_position = False
entry_price = 0.0
position_size = 0.0
take_profit_target = 0.0
stop_loss_target = 0.0
is_breakeven_set = False
consecutive_losses = 0
cooldown_until = None

try:
    bal = exchange.fetch_balance()
    start_usdt = bal['total'].get('USDT', 0.0)
    print(f"✅ เชื่อมต่อ Testnet สำเร็จ! ยอดเงินเริ่มต้น: {start_usdt:.2f} USDT", flush=True)
except Exception as e:
    print(f"❌ เชื่อมต่อ Testnet ไม่สำเร็จ: {e}", flush=True)
    exit()

# ==========================================
# 🧠 AG 2.0 NATIVE LEARNING BRAIN
# ==========================================
DEFAULT_MEMORY = {
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "learned_params": {
        "min_volume_ratio": 1.30,
        "min_adx": 18.0,
        "risk_reward_ratio": 1.75,
        "base_confidence_weight": 50
    },
    "reflections": []
}

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "learned_params" not in data:
                    data["learned_params"] = DEFAULT_MEMORY["learned_params"]
                if "min_adx" not in data["learned_params"]:
                    data["learned_params"]["min_adx"] = 18.0
                return data
        except Exception:
            pass
    return DEFAULT_MEMORY

def save_memory(mem):
    try:
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

memory = load_memory()

last_update_check = 0
def check_for_updates():
    global last_update_check
    now = time.time()
    if now - last_update_check < 300: # เช็คทุกๆ 5 นาที ลดการใช้งานเครือข่าย
        return
    last_update_check = now
    
    try:
        subprocess.run(["git", "fetch"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        status = subprocess.run(["git", "status", "-uno"], capture_output=True, text=True)
        if "Your branch is behind" in status.stdout:
            log_trade("🔄 [AUTO-PATCH] พบอัปเดตใหม่บน GitHub! กำลังดาวน์โหลดและรีสตาร์ทตัวเอง...")
            subprocess.run(["git", "pull"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(2) # รอไฟล์บันทึกเสร็จ
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        pass # ถ้ามีปัญหาเครือข่าย ปล่อยผ่านไปไม่ให้บอทหยุดทำงาน

def get_thai_time():
    return (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')

def log_trade(text):
    now = get_thai_time()
    log_msg = f"[{now}] {text}"
    print(log_msg, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_msg + "\n")

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

    return df

def ag_evaluate_market(current_price, prev_high, avg_volume, current_volume, ema_200_1h, rsi, adx, atr, wyckoff_valid):
    learned = memory["learned_params"]
    min_vol = learned.get("min_volume_ratio", 1.30)
    # [AG Learning Adjust] ยอมรับสภาวะ Sideway มากขึ้น ลด ADX ลงมา
    min_adx = learned.get("min_adx", 18.0)
    min_adx = min(min_adx, 14.0) # ลดกำแพง ADX ให้เทรดง่ายขึ้น
    vol_ratio = (current_volume / avg_volume) if avg_volume > 0 else 1.0

    is_htf_bull = current_price > ema_200_1h
    is_breakout = current_price > prev_high
    vol_confirmed = vol_ratio >= min_vol
    # [AG Learning Adjust] ขยายกรอบโมเมนตัม
    rsi_valid = 50 <= rsi <= 75
    adx_valid = adx >= min_adx

    score = learned.get("base_confidence_weight", 50)
    if is_htf_bull: score += 10
    else: score -= 20
    if is_breakout: score += 15
    if vol_confirmed: score += 10
    if rsi_valid: score += 10
    if adx_valid: score += 10
    if wyckoff_valid: score += 10

    score = max(5, min(99, score))
    decision = "BUY" if (is_htf_bull and is_breakout and vol_confirmed and rsi_valid and adx_valid and wyckoff_valid and score >= 75) else "WAIT"
    
    if decision == "BUY": reason = f"ยืนยันครบ 5 ชั้น | RSI:{rsi:.1f} ADX:{adx:.1f} Vol:{vol_ratio:.2f}x"
    elif not is_htf_bull: reason = f"ราคาใต้ 1h EMA200 (ตลาดเสี่ยง)"
    elif not is_breakout: reason = f"ยังไม่ทะลุ Swing High ${prev_high:.4f}"
    elif not wyckoff_valid: reason = f"เทียนทิ้งไส้บนยาว (Wyckoff Fail)"
    elif not rsi_valid: reason = f"RSI ไม่อยู่ในโซน 52-70 (RSI: {rsi:.1f})"
    elif not adx_valid: reason = f"ADX ต่ำกว่าเกณฑ์ (ADX: {adx:.1f} < {min_adx:.1f})"
    else: reason = f"Volume {vol_ratio:.2f}x < เกณฑ์ {min_vol:.2f}x"

    return {
        "decision": decision,
        "confidence": score,
        "suggested_tp_price": current_price + (2.5 * atr),
        "suggested_sl_price": current_price - (1.5 * atr),
        "reason": reason,
        "vol_ratio": vol_ratio,
        "rsi": rsi, "adx": adx, "atr": atr
    }

def ag_learn_from_trade(trade_type, pnl_pct):
    learned = memory["learned_params"]
    current_min_vol = learned.get("min_volume_ratio", 1.30)
    current_min_adx = learned.get("min_adx", 18.0)

    if trade_type == "WIN":
        new_min_vol = max(1.20, round(current_min_vol - 0.03, 2))
        new_min_adx = max(15.0, round(current_min_adx - 0.5, 1))
        lesson = f"Win (+{pnl_pct:.2f}%): ลดเกณฑ์ Vol->{new_min_vol}x, ADX->{new_min_adx}"
    else:
        new_min_vol = min(1.80, round(current_min_vol + 0.08, 2))
        new_min_adx = min(30.0, round(current_min_adx + 1.0, 1))
        lesson = f"Loss (False Breakout): เพิ่มเกณฑ์ Vol->{new_min_vol}x, ADX->{new_min_adx}"

    learned["min_volume_ratio"] = new_min_vol
    learned["min_adx"] = new_min_adx
    memory["reflections"].append({
        "date": get_thai_time(),
        "type": trade_type,
        "pnl": f"{pnl_pct:+.2f}%",
        "lesson": lesson
    })
    save_memory(memory)
    return lesson

def print_dashboard(current_price, prev_high, ema_200_1h, eval_result):
    now = get_thai_time()
    try:
        bal = exchange.fetch_balance()
        current_usdt = bal['total'].get('USDT', 0.0)
    except:
        current_usdt = 0.0

    total = memory["total_trades"]
    wins = memory["wins"]
    losses = memory["losses"]
    win_rate = (wins / total * 100) if total > 0 else 0.0
    
    learned = memory["learned_params"]
    learned_vol = learned.get("min_volume_ratio", 1.30)
    learned_adx = learned.get("min_adx", 18.0)
    latest_lesson = memory["reflections"][-1]["lesson"] if memory["reflections"] else f"กำลังเฝ้าสังเกตการณ์"

    if cooldown_until and datetime.utcnow() < cooldown_until:
        remaining_min = int((cooldown_until - datetime.utcnow()).total_seconds() / 60)
        pos_status = f"🛑 COOLDOWN ({remaining_min} นาที)"
        pos_detail = "ระบบสั่งพักอัตโนมัติ"
    elif in_position:
        unrealized_pnl = ((current_price - entry_price) / entry_price) * 100
        be_status = " [🛡️ SL บังหน้าทุนแล้ว]" if is_breakeven_set else ""
        pos_status = f"🟢 LIVE LONG ({position_size:.2f} SOL){be_status}"
        pos_detail = f"Entry: ${entry_price:.4f} | PnL: {unrealized_pnl:+.2f}% | TP: ${take_profit_target:.2f} | SL: ${stop_loss_target:.2f}"
    else:
        pos_status = f"WAITING | AG Agent: {eval_result['decision']}"
        pos_detail = f"{eval_result['reason']}"

    dashboard = f"""
================== [ AG 2.0 TESTNET LIVE TRADING ] ==================
🕒 เวลาปัจจุบัน (TH)  : {now}
📊 สินทรัพย์ที่เฝ้า    : {SYMBOL} (TF: {TIMEFRAME})
💵 ราคาตลาดล่าสุด      : ${current_price:.4f} | Swing High: ${prev_high:.4f}
📈 เทรนด์ใหญ่ 1h EMA200: ${ema_200_1h:.4f}
⚡ โมเมนตัม & เทรนด์  : RSI(14)={eval_result['rsi']:.1f} | ADX(14)={eval_result['adx']:.1f}
🧠 เกณฑ์ AI ปัจจุบัน    : Min Vol={learned_vol:.2f}x | Min ADX={learned_adx:.1f}
----------------------------------------------------------------------
📌 สถานะพอร์ต        : {pos_status}
🎯 การประเมินสถานะ    : {pos_detail}
🧠 AG บทเรียนล่าสุด   : {latest_lesson}
----------------------------------------------------------------------
💰 ยอดเงิน Testnet    : {current_usdt:.2f} USDT
🏆 สถิติสะสม          : ทั้งหมด {total} ไม้ | ชนะ {wins} | แพ้ {losses} | Win Rate: {win_rate:.1f}%
==========================================================================
"""
    print(dashboard, flush=True)

# ==========================================
# 🚀 MAIN LOOP (TESTNET EXECUTION)
# ==========================================
if __name__ == '__main__':
    log_trade(f"🚀 เริ่มรันระบบ AG 2.0 บน Binance Testnet ({SYMBOL})")

    while True:
        try:
            check_for_updates()
            
            bars_15m = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=100)
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
            
            # [AG Learning Adjust] ลดการมองย้อนหลังเหลือ 10 แท่งเพื่อให้จับรอบสั้นขึ้น
            prev_high = float(df_15m['high'].iloc[-11:-1].max())
            avg_volume = float(df_15m['volume'].iloc[-11:-1].mean())
            current_volume = float(current_row['volume'])

            bars_1h = exchange.fetch_ohlcv(SYMBOL, timeframe=HTF_TIMEFRAME, limit=210)
            df_1h = pd.DataFrame(bars_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_1h['ema200'] = df_1h['close'].ewm(span=200, adjust=False).mean()
            ema_200_1h = float(df_1h['ema200'].iloc[-1])

            eval_result = ag_evaluate_market(current_price, prev_high, avg_volume, current_volume, ema_200_1h, rsi_14, adx_14, atr_14, wyckoff_valid)
            print_dashboard(current_price, prev_high, ema_200_1h, eval_result)

            is_cooling_down = cooldown_until and datetime.utcnow() < cooldown_until

            # 4. เงื่อนไขเปิดออเดอร์บน Testnet
            if not in_position and not is_cooling_down:
                if eval_result["decision"] == "BUY":
                    ticker = exchange.fetch_ticker(SYMBOL)
                    real_entry = float(ticker['last'])
                    size = round(TRADE_AMOUNT_USDT / real_entry, 2)
                    
                    try:
                        # ยิงคำสั่งซื้อ Market Order ไปยัง Binance Testnet
                        order = exchange.create_market_buy_order(SYMBOL, size)
                        entry_price = float(order.get('average', real_entry))
                        position_size = size
                        in_position = True
                        is_breakeven_set = False

                        take_profit_target = eval_result["suggested_tp_price"]
                        stop_loss_target = eval_result["suggested_sl_price"]

                        log_trade(f"🟢 [TESTNET BUY SUCCESS] ซื้อ {position_size} SOL @ ${entry_price:.4f} | TP: ${take_profit_target:.4f} | SL: ${stop_loss_target:.4f}")
                    except Exception as e:
                        log_trade(f"❌ [TESTNET BUY FAILED] {e}")

            # 5. จัดการออเดอร์ Trailing Stop / TP / SL บน Testnet
            elif in_position:
                pnl_percent = (current_price - entry_price) / entry_price

                # Trailing Stop
                if pnl_percent >= 0.015:
                    trailing_sl = current_price * 0.99
                    if trailing_sl > stop_loss_target:
                        stop_loss_target = trailing_sl
                        is_breakeven_set = True
                        log_trade(f"🛡️ [TRAILING STOP] ขยับ SL ตามกำไรไปที่ ${stop_loss_target:.4f}")

                # ปิดทำกำไร (Take Profit)
                if current_price >= take_profit_target:
                    try:
                        order = exchange.create_market_sell_order(SYMBOL, position_size)
                        exit_price = float(order.get('average', current_price))
                        real_pnl_pct = (exit_price - entry_price) / entry_price
                        
                        in_position = False
                        consecutive_losses = 0
                        memory["total_trades"] += 1
                        memory["wins"] += 1

                        lesson = ag_learn_from_trade("WIN", real_pnl_pct * 100)
                        log_trade(f"🎯 [TESTNET TP SUCCESS] ขายปิดกำไรที่ ${exit_price:.4f} (+{real_pnl_pct*100:.2f}%) | {lesson}")
                    except Exception as e:
                        log_trade(f"❌ [TESTNET TP FAILED] {e}")

                # ตัดขาดทุน (Stop Loss)
                elif current_price <= stop_loss_target:
                    try:
                        order = exchange.create_market_sell_order(SYMBOL, position_size)
                        exit_price = float(order.get('average', current_price))
                        real_pnl_pct = (exit_price - entry_price) / entry_price
                        
                        in_position = False
                        memory["total_trades"] += 1

                        if is_breakeven_set and real_pnl_pct >= 0:
                            log_trade(f"🛡️ [TESTNET SL-BREAKEVEN] ปิดเสมอตัวที่ ${exit_price:.4f} (+{real_pnl_pct*100:.2f}%) ไม่เสียต้นทุน")
                        else:
                            memory["losses"] += 1
                            consecutive_losses += 1

                            if consecutive_losses >= 2:
                                cooldown_until = datetime.utcnow() + timedelta(hours=4)
                                log_trade(f"🚨 [CIRCUIT BREAKER] ขาดทุนติดกัน 2 ครั้ง พักระบบ 4 ชั่วโมง")

                            lesson = ag_learn_from_trade("LOSS", real_pnl_pct * 100)
                            log_trade(f"🛑 [TESTNET SL SUCCESS] คัทลอสที่ ${exit_price:.4f} ({real_pnl_pct*100:.2f}%) | {lesson}")
                    except Exception as e:
                        log_trade(f"❌ [TESTNET SL FAILED] {e}")

            time.sleep(60)

        except Exception as e:
            log_trade(f"⚠️ Error หลัก: {e}")
            time.sleep(15)