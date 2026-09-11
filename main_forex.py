import os
import sys
import time
import json
import ssl
import asyncio
import urllib.request
import urllib.error
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
APP_ID = os.getenv("DERIV_APP_ID", "34lQGsI4JVHDtfZhaHAqk") # User's Registered App ID
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"

# บังคับใช้บัญชี Demo DOT94482469 เท่านั้น (ห้ามใช้เงินจริงเด็ดขาด)
TARGET_DEMO_ACCOUNT = "DOT94482469"

SYMBOLS = ["frxEURUSD", "frxGBPUSD", "frxUSDJPY"]
PRIMARY_SYMBOL = "frxEURUSD"
TIMEFRAME_SEC = 900 # 15m (15 * 60)
STAKE_USD = float(os.getenv("STAKE_USD", "2.0"))     # เงินเดิมพันต่อไม้ ~2.00 USD (~68 บาท สำหรับงbไมโคร)
MULTIPLIER = int(os.getenv("DERIV_MULTIPLIER", "100")) # สัญญา CFDs Multipliers (MULTUP) x100
MAX_SPREAD_PIPS = float(os.getenv("MAX_SPREAD_PIPS", "1.8")) # ตัวกรองสเปรดสดสูงสุด 1.8 pips

MEMORY_FILE = "agent_memory_deriv.json"
STATUS_FILE = "status_log_deriv.txt"
TRADE_LOG_FILE = "trade_log_deriv.txt"
STATE_FILE = "active_state_deriv.json"

ENABLE_DERIV = os.getenv("ENABLE_DERIV", "true").lower() in ("true", "1", "yes")

usd_thb_rate = 34.00

def get_thai_time():
    return (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S')

def log(text):
    now = get_thai_time()
    msg = f"[{now}] [DERIV-FOREX] {text}"
    print(msg, flush=True)
    try:
        with open(TRADE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

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

def print_quant_table(thai_time, rows, account_info, memory, active_trade=None, h1_bull=True):
    """ตารางสรุปสถานะ Forex แบบ Compact สไตล์ Quant Terminal ไม่สแปมซ้ำซ้อน"""
    curr = account_info.get("currency", "USD")
    bal = float(account_info.get("balance", 0.0))
    bal_thb = bal * usd_thb_rate
    loginid = account_info.get("loginid", TARGET_DEMO_ACCOUNT)
    
    total_trades = memory.get("total_trades", 0)
    wins = memory.get("wins", 0)
    losses = memory.get("losses", 0)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    
    # คำนวณกำไรจริงจาก Balance ของ Deriv (เทียบกับทุนตั้งต้น $10,000 Demo)
    initial_demo_bal = 10000.0
    account_profit_usd = round(bal - initial_demo_bal, 2)
    account_profit_thb = round(account_profit_usd * usd_thb_rate, 1)

    h1_str = "🟢 BULLISH" if h1_bull else "🔴 BEARISH"
    lines = [
        "╔══════════════════════════════════════════════════════════════════════════════════╗",
        f"║  ⚡ AG 2.0 QUANT TERMINAL | DERIV FOREX (DEMO: {TARGET_DEMO_ACCOUNT:<24})║",
        f"║  🕒 {thai_time} | H1 Trend: {h1_str} | โหมด: REAL CFDs MULTIPLIERS (MULTUP) ║",
        "╠═════════════╦══════════════╦══════╦══════════╦════════════╦═════════════════╦════╣",
        "║ Symbol      ║ Bid Price    ║ RSI  ║ BB-Width ║ Pattern    ║ Position / PnL  ║ St ║",
        "╠═════════════╬══════════════╬══════╬══════════╬════════════╬═════════════════╬════╣"
    ]
    for r in rows:
        lines.append(
            f"║ {r['symbol']:<11} ║ {r['price']:>12} ║ {r['rsi']:>4} ║ {r['bb_w']:>8} ║ {r['pattern']:<10} ║ {r['pos']:<15} ║ {r['st']:<2} ║"
        )
    lines.append("╠═════════════╩══════════════╩══════╩══════════╩════════════╩═════════════════╩════╣")
    lines.append(f"║ 👤 บัญชี Demo: {loginid:<14} 💰 Balance: ${bal:>10,.2f} USD (~{bal_thb:,.0f} ฿)          ║")
    if active_trade and active_trade.get("contract_id"):
        cid = str(active_trade["contract_id"])
        txid = str(active_trade.get("transaction_id", "N/A"))
        lines.append(f"║ 🎯 Active Contract ID: {cid:<16} TxID: {txid:<18} MULTUP x{MULTIPLIER} ║")
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
# 🧠 REINFORCEMENT LEARNING & STATE PERSISTENCE
# ==========================================
def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"🧠 [MEMORY] โหลด {MEMORY_FILE} สำเร็จ (เทรดรวม: {data.get('total_trades', 0)} ไม้)", flush=True)
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
    temp_file = f"{MEMORY_FILE}.tmp_{os.getpid()}_{int(time.time() * 1000)}"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, MEMORY_FILE)
    except Exception:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

memory = load_memory()

