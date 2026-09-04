import os
import time
import json
import ccxt
import pandas as pd
from datetime import datetime, timedelta

# ==========================================
# ⚙️ CONFIGURATION & ASSET SETTINGS
# ==========================================
SYMBOL = 'SOL/USDT'
TIMEFRAME = '15m'
HTF_TIMEFRAME = '1h'
INITIAL_BALANCE = 1000.0
TRADE_AMOUNT_USDT = 10.0

MEMORY_FILE = "agent_memory.json"
LOG_FILE = "trade_log.txt"

usdt_balance = INITIAL_BALANCE
in_position = False
entry_price = 0.0
position_size = 0.0
take_profit_target = 0.0
stop_loss_target = 0.0
is_breakeven_set = False
consecutive_losses = 0
cooldown_until = None
last_setup_info = {}

exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# ==========================================
# 🧠 AG 2.0 NATIVE LEARNING BRAIN (RL SYSTEM)
# ==========================================
DEFAULT_MEMORY = {
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "learned_params": {
        "min_volume_ratio": 1.30,      # เกณฑ์ Volume เริ่มต้น (ระบบจะปรับเอง)
        "risk_reward_ratio": 1.75,     # สัดส่วน TP ต่อ SL
        "base_confidence_weight": 50   # น้ำหนักคะแนนพื้นฐาน
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
                return data
        except Exception:
            pass
    return DEFAULT_MEMORY

def save_memory(mem):
    try:
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_trade(f"⚠️ บันทึก Memory ไม่สำเร็จ: {e}")

memory = load_memory()

def get_thai_time():
    return (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')

def log_trade(text):
    now = get_thai_time()
    log_msg = f"[{now}] {text}"
    print(log_msg, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_msg + "\n")

# ฟังก์ชันประเมินและคำนวณคะแนนด้วยโมเดล AG Native
def ag_evaluate_market(current_price, prev_high, avg_volume, current_volume, ema_200_1h):
    learned = memory["learned_params"]
    min_vol = learned.get("min_volume_ratio", 1.30)
    vol_ratio = (current_volume / avg_volume) if avg_volume > 0 else 1.0

    is_htf_bull = current_price > ema_200_1h
    is_breakout = current_price > prev_high
    vol_confirmed = vol_ratio >= min_vol

    # คำนวณคะแนนความมั่นใจ (Confidence Scoring) 0-100%
    score = learned.get("base_confidence_weight", 50)
    
    if is_htf_bull:
        score += 15
    else:
        score -= 30

    if is_breakout:
        score += 20
    else:
        score -= 20

    if vol_confirmed:
        score += min(int((vol_ratio - min_vol) * 15), 20)
    else:
        score -= 15

    score = max(5, min(99, score))

    decision = "BUY" if (is_htf_bull and is_breakout and vol_confirmed and score >= 75) else "WAIT"
    
    if decision == "BUY":
        reason = f"ยืนยัน BOS สมบูรณ์ | Vol แข็งแกร่ง {vol_ratio:.2f}x (เกณฑ์เรียนรู้: {min_vol:.2f}x)"
    elif not is_htf_bull:
        reason = f"ราคาอยู่ใต้ 1h EMA200 (ตลาดใหญ่เสี่ยงสูง) สั่ง WAIT"
    elif not is_breakout:
        reason = f"ราคายังไม่ทะลุ Swing High ${prev_high:.4f} สั่ง WAIT"
    else:
        reason = f"Volume {vol_ratio:.2f}x ยังไม่ถึงเกณฑ์ที่ระบบเรียนรู้ไว้ ({min_vol:.2f}x)"

    return {
        "decision": decision,
        "confidence": score,
        "suggested_tp_pct": 0.035,
        "suggested_sl_pct": 0.020,
        "setup_type": "Break of Structure (BOS)" if is_breakout else "Consolidation",
        "reason": reason,
        "vol_ratio": vol_ratio
    }

# ฟังก์ชัน Reinforcement Learning (เรียนรู้และปรับพารามิเตอร์อัตโนมัติ)
def ag_learn_from_trade(trade_type, entry_p, exit_p, pnl_pct):
    learned = memory["learned_params"]
    current_min_vol = learned.get("min_volume_ratio", 1.30)

    if trade_type == "WIN":
        # รางวัล: ปรับเกณฑ์ Vol ลงเล็กน้อยเพื่อไม่ให้พลาดโอกาสไม้ถัดไป
        new_min_vol = max(1.20, round(current_min_vol - 0.03, 2))
        learned["min_volume_ratio"] = new_min_vol
        lesson = f"โมเดลจำรูปแบบสำเร็จ: ยืนยัน Setup ชนะ (+{pnl_pct:.2f}%) ผ่อนเกณฑ์ Vol สู่ {new_min_vol}x"
    else:
        # บทลงโทษ: ปรับเกณฑ์ Vol ขึ้นเพื่อคัดกรองไม้หลอกให้โหดขึ้น
        new_min_vol = min(1.80, round(current_min_vol + 0.08, 2))
        learned["min_volume_ratio"] = new_min_vol
        lesson = f"โมเดลตรวจพบ False Breakout: ปรับเกณฑ์ Vol ให้เข้มงวดขึ้นเป็น {new_min_vol}x เพื่อป้องกันขาดทุนซ้ำ"

    memory["reflections"].append({
        "date": get_thai_time(),
        "type": trade_type,
        "pnl": f"{pnl_pct:+.2f}%",
        "lesson": lesson
    })
    save_memory(memory)
    return lesson

# ==========================================
# 📊 DASHBOARD DISPLAY
# ==========================================
def print_dashboard(current_price, prev_high, ema_200_1h, eval_result):
    now = get_thai_time()
    total = memory["total_trades"]
    wins = memory["wins"]
    losses = memory["losses"]
    win_rate = (wins / total * 100) if total > 0 else 0.0
    net_pnl = usdt_balance - INITIAL_BALANCE
    net_pnl_pct = (net_pnl / INITIAL_BALANCE) * 100
    learned_vol = memory["learned_params"].get("min_volume_ratio", 1.30)

    latest_lesson = memory["reflections"][-1]["lesson"] if memory["reflections"] else f"กำลังเฝ้าสังเกตการณ์ (เกณฑ์ Vol ที่เรียนรู้: {learned_vol}x)"

    if cooldown_until and datetime.utcnow() < cooldown_until:
        remaining_min = int((cooldown_until - datetime.utcnow()).total_seconds() / 60)
        pos_status = f"🛑 COOLDOWN (ตัดวงจรพักระบบ เหลืออีก {remaining_min} นาที)"
        pos_detail = "ระบบสั่งพักอัตโนมัติเพื่อป้องกันตลาดสะบัด"
    elif in_position:
        unrealized_pnl = ((current_price - entry_price) / entry_price) * 100
        be_status = " [🛡️ SL บังหน้าทุนแล้ว]" if is_breakeven_set else ""
        pos_status = f"LONG ({position_size:.4f} SOL){be_status}"
        pos_detail = f"Entry: ${entry_price:.4f} | PnL: {unrealized_pnl:+.2f}% | TP: ${take_profit_target:.2f} | SL: ${stop_loss_target:.2f}"
    else:
        pos_status = f"WAITING | AG Agent: {eval_result['decision']} (ความมั่นใจ {eval_result['confidence']}%)"
        pos_detail = f"{eval_result['reason']}"

    htf_trend = "🟢 UPTREND" if current_price > ema_200_1h else "🔴 DOWNTREND"

    dashboard = f"""
================== [ AG 2.0 AUTONOMOUS QUANT BRAIN ] ==================
🕒 เวลาปัจจุบัน (TH)  : {now}
📊 สินทรัพย์ที่เฝ้า    : {SYMBOL} (TF: {TIMEFRAME})
💵 ราคาตลาดล่าสุด      : ${current_price:.4f} | Swing High 20 แท่ง: ${prev_high:.4f}
📈 เทรนด์ใหญ่ 1h EMA200: ${ema_200_1h:.4f} ({htf_trend})
----------------------------------------------------------------------
📌 สถานะพอร์ต        : {pos_status}
🎯 การประเมินสถานะ    : {pos_detail}
🧠 AG บทเรียนล่าสุด   : {latest_lesson}
----------------------------------------------------------------------
💰 ยอดเงินคงเหลือ     : ${usdt_balance:.2f} USDT
📈 กำไรรวม (Net PnL)  : {net_pnl:+.4f} USDT ({net_pnl_pct:+.2f}%)
🏆 สถิติสะสม          : ทั้งหมด {total} ไม้ | ชนะ {wins} | แพ้ {losses} | Win Rate: {win_rate:.1f}%
======================================================================
"""
    print(dashboard, flush=True)

# ==========================================
# 🚀 MAIN LOOP
# ==========================================
log_trade(f"🚀 เริ่มรันระบบ AG 2.0 Autonomous Quant Brain ({SYMBOL}) บนเซิร์ฟเวอร์เรียบร้อย")

while True:
    try:
        # 1. ดึงแท่งเทียน 15m
        bars_15m = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=25)
        df_15m = pd.DataFrame(bars_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        current_price = float(df_15m['close'].iloc[-1])
        prev_high = float(df_15m['high'].iloc[-21:-1].max())
        avg_volume = float(df_15m['volume'].iloc[-21:-1].mean())
        current_volume = float(df_15m['volume'].iloc[-1])

        # 2. ดึงแท่งเทียน 1h คำนวณ EMA 200
        bars_1h = exchange.fetch_ohlcv(SYMBOL, timeframe=HTF_TIMEFRAME, limit=210)
        df_1h = pd.DataFrame(bars_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_1h['ema200'] = df_1h['close'].ewm(span=200, adjust=False).mean()
        ema_200_1h = float(df_1h['ema200'].iloc[-1])

        # 3. ให้ AG Brain ประเมินตลาด
        eval_result = ag_evaluate_market(current_price, prev_high, avg_volume, current_volume, ema_200_1h)
        print_dashboard(current_price, prev_high, ema_200_1h, eval_result)

        is_cooling_down = cooldown_until and datetime.utcnow() < cooldown_until

        # 4. เงื่อนไขเปิดออเดอร์
        if not in_position and not is_cooling_down:
            if eval_result["decision"] == "BUY":
                entry_price = current_price
                position_size = TRADE_AMOUNT_USDT / entry_price
                usdt_balance -= TRADE_AMOUNT_USDT
                in_position = True
                is_breakeven_set = False

                take_profit_target = entry_price * (1 + eval_result["suggested_tp_pct"])
                stop_loss_target = entry_price * (1 - eval_result["suggested_sl_pct"])
                last_setup_info = eval_result

                log_trade(f"🟢 [AG BUY] เปิดออเดอร์ ${entry_price:.4f} | TP: ${take_profit_target:.4f} | SL: ${stop_loss_target:.4f} (ความมั่นใจ {eval_result['confidence']}%)")

        # 5. จัดการออเดอร์และดึง SL บังทุน
        elif in_position:
            pnl_percent = (current_price - entry_price) / entry_price

            # กลไก Breakeven: กำไรแตะ +1.5% เลื่อน SL บังทุน
            if pnl_percent >= 0.015 and not is_breakeven_set:
                stop_loss_target = entry_price * 1.001
                is_breakeven_set = True
                log_trade(f"🛡️ [BREAKEVEN] กำไรแตะ +1.5% ขยับ SL บังหน้าทุนที่ ${stop_loss_target:.4f}")

            # ปิดทำกำไร (Take Profit)
            if current_price >= take_profit_target:
                gain = position_size * current_price
                usdt_balance += gain
                in_position = False
                consecutive_losses = 0
                memory["total_trades"] += 1
                memory["wins"] += 1

                lesson = ag_learn_from_trade("WIN", entry_price, current_price, pnl_percent * 100)
                log_trade(f"🎯 [TAKE PROFIT] กำไร +{pnl_percent*100:.2f}% ปิดที่ ${current_price:.4f} | {lesson}")

            # ตัดขาดทุน (Stop Loss)
            elif current_price <= stop_loss_target:
                loss = position_size * current_price
                usdt_balance += loss
                in_position = False
                memory["total_trades"] += 1

                if is_breakeven_set and pnl_percent >= 0:
                    log_trade(f"🛡️ [STOP LOSS - BREAKEVEN] ปิดเสมอตัวที่ ${current_price:.4f} (+{pnl_percent*100:.2f}%) ไม่เสียเงินต้น")
                else:
                    memory["losses"] += 1
                    consecutive_losses += 1

                    if consecutive_losses >= 2:
                        cooldown_until = datetime.utcnow() + timedelta(hours=4)
                        log_trade(f"🚨 [CIRCUIT BREAKER] ขาดทุนติดกัน 2 ครั้ง สั่งพักระบบ 4 ชั่วโมงอัตโนมัติ")

                    lesson = ag_learn_from_trade("LOSS", entry_price, current_price, pnl_percent * 100)
                    log_trade(f"🛑 [STOP LOSS] คัทลอสที่ ${current_price:.4f} ({pnl_percent*100:.2f}%) | {lesson}")

        time.sleep(60)

    except Exception as e:
        log_trade(f"⚠️ Error: {e}")
        time.sleep(15)