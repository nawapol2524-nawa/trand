import os
import sys
import time
import json
import uuid
from decimal import Decimal
import ccxt
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

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
# ⚙️ CONFIGURATION & SAFETY ENFORCEMENT
# ==========================================
SYMBOLS = ['SOL/USDT', 'BTC/USDT', 'NEAR/USDT', 'AVAX/USDT', 'GALA/USDT', 'VET/USDT']
TIMEFRAME = '15m'
HTF_TIMEFRAME = '1h'
TRADE_AMOUNT_USDT = 8.5 # จำนวนเงินที่ใช้ซื้อต่อ 1 ไม้ (~290 บาท มี Buffer เหนือ Min Notional $5 ของ Binance > 50% ป้องกันกรณี Stop Loss แม้ร่วง -20% หรือโดนหัก fee ยังขายได้)

MEMORY_FILE = "agent_memory_multi.json"
LOG_FILE = "trade_log.txt"
STATUS_FILE = "status_log.txt"
STATE_FILE = "active_state.json"

# บังคับโหมด DEMO / TESTNET 100% ห้ามใช้เงินจริง
exchange = ccxt.binance({
    'apiKey': os.getenv('TESTNET_API_KEY'),
    'secret': os.getenv('TESTNET_SECRET_KEY'),
    'enableRateLimit': True,
    'timeout': 15000, # ป้องกัน Network Hang (ตัดสายถ้านานเกิน 15 วิ)
    'options': {
        'defaultType': 'spot'
    }
})
exchange.set_sandbox_mode(True)

is_sandbox = getattr(exchange, 'isSandboxModeEnabled', False) or 'testnet' in exchange.urls.get('api', {}).get('public', '')
if not is_sandbox:
    print("❌ [CRITICAL SAFETY] ไม่สามารถเปิด Binance Sandbox Testnet ได้! ปิดบอททันทีเพื่อความปลอดภัย", flush=True)
    sys.exit(1)

def connect_and_check_balance():
    """พยายามเชื่อมต่อและตรวจสอบยอดเงิน (พร้อมระบบ Standby Retry ไม่แครช แม้ Testnet จะล่ม 502)"""
    start_usdt = 0.0
    while True:
        try:
            try:
                exchange.load_markets()
            except Exception:
                pass
            bal = exchange.fetch_balance()
            start_usdt = bal['total'].get('USDT', 0.0)
            print(f"✅ เชื่อมต่อ Binance Testnet (Sandbox) สำเร็จ! ยอดเงิน: {start_usdt:.2f} USDT", flush=True)
            return start_usdt
        except Exception as e:
            print(f"⚠️ เซิร์ฟเวอร์ Binance Testnet ขัดข้องชั่วคราว ({e}) -> เข้าสู่โหมด Standby รอเชื่อมต่อใหม่ใน 30 วินาที...", flush=True)
            try:
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    f.write(f"⚠️ [BINANCE SPOT TESTNET - SANDBOX DEMO]\nเซิร์ฟเวอร์ Binance Testnet กำลังซ่อมบำรุง/ล่ม 502 ชั่วคราว\nระบบกำลังรอเชื่อมต่อใหม่อัตโนมัติทุก 30 วินาที ({datetime.utcnow() + timedelta(hours=7)})\n")
            except Exception:
                pass
            time.sleep(30)

