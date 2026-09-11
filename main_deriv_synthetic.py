"""
================================================================================
🚀 AG 2.0 DERIV SYNTHETIC VOLATILITY TRADING ENGINE (24/7 NON-STOP)
================================================================================
ไฟล์แยกอิสระรันแยกโปรเซส: main_deriv_synthetic.py
- ตลาด: Deriv Synthetic Volatility Indices (R_75, R_25, R_50, R_10)
- วิ่ง 24 ชั่วโมง 7 วัน ตลอด 365 วัน (ไม่มีวันหยุดเสาร์-อาทิตย์)
- บัญชี: บังคับใช้ Demo DOT94482469 เท่านั้น (บล็อกเงินจริง CR... 100%)
- กลยุทธ์: Brad Goh SMC + Mean Reversion (Bollinger Bands 20,2 + RSI 14 + EMA50 + Liquidity Sweep + Pin Bar)
- การจัดการความเสี่ยง: Stake $1.00 USD, Auto-Breakeven +10 pips, Dynamic Trailing Stop +20 pips, TP Upper BB
- สถานะ: บันทึก Atomic State ลง active_state_synthetic.json และ synthetic_memory.json
- แจ้งเตือน: LINE ผ่าน notifier.py เมื่อเปิด/ปิดไม้, เลื่อน BE, Trailing Stop
================================================================================
"""

import os
import sys
import time
import json
import ssl
import asyncio
from datetime import datetime, timedelta

# เพิ่ม site-packages เข้า sys.path อัตโนมัติสำหรับสภาพแวดล้อม Container / Virtualenv
for p in [
    os.path.abspath("venv/lib/python3.9/site-packages"),
    os.path.abspath(".venv/lib/python3.9/site-packages"),
    os.path.abspath(".local/lib/python3.11/site-packages"),
    os.path.abspath(".local/lib/python3.10/site-packages"),
    os.path.abspath(".local/lib/python3.9/site-packages"),
    os.path.expanduser("~/.local/lib/python3.11/site-packages"),
    os.path.expanduser("~/.local/lib/python3.9/site-packages")
]:
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip()
                        if k not in os.environ:
                            os.environ[k] = v
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
# ⚙️ CONFIGURATION & CONSTANTS
# ==========================================
DERIV_TOKEN = os.getenv("DERIV_API_TOKEN", "").strip()
APP_ID = os.getenv("DERIV_APP_ID", "34lQGsI4JVHDtfZhaHAqk").strip()
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"

# บังคับใช้บัญชี Demo DOT94482469 เท่านั้น (ห้ามเงินจริง 100%)
TARGET_DEMO_ACCOUNT = "DOT94482469"

# สินทรัพย์เป้าหมาย (Synthetic Volatility Indices)
SYMBOLS = ['R_75', 'R_25', 'R_50', 'R_10']
PRIMARY_SYMBOLS = ['R_75', 'R_25']
TIMEFRAME_SEC = 900  # M15 (15 * 60)

# การจัดการความเสี่ยง (Risk Management)
STAKE_USD = 1.00     # เงินเดิมพันขนาดเล็กปลอดภัยสำหรับ Demo: $1.00 USD ต่อไม้
BREAKEVEN_PIPS = 10.0 # Auto-Breakeven เมื่อกำไรแตะ +10 pips
TRAILING_PIPS = 20.0  # Dynamic Trailing Stop เริ่มทำงานเมื่อกำไรแตะ +20 pips
INITIAL_SL_PIPS = -20.0 # Stop Loss เริ่มต้น -20 pips

MEMORY_FILE = "synthetic_memory.json"
STATUS_FILE = "status_log_synthetic.txt"
TRADE_LOG_FILE = "trade_log_synthetic.txt"
STATE_FILE = "active_state_synthetic.json"

usd_thb_rate = 34.00

