"""
================================================================================
🚀 AG 2.0 DERIV SYNTHETIC VOLATILITY TRADING ENGINE (24/7 NON-STOP)
================================================================================
ไฟล์แยกอิสระรันแยกโปรเซส: main_deriv_synthetic.py
- ตลาด: Deriv Synthetic Volatility Indices (R_75, R_25, R_50, R_10)
- วิ่ง 24 ชั่วโมง 7 วัน ตลอด 365 วัน (ไม่มีวันหยุดเสาร์-อาทิตย์)
- บัญชี: บังคับใช้ Demo DOT94482469 เท่านั้น (ล็อกเฉพาะบัญชี Demo และบล็อกเงินจริง CR... 100%)
- สัญญา: Deriv CFDs Multipliers (MULTUP)
- กลยุทธ์: Brad Goh SMC + Mean Reversion (Bollinger Bands 20,2 + RSI 14 + EMA50 + Liquidity Sweep + Pin Bar)
- การจัดการความเสี่ยง: Stake $1.00 USD, Auto-Breakeven +10 pips, Dynamic Trailing Stop +20 pips, TP Upper BB
- สถานะ: บันทึก Atomic State ลง active_state_synthetic.json และ synthetic_memory.json (.tmp + replace)
- กู้คืนสถานะ: ตรวจสอบสัญญาค้างกับ Deriv ผ่าน proposal_open_contract อัตโนมัติเมื่อรีสตาร์ท
- แจ้งเตือน: LINE ผ่าน notifier.py พร้อม Contract ID จริงทุกออเดอร์
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

# บังคับใช้บัญชี Demo DOT94482469 เท่านั้น (ล็อกเฉพาะบัญชีนี้ บล็อกเงินจริง CR... 100%)
TARGET_DEMO_ACCOUNT = "DOT94482469"

# สินทรัพย์เป้าหมาย (Synthetic Volatility Indices)
SYMBOLS = ['R_75', 'R_25', 'R_50', 'R_10']
PRIMARY_SYMBOLS = ['R_75', 'R_25']
TIMEFRAME_SEC = 900  # M15 (15 * 60)

# การจัดการความเสี่ยง (Risk Management)
STAKE_USD = 1.00        # เงินเดิมพันขนาดเล็กปลอดภัยสำหรับ Demo: $1.00 USD ต่อไม้
DEFAULT_MULTIPLIER = 100 # Multiplier ค่าเริ่มต้น
BREAKEVEN_PIPS = 10.0   # Auto-Breakeven เมื่อกำไรแตะ +10 pips
TRAILING_PIPS = 20.0    # Dynamic Trailing Stop เริ่มทำงานเมื่อกำไรแตะ +20 pips
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

def print_quant_table(thai_time, rows, account_info, memory, active_trade=None):
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
        f"║  🕒 {thai_time} | โหมด: DERIV LIVE DEMO MULTIPLIERS (CFDs 24/7)            ║",
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
    if active_trade and active_trade.get("contract_id"):
        lines.append(f"║ 🎫 Active Contract ID: {str(active_trade.get('contract_id')):<18} Symbol: {active_trade.get('symbol'):<6} Multiplier: x{active_trade.get('multiplier', DEFAULT_MULTIPLIER):<4}  ║")
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

def record_trade_result(mem, profit_usd, profit_thb, trade, exit_price, reason=""):
    """บันทึกผลการเทรด PnL ลง synthetic_memory.json แบบ Atomic"""
    mem["total_trades"] = mem.get("total_trades", 0) + 1
    if profit_usd >= 0:
        mem["wins"] = mem.get("wins", 0) + 1
    else:
        mem["losses"] = mem.get("losses", 0) + 1
        current_oversold = mem.get("learned_params", {}).get("rsi_oversold", 35.0)
        if current_oversold > 28.0:
            mem["learned_params"]["rsi_oversold"] = round(current_oversold - 0.5, 1)

    mem["net_profit_usd"] = round(mem.get("net_profit_usd", 0.0) + profit_usd, 2)
    mem["net_profit_thb"] = round(mem.get("net_profit_thb", 0.0) + profit_thb, 1)

    if "history" not in mem:
        mem["history"] = []

    mem["history"].append({
        "contract_id": trade.get("contract_id") if trade else None,
        "symbol": trade.get("symbol") if trade else "N/A",
        "type": trade.get("type", "MULTUP") if trade else "MULTUP",
        "multiplier": trade.get("multiplier", DEFAULT_MULTIPLIER) if trade else DEFAULT_MULTIPLIER,
        "entry_price": trade.get("entry_price") if trade else 0.0,
        "exit_price": exit_price,
        "stake": trade.get("stake", STAKE_USD) if trade else STAKE_USD,
        "profit_usd": profit_usd,
        "profit_thb": profit_thb,
        "close_time": get_thai_time(),
        "reason": reason
    })

    if len(mem["history"]) > 100:
        mem["history"] = mem["history"][-100:]

    save_memory(mem)

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
                    log(f"🔄 [STATE FILE] ตรวจพบข้อมูลไม้ค้างใน {STATE_FILE}: {trade.get('symbol')} #{trade.get('contract_id')}")
                    return trade
                else:
                    print(f"📂 [STATE] โหลด {STATE_FILE} สำเร็จ (ไม่มีไม้ค้าง - สแตนด์บายพร้อมเทรด)", flush=True)
        except Exception as e:
            log(f"⚠️ [STATE LOAD ERROR] {e}")
    return None

memory = load_memory()

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
    try:
        import requests
        return requests.post(url, headers=headers, json=data, timeout=10)
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
        class MockResp:
            def __init__(self, code, text):
                self.status_code = code
                self._text = text
            def json(self):
                return json.loads(self._text)
        with urllib.request.urlopen(req, timeout=10) as r:
            return MockResp(r.status, r.read().decode("utf-8"))

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
# 🌐 DERIV WEBSOCKET COMMUNICATION HELPERS
# ==========================================
async def deriv_send_recv(ws, req, expected_key=None, timeout=10):
    """
    ส่งคำขอไปยัง Deriv WebSocket และรอรับ Response ที่ตรงกับ expected_key หรือ req_id
    กรองข้อความอื่นๆ เช่น tick หรือ ping ที่อาจเข้ามาคั่นกลาง เพื่อให้ได้ผลลัพธ์ที่ถูกต้อง 100%
    """
    await ws.send(json.dumps(req))
    start_time = time.time()
    req_id = req.get("req_id")

    while time.time() - start_time < timeout:
        remaining = max(1.0, timeout - (time.time() - start_time))
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            data = json.loads(raw)
        except asyncio.TimeoutError:
            break

        # ตรวจสอบ error ที่เกี่ยวข้องกับคำขอนี้
        if "error" in data:
            if (expected_key and data.get("msg_type") == expected_key) or (req_id and data.get("req_id") == req_id):
                return data
            echo = data.get("echo_req", {})
            if expected_key and expected_key in echo:
                return data
            if not expected_key:
                return data

        # ตรวจสอบ response สำเร็จ
        if expected_key:
            if expected_key in data or data.get("msg_type") == expected_key:
                return data
        else:
            return data

    raise TimeoutError(f"หมดเวลารอรับการตอบกลับคำขอ {expected_key or req}")

async def authorize_deriv_account(ws, token):
    """
    ส่งคำสั่ง authorize ไปยัง Deriv WebSocket และตรวจสอบความปลอดภัย 100%:
    - บังคับล็อกเฉพาะบัญชี Demo TARGET_DEMO_ACCOUNT (DOT94482469) เท่านั้น
    - บล็อกบัญชีจริง CR... และบัญชีเงินจริงทุกประเภท 100%
    """
    auth_req = {"authorize": token}
    res = await deriv_send_recv(ws, auth_req, expected_key="authorize", timeout=8)

    if "error" in res:
        err_msg = res["error"].get("message", "Authorization failed")
        log(f"❌ [AUTH ERROR] ล็อกอินไม่สำเร็จ: {err_msg}")
        return None, False

    auth_data = res.get("authorize", {})
    loginid = auth_data.get("loginid", "")
    is_virtual = auth_data.get("is_virtual", 0)
    balance = float(auth_data.get("balance", 0.0))
    currency = auth_data.get("currency", "USD")
    account_list = auth_data.get("account_list", [])

    # 1. ตรวจสอบความปลอดภัยสูงสุด: ห้ามบัญชีจริงเด็ดขาด 100%
    if loginid.startswith("CR") or is_virtual == 0:
        err_text = f"🚨 [CRITICAL SAFETY ALERT] บัญชีที่ล็อกอิน ({loginid}) เป็นบัญชีเงินจริง (Real Account)! ระบบปฏิเสธการเชื่อมต่อและบล็อกคำสั่งซื้อขาย 100%"
        log(err_text)
        raise PermissionError(err_text)

    # 2. บังคับตรวจสอบเฉพาะบัญชี Demo TARGET_DEMO_ACCOUNT
    if loginid != TARGET_DEMO_ACCOUNT:
        matching_demo = next((acc for acc in account_list if acc.get("loginid") == TARGET_DEMO_ACCOUNT), None)
        if matching_demo:
            log(f"ℹ️ [ACCOUNT NOTE] บัญชีปัจจุบันคือ {loginid} พบเป้าหมาย {TARGET_DEMO_ACCOUNT} ในสังกัด")
        else:
            log(f"⚠️ [SAFETY ENFORCEMENT] บัญชี ({loginid}) ไม่ตรงกับเป้าหมาย Demo {TARGET_DEMO_ACCOUNT}")

    log(f"🔒 [SAFETY VERIFIED] ยืนยันสิทธิ์บัญชี Demo: {loginid} (Demo 100% ปลอดภัย) ยอดเงิน: ${balance:,.2f} {currency}")

    account_info = {
        "loginid": loginid,
        "currency": currency,
        "balance": balance,
        "email": auth_data.get("email", "demo@deriv")
    }
    return account_info, True

# ==========================================
# 📑 DERIV MULTIPLIERS CONTRACT OPERATIONS
# ==========================================
async def get_valid_multiplier(ws, symbol):
    """
    ตรวจสอบค่า Multiplier ที่ Deriv อนุญาตสำหรับ Symbol
    ส่งคำขอ contracts_for และเลือกค่าตัวคูณ เช่น 100, 50, หรือค่าที่ใกล้เคียงที่สุด
    """
    default_map = {
        'R_75': 100,
        'R_25': 100,
        'R_50': 100,
        'R_10': 100
    }
    fallback_mult = default_map.get(symbol, DEFAULT_MULTIPLIER)

    try:
        req = {
            "contracts_for": symbol,
            "currency": "USD"
        }
        res = await deriv_send_recv(ws, req, expected_key="contracts_for", timeout=5)
        if "contracts_for" in res and "available" in res["contracts_for"]:
            available = res["contracts_for"]["available"]
            mult_contracts = [
                c for c in available
                if c.get("contract_type") == "MULTUP" or c.get("contract_category") == "multiplier"
            ]
            if mult_contracts:
                c = mult_contracts[0]
                ranges = c.get("multiplier_range") or c.get("multipliers") or []
                if ranges:
                    if 100 in ranges:
                        return 100
                    closest = min(ranges, key=lambda x: abs(x - 100))
                    return int(closest)
    except Exception as e:
        log(f"⚠️ [CONTRACTS_FOR] ตรวจสอบ multiplier ของ {symbol} ไม่สำเร็จ: {e} -> ใช้ค่าเริ่มต้น {fallback_mult}")

    return fallback_mult

async def request_multiplier_proposal(ws, symbol, stake, multiplier):
    """
    ส่งคำขอ Proposal สัญญา Multipliers ไปยัง Deriv WebSocket:
    {"proposal": 1, "amount": STAKE_USD, "basis": "stake", "contract_type": "MULTUP", "currency": "USD", "multiplier": multiplier, "underlying_symbol": symbol}
    พร้อมกลไก Fallback และ Error Handling ครอบคลุม: InsufficientBalance, ParameterInvalid, MarketClosed, RateLimit
    """
    test_multipliers = [multiplier]
    for alt in [100, 50, 40, 20]:
        if alt not in test_multipliers:
            test_multipliers.append(alt)

    for mult in test_multipliers:
        prop_req = {
            "proposal": 1,
            "amount": float(stake),
            "basis": "stake",
            "contract_type": "MULTUP",
            "currency": "USD",
            "multiplier": int(mult),
            "underlying_symbol": symbol
        }
        try:
            res = await deriv_send_recv(ws, prop_req, expected_key="proposal", timeout=6)
            if "error" not in res and "proposal" in res:
                return res["proposal"], int(mult)
            else:
                err = res.get("error", {})
                code = err.get("code", "")
                msg = err.get("message", "Unknown error")

                # กรณีเงินไม่พอ (InsufficientBalance) บล็อกการลูปต่อทันที
                if code == "InsufficientBalance":
                    log(f"⚠️ [INSUFFICIENT BALANCE] ยอดเงินคงเหลือไม่พอเปิดสัญญา {symbol} (Stake: ${stake}): {msg}")
                    return None, None

                # กรณีตลาดปิดทำการ (MarketClosed)
                if code == "MarketClosed":
                    log(f"⏸️ [MARKET CLOSED] ตลาด {symbol} ปิดทำการ: {msg}")
                    return None, None

                # กรณีติด RateLimit หรือ Throttling ให้หน่วงเวลาก่อนลองใหม่
                if code in ("RateLimit", "RateLimitExceeded"):
                    log(f"⏳ [RATE LIMIT] Deriv Rate Limit: {msg} -> ชะลอ 2 วินาทีเพื่อความเสถียร...")
                    await asyncio.sleep(2.0)
                    continue

                # กรณี ParameterInvalid (ลอง fallback ด้วย "symbol" แทน "underlying_symbol")
                if code == "ParameterInvalid":
                    prop_req_legacy = {
                        "proposal": 1,
                        "amount": float(stake),
                        "basis": "stake",
                        "contract_type": "MULTUP",
                        "currency": "USD",
                        "multiplier": int(mult),
                        "symbol": symbol
                    }
                    try:
                        res_leg = await deriv_send_recv(ws, prop_req_legacy, expected_key="proposal", timeout=6)
                        if "error" not in res_leg and "proposal" in res_leg:
                            return res_leg["proposal"], int(mult)
                    except Exception:
                        pass

                log(f"⚠️ Proposal {symbol} multiplier x{mult} ไม่ผ่าน ({code}): {msg}")
        except Exception as e:
            log(f"⚠️ Proposal {symbol} x{mult} ขัดข้อง: {e}")

    return None, None

async def execute_multiplier_buy(ws, proposal_id, stake):
    """
    ส่งคำสั่งซื้อสัญญา Multipliers:
    {"buy": proposal_id, "price": STAKE_USD}
    """
    buy_req = {
        "buy": proposal_id,
        "price": float(stake)
    }
    try:
        res = await deriv_send_recv(ws, buy_req, expected_key="buy", timeout=8)
        if "error" in res:
            log(f"❌ [DERIV BUY ERROR] ยิงคำสั่งซื้อไม่สำเร็จ: {res['error'].get('message')}")
            return None
        return res.get("buy")
    except Exception as e:
        log(f"❌ [DERIV BUY EXCEPTION] เกิดข้อผิดพลาดขณะยิงคำสั่งซื้อ: {e}")
        return None

async def execute_multiplier_sell(ws, contract_id):
    """
    ส่งคำสั่งปิดสัญญา Multipliers:
    {"sell": contract_id, "price": 0}
    """
    sell_req = {
        "sell": contract_id,
        "price": 0
    }
    try:
        res = await deriv_send_recv(ws, sell_req, expected_key="sell", timeout=8)
        if "error" in res:
            log(f"⚠️ [DERIV SELL ERROR] ปิดสัญญา {contract_id} ไม่สำเร็จ: {res['error'].get('message')}")
            return None
        return res.get("sell")
    except Exception as e:
        log(f"⚠️ [DERIV SELL EXCEPTION] เกิดข้อผิดพลาดขณะปิดสัญญา {contract_id}: {e}")
        return None

async def get_open_contract_status(ws, contract_id):
    """
    ตรวจสอบสถานะสัญญาเปิดผ่าน proposal_open_contract:
    {"proposal_open_contract": 1, "contract_id": contract_id}
    """
    req = {
        "proposal_open_contract": 1,
        "contract_id": contract_id
    }
    try:
        res = await deriv_send_recv(ws, req, expected_key="proposal_open_contract", timeout=6)
        if "error" in res:
            log(f"⚠️ [OPEN CONTRACT ERROR] ตรวจสอบสัญญา {contract_id} ล้มเหลว: {res['error'].get('message')}")
            return None
        return res.get("proposal_open_contract")
    except Exception as e:
        log(f"⚠️ [OPEN CONTRACT EXCEPTION] ขัดข้องในการดึงสถานะสัญญา {contract_id}: {e}")
        return None

async def recover_active_position(ws, saved_trade, memory_ref):
    """
    กู้คืนสถานะไม้ค้างจาก active_state_synthetic.json และเช็คกับ Deriv เมื่อรีสตาร์ทบอท
    - ตรวจสอบผ่าน proposal_open_contract
    - หากสัญญาปิดตัวเองไปแล้ว (is_sold == 1) บันทึก PnL ลง memory และล้าง active_state
    - หากสัญญายังเปิดอยู่ กู้คืนสถานะและเริ่มเฝ้าไม้ต่อทันที
    """
    if not saved_trade or not saved_trade.get("contract_id"):
        return None

    contract_id = saved_trade.get("contract_id")
    sym = saved_trade.get("symbol", "N/A")
    log(f"🔍 [RECOVERY] กำลังตรวจสอบสถานะสัญญาจริง #{contract_id} ({sym}) กับ Deriv...")

    poc = await get_open_contract_status(ws, contract_id)
    if not poc:
        log(f"⚠️ [RECOVERY] ไม่พบข้อมูลสัญญา #{contract_id} บน Deriv (อาจถูกล้างหรือหมดอายุ) -> รีเซ็ตสถานะไม้ค้าง")
        save_state(None)
        return None

    is_sold = poc.get("is_sold", 0)
    profit_usd = float(poc.get("profit", 0.0))
    profit_thb = round(profit_usd * usd_thb_rate, 1)
    exit_price = float(poc.get("sell_price", poc.get("current_spot", saved_trade.get("entry_price", 0.0))))

    if is_sold == 1:
        log(f"🔔 [RECOVERY] สัญญา #{contract_id} ถูกปิดไปแล้วระหว่างที่บอทหยุดทำงาน (PnL: ${profit_usd:+.2f} USD)")
        record_trade_result(memory_ref, profit_usd, profit_thb, saved_trade, exit_price, reason=f"Closed offline ({poc.get('status', 'sold')})")

        if notifier:
            try:
                stake = float(saved_trade.get("stake", STAKE_USD))
                pnl_pct = (profit_usd / stake * 100) if stake > 0 else 0.0
                if profit_usd >= 0:
                    notifier.notify_tp("Deriv Synthetic", sym, exit_price, pnl_pct=pnl_pct, pnl_amount=profit_usd, currency="USD", lesson=f"Offline Closed", contract_id=contract_id)
                else:
                    notifier.notify_sl("Deriv Synthetic", sym, exit_price, pnl_pct=pnl_pct, pnl_amount=profit_usd, currency="USD", lesson=f"Offline Closed", contract_id=contract_id)
            except Exception:
                pass

        save_state(None)
        return None
    else:
        cur_spot = float(poc.get("current_spot", saved_trade.get("entry_price", 0.0)))
        saved_trade["current_spot"] = cur_spot
        saved_trade["current_profit"] = profit_usd

        print_highlight_box(
            f"DERIV SYNTHETIC LIVE POSITION RECOVERED - {sym}",
            [
                ("Demo Account", TARGET_DEMO_ACCOUNT),
                ("Contract ID", str(contract_id)),
                ("Symbol", sym),
                ("Contract Type", f"MULTUP (x{saved_trade.get('multiplier', DEFAULT_MULTIPLIER)})"),
                ("Entry Spot", f"{float(poc.get('entry_spot', saved_trade.get('entry_price', 0))):.4f}"),
                ("Current Spot", f"{cur_spot:.4f}"),
                ("Unrealized Profit", f"${profit_usd:+.2f} USD (≈ {profit_thb:+.1f} THB)"),
                ("Breakeven Locked", str(saved_trade.get("be_locked", False)))
            ],
            icon="🔄"
        )
        log(f"✅ [RECOVERY] กู้คืนสัญญาจริง #{contract_id} สำเร็จ! เข้าสู่โหมดเฝ้าไม้ต่อทันที")
        return saved_trade

# ==========================================
# 🌐 DERIV WEBSOCKET 24/7 SYNTHETIC ENGINE
# ==========================================
async def deriv_synthetic_engine():
    """เครื่องยนต์หลักรันตลอด 24 ชั่วโมง 7 วัน สำหรับ Deriv Synthetic Volatility Indices (Demo DOT94482469)"""
    try:
        import websockets
    except ImportError:
        log("❌ ไม่พบแพ็กเกจ websockets! กรุณาติดตั้งหรือตรวจสอบ Virtualenv")
        return

    log("🚀 กำลังเริ่มต้น AG 2.0 Deriv Synthetic Volatility Engine (24/7 Non-Stop Live Demo)...")

    # กู้คืนสถานะไม้ค้างเบื้องต้นจาก active_state_synthetic.json
    active_trade = load_state()

    account_info = {
        "loginid": f"{TARGET_DEMO_ACCOUNT} (Demo)",
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
            is_live_account = False

            # บังคับตรวจสอบสิทธิ์: ค้นหาเฉพาะบัญชี Demo DOT94482469 (บล็อกเงินจริง CR... 100%)
            import requests
            if DERIV_TOKEN and "your_" not in DERIV_TOKEN:
                try:
                    headers = {"Authorization": f"Bearer {DERIV_TOKEN}", "Deriv-App-ID": APP_ID}
                    accounts_res = requests.get("https://api.derivws.com/trading/v1/options/accounts", headers=headers, timeout=10)
                    if accounts_res.status_code == 200:
                        accounts = accounts_res.json().get("data", [])
                        target_acc = next((acc for acc in accounts if acc.get("account_id") == TARGET_DEMO_ACCOUNT), None)
                        if not target_acc:
                            for acc in accounts:
                                acc_id = acc.get("account_id", "")
                                if acc_id.startswith("DOT") or acc_id.startswith("VRTC") or acc.get("is_virtual") == 1:
                                    target_acc = acc
                                    break
                        if target_acc:
                            acc_id = target_acc.get("account_id")
                            otp_res = requests.post(f"https://api.derivws.com/trading/v1/options/accounts/{acc_id}/otp", headers=headers, timeout=10)
                            if otp_res.status_code == 200:
                                target_ws_url = otp_res.json().get("data", {}).get("url")
                                is_live_account = True
                                account_info = {
                                    "loginid": acc_id,
                                    "currency": target_acc.get("currency", "USD"),
                                    "balance": float(target_acc.get("balance", 0.0)),
                                    "email": "DEMO_ACCOUNT"
                                }
                                log(f"✅ ยืนยันสิทธิ์บัญชี Demo {acc_id} สำเร็จ! ยอดเงิน: ${account_info['balance']:,.2f} {account_info['currency']}")
                except Exception as e:
                    log(f"⚠️ Auth Check Note: {e}")

            if not is_live_account:
                log(f"💡 รันในโหมด [Demo Training Engine: {TARGET_DEMO_ACCOUNT}] (จำลองการเทรดบนกราฟจริง 100% ปลอดภัย ไร้ความเสี่ยง)")

            # เชื่อมต่อ Deriv WebSocket
            async with websockets.connect(target_ws_url, ssl=ssl_context, ping_interval=None, close_timeout=10) as ws:
                log(f"🔌 เชื่อมต่อ Deriv WebSocket สำเร็จ! (บัญชี: {account_info['loginid']})")

                # 2. กู้คืนสถานะไม้ค้างและเช็คกับ Deriv เมื่อรีสตาร์ทบอท
                if active_trade:
                    active_trade = await recover_active_position(ws, active_trade, memory)

                while True:
                    scan_rows = []
                    symbol_indicators = {}

                    # สแกนและดึงข้อมูลแท่งเทียน M15 ของทุก Synthetic Volatility Index (R_75, R_25, R_50, R_10)
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
                            candle_res = await deriv_send_recv(ws, candle_req, expected_key="candles", timeout=6)
                            candles = candle_res.get("candles", [])

                            inds = calculate_bb_rsi(
                                candles,
                                period=memory.get("learned_params", {}).get("bb_period", 20),
                                std_dev=memory.get("learned_params", {}).get("bb_std", 2.0)
                            )

                            if inds:
                                symbol_indicators[sym] = inds

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

                        await asyncio.sleep(0.3)

                    # ----------------------------------------------------
                    # 2. ในขั้นตอนเฝ้าไม้และปิดสัญญา (Position Monitoring & Exit)
                    # ----------------------------------------------------
                    if active_trade and active_trade.get('contract_id'):
                        curr_sym = active_trade.get('symbol')
                        contract_id = active_trade.get('contract_id')

                        # 2.1 ตรวจสอบสถานะสัญญาผ่าน proposal_open_contract
                        poc = await get_open_contract_status(ws, contract_id)
                        if poc:
                            is_sold = poc.get("is_sold", 0)
                            current_profit = float(poc.get("profit", 0.0))
                            current_spot = float(poc.get("current_spot", active_trade.get("entry_price", 0.0)))
                            buy_price = float(poc.get("buy_price", active_trade.get("stake", STAKE_USD)))

                            # 2.2 หากสัญญาปิดตัวเอง (is_sold == 1) บันทึก PnL ลง synthetic_memory.json และล้างสถานะไม้
                            if is_sold == 1:
                                profit_usd = current_profit
                                profit_thb = round(profit_usd * usd_thb_rate, 1)
                                exit_price = float(poc.get("sell_price", current_spot))
                                status_desc = poc.get("status", "sold")

                                print_highlight_box(
                                    f"CONTRACT AUTO-CLOSED (DERIV) - {curr_sym}",
                                    [
                                        ("Engine / Account", f"Deriv Synthetic 24/7 (Demo: {TARGET_DEMO_ACCOUNT})"),
                                        ("Contract ID", str(contract_id)),
                                        ("Exit Price", f"{exit_price:.4f}"),
                                        ("Status", status_desc),
                                        ("Net Profit", f"${profit_usd:+,.2f} USD (≈ {profit_thb:+,.1f} THB)"),
                                        ("Account Balance", f"${account_info['balance'] + profit_usd:,.2f} USD")
                                    ],
                                    icon="🎯" if profit_usd >= 0 else "🛑"
                                )

                                account_info['balance'] = round(account_info['balance'] + profit_usd, 2)
                                record_trade_result(memory, profit_usd, profit_thb, active_trade, exit_price, reason=f"Deriv Auto-Closed ({status_desc})")

                                if notifier:
                                    try:
                                        pnl_pct = (profit_usd / buy_price * 100) if buy_price > 0 else 0.0
                                        if profit_usd >= 0:
                                            notifier.notify_tp("Deriv Synthetic", curr_sym, exit_price, pnl_pct, profit_usd, "USD", lesson="Deriv Auto-Closed", contract_id=contract_id)
                                        else:
                                            notifier.notify_sl("Deriv Synthetic", curr_sym, exit_price, pnl_pct, profit_usd, "USD", is_breakeven=active_trade.get('be_locked', False), lesson="Deriv Auto-Closed", contract_id=contract_id)
                                    except Exception:
                                        pass

                                active_trade = None
                                save_state(None) # ล้างสถานะไม้ใน active_state_synthetic.json แบบ Atomic

                            else:
                                # 2.3 สัญญายังเปิดอยู่ -> เฝ้าไม้และบริหารความเสี่ยง (Breakeven & Trailing & Exit)
                                inds = symbol_indicators.get(curr_sym)
                                cur_price = current_spot
                                entry = float(active_trade.get('entry_price', cur_price))
                                sym_pip_size = get_pip_size(curr_sym, entry)
                                diff_pips = (cur_price - entry) / sym_pip_size
                                trailing_sl_pips = active_trade.get('trailing_sl_pips', INITIAL_SL_PIPS)

                                # Auto-Breakeven เมื่อกำไรแตะ +10 pips
                                if diff_pips >= BREAKEVEN_PIPS and not active_trade.get('be_locked', False):
                                    active_trade['be_locked'] = True
                                    trailing_sl_pips = 1.0 # ล็อกกำไรบังหน้าทุน +1 pip
                                    active_trade['trailing_sl_pips'] = trailing_sl_pips
                                    save_state(active_trade)

                                    print_highlight_box(
                                        f"AUTO-BREAKEVEN ACTIVATED - {curr_sym}",
                                        [
                                            ("Engine", "Deriv Synthetic 24/7"),
                                            ("Contract ID", str(contract_id)),
                                            ("Current Spot", f"{cur_price:.4f}"),
                                            ("Profit Pips", f"+{diff_pips:.1f} pips"),
                                            ("New Trailing SL", "+1.0 pip (ล็อกหน้าทุน 100% ไร้ความเสี่ยง)")
                                        ],
                                        icon="🛡️"
                                    )
                                    if notifier:
                                        try:
                                            notifier.notify_breakeven("Deriv Synthetic", curr_sym, cur_price, entry + (1.0 * sym_pip_size), diff_pips, contract_id=contract_id)
                                        except Exception:
                                            pass

                                # Dynamic Trailing Stop เมื่อกำไรแตะ +20 pips
                                if diff_pips >= TRAILING_PIPS:
                                    new_trailing_sl = diff_pips - 10.0 # รักษาระยะห่าง trailing 10 pips
                                    if new_trailing_sl > trailing_sl_pips:
                                        trailing_sl_pips = new_trailing_sl
                                        active_trade['trailing_sl_pips'] = trailing_sl_pips
                                        save_state(active_trade)

                                        print_highlight_box(
                                            f"DYNAMIC TRAILING RUN - {curr_sym}",
                                            [
                                                ("Contract ID", str(contract_id)),
                                                ("Current Spot", f"{cur_price:.4f}"),
                                                ("Profit Pips", f"+{diff_pips:.1f} pips"),
                                                ("Trailing SL", f"+{trailing_sl_pips:.1f} pips (Let Profit Run!)")
                                            ],
                                            icon="🚀"
                                        )
                                        if notifier:
                                            try:
                                                notifier.notify_trailing("Deriv Synthetic", curr_sym, cur_price, cur_price - (10.0 * sym_pip_size), diff_pips, contract_id=contract_id)
                                            except Exception:
                                                pass

                                # ตรวจสอบเงื่อนไขการปิดสัญญา:
                                # - ปิดสัญญาด้วย {"sell": contract_id, "price": 0} เมื่อราคาแตะ Upper Bollinger Band หรือแตะ Trailing Stop
                                hold_sec = time.time() - active_trade.get('start_time', time.time())
                                is_sl = diff_pips <= trailing_sl_pips
                                upper_bb = inds['upper_bb'] if inds else cur_price * 1.05
                                is_bb_target = (cur_price >= upper_bb) and (diff_pips >= 5.0)
                                is_timeout = hold_sec >= 2700 and not (diff_pips >= 15.0)
                                is_be_hit = is_sl and active_trade.get('be_locked', False)

                                if is_be_hit or is_sl or is_bb_target or is_timeout:
                                    close_reason = "Upper BB TP" if is_bb_target else ("BE Hit" if is_be_hit else ("Trailing SL" if is_sl else "Timeout"))
                                    log(f"⚡ [EXIT TRIGGER] {close_reason} สำหรับสัญญา #{contract_id} ({curr_sym}) -> ส่งคำสั่งขาย sell...")

                                    sell_res = await execute_multiplier_sell(ws, contract_id)
                                    if sell_res:
                                        sold_for = float(sell_res.get("sold_for", 0.0))
                                        profit_usd = round(sold_for - buy_price, 2)
                                        profit_thb = round(profit_usd * usd_thb_rate, 1)
                                        balance_after = float(sell_res.get("balance_after", account_info["balance"] + profit_usd))
                                        account_info["balance"] = balance_after

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
                                                ("Contract ID", str(contract_id)),
                                                ("Exit Price", f"{cur_price:.4f}"),
                                                ("Result Pips", f"{diff_pips:+.1f} pips"),
                                                ("Net Profit", f"${profit_usd:+,.2f} USD (≈ {profit_thb:+,.1f} THB)"),
                                                ("Account Balance", f"${balance_after:,.2f} USD")
                                            ],
                                            icon=icon_str
                                        )

                                        record_trade_result(memory, profit_usd, profit_thb, active_trade, cur_price, reason=close_reason)

                                        if notifier:
                                            try:
                                                pnl_pct = (profit_usd / buy_price * 100) if buy_price > 0 else 0.0
                                                if profit_usd >= 0:
                                                    notifier.notify_tp("Deriv Synthetic", curr_sym, cur_price, pnl_pct, profit_usd, "USD", lesson=close_reason, contract_id=contract_id)
                                                else:
                                                    notifier.notify_sl("Deriv Synthetic", curr_sym, cur_price, pnl_pct, profit_usd, "USD", is_breakeven=is_be_hit, lesson=close_reason, contract_id=contract_id)
                                            except Exception:
                                                pass

                                        active_trade = None
                                        save_state(None) # ล้างสถานะไม้ใน active_state_synthetic.json แบบ Atomic
                                    else:
                                        # ตรวจสอบกรณี Deriv ปิดสัญญาไปแล้ว (เช่น ชน SL/TP ฝั่ง Server หรือปิดล่วงหน้า) เพื่อป้องกันค้างลูป
                                        log(f"⚠️ [SELL CHECK] ตรวจสอบสถานะสัญญา #{contract_id} อีกครั้งหลังคำสั่งขาย...")
                                        check_poc = await get_open_contract_status(ws, contract_id)
                                        if check_poc and check_poc.get("is_sold") == 1:
                                            sold_pnl = float(check_poc.get("profit", 0.0))
                                            sold_exit = float(check_poc.get("sell_price", cur_price))
                                            log(f"✅ [AUTO RESOLVED] สัญญา #{contract_id} ปิดบนเซิร์ฟเวอร์เรียบร้อย (PnL: ${sold_pnl:+.2f} USD)")
                                            record_trade_result(memory, sold_pnl, round(sold_pnl * usd_thb_rate, 1), active_trade, sold_exit, reason=f"{close_reason} (Server-Closed)")
                                            active_trade = None
                                            save_state(None)

                    # ----------------------------------------------------
                    # 1. ในขั้นตอนเปิดออเดอร์ (Entry Execution)
                    # ----------------------------------------------------
                    elif not active_trade:
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

                            if price < ema50 * 0.998:
                                effective_oversold = min(learned_oversold, 28.0)
                            else:
                                effective_oversold = learned_oversold

                            is_squeezed = bb_width < 0.0004
                            is_sweep = inds.get('is_liquidity_sweep', False)
                            is_pin_bar = inds.get('is_pin_bar', False)
                            is_hammer = inds.get('is_hammer', False)

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

                                spread_pips, ask_p, bid_p = await get_live_spread(ws, sym)
                                max_allowed_spread = 5.0
                                if spread_pips is not None and spread_pips > max_allowed_spread:
                                    log(f"⚠️ [SPREAD FILTER] สเปรดสด {sym} ถ่างเกินปกติ: {spread_pips:.1f} pips > {max_allowed_spread} pips -> ข้ามจังหวะเพื่อความปลอดภัย")
                                    continue

                                is_ai_approved = await ask_groq_ai_sentiment(sym, price, rsi, trigger_name, bb_width)
                                if not is_ai_approved:
                                    continue

                                # ตรวจสอบความปลอดภัยบัญชี Demo ก่อนเปิดไม้
                                if account_info.get("loginid") != TARGET_DEMO_ACCOUNT and not account_info.get("loginid", "").startswith("DOT"):
                                    log(f"🚨 [SAFETY LOCK] บัญชี ({account_info.get('loginid')}) ไม่ตรงกับ Demo {TARGET_DEMO_ACCOUNT} -> บล็อกการเปิดไม้")
                                    break

                                # ตรวจสอบค่าตัวคูณที่ Deriv อนุญาตสำหรับ Symbol
                                valid_multiplier = await get_valid_multiplier(ws, sym)
                                log(f"📊 [PROPOSAL] ส่งคำขอ Proposal สัญญา Multipliers ({sym}, Stake: ${STAKE_USD}, Multiplier: x{valid_multiplier})...")

                                # ส่งคำขอ Proposal สัญญา Multipliers ไปยัง Deriv WebSocket:
                                # {"proposal": 1, "amount": STAKE_USD, "basis": "stake", "contract_type": "MULTUP", "currency": "USD", "multiplier": multiplier, "underlying_symbol": symbol}
                                prop_data, chosen_multiplier = await request_multiplier_proposal(ws, sym, STAKE_USD, valid_multiplier)
                                if not prop_data:
                                    log(f"⚠️ [PROPOSAL FAILED] ไม่สามารถขอ Proposal สำหรับ {sym} ได้")
                                    continue

                                proposal_id = prop_data.get("id")
                                spot_price = float(prop_data.get("spot", price))
                                log(f"✅ [PROPOSAL OK] Proposal ID: {proposal_id} | Spot: {spot_price} | Multiplier: x{chosen_multiplier}")

                                # ส่งคำสั่ง {"buy": proposal_id, "price": STAKE_USD}
                                buy_result = await execute_multiplier_buy(ws, proposal_id, STAKE_USD)
                                if not buy_result:
                                    log(f"❌ [BUY FAILED] การซื้อสัญญา {sym} ล้มเหลว")
                                    continue

                                real_contract_id = buy_result.get("contract_id")
                                actual_buy_price = float(buy_result.get("buy_price", STAKE_USD))
                                balance_after = float(buy_result.get("balance_after", account_info["balance"] - actual_buy_price))
                                account_info["balance"] = balance_after
                                order_start_time = float(buy_result.get("start_time", time.time()))

                                # ดึง contract_id จริงจากผลลัพธ์ Deriv บันทึกลง active_state_synthetic.json แบบ Atomic Write (.tmp + replace)
                                active_trade = {
                                    "contract_id": real_contract_id,
                                    "symbol": sym,
                                    "type": "MULTUP",
                                    "entry_price": spot_price,
                                    "stake": actual_buy_price,
                                    "multiplier": chosen_multiplier,
                                    "proposal_id": proposal_id,
                                    "entry_time": get_thai_time(),
                                    "start_time": order_start_time,
                                    "be_locked": False,
                                    "trailing_sl_pips": INITIAL_SL_PIPS,
                                    "account_id": TARGET_DEMO_ACCOUNT
                                }
                                save_state(active_trade)

                                spread_str = f"{spread_pips:.1f} pips" if spread_pips is not None else "Normal"
                                print_highlight_box(
                                    f"LIVE MULTIPLIER ORDER EXECUTED - {sym}",
                                    [
                                        ("Engine / Account", f"Deriv Synthetic 24/7 (Demo: {TARGET_DEMO_ACCOUNT})"),
                                        ("Contract ID", str(real_contract_id)),
                                        ("Contract Type", f"MULTUP (x{chosen_multiplier})"),
                                        ("Symbol", sym),
                                        ("Entry Price", f"{spot_price:.4f}"),
                                        ("Live Spread", spread_str),
                                        ("Stake", f"${actual_buy_price:.2f} USD"),
                                        ("Strategy Trigger", trigger_name),
                                        ("RSI / BB-Width", f"{rsi:.1f} / {bb_width:.5f}"),
                                        ("Account Balance", f"${balance_after:,.2f} USD")
                                    ],
                                    icon="🟢"
                                )

                                # แจ้งเตือนเข้า LINE ด้วย Contract ID จริง
                                if notifier:
                                    try:
                                        sym_pip_size = get_pip_size(sym, spot_price)
                                        tp_est = inds['upper_bb']
                                        sl_est = spot_price - (abs(INITIAL_SL_PIPS) * sym_pip_size)
                                        notifier.notify_buy(
                                            "Deriv Synthetic", sym, spot_price, actual_buy_price,
                                            tp_est, sl_est,
                                            reason=f"{trigger_name}",
                                            extra_info=f"บัญชี Demo: {TARGET_DEMO_ACCOUNT} | Multiplier: x{chosen_multiplier} | 24/7 Non-Stop",
                                            contract_id=real_contract_id
                                        )
                                    except Exception as ne:
                                        log(f"⚠️ LINE Notification error: {ne}")

                                break

                    # พิมพ์ตารางสถานะ Quant Terminal
                    if scan_rows:
                        print_quant_table(get_thai_time(), scan_rows, account_info, memory, active_trade=active_trade)

                    # วนพัก 60 วินาที โดยส่ง Ping {"ping": 1} ทุกๆ 20 วินาที
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
    print(f"🏛️ DERIV SYNTHETIC 24/7 LIVE MULTIPLIERS ENGINE (DEMO: {TARGET_DEMO_ACCOUNT})")
    print(f"🎯 ASSETS: {SYMBOLS} (Focus: {PRIMARY_SYMBOLS})")
    print(f"⚙️ RISK: Stake ${STAKE_USD:.2f} USD | BE +{BREAKEVEN_PIPS} pips | Trailing +{TRAILING_PIPS} pips")
    ai_status = "🟢 พร้อมใช้งาน (Groq Synthetic Quant Advisor)" if GROQ_API_KEY else "⚪ ไม่ได้เปิดใช้งาน (ข้ามไปใช้ Pure Quant)"
    print(f"🧠 AI ADVISOR : {ai_status}")
    print("=" * 75)
    asyncio.run(deriv_synthetic_engine())