def save_state(trade):
    """บันทึกสถานะไม้ Deriv ลง active_state_deriv.json ทันทีแบบ Atomic (.tmp + os.replace) เพื่อป้องกันไฟล์เสียหาย (0 bytes)"""
    temp_file = f"{STATE_FILE}.tmp_{os.getpid()}_{int(time.time() * 1000)}"
    try:
        payload = {
            "account_id": TARGET_DEMO_ACCOUNT,
            "active_trade": trade,
            "updated_at": get_thai_time()
        }
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())  # ยืนยันการเขียนข้อมูลลงดิสก์โดยตรง
        os.replace(temp_file, STATE_FILE)  # Atomic rename ป้องกันปัญหาไฟล์ 0 bytes
    except Exception as e:
        log(f"⚠️ [STATE SAVE ERROR] {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

def load_state():
    """กู้คืนสถานะไม้ Deriv จาก active_state_deriv.json ทันทีที่สตาร์ท/รีสตาร์ท"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                trade = data.get("active_trade")
                if trade:
                    print_highlight_box(
                        f"DERIV STATE RECOVERED - {trade.get('symbol', PRIMARY_SYMBOL)}",
                        [
                            ("Demo Account", TARGET_DEMO_ACCOUNT),
                            ("Symbol", trade.get('symbol', PRIMARY_SYMBOL)),
                            ("Type", trade.get('type', 'BUY')),
                            ("Entry Price", f"{trade.get('entry_price', 0):.5f}"),
                            ("Contract ID", str(trade.get('contract_id', 'N/A'))),
                            ("Breakeven Locked", str(trade.get('be_locked', False)))
                        ],
                        icon="🔄"
                    )
                    log(f"🔄 [RECOVER] กู้คืนสถานะไม้ค้าง {trade.get('symbol')} @ {trade.get('entry_price', 0):.5f} สำเร็จ!")
                    return trade
                else:
                    print(f"📂 [STATE] โหลด {STATE_FILE} สำเร็จ (ไม่มีไม้ค้าง - สแตนด์บายพร้อมเทรด)", flush=True)
        except Exception as e:
            log(f"⚠️ [STATE LOAD ERROR] {e}")
    return None

# ==========================================
# 📰 NEWS AVOIDANCE SYSTEM (CACHED 1 HOUR)
# ==========================================
import urllib.request
import xml.etree.ElementTree as ET

last_news_check = 0
news_events = []

import threading

def fetch_high_impact_news():
    global last_news_check
    now = time.time()
    if now - last_news_check < 3600:
        return
    last_news_check = now
    
    def _worker():
        global news_events
        try:
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                
            root = ET.fromstring(xml_data)
            parsed_events = []
            
            for event in root.findall('event'):
                impact = event.find('impact').text
                currency = event.find('country').text
                if impact and impact.strip() == 'High' and currency and currency.strip() in ['USD', 'EUR']:
                    date_str = event.find('date').text.strip()
                    time_str = event.find('time').text.strip()
                    if time_str:
                        try:
                            dt_str = f"{date_str} {time_str}"
                            event_dt = datetime.strptime(dt_str, '%m-%d-%Y %I:%M%p')
                            event_utc = event_dt + timedelta(hours=4)
                            parsed_events.append(event_utc)
                        except Exception:
                            pass
            news_events = parsed_events
        except Exception as e:
            log(f"⚠️ ไม่สามารถอัปเดตปฏิทินข่าวได้: {e}")

    threading.Thread(target=_worker, daemon=True).start()

def is_news_freeze():
    fetch_high_impact_news()
    now_utc = datetime.utcnow()
    for evt in news_events:
        diff = (now_utc - evt).total_seconds() / 60.0
        if -30 <= diff <= 30:
            return True
    return False

def is_cpi_news_freeze():
    """
    ตัวล็อกงดเปิดไม้ใหม่ช่วงข่าวเงินเฟ้อสหรัฐฯ (US CPI 19:30 น.)
    ตามแผนกลยุทธ์ของ Gemini Spark: ช่วง 19:00 - 20:30 น. ของวันที่ 11 ก.ย. 2026
    เมื่อพ้น 20:30:00 น. จะปลดล็อกตัวเองและกลับมาสแกนเทรดอัตโนมัติ 100%
    """
    now_th = datetime.utcnow() + timedelta(hours=7)
    if now_th.year == 2026 and now_th.month == 9 and now_th.day == 11:
        if (19, 0) <= (now_th.hour, now_th.minute) < (20, 30):
            return True
    return False

# ==========================================
# 📊 TECHNICAL INDICATORS
# ==========================================
def calculate_bb_rsi(candles, period=20, std_dev=2.0, rsi_period=14):
    """คำนวณ Bollinger Bands, BandWidth, EMA50 และ RSI จากแท่งเทียน"""
    closes = [c['close'] for c in candles]
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

    is_hammer = (lower_wick >= 2 * body) and (upper_wick <= candle_range * 0.1) and (body > 0)
    is_pin_bar = (lower_wick >= 0.55 * candle_range) and (upper_wick <= 0.25 * candle_range) and (candle_range > 0)
    is_bullish_engulfing = (prev['close'] < prev['open']) and (curr['close'] > curr['open']) and (curr['open'] <= prev['close']) and (curr['close'] >= prev['open']) and (body > prev_body)
    is_morning_star = (prev2['close'] < prev2['open']) and (prev_body < (prev2_body * 0.3)) and (curr['close'] > curr['open']) and (curr['close'] > (prev2['close'] + prev2['open']) / 2)

    # 🌊 Brad Goh Step 4: Liquidity Sweep (ราคากวาด Low แท่งก่อนหน้าแล้วดึงกลับขึ้นมา)
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
        'upper_bb': upper_bb,
        'lower_bb': lower_bb,
        'bb_width': bb_width,
        'ema50': ema50,
        'rsi': rsi
    }

# ==========================================
# 🤖 GROQ AI SECOND OPINION ENGINE (v3 NEWS-AWARE)
# ==========================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
_forex_news_cache = {"data": None, "ts": 0}

def _fetch_market_context_sync():
    """ดึง Fear & Greed Index + ข่าวสดจาก RSS (รันใน Background Thread ผ่าน asyncio.to_thread)"""
    import xml.etree.ElementTree as ET
    context = {}
    ctx = ssl._create_unverified_context()

    def _http_get(u):
        try:
            import requests
            r = requests.get(u, timeout=5)
            return r.status_code, r.content
        except Exception:
            req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
                    return resp.status, resp.read()
            except Exception:
                return 500, b""

    try:
        status, body = _http_get("https://api.alternative.me/fng/?limit=1")
        if status == 200:
            d = json.loads(body.decode("utf-8"))["data"][0]
            context["fear_greed"] = f"{d['value']} ({d['value_classification']})"
    except Exception:
        context["fear_greed"] = "N/A"

    try:
        status, body = _http_get("https://api.coingecko.com/api/v3/global")
        if status == 200:
            d = json.loads(body.decode("utf-8"))["data"]
            mktcap_change = d.get("market_cap_change_percentage_24h_usd", 0)
            context["market_cap_change_24h"] = f"{mktcap_change:+.2f}%"
    except Exception:
        context["market_cap_change_24h"] = "N/A"

    headlines = []
    try:
        status, body = _http_get("https://www.forexlive.com/feed/news/")
        if status == 200:
            root = ET.fromstring(body)
            for item in root.findall(".//item")[:5]:
                title = item.find("title")
                if title is not None and title.text:
                    headlines.append(title.text.strip())
    except Exception:
        pass
    if not headlines:
        try:
            status, body = _http_get("https://cryptopanic.com/news/rss/")
            if status == 200:
                root = ET.fromstring(body)
                for item in root.findall(".//item")[:5]:
                    title = item.find("title")
                    if title is not None and title.text:
                        headlines.append(title.text.strip())
        except Exception:
            pass
    context["headlines"] = headlines
    return context

async def get_market_context_async():
    """ดึง Fear & Greed Index + ข่าวสดจาก RSS ฟรี (แคช 3 นาทีเพื่อ Low-CPU) แบบ Non-blocking"""
    global _forex_news_cache
    now = time.time()
    if _forex_news_cache["data"] and (now - _forex_news_cache["ts"] < 180):
        return _forex_news_cache["data"]

    try:
        context = await asyncio.to_thread(_fetch_market_context_sync)
    except Exception:
        context = {"fear_greed": "N/A", "market_cap_change_24h": "N/A", "headlines": []}
    _forex_news_cache = {"data": context, "ts": now}
    return context

def _query_groq_api_sync(url, headers, data):
    """ส่ง Request ไปยัง Groq API แบบ Synchronous (รันใน Background Thread ผ่าน asyncio.to_thread)"""
    try:
        import requests
        return requests.post(url, headers=headers, json=data, timeout=15)
    except Exception:
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                class DummyResp:
                    status_code = resp.status
                    def json(self):
                        return body
                return DummyResp()
        except Exception:
            class DummyErrorResp:
                status_code = 500
                def json(self):
                    return {}
            return DummyErrorResp()

async def ask_groq_ai_sentiment(symbol, price, rsi, pattern_name):
    if not GROQ_API_KEY:
        return True
        
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

        ctx = await get_market_context_async()
        news_block = "\n".join([f"- {h}" for h in ctx.get("headlines", [])]) or "N/A"
        
        prompt = f"""You are a strict Forex quantitative analyst. A technical BUY signal was triggered for {symbol}.
Price: {price:.5f}, RSI: {rsi:.1f}, Pattern: {pattern_name}, Timeframe: 15m.

=== LIVE MARKET CONTEXT ===
Fear & Greed Index: {ctx.get("fear_greed", "N/A")}
Global Market Cap Change (24h): {ctx.get("market_cap_change_24h", "N/A")}

=== LATEST FOREX & ECONOMIC HEADLINES ===
{news_block}

Based on the technical signal AND the live market context, is this Forex BUY setup highly probable?
Reply ONLY with YES or NO."""

        data = {
            "model": "openai/gpt-oss-120b",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 10,
            "temperature": 0.1
        }
        
        # รัน external HTTP request ในแยก Thread ผ่าน asyncio.to_thread ไม่บล็อก Async Event Loop
        res = await asyncio.to_thread(_query_groq_api_sync, url, headers, data)
        if res.status_code == 200:
            content = res.json()["choices"][0]["message"]["content"].strip().upper()
            is_approved = "NO" not in content
            status_text = "APPROVED (YES)" if is_approved else "REJECTED (NO)"
            
            print_highlight_box(
                f"GROQ AI v3 EVALUATION - {symbol}",
                [
                    ("Decision", status_text),
                    ("Market Fear & Greed", ctx.get("fear_greed", "N/A")),
                    ("Setup", f"Price: {price:.5f} | RSI: {rsi:.1f} | {pattern_name}")
                ],
                icon="🧠"
            )
            
            if notifier:
                try:
                    notifier.notify_ai_evaluation("Deriv", symbol, status_text, f"Price: {price:.5f}, RSI: {rsi:.1f}, Pattern: {pattern_name}")
                except Exception:
                    pass

            if not is_approved:
                log(f"🧠 [GROQ AI v3] ปฏิเสธ! (AI อ่านข่าวแล้วไม่ปลอดภัย | F&G: {ctx.get('fear_greed','N/A')})")
                return False
            log(f"🧠 [GROQ AI v3] อนุมัติ! (AI อ่านข่าวแล้วคอนเฟิร์ม | F&G: {ctx.get('fear_greed','N/A')})")
            return True
        else:
            return True
    except Exception as e:
        log(f"⚠️ [GROQ AI ERROR] {e}")
        return True

# ==========================================
# 🎯 LIVE SPREAD FILTER (MAX 1.8 PIPS)
# ==========================================
async def get_live_spread(ws, symbol):
    """
    ตรวจสอบสเปรดสด (Ask - Bid) ผ่าน Deriv WebSocket
    คืนค่า (spread_pips, ask, bid) หรือ (None, None, None) หากเกิดข้อผิดพลาด
    """
    pip_size = 0.01 if "JPY" in symbol else 0.0001
    try:
        # ส่งคำขอ tick สดจาก Deriv
        await ws.send(json.dumps({"ticks": symbol}))
        raw_res = await asyncio.wait_for(ws.recv(), timeout=5)
        res = json.loads(raw_res)
        
        # ป้องกันกรณีมีข้อความค้างในคิว WebSocket
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

        # ยกเลิก subscription ทันทีเพื่อไม่ให้สตรีม tick ค้างรบกวนลูป WebSocket
        if sub_id:
            await ws.send(json.dumps({"forget": sub_id}))
            try:
                drain = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                while drain.get("msg_type") == "tick":
                    drain = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
            except Exception:
                pass

        if ask > 0 and bid > 0 and ask >= bid:
            spread_pips = round((ask - bid) / pip_size, 2)
            return spread_pips, ask, bid
    except Exception as e:
        log(f"⚠️ [LIVE SPREAD] ไม่สามารถตรวจสอบสเปรดสด {symbol}: {e}")
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

async def request_multiplier_proposal(ws, symbol, stake, multiplier=100):
    """
    ส่งคำขอ Proposal สัญญา Multipliers ไปยัง Deriv WebSocket:
    {"proposal": 1, "amount": STAKE_USD, "basis": "stake", "contract_type": "MULTUP", "currency": "USD", "multiplier": multiplier, "underlying_symbol": symbol}
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

                if code == "InsufficientBalance":
                    log(f"⚠️ [INSUFFICIENT BALANCE] ยอดเงินคงเหลือไม่พอเปิดสัญญา {symbol} (Stake: ${stake}): {msg}")
                    return None, None
                if code == "MarketClosed":
                    log(f"⏸️ [MARKET CLOSED] ตลาด {symbol} ปิดทำการ: {msg}")
                    return None, None
                if code in ("RateLimit", "RateLimitExceeded"):
                    log(f"⏳ [RATE LIMIT] Deriv Rate Limit: {msg} -> ชะลอ 2 วินาที...")
                    await asyncio.sleep(2.0)
                    continue
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
    กู้คืนสถานะไม้ค้างจาก active_state_deriv.json และเช็คกับ Deriv เมื่อรีสตาร์ทบอท
    """
    if not saved_trade or not saved_trade.get("contract_id"):
        return None

    contract_id = saved_trade.get("contract_id")
    sym = saved_trade.get("symbol", "N/A")
    log(f"🔍 [RECOVERY] กำลังตรวจสอบสถานะสัญญาจริง #{contract_id} ({sym}) กับ Deriv...")

    poc = await get_open_contract_status(ws, contract_id)
    if not poc:
        log(f"⚠️ [RECOVERY] ไม่พบข้อมูลสัญญา #{contract_id} บน Deriv (อาจปิดไปแล้วหรือเป็น Demo เก่า) -> รีเซ็ตสถานะไม้ค้าง")
        save_state(None)
        return None

    is_sold = poc.get("is_sold", 0)
    profit_usd = float(poc.get("profit", 0.0))
    profit_thb = round(profit_usd * usd_thb_rate, 1)

    if is_sold == 1:
        log(f"🔔 [RECOVERY] สัญญา #{contract_id} ถูกปิดไปแล้วระหว่างที่บอทหยุดทำงาน (PnL: ${profit_usd:+.2f} USD)")
        memory_ref["total_trades"] = memory_ref.get("total_trades", 0) + 1
        if profit_usd >= 0:
            memory_ref["wins"] = memory_ref.get("wins", 0) + 1
        else:
            memory_ref["losses"] = memory_ref.get("losses", 0) + 1
        memory_ref["net_profit_usd"] = round(memory_ref.get("net_profit_usd", 0.0) + profit_usd, 2)
        memory_ref["net_profit_thb"] = round(memory_ref.get("net_profit_thb", 0.0) + profit_thb, 1)
        save_memory(memory_ref)
        save_state(None)

        if notifier:
            try:
                notifier.notify_trade_close("Deriv", sym, profit_usd, profit_thb, profit_usd >= 0, (memory_ref["wins"]/memory_ref["total_trades"]*100), f"Recovery Closed (#{contract_id})")
            except Exception:
                pass
        return None
    else:
        log(f"✅ [RECOVERY] สัญญา #{contract_id} ({sym}) ยังเปิดอยู่! PnL ปัจจุบัน: ${profit_usd:+.2f} USD -> เฝ้าไม้ต่อทันที")
        saved_trade["current_profit_usd"] = profit_usd
        return saved_trade

# ==========================================
# 🌐 WEBSOCKET ENGINE (STRICT DEMO DOT94482469)
# ==========================================
async def deriv_engine():
    try:
        import websockets
    except ImportError:
        log("❌ ไม่พบแพ็กเกจ websockets! กรุณาติดตั้งผ่าน pip install websockets")
        return

    log("🚀 กำลังตรวจสอบและเชื่อมต่อ Deriv Engine...")
    
    # 1. กู้คืนสถานะไม้ที่ค้างอยู่จาก active_state_deriv.json ทันทีที่สตาร์ท
    active_trade = load_state()

    account_info = {
        "loginid": f"{TARGET_DEMO_ACCOUNT} (Demo Training)",
        "currency": "USD",
        "balance": 10000.0,
        "email": "demo_training@deriv"
    }

    while True:
        try:
            target_ws_url = "wss://api.derivws.com/trading/v1/options/ws/public"
            is_live_account = False
            
            # บังคับตรวจสอบสิทธิ์: ค้นหาเฉพาะบัญชี Demo DOT94482469 (บล็อกเงินจริง CR... 100%)
            import requests
            if DERIV_TOKEN and "your_" not in DERIV_TOKEN:
                try:
                    headers = {"Authorization": f"Bearer {DERIV_TOKEN}", "Deriv-App-ID": APP_ID}
                    accounts_res = requests.get("https://api.derivws.com/trading/v1/options/accounts", headers=headers, timeout=10)
                    if accounts_res.status_code == 200:
                        accounts = accounts_res.json().get("data", [])
                        
                        target_acc = None
                        for acc in accounts:
                            acc_id = acc.get("account_id", "")
                            # บังคับหาบัญชีเป้าหมาย DOT94482469
                            if acc_id == TARGET_DEMO_ACCOUNT:
                                target_acc = acc
                                break
                        
                        # หากไม่พบเป้าหมายตรง ให้หาบัญชี Demo/Virtual อื่น (ห้ามแตะต้อง CR เงินจริง)
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
                        else:
                            log(f"⚠️ [SAFETY] ไม่พบบัญชี Demo {TARGET_DEMO_ACCOUNT} หรือมีแต่บัญชีจริง (บล็อกเงินจริง 100%) -> สลับเข้าสู่ Demo Training Mode")
                except Exception as e:
                    log(f"⚠️ Auth Check Note: {e}")

            if not is_live_account:
                log(f"💡 รันในโหมด [Demo Training Engine: {TARGET_DEMO_ACCOUNT}] (จำลองการเทรดบนกราฟจริง 100% ปลอดภัย ไร้ความเสี่ยง)")
            # ใช้ ping_interval=None เพื่อป้องกันปัญหา Deriv ปฏิเสธ RFC 6455 Ping Frame (ส่งผลให้เกิด error 1011)
            # แล้วใช้ Deriv Application-level Ping {"ping": 1} แทน ซึ่งเสถียรที่สุด 100%
            async with websockets.connect(target_ws_url, ping_interval=None, close_timeout=10) as ws:
                log(f"🔌 เชื่อมต่อ Deriv WebSocket สำเร็จ! (บัญชี: {account_info['loginid']})")

                # ตรวจสอบและกู้คืนสถานะไม้ค้างจาก Deriv ทันทีเมื่อสตาร์ท/รีสตาร์ท
                if active_trade:
                    active_trade = await recover_active_position(ws, active_trade, memory)

                while True:
                    # ตรวจสอบวันหยุดเสาร์-อาทิตย์ และช่วง Rollover Spread Blackout
                    utcnow = datetime.utcnow()
                    thai_dt = utcnow + timedelta(hours=7)
                    thai_minute = thai_dt.hour * 60 + thai_dt.minute
                    is_weekend = utcnow.weekday() == 5 or (utcnow.weekday() == 6 and utcnow.hour < 21)
                    is_rollover = (3 * 60 + 45) <= thai_minute <= (6 * 60 + 15)

                    if is_weekend:
                        log("⏸️ ตลาด Forex ปิดสุดสัปดาห์ (Standby รอเปิดวันจันทร์)...")
                        await asyncio.sleep(60)
                        continue

                    if is_rollover:
                        if active_trade:
                            log("🛡️ [ROLLOVER WINDOW 03:45-06:15] New Entry Freeze แต่ยังคงเฝ้าดูแล SL/TP และ Trailing Stop ของไม้ที่ถืออยู่ 100%")
                        else:
                            log("⏸️ [ROLLOVER WINDOW 03:45-06:15] เข้าสู่ช่วง Rollover Spread Freeze (งดเปิดไม้ใหม่เพื่อเลี่ยงสเปรดถ่าง)...")

                    if is_cpi_news_freeze():
                        if active_trade:
                            log("🛡️ [CPI NEWS FREEZE 19:00-20:30] New Entry Freeze (ข่าว US CPI) แต่ยังคงเฝ้าดูแล SL/TP ของไม้ที่ถืออยู่ 100%")
                        else:
                            log("⏸️ [CPI NEWS FREEZE 19:00-20:30] เข้าสู่ช่วง US CPI Red Folder Freeze (งดเปิดไม้ใหม่เพื่อเลี่ยงสเปรดถ่างและ Slippage)...")

                    # 1. ขอข้อมูลแท่งเทียน H1 ของ PRIMARY_SYMBOL (แคช 5 นาทีเพื่อ Low-CPU)
                    now_ts = time.time()
                    if not hasattr(deriv_engine, "_last_h1_time") or (now_ts - deriv_engine._last_h1_time > 300):
                        try:
                            h1_req = {
                                "ticks_history": PRIMARY_SYMBOL,
                                "adjust_start_time": 1,
                                "count": 60,
                                "end": "latest",
                                "style": "candles",
                                "granularity": 3600
                            }
                            await ws.send(json.dumps(h1_req))
                            h1_res = json.loads(await ws.recv())
                            h1_candles = h1_res.get("candles", [])
                            deriv_engine._cached_h1_bull = False
                            if len(h1_candles) > 50:
                                h1_closes = [c['close'] for c in h1_candles]
                                h1_ema50 = h1_closes[0]
                                alpha = 2.0 / (51)
                                for p in h1_closes[1:]:
                                    h1_ema50 = (p * alpha) + (h1_ema50 * (1 - alpha))
                                deriv_engine._cached_h1_bull = h1_closes[-1] > h1_ema50
                            deriv_engine._last_h1_time = now_ts
                        except Exception as e:
                            if "closed" in str(e).lower() or "keepalive" in str(e).lower():
                                raise e
                            pass

                    # 2. สแกนและดึงข้อมูลแท่งเทียน M15 ของทุกคู่เงิน
                    scan_rows = []
                    primary_indicators = None

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
                                if sym == PRIMARY_SYMBOL:
                                    primary_indicators = inds
                                
                                # กำหนดสถานะตาราง
                                pos_str = "⚪ FLAT"
                                st_str = "OK"
                                if active_trade and active_trade.get('symbol') == sym:
                                    cur_p = inds['price']
                                    ent = active_trade['entry_price']
                                    pips = (cur_p - ent) / 0.00010
                                    pos_str = f"🟢 {pips:+.1f} pips"
                                    st_str = "BE" if active_trade.get('be_locked') else "IN"

                                scan_rows.append({
                                    'symbol': sym,
                                    'price': f"{inds['price']:.5f}",
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
                        
                        await asyncio.sleep(0.5) # ป้องกัน Rate limit

                    # 3. จัดการสถานะไม้ที่ถืออยู่ (Active Position Management)
                    if active_trade and primary_indicators:
                        cur_price = primary_indicators['price']
                        entry = active_trade['entry_price']
                        diff_pips = (cur_price - entry) / 0.00010
                        trailing_sl_pips = active_trade.get('trailing_sl_pips', 1.0 if active_trade.get('be_locked', False) else -20.0)
                        real_cid = active_trade.get('contract_id')
                        is_real_contract = real_cid and not str(real_cid).startswith("DEMO-")

                        # 3.1 ตรวจสอบสถานะสัญญาเปิดสดกับ Deriv หากเป็นสัญญาจริง
                        contract_closed_by_broker = False
                        broker_pnl_usd = 0.0
                        if is_real_contract:
                            poc = await get_open_contract_status(ws, real_cid)
                            if poc:
                                if poc.get("is_sold") == 1:
                                    contract_closed_by_broker = True
                                    broker_pnl_usd = float(poc.get("profit", 0.0))
                                    log(f"🔔 [BROKER EXIT] สัญญา #{real_cid} ปิดแล้วโดย Deriv (Status: {poc.get('status','sold')}) PnL: ${broker_pnl_usd:+.2f}")
                                else:
                                    active_trade["current_profit_usd"] = float(poc.get("profit", 0.0))

                        # Auto-Breakeven เมื่อกำไรแตะ +15 pips
                        if diff_pips >= 15.0 and not active_trade.get('be_locked', False):
                            active_trade['be_locked'] = True
                            trailing_sl_pips = 1.0
                            active_trade['trailing_sl_pips'] = trailing_sl_pips
                            save_state(active_trade)
                            
                            print_highlight_box(
                                f"AUTO-BREAKEVEN ACTIVATED - {active_trade['symbol']}",
                                [
                                    ("Current Price", f"{cur_price:.5f}"),
                                    ("Profit Pips", f"+{diff_pips:.1f} pips"),
                                    ("New Trailing SL", "+1.0 pip (ล็อกต้นทุนเรียบร้อย)")
                                ],
                                icon="🛡️"
                            )
                            if notifier:
                                try:
                                    notifier.notify_breakeven("Deriv", active_trade['symbol'], cur_price, entry + 0.00010, diff_pips, contract_id=active_trade.get('contract_id'))
                                except Exception:
                                    pass

                        # Dynamic Trailing Run เมื่อกำไรเกิน 30 pips
                        if diff_pips >= 30.0:
                            new_trailing_sl = diff_pips - 15.0
                            if new_trailing_sl > trailing_sl_pips:
                                trailing_sl_pips = new_trailing_sl
                                active_trade['trailing_sl_pips'] = trailing_sl_pips
                                save_state(active_trade)
                                
                                print_highlight_box(
                                    f"DYNAMIC TRAILING RUN - {active_trade['symbol']}",
                                    [
                                        ("Current Price", f"{cur_price:.5f}"),
                                        ("Profit Pips", f"+{diff_pips:.1f} pips"),
                                        ("Trailing SL", f"+{trailing_sl_pips:.1f} pips (Let Profit Run!)")
                                    ],
                                    icon="🚀"
                                )
                                if notifier:
                                    try:
                                        notifier.notify_trailing("Deriv", active_trade['symbol'], cur_price, cur_price - (15.0 * 0.00010), diff_pips, contract_id=active_trade.get('contract_id'))
                                    except Exception:
                                        pass

                        # ตรวจสอบจุดปิดไม้: ชนเส้น Trailing SL, ชนเป้าหมาย Swing High / Upper BB, หรือหมดเวลา 15 นาที หรือ Broker ปิดให้
                        hold_sec = time.time() - active_trade.get('start_time', time.time())
                        is_sl = diff_pips <= trailing_sl_pips
                        is_bb_target = (cur_price >= primary_indicators['upper_bb']) and (diff_pips >= 10.0)
                        is_timeout = hold_sec >= 900 and not (diff_pips >= 30.0)
                        is_be_hit = is_sl and active_trade.get('be_locked', False)

                        if contract_closed_by_broker or is_be_hit or is_sl or is_timeout or is_bb_target:
                            profit_usd = 0.0
                            if contract_closed_by_broker:
                                profit_usd = broker_pnl_usd
                            elif is_real_contract:
                                # ส่งคำสั่งขายที่ราคาตลาดไปยัง Deriv
                                sell_res = await execute_multiplier_sell(ws, real_cid)
                                if sell_res:
                                    sold_for = float(sell_res.get("sold_for", 0.0))
                                    stake_paid = float(active_trade.get("stake", STAKE_USD))
                                    profit_usd = round(sold_for - stake_paid, 2)
                                else:
                                    poc_check = await get_open_contract_status(ws, real_cid)
                                    if poc_check and poc_check.get("is_sold") == 1:
                                        profit_usd = float(poc_check.get("profit", 0.0))
                                    else:
                                        profit_usd = (diff_pips * 0.10)
                            else:
                                profit_usd = (diff_pips * 0.10) # 0.01 lot pip value ~$0.10

                            profit_thb = profit_usd * usd_thb_rate
                            
                            if is_be_hit:
                                status_title = "SL-BREAKEVEN CLOSED"
                                icon_str = "🛡️"
                            elif is_bb_target:
                                status_title = "TAKE PROFIT (UPPER BB / SWING HIGH - เข้าไวออกไวกว่า)"
                                icon_str = "🎯"
                            elif profit_usd >= 0:
                                status_title = "TAKE PROFIT (WIN)"
                                icon_str = "🎯"
                            else:
                                status_title = "STOP LOSS (LOSS)"
                                icon_str = "🛑"

                            print_highlight_box(
                                f"{status_title} - {active_trade['symbol']}",
                                [
                                    ("Exit Price", f"{cur_price:.5f}"),
                                    ("Result Pips", f"{diff_pips:+.1f} pips"),
                                    ("Net Profit", f"${profit_usd:+,.2f} USD (≈ {profit_thb:+,.2f} THB)"),
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
                                        notifier.notify_tp("Deriv", active_trade['symbol'], cur_price, diff_pips, profit_usd, "USD", contract_id=active_trade.get('contract_id'))
                                    except Exception:
                                        pass
                            else:
                                memory["losses"] = memory.get("losses", 0) + 1
                                current_oversold = memory.get("learned_params", {}).get("rsi_oversold", 35.0)
                                if current_oversold > 28.0:
                                    memory["learned_params"]["rsi_oversold"] = round(current_oversold - 0.5, 1)
                                if notifier:
                                    try:
                                        notifier.notify_sl("Deriv", active_trade['symbol'], cur_price, diff_pips, profit_usd, "USD", is_breakeven=is_be_hit, contract_id=active_trade.get('contract_id'))
                                    except Exception:
                                        pass

                            memory["net_profit_usd"] = memory.get("net_profit_usd", 0.0) + profit_usd
                            memory["net_profit_thb"] = memory.get("net_profit_thb", 0.0) + profit_thb
                            save_memory(memory)
                            
                            active_trade = None
                            save_state(None) # ล้างสถานะไม้ในไฟล์

                    # 4. สแกนหาจังหวะเปิดไม้ใหม่ (เมื่อไม่มีไม้ค้าง และไม่อยู่ในช่วง Rollover Freeze หรือ CPI Freeze)
                    elif not active_trade and primary_indicators:
                        if is_rollover or is_cpi_news_freeze():
                            # New Entry Freeze ในช่วง Rollover 03:45 - 06:15 น. หรือช่วงข่าว CPI 19:00 - 20:30 น.
                            pass
                        else:
                            price = primary_indicators['price']
                            rsi = primary_indicators['rsi']
                            lower_bb = primary_indicators['lower_bb']
                            bb_width = primary_indicators.get('bb_width', 0.001)
                            ema50 = primary_indicators.get('ema50', price)
                            learned_oversold = memory.get("learned_params", {}).get("rsi_oversold", 35.0)

                            if price < ema50 * 0.9990:
                                effective_oversold = min(learned_oversold, 25.0)
                            else:
                                effective_oversold = learned_oversold

                            is_squeezed = bb_width < 0.0006
                            has_pattern = primary_indicators.get('has_bullish_pattern', False)
                            is_sweep = primary_indicators.get('is_liquidity_sweep', False)
                            is_h1_bull = getattr(deriv_engine, "_cached_h1_bull", True)

                            # 🛡️ Brad Goh Step 1: Trend Alignment (1H ต้องเป็น Bullish > EMA50)
                            # A+ Setup 1: Pullback แตะ Lower BB + RSI Oversold (เมื่อ 1H Bullish)
                            is_pullback = (price <= lower_bb * 1.0002) and (rsi <= effective_oversold) and not is_squeezed and is_h1_bull
                            
                            # A+ Setup 2: Reversal Pattern / Liquidity Sweep (เมื่อ 1H Bullish)
                            is_reversal = (has_pattern or is_sweep) and (rsi <= 45.0) and not is_squeezed and is_h1_bull

                            # A+ Setup 3: Extreme Confluence (คลิป 2) - RSI ดิ่งลึก (<25) + หลุด BB + มีแท่งกลับตัว/Sweep
                            is_extreme_confluence = (rsi <= 25.0) and (price <= lower_bb) and (has_pattern or is_sweep) and not is_squeezed
                            
                            if (is_pullback or is_reversal or is_extreme_confluence) and not is_news_freeze():
                                if is_extreme_confluence:
                                    trigger_name = "Extreme_Confluence"
                                elif is_sweep:
                                    trigger_name = f"LiqSweep_{primary_indicators.get('pattern_name', 'Rej')}"
                                elif is_reversal and not is_pullback:
                                    trigger_name = f"Candle_{primary_indicators.get('pattern_name', 'Reversal')}"
                                else:
                                    trigger_name = "Pullback_Oversold"
                                
                                # 4.1 ตรวจสอบ Live Spread Filter (Ask - Bid <= MAX_SPREAD_PIPS) ก่อนเปิดไม้
                                spread_pips, ask_p, bid_p = await get_live_spread(ws, PRIMARY_SYMBOL)
                                if spread_pips is not None and spread_pips > MAX_SPREAD_PIPS:
                                    log(f"⚠️ [SPREAD FILTER] สเปรดสด {PRIMARY_SYMBOL} ถ่างเกินกำหนด: {spread_pips:.1f} pips (Max: {MAX_SPREAD_PIPS} pips | Ask: {ask_p:.5f}, Bid: {bid_p:.5f}) -> ข้ามจังหวะเปิดไม้เพื่อความปลอดภัย")
                                else:
                                    if spread_pips is not None:
                                        log(f"✅ [SPREAD PASS] สเปรดสด {PRIMARY_SYMBOL}: {spread_pips:.1f} pips <= {MAX_SPREAD_PIPS} pips (Ask: {ask_p:.5f}, Bid: {bid_p:.5f})")
                                    
                                    # 4.2 ปรึกษา Groq AI
                                    is_ai_approved = await ask_groq_ai_sentiment(PRIMARY_SYMBOL, price, rsi, trigger_name)
                                    if is_ai_approved:
                                        real_contract_id = None
                                        buy_price = price
                                        tx_id = None
                                        used_mult = 100

                                        if is_live_account:
                                            prop, used_mult = await request_multiplier_proposal(ws, PRIMARY_SYMBOL, STAKE_USD, multiplier=100)
                                            if prop and "id" in prop:
                                                buy_res = await execute_multiplier_buy(ws, prop["id"], STAKE_USD)
                                                if buy_res and "contract_id" in buy_res:
                                                    real_contract_id = buy_res["contract_id"]
                                                    buy_price = float(buy_res.get("buy_price", price))
                                                    tx_id = buy_res.get("transaction_id")
                                                    account_info['balance'] = float(buy_res.get("balance_after", account_info['balance'] - STAKE_USD))
                                                    log(f"🎉 [DERIV MULTIPLIER EXECUTED] เปิดสัญญา MULTUP #{real_contract_id} สำเร็จ! Stake: ${STAKE_USD} x{used_mult} | Balance: ${account_info['balance']:,.2f}")
                                                else:
                                                    log(f"⚠️ [BUY FAILED] ยิงคำสั่งซื้อ Multiplier ไม่สำเร็จ -> ข้ามรอบนี้")
                                                    continue
                                            else:
                                                log(f"⚠️ [PROPOSAL FAILED] ไม่สามารถขอ Proposal สัญญา Multiplier ได้ -> ข้ามรอบนี้")
                                                continue
                                        else:
                                            real_contract_id = f"DEMO-{int(time.time())}"

                                        active_trade = {
                                            "contract_id": real_contract_id,
                                            "transaction_id": tx_id,
                                            "symbol": PRIMARY_SYMBOL,
                                            "type": f"CFD MULTUP x{used_mult}",
                                            "entry_price": buy_price,
                                            "stake": STAKE_USD,
                                            "entry_time": get_thai_time(),
                                            "start_time": time.time(),
                                            "be_locked": False,
                                            "trailing_sl_pips": -20.0
                                        }
                                        save_state(active_trade) # บันทึกลง active_state_deriv.json ทันทีแบบ Atomic
                                        
                                        spread_str = f"{spread_pips:.1f} pips" if spread_pips is not None else "N/A"
                                        print_highlight_box(
                                            f"BUY ORDER EXECUTED - {PRIMARY_SYMBOL}",
                                            [
                                                ("Engine / Account", f"Deriv Forex (Demo: {TARGET_DEMO_ACCOUNT})"),
                                                ("Symbol", PRIMARY_SYMBOL),
                                                ("Contract ID", f"#{real_contract_id}"),
                                                ("Entry Price", f"{buy_price:.5f}"),
                                                ("Live Spread", spread_str),
                                                ("Multiplier / Stake", f"MULTUP x{used_mult} (${STAKE_USD:.2f} USD)"),
                                                ("Strategy Trigger", trigger_name),
                                                ("RSI / BB-Width", f"{rsi:.1f} / {bb_width:.5f}")
                                            ],
                                            icon="🟢"
                                        )
                                        
                                        if notifier:
                                            try:
                                                notifier.notify_buy(
                                                    "Deriv", PRIMARY_SYMBOL, buy_price, STAKE_USD,
                                                    buy_price + 0.0030, buy_price - 0.0020, trigger_name,
                                                    f"บัญชี Demo: {TARGET_DEMO_ACCOUNT} (MULTUP x{used_mult})",
                                                    contract_id=real_contract_id
                                                )
                                            except Exception:
                                                pass

                    # 5. พิมพ์ตารางสถานะ Quant Terminal
                    if scan_rows:
                        print_quant_table(get_thai_time(), scan_rows, account_info, memory, h1_bull=getattr(deriv_engine, "_cached_h1_bull", True))

                    # วนพัก 60 วินาที โดยส่ง Keepalive Ping {"ping": 1} ทุกๆ 20 วินาที เพื่อรักษาการเชื่อมต่อ
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
    print("=" * 65)
    print(f"🏛️ DERIV FOREX QUANT ENGINE STARTING (DEMO: {TARGET_DEMO_ACCOUNT})")
    ai_status = "🟢 พร้อมใช้งาน (v3 News-Aware)" if GROQ_API_KEY else "⚪ ไม่ได้เปิดใช้งาน (ข้ามไปใช้ Pure Quant)"
    print(f"🧠 GROQ AI ENGINE : {ai_status}")
    print("=" * 65)
    asyncio.run(deriv_engine())