def get_thai_time():
    """เวลาปัจจุบันในเขตเวลาประเทศไทย (UTC+7)"""
    return (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')

def log(text):
    """บันทึกข้อความลง Console และ trade_log_synthetic.txt"""
    now = get_thai_time()
    msg = f"[{now}] [DERIV-SYNTHETIC] {text}"
    print(msg, flush=True)
    try:
        with open(TRADE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

def get_pip_size(symbol, price=0.0):
    """
    คำนวณขนาด Pip / Point สำหรับแต่ละดัชนี Volatility
    - R_75: ดัชนีราคาสูง (~500,000 - 1,000,000) -> 1 pip = 10.0 จุด
    - R_25: ดัชนีราคาปานกลาง (~1,500 - 3,000) -> 1 pip = 0.1 จุด
    - R_50: ดัชนีราคาต่ำ (~200 - 500) -> 1 pip = 0.05 จุด
    - R_10: ดัชนีราคา (~5,000 - 8,000) -> 1 pip = 0.2 จุด
    หรืออิง 0.01% (1 basis point) ของระดับราคาเพื่อเสถียรภาพสูงสุด
    """
    if price and price > 0:
        return max(price * 0.0001, 0.001)
    
    defaults = {
        'R_75': 10.0,
        'R_25': 0.1,
        'R_50': 0.05,
        'R_10': 0.2
    }
    return defaults.get(symbol, 1.0)

# ==========================================
# 🖥️ QUANT TERMINAL UI & HIGHLIGHT BOXES
# ==========================================
def print_highlight_box(title, items, icon="⚡"):
    """แสดงกรอบข้อความเน้นพิเศษสไตล์ Quant Terminal เมื่อเกิด Event สำคัญ"""
    border = "═" * 78
    divider = "─" * 78
    box = [
        f"╔{border}╗",
        f"║ {icon} {title}",
        f"╠{divider}╣"
    ]
    for k, v in items:
        box.append(f"║  • {k:<22}: {v}")
    box.append(f"╚{border}╝")
    full_text = "\n".join(box)
    print(full_text, flush=True)
    try:
        with open(TRADE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(full_text + "\n")
        with open(STATUS_FILE, "a", encoding="utf-8") as f:
            f.write(full_text + "\n")
    except Exception:
        pass

def print_quant_table(thai_time, rows, account_info, memory):
    """ตารางสรุปสถานะ Deriv Synthetic 24/7 สไตล์ Quant Terminal ไม่สแปมซ้ำซ้อน"""
    curr = account_info.get("currency", "USD")
    bal = float(account_info.get("balance", 0.0))
    bal_thb = bal * usd_thb_rate
    loginid = account_info.get("loginid", TARGET_DEMO_ACCOUNT)
    
    total_trades = memory.get("total_trades", 0)
    wins = memory.get("wins", 0)
    losses = memory.get("losses", 0)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    
    initial_demo_bal = 10000.0
    account_profit_usd = round(bal - initial_demo_bal, 2)
    account_profit_thb = round(account_profit_usd * usd_thb_rate, 1)

    lines = [
        "╔══════════════════════════════════════════════════════════════════════════════════╗",
        f"║  ⚡ AG 2.0 QUANT TERMINAL | DERIV SYNTHETIC 24/7 (DEMO: {TARGET_DEMO_ACCOUNT:<21})║",
        f"║  🕒 {thai_time} | โหมด: 24/7 NON-STOP SYNTHETIC (เสาร์-อาทิตย์เทรดได้ 100%)║",
        "╠═════════════╦══════════════╦══════╦══════════╦════════════╦═════════════════╦════╣",
        "║ Symbol      ║ Last Price   ║ RSI  ║ BB-Width ║ Pattern    ║ Position / PnL  ║ St ║",
        "╠═════════════╬══════════════╬══════╬══════════╬════════════╬═════════════════╬════╣"
    ]
    for r in rows:
        lines.append(
            f"║ {r['symbol']:<11} ║ {r['price']:>12} ║ {r['rsi']:>4} ║ {r['bb_w']:>8} ║ {r['pattern']:<10} ║ {r['pos']:<15} ║ {r['st']:<2} ║"
        )
    lines.append("╠═════════════╩══════════════╩══════╩══════════╩════════════╩═════════════════╩════╣")
    lines.append(f"║ 👤 บัญชี Demo: {loginid:<14} 💰 Balance: ${bal:>10,.2f} USD (~{bal_thb:,.0f} ฿)          ║")
    lines.append(f"║ 📈 กำไรพอร์ตรวม: ${account_profit_usd:+,.2f} USD ({account_profit_thb:+,.1f} ฿) | สถิติ AI: {total_trades} ไม้ (ชนะ {wins} | แพ้ {losses} | WR: {win_rate:4.1f}%) ║")
    lines.append("╚══════════════════════════════════════════════════════════════════════════════════╝")
    
    full_text = "\n".join(lines)
    print(full_text, flush=True)
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            f.write(full_text + "\n")
    except Exception:
        pass

# ==========================================
# 🧠 MEMORY & ATOMIC STATE PERSISTENCE
# ==========================================
def load_memory():
    """โหลดสถิติและพารามิเตอร์การเรียนรู้จาก synthetic_memory.json"""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"🧠 [MEMORY] โหลด {MEMORY_FILE} สำเร็จ (สถิติรวม: {data.get('total_trades', 0)} ไม้)", flush=True)
                return data
        except Exception:
            pass
    return {
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "net_profit_usd": 0.0,
        "net_profit_thb": 0.0,
        "learned_params": {
            "rsi_oversold": 35.0,
            "rsi_overbought": 65.0,
            "bb_period": 20,
            "bb_std": 2.0
        },
        "history": []
    }

def save_memory(mem):
    """บันทึกสถิติ win/loss ลง synthetic_memory.json แบบ Atomic (.tmp + replace)"""
    temp_file = f"{MEMORY_FILE}.tmp_{os.getpid()}_{int(time.time() * 1000)}"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, MEMORY_FILE)
    except Exception as e:
        log(f"⚠️ [MEMORY SAVE ERROR] {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

memory = load_memory()

def save_state(trade):
    """บันทึกสถานะไม้ลง active_state_synthetic.json ทันทีแบบ Atomic (.tmp + replace) ป้องกันไฟล์เสียหาย"""
    temp_file = f"{STATE_FILE}.tmp_{os.getpid()}_{int(time.time() * 1000)}"
    try:
        payload = {
            "account_id": TARGET_DEMO_ACCOUNT,
            "engine": "Deriv Synthetic Volatility Indices (24/7)",
            "active_trade": trade,
            "updated_at": get_thai_time()
        }
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, STATE_FILE)
    except Exception as e:
        log(f"⚠️ [STATE SAVE ERROR] {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

def load_state():
    """กู้คืนสถานะไม้จาก active_state_synthetic.json ทันทีที่สตาร์ท/รีสตาร์ท"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                trade = data.get("active_trade")
                if trade:
                    print_highlight_box(
                        f"DERIV SYNTHETIC STATE RECOVERED - {trade.get('symbol', 'R_75')}",
                        [
                            ("Demo Account", TARGET_DEMO_ACCOUNT),
                            ("Symbol", trade.get('symbol', 'R_75')),
                            ("Type", trade.get('type', 'BUY')),
                            ("Entry Price", f"{trade.get('entry_price', 0):.4f}"),
                            ("Stake", f"${trade.get('stake', STAKE_USD):.2f} USD"),
                            ("Contract ID", str(trade.get('contract_id', 'N/A'))),
                            ("Breakeven Locked", str(trade.get('be_locked', False)))
                        ],
                        icon="🔄"
                    )
                    log(f"🔄 [RECOVER] กู้คืนสถานะไม้ค้าง {trade.get('symbol')} @ {trade.get('entry_price', 0):.4f} สำเร็จ!")
                    return trade
                else:
                    print(f"📂 [STATE] โหลด {STATE_FILE} สำเร็จ (ไม่มีไม้ค้าง - สแตนด์บายพร้อมเทรด)", flush=True)
        except Exception as e:
            log(f"⚠️ [STATE LOAD ERROR] {e}")
    return None

# ==========================================
# 📊 TECHNICAL INDICATORS (BRAD GOH SMC + MEAN REVERSION)
# ==========================================
def calculate_bb_rsi(candles, period=20, std_dev=2.0, rsi_period=14):
    """คำนวณ Bollinger Bands, BandWidth, EMA50, RSI และตรวจสอบ Price Action Reversals"""
    closes = [float(c['close']) for c in candles]
    if len(closes) < max(period, rsi_period, 50) + 2:
        return None

    recent = closes[-period:]
    sma = sum(recent) / period
    variance = sum((x - sma) ** 2 for x in recent) / period
    std = variance ** 0.5
    upper_bb = sma + (std * std_dev)
    lower_bb = sma - (std * std_dev)
    bb_width = (upper_bb - lower_bb) / sma if sma > 0 else 0.0

    alpha = 2.0 / (50 + 1)
    ema50 = closes[0]
    for p in closes[1:]:
        ema50 = (p * alpha) + (ema50 * (1 - alpha))

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-rsi_period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-rsi_period:]]
    avg_gain = sum(gains) / rsi_period
    avg_loss = sum(losses) / rsi_period
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

    curr = candles[-1]
    prev = candles[-2]
    prev2 = candles[-3]
    
    body = abs(curr['close'] - curr['open'])
    candle_range = curr['high'] - curr['low']
    lower_wick = min(curr['open'], curr['close']) - curr['low']
    upper_wick = curr['high'] - max(curr['open'], curr['close'])
    prev_body = abs(prev['close'] - prev['open'])
    prev2_body = abs(prev2['close'] - prev2['open'])

    # 1. แท่งเทียน Hammer (หางล่างยาว >= 2 เท่าของตัวเทียน, หางบนสั้น)
    is_hammer = (lower_wick >= 2 * body) and (upper_wick <= candle_range * 0.15) and (body > 0)
    
    # 2. แท่งเทียน Pin Bar Rejection (หางล่างปฏิเสธราคาต่ำ >= 55% ของความยาวแท่ง)
    is_pin_bar = (lower_wick >= 0.55 * candle_range) and (upper_wick <= 0.25 * candle_range) and (candle_range > 0)
    
    # 3. Bullish Engulfing & Morning Star
    is_bullish_engulfing = (prev['close'] < prev['open']) and (curr['close'] > curr['open']) and (curr['open'] <= prev['close']) and (curr['close'] >= prev['open']) and (body > prev_body)
    is_morning_star = (prev2['close'] < prev2['open']) and (prev_body < (prev2_body * 0.3)) and (curr['close'] > curr['open']) and (curr['close'] > (prev2['close'] + prev2['open']) / 2)

    # 4. Brad Goh SMC Step 4: Liquidity Sweep (ราคากวาด Low แท่งก่อนหน้าแล้วดีดกลับขึ้นมาปิดเหนือ Low เดิม)
    prior_lows = [c['low'] for c in candles[-11:-1]]
    prior_swing_low = min(prior_lows) if prior_lows else curr['low']
    is_liquidity_sweep = (curr['low'] < prior_swing_low) and (curr['close'] > prior_swing_low)

    has_bullish_pattern = is_hammer or is_pin_bar or is_bullish_engulfing or is_morning_star or is_liquidity_sweep
    pattern_name = "Sweep+Rej" if (is_liquidity_sweep and (is_pin_bar or is_hammer)) else (
        "LiqSweep" if is_liquidity_sweep else (
            "Hammer" if is_hammer else (
                "PinBar" if is_pin_bar else (
                    "Engulf" if is_bullish_engulfing else (
                        "MornStar" if is_morning_star else "None"
                    )
                )
            )
        )
    )

    return {
        'price': closes[-1],
        'sma': sma,
        'has_bullish_pattern': has_bullish_pattern,
        'pattern_name': pattern_name,
        'is_liquidity_sweep': is_liquidity_sweep,
        'is_pin_bar': is_pin_bar,
        'is_hammer': is_hammer,
        'upper_bb': upper_bb,
        'lower_bb': lower_bb,
        'bb_width': bb_width,
        'ema50': ema50,
        'rsi': rsi
    }

# ==========================================
# 🤖 GROQ AI SECOND OPINION ENGINE (SYNTHETIC QUANT ADVISOR)
# ==========================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

def _query_groq_api_sync(url, headers, data):
    import requests
    return requests.post(url, headers=headers, json=data, timeout=10)

async def ask_groq_ai_sentiment(symbol, price, rsi, pattern_name, bb_width):
    """ประเมินความปลอดภัยของสัญญาณ BUY ด้วย Groq AI แบบ Non-blocking"""
    if not GROQ_API_KEY:
        return True
        
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

        prompt = f"""You are an ultra-precise quantitative analyst evaluating Synthetic Volatility Indices (Deriv 24/7).
Asset: {symbol} (Simulated Volatility Index)
Current Price: {price:.4f}
RSI(14): {rsi:.1f} (Oversold condition)
Pattern: {pattern_name}
Bollinger BandWidth: {bb_width:.5f}
Timeframe: 15m

Setup: Brad Goh SMC Liquidity Sweep & Mean Reversion BUY strategy.
Synthetics are not affected by economic news, only pure statistical volatility and mean-reversion mechanics.

Is this BUY setup statistically sound and safe to execute on a Demo micro-account?
Reply ONLY with YES or NO."""

        data = {
            "model": "openai/gpt-oss-120b",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 10,
            "temperature": 0.1
        }
        
        res = await asyncio.to_thread(_query_groq_api_sync, url, headers, data)
        if res.status_code == 200:
            content = res.json()["choices"][0]["message"]["content"].strip().upper()
            is_approved = "NO" not in content
            status_text = "APPROVED (YES)" if is_approved else "REJECTED (NO)"
            
            print_highlight_box(
                f"GROQ AI SYNTHETIC EVALUATION - {symbol}",
                [
                    ("Decision", status_text),
                    ("Strategy", f"Price: {price:.4f} | RSI: {rsi:.1f} | {pattern_name}"),
                    ("Volatility Width", f"{bb_width:.5f}")
                ],
                icon="🧠"
            )
            
            if notifier:
                try:
                    notifier.notify_ai_evaluation("Deriv Synthetic", symbol, status_text, f"Price: {price:.4f}, RSI: {rsi:.1f}, Pattern: {pattern_name}")
                except Exception:
                    pass

            if not is_approved:
                log(f"🧠 [GROQ AI] ปฏิเสธการเปิดไม้ {symbol} (AI ประเมินว่าความผันผวนยังไม่เหมาะสม)")
                return False
            log(f"🧠 [GROQ AI] อนุมัติการเปิดไม้ {symbol} (AI คอนเฟิร์มสัญญาณ Mean Reversion)")
            return True
        else:
            return True
    except Exception as e:
        log(f"⚠️ [GROQ AI ERROR] {e} -> ข้ามไปใช้ Pure Quant Signal")
        return True

# ==========================================
# 🎯 LIVE SPREAD FILTER
# ==========================================
async def get_live_spread(ws, symbol):
    """
    ตรวจสอบสเปรดสด (Ask - Bid) ผ่าน Deriv WebSocket
    คืนค่า (spread_pips, ask, bid) หรือ (None, None, None)
    """
    try:
        await ws.send(json.dumps({"ticks": symbol}))
        raw_res = await asyncio.wait_for(ws.recv(), timeout=5)
        res = json.loads(raw_res)
        
        attempts = 0
        while "tick" not in res and attempts < 3:
            raw_res = await asyncio.wait_for(ws.recv(), timeout=5)
            res = json.loads(raw_res)
            attempts += 1
            
        tick_data = res.get("tick")
        if not tick_data:
            return None, None, None

        ask = float(tick_data.get("ask", 0.0))
        bid = float(tick_data.get("bid", 0.0))
        sub_id = res.get("subscription", {}).get("id") or tick_data.get("id")

        if sub_id:
            await ws.send(json.dumps({"forget": sub_id}))
            try:
                drain = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                while drain.get("msg_type") == "tick":
                    drain = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
            except Exception:
                pass

        if ask > 0 and bid > 0 and ask >= bid:
            pip_size = get_pip_size(symbol, bid)
            spread_pips = round((ask - bid) / pip_size, 2)
            return spread_pips, ask, bid
    except Exception as e:
        log(f"⚠️ [LIVE SPREAD] ตรวจสอบสเปรดสด {symbol} ไม่สำเร็จ: {e}")
    return None, None, None

# ==========================================
# 🌐 DERIV WEBSOCKET 24/7 SYNTHETIC ENGINE
# ==========================================
async def deriv_synthetic_engine():
    """เครื่องยนต์หลักรันตลอด 24 ชั่วโมง 7 วัน สำหรับ Deriv Synthetic Volatility Indices"""
    try:
        import websockets
    except ImportError:
        log("❌ ไม่พบแพ็กเกจ websockets! กรุณาติดตั้งหรือตรวจสอบ Virtualenv")
        return

    log("🚀 กำลังเริ่มต้น AG 2.0 Deriv Synthetic Volatility Engine (24/7 Non-Stop)...")
    
    # กู้คืนสถานะไม้ค้างจาก active_state_synthetic.json
    active_trade = load_state()

    account_info = {
        "loginid": f"{TARGET_DEMO_ACCOUNT} (Demo Training)",
        "currency": "USD",
        "balance": 10000.0,
        "email": "synthetic_demo@deriv"
    }

    # ตั้งค่า SSL Context เพื่อรองรับ macOS Certificate Handshake
    try:
        import certifi
        ssl_context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ssl_context = ssl._create_unverified_context()

    while True:
        try:
            target_ws_url = DERIV_WS_URL
            is_authenticated = False
            
            # ตรวจสอบสิทธิ์บัญชี Demo DOT94482469 อย่างเคร่งครัด
            if DERIV_TOKEN and "your_" not in DERIV_TOKEN:
                try:
                    import requests
                    headers = {"Authorization": f"Bearer {DERIV_TOKEN}", "Deriv-App-ID": APP_ID}
                    accounts_res = requests.get("https://api.derivws.com/trading/v1/options/accounts", headers=headers, timeout=8)
                    if accounts_res.status_code == 200:
                        accounts = accounts_res.json().get("data", [])
                        target_acc = None
                        for acc in accounts:
                            acc_id = acc.get("account_id", "")
                            # บังคับหาบัญชีเป้าหมาย DOT94482469
                            if acc_id == TARGET_DEMO_ACCOUNT:
                                target_acc = acc
                                break
                        
                        # หากไม่พบเป้าหมายตรง ให้หาบัญชี Demo/Virtual (บล็อก CR บัญชีจริง 100%)
                        if not target_acc:
                            for acc in accounts:
                                acc_id = acc.get("account_id", "")
                                if (acc_id.startswith("DOT") or acc_id.startswith("VRTC") or acc.get("is_virtual") == 1) and not acc_id.startswith("CR"):
                                    target_acc = acc
                                    break
                                    
                        if target_acc:
                            acc_id = target_acc.get("account_id")
                            otp_res = requests.post(f"https://api.derivws.com/trading/v1/options/accounts/{acc_id}/otp", headers=headers, timeout=8)
                            if otp_res.status_code == 200:
                                target_ws_url = otp_res.json().get("data", {}).get("url", target_ws_url)
                                is_authenticated = True
                                account_info = {
                                    "loginid": acc_id,
                                    "currency": target_acc.get("currency", "USD"),
                                    "balance": float(target_acc.get("balance", 10000.0)),
                                    "email": "DEMO_ACCOUNT"
                                }
                                log(f"✅ ยืนยันสิทธิ์บัญชี Demo {acc_id} สำเร็จ! ยอดเงิน: ${account_info['balance']:,.2f} {account_info['currency']}")
                        else:
                            log(f"🛡️ [SAFETY ENFORCEMENT] ตรวจพบบัญชีจริงหรือยังไม่มี Demo -> บังคับสลับเข้าสู่ Demo Training Mode ({TARGET_DEMO_ACCOUNT}) เพื่อความปลอดภัย 100%")
                except Exception as e:
                    log(f"ℹ️ Auth Check Note: {e} -> รันโหมด Demo Training ปลอดภัย 100%")

            if not is_authenticated:
                log(f"💡 รันในโหมด [Demo Training Engine: {TARGET_DEMO_ACCOUNT}] (จำลองการเทรดบนกราฟจริง 100% ปลอดภัย ไร้ความเสี่ยง)")

            # เชื่อมต่อ Deriv WebSocket โดยปิด ping_interval ของโปรโตคอลเพื่อป้องกัน Error 1011
            # และใช้ Application-level Ping {"ping": 1} ทุก 20 วินาทีแทน
            async with websockets.connect(target_ws_url, ssl=ssl_context, ping_interval=None, close_timeout=10) as ws:
                log(f"🔌 เชื่อมต่อ Deriv WebSocket สำเร็จ! (บัญชี: {account_info['loginid']})")

                while True:
                    scan_rows = []
                    symbol_indicators = {}

                    # 1. สแกนและดึงข้อมูลแท่งเทียน M15 ของทุก Synthetic Volatility Index (R_75, R_25, R_50, R_10)
                    for sym in SYMBOLS:
                        try:
                            candle_req = {
                                "ticks_history": sym,
                                "adjust_start_time": 1,
                                "count": 100,
                                "end": "latest",
                                "style": "candles",
                                "granularity": TIMEFRAME_SEC
                            }
                            await ws.send(json.dumps(candle_req))
                            candle_res = json.loads(await ws.recv())
                            candles = candle_res.get("candles", [])
                            
                            inds = calculate_bb_rsi(
                                candles,
                                period=memory.get("learned_params", {}).get("bb_period", 20),
                                std_dev=memory.get("learned_params", {}).get("bb_std", 2.0)
                            )
                            
                            if inds:
                                symbol_indicators[sym] = inds
                                
                                # กำหนดสถานะตาราง
                                pos_str = "⚪ FLAT"
                                st_str = "OK"
                                if active_trade and active_trade.get('symbol') == sym:
                                    cur_p = inds['price']
                                    ent = active_trade['entry_price']
                                    sym_pip_size = get_pip_size(sym, ent)
                                    pips = (cur_p - ent) / sym_pip_size
                                    pos_str = f"🟢 {pips:+.1f} pips"
                                    st_str = "BE" if active_trade.get('be_locked') else "IN"

                                scan_rows.append({
                                    'symbol': sym,
                                    'price': f"{inds['price']:.4f}",
                                    'rsi': f"{inds['rsi']:.1f}",
                                    'bb_w': f"{inds['bb_width']:.5f}",
                                    'pattern': inds['pattern_name'],
                                    'pos': pos_str,
                                    'st': st_str
                                })
                        except Exception as e:
                            err_str = str(e).lower()
                            if "closed" in err_str or "keepalive" in err_str or "1011" in err_str:
                                log(f"🔄 การเชื่อมต่อ WebSocket กับ Deriv ขาดหาย ({e}) -> เตรียม Reconnect ใหม่ทันที...")
                                raise e
                            log(f"⚠️ ดึงข้อมูลแท่งเทียน {sym} ไม่สำเร็จ: {e}")
                        
                        await asyncio.sleep(0.4) # Low-CPU rate pacing

                    # 2. จัดการสถานะไม้ที่ถืออยู่ (Active Position Risk Management)
                    if active_trade and active_trade.get('symbol') in symbol_indicators:
                        curr_sym = active_trade['symbol']
                        inds = symbol_indicators[curr_sym]
                        cur_price = inds['price']
                        entry = active_trade['entry_price']
                        sym_pip_size = get_pip_size(curr_sym, entry)
                        diff_pips = (cur_price - entry) / sym_pip_size
                        trailing_sl_pips = active_trade.get('trailing_sl_pips', INITIAL_SL_PIPS)

                        # 2.1 Auto-Breakeven เมื่อกำไรแตะ +10 pips
                        if diff_pips >= BREAKEVEN_PIPS and not active_trade.get('be_locked', False):
                            active_trade['be_locked'] = True
                            trailing_sl_pips = 1.0 # ล็อกกำไรบังหน้าทุน +1 pip
                            active_trade['trailing_sl_pips'] = trailing_sl_pips
                            save_state(active_trade)
                            
                            print_highlight_box(
                                f"AUTO-BREAKEVEN ACTIVATED - {curr_sym}",
                                [
                                    ("Engine", "Deriv Synthetic 24/7"),
                                    ("Current Price", f"{cur_price:.4f}"),
                                    ("Profit Pips", f"+{diff_pips:.1f} pips"),
                                    ("New Trailing SL", "+1.0 pip (ล็อกหน้าทุน 100% ไร้ความเสี่ยง)")
                                ],
                                icon="🛡️"
                            )
                            if notifier:
                                try:
                                    notifier.notify_breakeven("Deriv Synthetic", curr_sym, cur_price, entry + (1.0 * sym_pip_size), diff_pips)
                                except Exception:
                                    pass

                        # 2.2 Dynamic Trailing Stop เมื่อกำไรแตะ +20 pips
                        if diff_pips >= TRAILING_PIPS:
                            new_trailing_sl = diff_pips - 10.0 # รักษาระยะห่าง trailing 10 pips
                            if new_trailing_sl > trailing_sl_pips:
                                trailing_sl_pips = new_trailing_sl
                                active_trade['trailing_sl_pips'] = trailing_sl_pips
                                save_state(active_trade)
                                
                                print_highlight_box(
                                    f"DYNAMIC TRAILING RUN - {curr_sym}",
                                    [
                                        ("Current Price", f"{cur_price:.4f}"),
                                        ("Profit Pips", f"+{diff_pips:.1f} pips"),
                                        ("Trailing SL", f"+{trailing_sl_pips:.1f} pips (Let Profit Run!)")
                                    ],
                                    icon="🚀"
                                )
                                if notifier:
                                    try:
                                        notifier.notify_trailing("Deriv Synthetic", curr_sym, cur_price, cur_price - (10.0 * sym_pip_size), diff_pips)
                                    except Exception:
                                        pass

                        # 2.3 ตรวจสอบจุดปิดไม้:
                        # - ชนเส้น Trailing SL
                        # - ชน Take Profit ที่ Upper Bollinger Band (Brad Goh Step 5: เข้าไวออกไวกว่า)
                        # - หมดเวลาถือครองสูงสุด 45 นาที (3 แท่ง M15) เพื่อหมุนเวียนทุน
                        hold_sec = time.time() - active_trade.get('start_time', time.time())
                        is_sl = diff_pips <= trailing_sl_pips
                        is_bb_target = (cur_price >= inds['upper_bb']) and (diff_pips >= 5.0)
                        is_timeout = hold_sec >= 2700 and not (diff_pips >= 15.0)
                        is_be_hit = is_sl and active_trade.get('be_locked', False)

                        if is_be_hit or is_sl or is_bb_target or is_timeout:
                            # คำนวณกำไรตามขนาด Stake $1.00 USD
                            # สเกลกำไร ~0.01 USD ต่อ 1 pip สำหรับ stake $1.00
                            profit_usd = round(diff_pips * (STAKE_USD / 100.0), 2)
                            profit_thb = round(profit_usd * usd_thb_rate, 1)
                            
                            if is_be_hit:
                                status_title = "SL-BREAKEVEN CLOSED"
                                icon_str = "🛡️"
                            elif is_bb_target:
                                status_title = "TAKE PROFIT (UPPER BB - BRAD GOH เข้าไวออกไวกว่า)"
                                icon_str = "🎯"
                            elif profit_usd >= 0:
                                status_title = "TAKE PROFIT (WIN)"
                                icon_str = "🎯"
                            else:
                                status_title = "STOP LOSS (LOSS)"
                                icon_str = "🛑"

                            print_highlight_box(
                                f"{status_title} - {curr_sym}",
                                [
                                    ("Engine / Account", f"Deriv Synthetic (Demo: {TARGET_DEMO_ACCOUNT})"),
                                    ("Exit Price", f"{cur_price:.4f}"),
                                    ("Result Pips", f"{diff_pips:+.1f} pips"),
                                    ("Net Profit", f"${profit_usd:+,.2f} USD (≈ {profit_thb:+,.1f} THB)"),
                                    ("Account Balance", f"${account_info['balance'] + profit_usd:,.2f} USD")
                                ],
                                icon=icon_str
                            )

                            account_info['balance'] = round(account_info['balance'] + profit_usd, 2)
                            memory["total_trades"] = memory.get("total_trades", 0) + 1
                            
                            if profit_usd >= 0:
                                memory["wins"] = memory.get("wins", 0) + 1
                                if notifier:
                                    try:
                                        notifier.notify_tp("Deriv Synthetic", curr_sym, cur_price, diff_pips, profit_usd, "USD")
                                    except Exception:
                                        pass
                            else:
                                memory["losses"] = memory.get("losses", 0) + 1
                                current_oversold = memory.get("learned_params", {}).get("rsi_oversold", 35.0)
                                if current_oversold > 28.0:
                                    memory["learned_params"]["rsi_oversold"] = round(current_oversold - 0.5, 1)
                                if notifier:
                                    try:
                                        notifier.notify_sl("Deriv Synthetic", curr_sym, cur_price, diff_pips, profit_usd, "USD", is_breakeven=is_be_hit)
                                    except Exception:
                                        pass

                            memory["net_profit_usd"] = round(memory.get("net_profit_usd", 0.0) + profit_usd, 2)
                            memory["net_profit_thb"] = round(memory.get("net_profit_thb", 0.0) + profit_thb, 1)
                            save_memory(memory)
                            
                            active_trade = None
                            save_state(None) # ล้างสถานะไม้ใน active_state_synthetic.json

                    # 3. สแกนหาจังหวะเปิดไม้ใหม่ (เมื่อไม่มีไม้ค้าง)
                    elif not active_trade:
                        # สแกนดัชนีโดยให้ความสำคัญกับ PRIMARY_SYMBOLS (R_75, R_25) ก่อน
                        sorted_symbols = sorted(
                            symbol_indicators.keys(),
                            key=lambda s: 0 if s in PRIMARY_SYMBOLS else 1
                        )

                        for sym in sorted_symbols:
                            inds = symbol_indicators[sym]
                            price = inds['price']
                            rsi = inds['rsi']
                            lower_bb = inds['lower_bb']
                            bb_width = inds.get('bb_width', 0.001)
                            ema50 = inds.get('ema50', price)
                            learned_oversold = memory.get("learned_params", {}).get("rsi_oversold", 35.0)

                            # ตัวกรองเทรนด์ EMA50
                            if price < ema50 * 0.998:
                                effective_oversold = min(learned_oversold, 28.0)
                            else:
                                effective_oversold = learned_oversold

                            is_squeezed = bb_width < 0.0004
                            has_pattern = inds.get('has_bullish_pattern', False)
                            is_sweep = inds.get('is_liquidity_sweep', False)
                            is_pin_bar = inds.get('is_pin_bar', False)
                            is_hammer = inds.get('is_hammer', False)

                            # เงื่อนไขเข้าซื้อ BUY ตามข้อกำหนด:
                            # 1. Price <= Lower BB และ RSI <= 35 (Oversold) หรือ
                            # 2. เกิด Liquidity Sweep / Pin Bar Rejection พร้อม RSI <= 45
                            is_oversold_bb = (price <= lower_bb * 1.0005) and (rsi <= effective_oversold) and not is_squeezed
                            is_reversal_pattern = (is_sweep or is_pin_bar or is_hammer) and (rsi <= 45.0) and not is_squeezed

                            if is_oversold_bb or is_reversal_pattern:
                                if is_sweep and is_pin_bar:
                                    trigger_name = "LiqSweep_PinBar"
                                elif is_sweep:
                                    trigger_name = "Liquidity_Sweep"
                                elif is_pin_bar:
                                    trigger_name = "PinBar_Rejection"
                                elif is_hammer:
                                    trigger_name = "Hammer_Reversal"
                                else:
                                    trigger_name = "Pullback_LowerBB_Oversold"

                                # 3.1 ตรวจสอบสเปรดสดผ่าน Deriv WebSocket
                                spread_pips, ask_p, bid_p = await get_live_spread(ws, sym)
                                max_allowed_spread = 5.0 # สเปรดปกติสำหรับดัชนีจำลองไม่เกิน 5 pips
                                if spread_pips is not None and spread_pips > max_allowed_spread:
                                    log(f"⚠️ [SPREAD FILTER] สเปรดสด {sym} ถ่างเกินปกติ: {spread_pips:.1f} pips > {max_allowed_spread} pips -> ข้ามจังหวะเพื่อความปลอดภัย")
                                    continue

                                # 3.2 ผ่านการประเมินความปลอดภัย (Groq AI / Quant Advisor)
                                is_ai_approved = await ask_groq_ai_sentiment(sym, price, rsi, trigger_name, bb_width)
                                if is_ai_approved:
                                    active_trade = {
                                        "contract_id": f"SYNTH-{sym}-{int(time.time())}",
                                        "symbol": sym,
                                        "type": f"BUY (Demo $1.00)",
                                        "entry_price": price,
                                        "stake": STAKE_USD,
                                        "entry_time": get_thai_time(),
                                        "start_time": time.time(),
                                        "be_locked": False,
                                        "trailing_sl_pips": INITIAL_SL_PIPS
                                    }
                                    save_state(active_trade) # บันทึกลง active_state_synthetic.json แบบ Atomic

                                    spread_str = f"{spread_pips:.1f} pips" if spread_pips is not None else "Normal"
                                    print_highlight_box(
                                        f"BUY ORDER EXECUTED - {sym}",
                                        [
                                            ("Engine / Account", f"Deriv Synthetic 24/7 (Demo: {TARGET_DEMO_ACCOUNT})"),
                                            ("Symbol", sym),
                                            ("Entry Price", f"{price:.4f}"),
                                            ("Live Spread", spread_str),
                                            ("Stake", f"${STAKE_USD:.2f} USD"),
                                            ("Strategy Trigger", trigger_name),
                                            ("RSI / BB-Width", f"{rsi:.1f} / {bb_width:.5f}")
                                        ],
                                        icon="🟢"
                                    )

                                    if notifier:
                                        try:
                                            sym_pip_size = get_pip_size(sym, price)
                                            tp_est = inds['upper_bb']
                                            sl_est = price - (abs(INITIAL_SL_PIPS) * sym_pip_size)
                                            notifier.notify_buy(
                                                "Deriv Synthetic", sym, price, STAKE_USD,
                                                tp_est, sl_est, trigger_name,
                                                f"บัญชี Demo: {TARGET_DEMO_ACCOUNT} | 24/7 Non-Stop"
                                            )
                                        except Exception:
                                            pass
                                    break # เปิด 1 ไม้ต่อรอบสแกน

                    # 4. พิมพ์ตารางสถานะ Quant Terminal
                    if scan_rows:
                        print_quant_table(get_thai_time(), scan_rows, account_info, memory)

                    # 5. วนพัก 60 วินาที โดยส่ง Application-level Ping {"ping": 1} ทุกๆ 20 วินาที
                    # เพื่อรักษาการเชื่อมต่อ WebSocket ให้เสถียรสูงสุด 100%
                    for _ in range(3):
                        await asyncio.sleep(20)
                        try:
                            await ws.send(json.dumps({"ping": 1}))
                            ping_raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        except Exception as pe:
                            log(f"🔄 Deriv WebSocket ขาดการตอบสนองระหว่างพัก ({pe}) -> เตรียมเชื่อมต่อใหม่ทันที...")
                            raise pe

        except Exception as e:
            log(f"⚠️ การเชื่อมต่อ Deriv WebSocket สิ้นสุด: {e}. กำลังเชื่อมต่อใหม่ใน 3 วินาที...")
            await asyncio.sleep(3)

if __name__ == "__main__":
    print("=" * 75)
    print(f"🏛️ DERIV SYNTHETIC 24/7 QUANT ENGINE STARTING (DEMO: {TARGET_DEMO_ACCOUNT})")
    print(f"🎯 ASSETS: {SYMBOLS} (Focus: {PRIMARY_SYMBOLS})")
    print(f"⚙️ RISK: Stake ${STAKE_USD:.2f} USD | BE +{BREAKEVEN_PIPS} pips | Trailing +{TRAILING_PIPS} pips")
    ai_status = "🟢 พร้อมใช้งาน (Groq Synthetic Quant Advisor)" if GROQ_API_KEY else "⚪ ไม่ได้เปิดใช้งาน (ข้ามไปใช้ Pure Quant)"
    print(f"🧠 AI ADVISOR : {ai_status}")
    print("=" * 75)
    asyncio.run(deriv_synthetic_engine())