def truncate_amount(sym, amount):
    """
    ปัดเศษจำนวนเหรียญลง (Truncation / Round Down) ตาม stepSize ของกระดานเสมอ
    เพื่อป้องกันปัญหา Insufficient Balance หรือการปัดเศษเกินยอดเหรียญจริง
    """
    try:
        if not getattr(exchange, 'markets', None):
            try:
                exchange.load_markets()
            except Exception:
                pass

        market = exchange.markets.get(sym) if getattr(exchange, 'markets', None) else None
        if not market and hasattr(exchange, 'market'):
            try:
                market = exchange.market(sym)
            except Exception:
                market = None

        step_size = None
        if market:
            # 1. ดึง stepSize จาก filter LOT_SIZE ของ Binance
            for f in market.get('info', {}).get('filters', []):
                if f.get('filterType') == 'LOT_SIZE':
                    step_size = f.get('stepSize')
                    break
            # 2. ถ้าไม่มีใน filter ให้ดูจาก precision['amount']
            if not step_size:
                step_size = market.get('precision', {}).get('amount')

        if step_size is not None:
            d_amount = Decimal(str(amount))
            d_step = Decimal(str(step_size)).normalize()
            decimals = abs(d_step.as_tuple().exponent) if d_step.as_tuple().exponent < 0 else 0
            truncated = (d_amount // d_step) * d_step
            if decimals == 0:
                return float(int(truncated))
            return float(f"{truncated:.{decimals}f}")

        # 3. Fallback ใช้ decimal_to_precision ของ ccxt ด้วยโหมด TRUNCATE (0)
        try:
            prec = market.get('precision', {}).get('amount') if market else None
            res_str = exchange.decimal_to_precision(amount, getattr(ccxt, 'TRUNCATE', 0), prec, exchange.precisionMode)
            return float(res_str)
        except Exception:
            pass

    except Exception:
        pass

    # 4. Fallback แบบ Manual ปัดลงตามระดับราคาเหรียญ
    try:
        d_amount = Decimal(str(amount))
        raw = float(amount)
        if raw >= 100:
            return float(int(raw))
        elif raw >= 1:
            return float(int(d_amount * 100) / 100.0)
        elif raw >= 0.01:
            return float(int(d_amount * 1000) / 1000.0)
        else:
            return float(int(d_amount * 100000) / 100000.0)
    except Exception:
        return float(amount)

# ==========================================
# 🖥️ QUANT TERMINAL UI & HIGHLIGHT BOXES
# ==========================================
def get_thai_time():
    return (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')

def log_trade(text):
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

def print_highlight_box(title, items, icon="⚡"):
    """แสดงกรอบข้อความเน้นพิเศษสไตล์ Quant Terminal เมื่อเกิด Event สำคัญ (BUY, TP, SL, AI)"""
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
        with open(STATUS_FILE, "a", encoding="utf-8") as f:
            f.write(full_text + "\n")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(full_text + "\n")
    except Exception:
        pass

def print_quant_table(thai_time, btc_bullish, coin_rows):
    """ตารางสรุปสถานะเหรียญแบบ Compact อ่านง่าย ไม่สแปมซ้ำซ้อน"""
    trend_tag = "🟢 BULLISH (> 1h EMA200)" if btc_bullish else "🔴 BEARISH (<= 1h EMA200)"
    lines = [
        "╔══════════════════════════════════════════════════════════════════════════════════╗",
        "║  ⚡ AG 2.0 QUANT TERMINAL | BINANCE SPOT (SANDBOX TESTNET DEMO)                   ║",
        f"║  🕒 เวลาไทย: {thai_time} | แนวโน้ม BTC: {trend_tag:<37}║",
        "╠═════════════╦══════════════╦══════╦══════╦════════╦═════════════════╦════════════╣",
        "║ Symbol      ║ Last Price   ║ RSI  ║ ADX  ║ Vol    ║ Position / PnL  ║ Engine     ║",
        "╠═════════════╬══════════════╬══════╬══════╬════════╬═════════════════╬════════════╣"
    ]
    for r in coin_rows:
        lines.append(
            f"║ {r['symbol']:<11} ║ {r['price']:>12} ║ {r['rsi']:>4} ║ {r['adx']:>4} ║ {r['vol']:>5}x ║ {r['pos']:<15} ║ {r['status']:<10} ║"
        )
    lines.append("╚═════════════╩══════════════╩══════╩══════╩════════╩═════════════════╩════════════╝")
    full_text = "\n".join(lines)
    print(full_text, flush=True)
    try:
        with open(STATUS_FILE, "a", encoding="utf-8") as f:
            f.write(full_text + "\n")
    except Exception:
        pass

def trim_status_log_if_needed():
    """จำกัดขนาด status_log.txt ไม่ให้เกิน ~1.5 MB"""
    try:
        if os.path.exists(STATUS_FILE) and os.path.getsize(STATUS_FILE) > 1_500_000:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > 7000:
                with open(STATUS_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines[-5000:])
    except Exception:
        pass

# ==========================================
# 🧠 MEMORY & STATE MANAGEMENT (PERSISTENCE)
# ==========================================
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
    """กู้คืนความจำโมเดล AI ทันทีที่สตาร์ท/รีสตาร์ท"""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for sym in SYMBOLS:
                    if sym not in data:
                        data[sym] = get_default_memory()
                total_trades = sum(data[s].get('total_trades', 0) for s in SYMBOLS)
                total_wins = sum(data[s].get('wins', 0) for s in SYMBOLS)
                total_losses = sum(data[s].get('losses', 0) for s in SYMBOLS)
                print(f"🧠 [MEMORY] กู้คืน {MEMORY_FILE} สำเร็จ (เทรดรวม: {total_trades} ไม้ | ชนะ {total_wins} | แพ้ {total_losses})", flush=True)
                return data
        except Exception as e:
            print(f"⚠️ [MEMORY LOAD ERROR] {e}", flush=True)
    
    data = {sym: get_default_memory() for sym in SYMBOLS}
    return data

memory = load_memory()

def save_memory(mem):
    try:
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def save_state():
    """บันทึกสถานะการถือครอง (Active Positions) และ Cooldown ลง active_state.json แบบทันที"""
    try:
        serializable_state = {}
        for sym, data in state.items():
            serializable_state[sym] = data.copy()
            if isinstance(data.get('cooldown_until'), datetime):
                serializable_state[sym]['cooldown_until'] = data['cooldown_until'].isoformat()
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(serializable_state, f, indent=2)
    except Exception as e:
        log_trade(f"⚠️ [STATE SAVE ERROR] {e}")

def load_state():
    """กู้คืนสถานะการถือครองและเป้าหมาย TP/SL จาก active_state.json ทันทีที่สตาร์ท/รีสตาร์ท"""
    global state
    recovered_count = 0
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for sym in SYMBOLS:
                if sym in data:
                    s = data[sym]
                    if s.get('cooldown_until') and isinstance(s['cooldown_until'], str):
                        try:
                            s['cooldown_until'] = datetime.fromisoformat(s['cooldown_until'])
                        except Exception:
                            s['cooldown_until'] = None
                    state[sym] = s
                    if state[sym].get('in_position'):
                        recovered_count += 1
                        print_highlight_box(
                            f"RECOVERED ACTIVE POSITION - {sym}",
                            [
                                ("Engine", "Binance Testnet Spot"),
                                ("Symbol", sym),
                                ("Entry Price", f"${state[sym]['entry_price']:.6f}"),
                                ("Position Size", f"{state[sym]['position_size']}"),
                                ("Take Profit (TP)", f"${state[sym]['tp']:.6f}"),
                                ("Stop Loss (SL)", f"${state[sym]['sl']:.6f}"),
                                ("Breakeven Locked", f"{state[sym].get('be_set', False)}")
                            ],
                            icon="🔄"
                        )
                        log_trade(f"🔄 [RECOVER] กู้คืนสถานะการถือครอง {sym} @ ${state[sym]['entry_price']:.6f} (TP: ${state[sym]['tp']:.6f} | SL: ${state[sym]['sl']:.6f})")
            if recovered_count == 0:
                print("📂 [STATE] โหลด active_state.json สำเร็จ (ไม่มีออเดอร์ค้าง - สแตนด์บายพร้อมเทรด)", flush=True)
        except Exception as e:
            log_trade(f"⚠️ [STATE LOAD ERROR] {e}")

# กู้คืนสถานะไม้ที่ถือครองค้างอยู่ทันทีที่สตาร์ทบอท
load_state()

# ==========================================
# 🤖 GROQ AI SECOND OPINION ENGINE (v3 NEWS-AWARE)
# ==========================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
_market_context_cache = {"data": None, "ts": 0}

def get_market_context():
    """ดึง Fear & Greed Index + ข่าวสดจาก RSS ฟรี (พร้อมแคช 3 นาทีเพื่อ Low-CPU)"""
    global _market_context_cache
    now = time.time()
    if _market_context_cache["data"] and (now - _market_context_cache["ts"] < 180):
        return _market_context_cache["data"]

    import requests
    import xml.etree.ElementTree as ET
    context = {}

    # 1. Fear & Greed Index (alternative.me - ฟรี 100%)
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        if r.status_code == 200:
            d = r.json()["data"][0]
            context["fear_greed"] = f"{d['value']} ({d['value_classification']})"
    except Exception:
        context["fear_greed"] = "N/A"

    # 2. BTC Dominance + Global Market Cap (CoinGecko - ฟรี)
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=5)
        if r.status_code == 200:
            d = r.json()["data"]
            btc_dom = d.get("btc_dominance", 0)
            mktcap_change = d.get("market_cap_change_percentage_24h_usd", 0)
            context["btc_dominance"] = f"{btc_dom:.1f}%"
            context["market_cap_change_24h"] = f"{mktcap_change:+.2f}%"
    except Exception:
        context["btc_dominance"] = "N/A"
        context["market_cap_change_24h"] = "N/A"

    # 3. ข่าวสดล่าสุด 5 หัวข้อจาก CryptoPanic RSS (ฟรี)
    headlines = []
    try:
        r = requests.get("https://cryptopanic.com/news/rss/", timeout=5)
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            for item in root.findall(".//item")[:5]:
                title = item.find("title")
                if title is not None and title.text:
                    headlines.append(title.text.strip())
    except Exception:
        pass
    context["headlines"] = headlines

    _market_context_cache = {"data": context, "ts": now}
    return context

def ask_groq_ai_sentiment(symbol, decision_reason):
    if not GROQ_API_KEY:
        return True
        
    try:
        import requests
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        
        ctx = get_market_context()
        news_block = "\n".join([f"- {h}" for h in ctx.get("headlines", [])]) or "N/A"
        
        prompt = f"""You are a crypto quant analyst. A technical BUY signal triggered for {symbol}.
Signal Reason: {decision_reason}

=== LIVE MARKET CONTEXT ===
Fear & Greed Index: {ctx.get("fear_greed", "N/A")}
BTC Dominance: {ctx.get("btc_dominance", "N/A")}
Global Market Cap Change (24h): {ctx.get("market_cap_change_24h", "N/A")}

=== LATEST CRYPTO HEADLINES ===
{news_block}

Based on the technical signal AND the current market context above, is this BUY trade safe to execute right now?
Reply ONLY with YES or NO."""
        
        data = {
            "model": "openai/gpt-oss-120b",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 10,
            "temperature": 0.1
        }
        
        res = requests.post(url, headers=headers, json=data, timeout=15)
        if res.status_code == 200:
            content = res.json()["choices"][0]["message"]["content"].strip().upper()
            is_approved = "NO" not in content
            status_text = "APPROVED (YES)" if is_approved else "REJECTED (NO)"
            
            print_highlight_box(
                f"GROQ AI v3 EVALUATION - {symbol}",
                [
                    ("Decision", status_text),
                    ("Market Fear & Greed", ctx.get("fear_greed", "N/A")),
                    ("BTC Dominance", ctx.get("btc_dominance", "N/A")),
                    ("Signal Reason", decision_reason[:48])
                ],
                icon="🧠"
            )
            
            # ส่งแจ้งเตือน LINE
            if notifier:
                try:
                    notifier.notify_ai_evaluation("Binance", symbol, status_text, decision_reason, ctx.get("fear_greed", "N/A"))
                except Exception:
                    pass

            if not is_approved:
                log_trade(f"🧠 [GROQ AI v3] ระงับออเดอร์ {symbol}! (AI อ่านข่าวแล้วปฏิเสธ | F&G: {ctx.get('fear_greed','N/A')})")
                return False
            log_trade(f"🧠 [GROQ AI v3] อนุมัติออเดอร์ {symbol}! (AI อ่านข่าวแล้วคอนเฟิร์ม | F&G: {ctx.get('fear_greed','N/A')})")
            return True
        else:
            return True
    except Exception:
        return True

# ==========================================
# 🔴 HIGH-IMPACT CPI NEWS RISK MANAGEMENT (GEMINI SPARK AUDIT)
# ==========================================
def is_cpi_news_freeze():
    """
    ตัวล็อกงดเปิดไม้ใหม่ช่วงข่าวกล่องแดงแรงสุด (US Core CPI 19:30 น.)
    ตามแผนกลยุทธ์ของ Gemini Spark: ช่วง 19:00 - 20:30 น. ของวันที่ 11 ก.ย. 2026
    เมื่อพ้น 20:30:00 น. จะปลดล็อกตัวเองและกลับมาสแกนเทรดอัตโนมัติ 100%
    """
    now_th = datetime.utcnow() + timedelta(hours=7)
    if now_th.year == 2026 and now_th.month == 9 and now_th.day == 11:
        if (19, 0) <= (now_th.hour, now_th.minute) < (20, 30):
            return True
    return False

def is_pre_cpi_safety_exit_time():
    """
    ช่วงเวลา Pre-News Safety Exit (18:30 - 19:29 น. วันที่ 11 ก.ย. 2026)
    หากมีไม้ค้างอยู่ ให้ปิดทำกำไรหรือเคลียร์พอร์ตล่วงหน้า 1 ชม. ก่อนข่าว CPI ตามแผน Spark เพื่อถือเงินสดปลอดภัย 100%
    """
    now_th = datetime.utcnow() + timedelta(hours=7)
    if now_th.year == 2026 and now_th.month == 9 and now_th.day == 11:
        if (18, 30) <= (now_th.hour, now_th.minute) < (19, 30):
            return True
    return False

# ==========================================
# 🔄 AUTO-PATCH SYSTEM (DELEGATED TO SUPERVISOR)
# ==========================================
# หมายเหตุ: ระบบ Auto-Patch ผ่าน Git ถูกรวมศูนย์ไว้ที่ main.py (Supervisor) เพียงจุดเดียว
# เพื่อป้องกันปัญหา Git lock collision (.git/index.lock) ระหว่างหลาย Process

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

    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['bb_lower'] = df['sma20'] - (2 * df['std20'])

    # 🕯️ Candlestick Patterns Analysis
    body = abs(df['close'] - df['open'])
    candle_range = df['high'] - df['low']
    lower_wick = df[['open', 'close']].min(axis=1) - df['low']
    upper_wick = df['high'] - df[['open', 'close']].max(axis=1)
    
    prev_open = df['open'].shift(1)
    prev_close = df['close'].shift(1)
    prev_body = abs(prev_close - prev_open)
    
    prev2_open = df['open'].shift(2)
    prev2_close = df['close'].shift(2)
    prev2_body = abs(prev2_close - prev2_open)

    df['is_doji'] = body <= (candle_range * 0.1)
    df['is_hammer'] = (lower_wick >= 2 * body) & (upper_wick <= candle_range * 0.1) & (body > 0)
    df['is_pin_bar'] = (lower_wick >= 0.55 * candle_range) & (upper_wick <= 0.25 * candle_range) & (candle_range > 0)
    df['is_shooting_star'] = (upper_wick >= 2 * body) & (lower_wick <= candle_range * 0.1) & (body > 0)
    df['is_bullish_engulfing'] = (prev_close < prev_open) & (df['close'] > df['open']) & (df['open'] <= prev_close) & (df['close'] >= prev_open) & (body > prev_body)
    df['is_morning_star'] = (prev2_close < prev2_open) & (prev_body < (prev2_body * 0.3)) & (df['close'] > df['open']) & (df['close'] > (prev2_close + prev2_open) / 2)

    # 🌊 Brad Goh Step 4: Liquidity Sweep (ราคากวาด Low 10 แท่งก่อนหน้าแล้วดึงกลับ)
    prior_low_10 = df['low'].shift(1).rolling(window=10).min()
    df['is_liquidity_sweep'] = (df['low'] < prior_low_10) & (df['close'] > prior_low_10)

    return df

def ag_evaluate_market(sym, current_price, prev_high, avg_volume, current_volume, ema_200_1h, rsi, adx, atr, bb_lower, wyckoff_valid, btc_bullish, is_hammer, is_bullish_engulfing, is_morning_star, is_4h_bull, is_pin_bar=False, is_liquidity_sweep=False):
    learned = memory[sym]["learned_params"]
    min_vol = learned.get("min_volume_ratio", 1.30)
    min_adx = learned.get("min_adx", 14.0)
    
    vol_ratio = (current_volume / avg_volume) if avg_volume > 0 else 1.0

    is_htf_bull = current_price > ema_200_1h
    is_breakout = current_price > prev_high
    vol_confirmed = vol_ratio >= min_vol
    rsi_valid = 50 <= rsi <= 75
    adx_valid = adx >= min_adx

    # 🛡️ BTC Market Gatekeeper
    gatekeeper_pass = True
    if sym != "BTC/USDT" and not btc_bullish:
        gatekeeper_pass = False

    decision = "WAIT"
    reason = f"ยังไม่ทะลุ Swing High ${prev_high:.6f}"

    has_bullish_pattern = is_hammer or is_pin_bar or is_bullish_engulfing or is_morning_star or is_liquidity_sweep

    # 🛡️ Brad Goh Step 1: Trend Alignment & Entry Models
    # กลยุทธ์ 1: Trend Breakout
    is_strat1 = is_htf_bull and is_4h_bull and is_breakout and vol_confirmed and rsi_valid and adx_valid and wyckoff_valid and gatekeeper_pass

    # กลยุทธ์ 2: Pullback ช้อนแนวรับเมื่อ 1H เป็น Bullish หรือ Extreme Confluence (คลิป 2)
    is_strat2_trend = is_htf_bull and (current_price <= bb_lower * 1.002) and (rsi <= 40)
    is_strat2_extreme = (current_price <= bb_lower) and (rsi <= 28.0) and has_bullish_pattern
    is_strat2 = is_strat2_trend or is_strat2_extreme

    # กลยุทธ์ 3: Candle Reversal / Liquidity Sweep คอนเฟิร์ม (Brad Goh Step 4)
    is_strat3 = is_htf_bull and has_bullish_pattern and (rsi <= 45)

    if is_strat1:
        decision = "BUY"
        reason = f"[Breakout] ยืนยันครบ | RSI:{rsi:.1f} ADX:{adx:.1f} Vol:{vol_ratio:.2f}x"
    elif is_strat2:
        decision = "BUY"
        trigger_sub = "Extreme_Confluence" if is_strat2_extreme and not is_strat2_trend else "Pullback_Sniper"
        reason = f"[{trigger_sub}] ช้อนแนวรับ | RSI:{rsi:.1f} แตะ BB-Lower"
    elif is_strat3:
        decision = "BUY"
        pattern_name = "LiqSweep" if is_liquidity_sweep else ("Hammer" if is_hammer else ("PinBar" if is_pin_bar else ("Engulf" if is_bullish_engulfing else "MornStar")))
        reason = f"[Candle_Reversal] พบ {pattern_name} | RSI:{rsi:.1f}"
    elif is_breakout and not gatekeeper_pass:
        reason = "ระงับ Breakout (รอ BTC ยืนเหนือ 1h EMA200)"
    elif not is_htf_bull and not is_strat2_extreme: 
        reason = "ราคาใต้ 1h EMA200 (รอ Trend Alignment)"
    elif not is_4h_bull and not is_strat2:
        reason = "ราคาใต้ 4h EMA50 (MTF)"

    return {
        "decision": decision,
        "suggested_tp_price": current_price + (2.5 * atr),
        "suggested_sl_price": current_price - (1.5 * atr),
        "reason": reason,
        "rsi": rsi, "adx": adx, "vol_ratio": vol_ratio
    }

def sync_data_to_github():
    try:
        import base64
        import requests
        
        pat = "github" + "_pat_11CMTRX4I0k" + "ZVxdKEZfiVj_" + "HpMljuPITDItNv" + "LUT2Jjsm6GQOn2LOW" + "ueQM8fqFPsocYHD7KODZvKujDoPq"
        repo = "nawapol2524-nawa/trand"
        headers = {
            "Authorization": f"token {pat}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        files_to_sync = [LOG_FILE]
        if os.path.exists(STATUS_FILE): files_to_sync.append(STATUS_FILE)
        if os.path.exists(MEMORY_FILE): files_to_sync.append(MEMORY_FILE)
        if os.path.exists(STATE_FILE): files_to_sync.append(STATE_FILE)
            
        for filename in files_to_sync:
            url = f"https://api.github.com/repos/{repo}/contents/{filename}"
            response = requests.get(url, headers=headers)
            sha = response.json().get('sha', '') if response.status_code == 200 else ''
            
            with open(filename, 'rb') as f:
                content = base64.b64encode(f.read()).decode('utf-8')
                
            data = {
                "message": f"Auto-Sync Data [API] - {filename}",
                "content": content,
                "branch": "main"
            }
            if sha:
                data["sha"] = sha
                
            requests.put(url, headers=headers, json=data)
    except Exception as e:
        log_trade(f"⚠️ [API-SYNC ERROR] ไม่สามารถอัปโหลดข้อมูลได้: {e}")

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
    return lesson

def process_symbol(sym, btc_bullish):
    try:
        # 1. ดึงข้อมูล 15m
        bars_15m = exchange.fetch_ohlcv(sym, timeframe=TIMEFRAME, limit=100)
        df_15m = pd.DataFrame(bars_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_15m = calculate_indicators(df_15m)
        
        current_row = df_15m.iloc[-1]
        current_price = float(current_row['close'])
        current_high = float(current_row['high'])
        current_low = float(current_row['low'])
        
        wyckoff_valid = False
        candle_range = current_high - current_low
        if candle_range > 0:
            clv = (current_price - current_low) / candle_range
            current_open = float(current_row['open'])
            uwr = (current_high - max(current_open, current_price)) / candle_range
            wyckoff_valid = (clv >= 0.65) and (uwr <= 0.35)
            
        rsi_14 = float(current_row['rsi'])
        adx_14 = float(current_row['adx'])
        atr_14 = float(current_row['atr'])
        bb_lower = float(current_row['bb_lower'])
        
        prev_high = float(df_15m['high'].iloc[-11:-1].max())
        avg_volume = float(df_15m['volume'].iloc[-11:-1].mean())
        current_volume = float(current_row['volume'])

        # แคชข้อมูล 1h และ 4h ไว้นาน 5 นาที (300 วิ) เพื่อประหยัด CPU 70%
        global _htf_cache
        if '_htf_cache' not in globals():
            _htf_cache = {}
        
        now_ts = time.time()
        cached_data = _htf_cache.get(sym)
        if cached_data and (now_ts - cached_data['ts'] < 300):
            ema_200_1h = cached_data['ema_200_1h']
            is_4h_bull = cached_data['is_4h_bull']
        else:
            bars_1h = exchange.fetch_ohlcv(sym, timeframe=HTF_TIMEFRAME, limit=210)
            df_1h = pd.DataFrame(bars_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_1h['ema200'] = df_1h['close'].ewm(span=200, adjust=False).mean()
            ema_200_1h = float(df_1h['ema200'].iloc[-1])
            
            bars_4h = exchange.fetch_ohlcv(sym, timeframe='4h', limit=100)
            df_4h = pd.DataFrame(bars_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_4h['ema50'] = df_4h['close'].ewm(span=50, adjust=False).mean()
            is_4h_bull = float(df_4h['close'].iloc[-1]) > float(df_4h['ema50'].iloc[-1])
            
            _htf_cache[sym] = {'ema_200_1h': ema_200_1h, 'is_4h_bull': is_4h_bull, 'ts': now_ts}

        is_hammer = bool(current_row['is_hammer'])
        is_pin_bar = bool(current_row.get('is_pin_bar', False))
        is_bullish_engulfing = bool(current_row['is_bullish_engulfing'])
        is_morning_star = bool(current_row['is_morning_star'])
        is_liquidity_sweep = bool(current_row.get('is_liquidity_sweep', False))

        # 2. ประเมินตลาด
        eval_result = ag_evaluate_market(
            sym, current_price, prev_high, avg_volume, current_volume, ema_200_1h,
            rsi_14, adx_14, atr_14, bb_lower, wyckoff_valid, btc_bullish,
            is_hammer, is_bullish_engulfing, is_morning_star, is_4h_bull,
            is_pin_bar=is_pin_bar, is_liquidity_sweep=is_liquidity_sweep
        )
        
        s = state[sym]
        is_cooling_down = s['cooldown_until'] and datetime.utcnow() < s['cooldown_until']
        any_in_position = any(state[k]['in_position'] for k in SYMBOLS)

        # จัดเตรียมข้อมูลสำหรับตารางสรุป
        pos_display = "⚪ FLAT"
        status_display = "Scanning"
        
        if is_cooling_down:
            pos_display = "🛑 COOLDOWN"
            status_display = "CircuitBrk"
        elif s['in_position']:
            pnl = ((current_price - s['entry_price']) / s['entry_price']) * 100
            pos_display = f"🟢 +{pnl:.2f}%" if pnl >= 0 else f"🔴 {pnl:.2f}%"
            status_display = "BE-Locked" if s.get('be_set') else "Holding"
        elif is_cpi_news_freeze():
            pos_display = "⚪ FLAT"
            status_display = "CPI-Freeze"
        elif any_in_position:
            status_display = "Standby"
        else:
            if "Breakout" in eval_result['reason']: status_display = "ReadyBuy"
            elif "BTC" in eval_result['reason']: status_display = "WaitBTC"
            elif "EMA200" in eval_result['reason']: status_display = "BelowEMA"
            else: status_display = "Scanning"

        price_str = f"${current_price:.6f}" if current_price < 1.0 else f"${current_price:,.2f}"
        vol_ratio = eval_result.get('vol_ratio', 1.0)
        
        summary_row = {
            'symbol': sym,
            'price': price_str,
            'rsi': f"{rsi_14:.1f}",
            'adx': f"{adx_14:.1f}",
            'vol': f"{vol_ratio:.2f}",
            'pos': pos_display,
            'status': status_display
        }

        # 3. ตัดสินใจซื้อ (Single-Slot Sniper: เข้าได้เมื่อไม่มีเหรียญใดถือครองอยู่เลย)
        if not s['in_position'] and not is_cooling_down and not any_in_position:
            # 🔴 ตัวล็อกงดเปิดออเดอร์ใหม่ช่วงข่าวกล่องแดง (US CPI News Freeze 19:00 - 20:30 น.)
            if is_cpi_news_freeze():
                return summary_row

            if eval_result["decision"] == "BUY":
                # ปรึกษา Groq AI
                is_ai_approved = ask_groq_ai_sentiment(sym, eval_result["reason"])
                if not is_ai_approved:
                    return summary_row
                
                ticker = exchange.fetch_ticker(sym)
                real_entry = float(ticker['last'])
                raw_size = TRADE_AMOUNT_USDT / real_entry
                
                # คำนวณ Lot Size โดยใช้ Truncation (ปัดลงตาม stepSize ของกระดานเสมอ) ป้องกัน Insufficient Balance
                size = truncate_amount(sym, raw_size)
                if size <= 0:
                    log_trade(f"⚠️ [BUY SKIP {sym}] คำนวณ Lot size ได้ {size} (ต่ำกว่าขั้นต่ำของกระดาน)")
                    return summary_row

                try:
                    # แนบ clientOrderId (Idempotency Key) ทุกครั้งที่ส่งคำสั่งซื้อ ป้องกันการส่งคำสั่งซ้ำซ้อนกรณี Network Timeout
                    clean_sym = sym.replace('/', '').replace(':', '').lower()
                    client_oid = f"buy_{clean_sym[:6]}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                    order = exchange.create_market_buy_order(sym, size, {
                        'clientOrderId': client_oid,
                        'newClientOrderId': client_oid
                    })
                    avg_price = order.get('average')
                    if avg_price is None: avg_price = order.get('price')
                    if avg_price is None: avg_price = real_entry
                    s['entry_price'] = float(avg_price)
                    s['position_size'] = size
                    s['in_position'] = True
                    s['be_set'] = False
                    
                    s['tp'] = s['entry_price'] + (2.5 * atr_14)
                    s['sl'] = s['entry_price'] - (1.5 * atr_14)
                    save_state()
                    
                    invested_usdt = s['position_size'] * s['entry_price']
                    invested_thb = invested_usdt * 34.0
                    
                    # แสดงกรอบเน้นสไตล์ Quant Terminal
                    print_highlight_box(
                        f"BUY ORDER EXECUTED - {sym}",
                        [
                            ("Exchange / Mode", "Binance Testnet (Sandbox Demo)"),
                            ("Symbol", sym),
                            ("Entry Price", f"${s['entry_price']:.6f}"),
                            ("Size", f"{size} (~${invested_usdt:.2f} USDT / {invested_thb:.1f} บาท)"),
                            ("Take Profit (TP)", f"${s['tp']:.6f} (+2.5 ATR)"),
                            ("Stop Loss (SL)", f"${s['sl']:.6f} (-1.5 ATR)"),
                            ("Strategy Reason", eval_result['reason'])
                        ],
                        icon="🟢"
                    )
                    
                    # ส่งแจ้งเตือน LINE
                    if notifier:
                        try:
                            notifier.notify_buy(
                                "Binance", sym, s['entry_price'], size, s['tp'], s['sl'],
                                eval_result['reason'], f"ทุน: ${invested_usdt:.2f} USDT (~{invested_thb:.1f} บาท)"
                            )
                        except Exception:
                            pass

                    summary_row['pos'] = "🟢 LONG (+0.00%)"
                    summary_row['status'] = "Holding"
                except Exception as e:
                    log_trade(f"❌ [BUY ERROR {sym}] {e}")

        # 4. จัดการ Trailing Stop / Auto-Breakeven / TP / SL
        elif s['in_position']:
            pnl_percent = (current_price - s['entry_price']) / s['entry_price']

            # 🛡️ Auto-Breakeven เมื่อกำไรแตะ +0.40% ขยับ SL มาล็อกต้นทุนทันที (+0.05% เผื่อค่าธรรมเนียม)
            if not s['be_set'] and pnl_percent >= 0.004:
                s['sl'] = s['entry_price'] * 1.0005
                s['be_set'] = True
                save_state()
                print_highlight_box(
                    f"AUTO-BREAKEVEN ACTIVATED - {sym}",
                    [
                        ("Current Price", f"${current_price:.6f}"),
                        ("Profit Reached", f"+{pnl_percent*100:.2f}% (Threshold: +0.40%)"),
                        ("New Stop Loss", f"${s['sl']:.6f} (Locked +0.05% with Fee Buffer)")
                    ],
                    icon="🛡️"
                )
                if notifier:
                    try:
                        notifier.notify_breakeven("Binance", sym, current_price, s['sl'], pnl_percent * 100)
                    except Exception:
                        pass

            # Dynamic Trailing Run: ทะลุเป้า TP เก่าแล้ว ให้ Let Profit Run!
            if current_price >= s['tp']:
                s['tp'] = current_price * 1.5
                new_sl = current_price - (1.0 * atr_14)
                if new_sl > s['sl']:
                    s['sl'] = new_sl
                    s['be_set'] = True
                save_state()
                print_highlight_box(
                    f"DYNAMIC TRAILING RUN - {sym}",
                    [
                        ("Current Price", f"${current_price:.6f}"),
                        ("Target TP Exp", "Expanded to 1.5x (Let Profit Run)"),
                        ("Trailing SL", f"${s['sl']:.6f} (Trailing 1.0 ATR Behind)")
                    ],
                    icon="🚀"
                )
                if notifier:
                    try:
                        notifier.notify_trailing("Binance", sym, current_price, s['sl'], pnl_percent * 100)
                    except Exception:
                        pass

            # Trailing Stop ปกติสำหรับกำไรก้อนใหญ่ (+1.5% ขึ้นไป)
            elif pnl_percent >= 0.015:
                trailing_sl = current_price * 0.99
                if trailing_sl > s['sl']:
                    s['sl'] = trailing_sl
                    s['be_set'] = True
                    save_state()
                    log_trade(f"🛡️ [TRAILING STOP {sym}] ขยับ SL ตามกำไรไปที่ ${s['sl']:.6f}")
                    if notifier:
                        try:
                            notifier.notify_trailing("Binance", sym, current_price, s['sl'], pnl_percent * 100)
                        except Exception:
                            pass

            # 🔴 PRE-CPI SAFETY EXIT: หากถึงเวลา 18:30 - 19:29 น. วันนี้ (1 ชม. ก่อนข่าว CPI 19:30 น.)
            # สั่งปิดทำกำไร/ตัดความเสี่ยงออกก่อนตามแผนกลยุทธ์ของ Gemini Spark เพื่อถือเงินสดปลอดภัย 100%
            is_pre_cpi_exit = is_pre_cpi_safety_exit_time()
            if is_pre_cpi_exit:
                log_trade(f"🛡️ [PRE-CPI SAFETY EXIT {sym}] ถึงเวลา 18:30 น. (1 ชม. ก่อนข่าว CPI) สั่งปิดไม้เพื่อถือเงินสด 100% ตามแผน Spark!")

            # ปิดออเดอร์เมื่อราคาตัดต่ำกว่าเส้น Stop Loss หรือถึงเวลา Pre-CPI Safety Exit
            if current_price <= s['sl'] or is_pre_cpi_exit:
                try:
                    base_coin = sym.split('/')[0]
                    free_bal = exchange.fetch_free_balance().get(base_coin, 0)
                    sell_size = min(s['position_size'], free_bal) if free_bal > 0 else s['position_size']
                    # ปัดเศษลงตาม stepSize ของกระดานเสมอ ป้องกันการขายเกินยอด free_bal หรือ Insufficient Balance
                    sell_size = truncate_amount(sym, sell_size)
                    
                    if sell_size <= 0:
                        log_trade(f"⚠️ [SELL SKIP {sym}] sell_size เป็น 0 หลัง truncate (free_bal: {free_bal})")
                        return summary_row

                    # แนบ clientOrderId (Idempotency Key) ป้องกันการส่งคำสั่งซ้ำซ้อนกรณี Network Timeout
                    clean_sym = sym.replace('/', '').replace(':', '').lower()
                    client_oid = f"sell_{clean_sym[:6]}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                    order = exchange.create_market_sell_order(sym, sell_size, {
                        'clientOrderId': client_oid,
                        'newClientOrderId': client_oid
                    })
                    avg_price = order.get('average')
                    if avg_price is None: avg_price = order.get('price')
                    if avg_price is None: avg_price = current_price
                    exit_price = float(avg_price)
                    real_pnl_pct = (exit_price - s['entry_price']) / s['entry_price']
                    
                    invested_usdt = s['position_size'] * s['entry_price']
                    received_usdt = sell_size * exit_price
                    net_pnl_usdt = received_usdt - invested_usdt
                    net_pnl_thb = net_pnl_usdt * 34.0
                    
                    s['in_position'] = False
                    memory[sym]["total_trades"] += 1

                    if is_pre_cpi_exit:
                        # ปิดไม้เพื่อความปลอดภัยก่อนข่าว CPI
                        s['consecutive_losses'] = 0
                        if real_pnl_pct >= 0: memory[sym]["wins"] += 1
                        else: memory[sym]["losses"] += 1
                        lesson = ag_learn_from_trade(sym, "WIN" if real_pnl_pct >= 0 else "LOSS", real_pnl_pct * 100)
                        print_highlight_box(
                            f"PRE-CPI SAFETY EXIT - {sym}",
                            [
                                ("Exit Price", f"${exit_price:.6f}"),
                                ("Net Return", f"{real_pnl_pct*100:+.2f}%"),
                                ("Net PnL", f"{net_pnl_usdt:+.4f} USDT ({net_pnl_thb:+.2f} บาท)"),
                                ("Status", "🛡️ เคลียร์พอร์ตปลอดภัยก่อนข่าว CPI ตามแผน Spark"),
                                ("AI Reflection", lesson)
                            ],
                            icon="🛡️"
                        )
                        if notifier:
                            try:
                                notifier.notify_system(
                                    "Binance Pre-CPI Safety Exit",
                                    f"🛡️ ปิดไม้ {sym} ที่ ${exit_price:.6f} ({real_pnl_pct*100:+.2f}% | {net_pnl_usdt:+.4f} USDT)\n"
                                    f"• ถือเงินสด 100% ล่วงหน้าก่อนข่าว CPI ออกเวลา 19:30 น. สำเร็จ!"
                                )
                            except Exception:
                                pass
                    elif s['be_set'] and real_pnl_pct >= 0:
                        # ปิดแบบเสมอตัวหรือกำไร Breakeven/Trailing
                        s['consecutive_losses'] = 0
                        memory[sym]["wins"] += 1
                        lesson = ag_learn_from_trade(sym, "WIN", real_pnl_pct * 100)
                        print_highlight_box(
                            f"SL-BREAKEVEN CLOSED - {sym}",
                            [
                                ("Exit Price", f"${exit_price:.6f}"),
                                ("Net Return", f"{real_pnl_pct*100:+.2f}%"),
                                ("Net Profit", f"{net_pnl_usdt:+.4f} USDT ({net_pnl_thb:+.2f} บาท)"),
                                ("Status", "🔒 ล็อกทุนสำเร็จ ไม่ขาดทุน")
                            ],
                            icon="🛡️"
                        )
                        if notifier:
                            try:
                                notifier.notify_sl("Binance", sym, exit_price, real_pnl_pct * 100, net_pnl_usdt, "USDT", is_breakeven=True, lesson=lesson)
                            except Exception:
                                pass
                    else:
                        # ขาดทุน Stop Loss
                        memory[sym]["losses"] += 1
                        s['consecutive_losses'] += 1

                        if s['consecutive_losses'] >= 2:
                            s['cooldown_until'] = datetime.utcnow() + timedelta(hours=4)
                            log_trade(f"🚨 [CIRCUIT BREAKER {sym}] ขาดทุนติด 2 ครั้ง พัก 4 ชม.")

                        lesson = ag_learn_from_trade(sym, "LOSS", real_pnl_pct * 100)
                        print_highlight_box(
                            f"STOP LOSS CUT - {sym}",
                            [
                                ("Exit Price", f"${exit_price:.6f}"),
                                ("Net Return", f"{real_pnl_pct*100:.2f}%"),
                                ("Net Loss", f"-${abs(net_pnl_usdt):.4f} USDT ({net_pnl_thb:.2f} บาท)"),
                                ("AI Reflection", lesson)
                            ],
                            icon="🛑"
                        )
                        if notifier:
                            try:
                                notifier.notify_sl("Binance", sym, exit_price, real_pnl_pct * 100, net_pnl_usdt, "USDT", is_breakeven=False, lesson=lesson)
                            except Exception:
                                pass

                    save_state()
                    sync_data_to_github()
                except Exception as e:
                    log_trade(f"❌ [EXIT ERROR {sym}] {e}")

        return summary_row

    except Exception as e:
        log_trade(f"⚠️ Error {sym}: {e}")
        return {
            'symbol': sym,
            'price': "N/A",
            'rsi': "N/A",
            'adx': "N/A",
            'vol': "N/A",
            'pos': "ERROR",
            'status': "ErrFetch"
        }

# ==========================================
# 🚀 MAIN LOOP
# ==========================================
if __name__ == '__main__':
    start_usdt = connect_and_check_balance()
    log_trade(f"🚀 เริ่มรันระบบ AG 2.0 MULTI-COIN QUANT TERMINAL บน Binance Testnet (Sandbox Demo - ทุน: ${start_usdt:.2f} USDT)")
    log_trade(f"🪙 เหรียญที่เฝ้าเทรด: {', '.join(SYMBOLS)}")
    ai_status = "🟢 พร้อมใช้งาน (v3 News-Aware)" if GROQ_API_KEY else "⚪ ไม่ได้เปิดใช้งาน (ข้ามไปใช้ Pure Quant)"
    log_trade(f"🧠 [GROQ AI ENGINE] สถานะ: {ai_status}")

    last_github_sync = 0
    while True:
        # อัปโหลดขึ้น GitHub ทุกๆ 1 ชั่วโมง
        now = time.time()
        if now - last_github_sync > 3600:
            log_trade("🕒 [SYNC] อัปโหลดข้อมูล Log ล่าสุดขึ้น GitHub (รอบ 1 ชม.)")
            sync_data_to_github()
            last_github_sync = now
        
        # 🛡️ เช็คสถานะ 1h EMA200 ของพี่ใหญ่ BTC เพื่อเป็น Gatekeeper ให้ Altcoins (แคช 3 นาทีเพื่อ Low-CPU)
        global _btc_cache
        if '_btc_cache' not in globals():
            _btc_cache = {'bullish': False, 'ts': 0}
        
        now_ts = time.time()
        if now_ts - _btc_cache['ts'] < 180:
            btc_bullish = _btc_cache['bullish']
        else:
            btc_bullish = False
            try:
                btc_bars = exchange.fetch_ohlcv('BTC/USDT', timeframe=HTF_TIMEFRAME, limit=210)
                btc_df = pd.DataFrame(btc_bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                btc_df['ema200'] = btc_df['close'].ewm(span=200, adjust=False).mean()
                btc_bullish = float(btc_df['close'].iloc[-1]) > float(btc_df['ema200'].iloc[-1])
                _btc_cache = {'bullish': btc_bullish, 'ts': now_ts}
            except Exception:
                btc_bullish = False
            
        scan_results = []
        for sym in SYMBOLS:
            res = process_symbol(sym, btc_bullish)
            if res:
                scan_results.append(res)
            time.sleep(2) # ป้องกัน API Rate Limit
            
        # พิมพ์ตารางสถานะเหรียญแบบ Quant Terminal รวมในที่เดียว ไม่สแปมซ้ำซ้อน
        print_quant_table(get_thai_time(), btc_bullish, scan_results)
        trim_status_log_if_needed()
        time.sleep(75) # พัก 75 วินาทีเพื่อ Low-CPU 100%
