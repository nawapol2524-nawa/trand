import os
import sys
import time
import json
import asyncio
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
STAKE_USD = 2.0     # เงินเดิมพันต่อไม้ ~2.00 USD (~68 บาท สำหรับงบไมโคร)

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

def print_quant_table(thai_time, rows, account_info, memory):
    """ตารางสรุปสถานะ Forex แบบ Compact สไตล์ Quant Terminal ไม่สแปมซ้ำซ้อน"""
    curr = account_info.get("currency", "USD")
    bal = float(account_info.get("balance", 0.0))
    bal_thb = bal * usd_thb_rate
    loginid = account_info.get("loginid", TARGET_DEMO_ACCOUNT)
    
    total_trades = memory.get("total_trades", 0)
    wins = memory.get("wins", 0)
    losses = memory.get("losses", 0)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    net_usd = memory.get("net_profit_usd", 0.0)
    net_thb = memory.get("net_profit_thb", 0.0)

    lines = [
        "╔══════════════════════════════════════════════════════════════════════════════════╗",
        f"║  ⚡ AG 2.0 QUANT TERMINAL | DERIV FOREX (DEMO: {TARGET_DEMO_ACCOUNT:<24})║",
        f"║  🕒 เวลาไทย: {thai_time} | โหมด: DEMO TRAINING (100% ห้ามใช้เงินจริง)       ║",
        "╠═════════════╦══════════════╦══════╦══════════╦════════════╦═════════════════╦════╣",
        "║ Symbol      ║ Bid Price    ║ RSI  ║ BB-Width ║ Pattern    ║ Position / PnL  ║ St ║",
        "╠═════════════╬══════════════╬══════╬══════════╬════════════╬═════════════════╬════╣"
    ]
    for r in rows:
        lines.append(
            f"║ {r['symbol']:<11} ║ {r['price']:>12} ║ {r['rsi']:>4} ║ {r['bb_w']:>8} ║ {r['pattern']:<10} ║ {r['pos']:<15} ║ {r['st']:<2} ║"
        )
    lines.append("╠═════════════╩══════════════╩══════╩══════════╩════════════╩═════════════════╩════╣")
    lines.append(f"║ 👤 บัญชี Demo: {loginid:<22} 💰 ยอดเงิน: ${bal:>10,.2f} USD (~{bal_thb:,.0f} THB)     ║")
    lines.append(f"║ 📊 สถิติ: {total_trades} ไม้ (ชนะ {wins} | แพ้ {losses} | WR: {win_rate:4.1f}%) | กำไรสุทธิ: ${net_usd:+,.2f} USD (~{net_thb:+,.1f} บ.)  ║")
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
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

memory = load_memory()

def save_state(trade):
    """บันทึกสถานะไม้ Deriv ลง active_state_deriv.json ทันทีเพื่อป้องกันลืมไม้"""
    try:
        payload = {
            "account_id": TARGET_DEMO_ACCOUNT,
            "active_trade": trade,
            "updated_at": get_thai_time()
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"⚠️ [STATE SAVE ERROR] {e}")

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

def fetch_high_impact_news():
    global last_news_check, news_events
    now = time.time()
    if now - last_news_check < 3600:
        return
    last_news_check = now
    
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

def is_news_freeze():
    fetch_high_impact_news()
    now_utc = datetime.utcnow()
    for evt in news_events:
        diff = (now_utc - evt).total_seconds() / 60.0
        if -30 <= diff <= 30:
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
    is_bullish_engulfing = (prev['close'] < prev['open']) and (curr['close'] > curr['open']) and (curr['open'] <= prev['close']) and (curr['close'] >= prev['open']) and (body > prev_body)
    is_morning_star = (prev2['close'] < prev2['open']) and (prev_body < (prev2_body * 0.3)) and (curr['close'] > curr['open']) and (curr['close'] > (prev2['close'] + prev2['open']) / 2)

    has_bullish_pattern = is_hammer or is_bullish_engulfing or is_morning_star
    pattern_name = "Hammer" if is_hammer else ("Engulf" if is_bullish_engulfing else ("MornStar" if is_morning_star else "None"))

    return {
        'price': closes[-1],
        'sma': sma,
        'has_bullish_pattern': has_bullish_pattern,
        'pattern_name': pattern_name,
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

async def get_market_context_async():
    """ดึง Fear & Greed Index + ข่าวสดจาก RSS ฟรี (แคช 3 นาทีเพื่อ Low-CPU)"""
    global _forex_news_cache
    now = time.time()
    if _forex_news_cache["data"] and (now - _forex_news_cache["ts"] < 180):
        return _forex_news_cache["data"]

    import requests
    import xml.etree.ElementTree as ET
    context = {}

    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        if r.status_code == 200:
            d = r.json()["data"][0]
            context["fear_greed"] = f"{d['value']} ({d['value_classification']})"
    except Exception:
        context["fear_greed"] = "N/A"

    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=5)
        if r.status_code == 200:
            d = r.json()["data"]
            mktcap_change = d.get("market_cap_change_percentage_24h_usd", 0)
            context["market_cap_change_24h"] = f"{mktcap_change:+.2f}%"
    except Exception:
        context["market_cap_change_24h"] = "N/A"

    headlines = []
    try:
        r = requests.get("https://www.forexlive.com/feed/news/", timeout=5)
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            for item in root.findall(".//item")[:5]:
                title = item.find("title")
                if title is not None and title.text:
                    headlines.append(title.text.strip())
    except Exception:
        pass
    if not headlines:
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
    _forex_news_cache = {"data": context, "ts": now}
    return context

async def ask_groq_ai_sentiment(symbol, price, rsi, pattern_name):
    if not GROQ_API_KEY:
        return True
        
    try:
        import requests
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
    except Exception:
        return True

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
                target_ws_url = "wss://api.derivws.com/trading/v1/options/ws/public"

            async with websockets.connect(target_ws_url, ping_interval=20, ping_timeout=20) as ws:
                log(f"🔌 เชื่อมต่อ Deriv WebSocket สำเร็จ! (บัญชี: {account_info['loginid']})")

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
                    elif is_rollover:
                        log("⏸️ Rollover Spread Freeze (03:45-06:15 น. เลี่ยงสเปรดถ่าง)...")
                        await asyncio.sleep(60)
                        continue

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
                        except Exception:
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
                            log(f"⚠️ ดึงข้อมูลแท่งเทียน {sym} ไม่สำเร็จ: {e}")
                        
                        await asyncio.sleep(0.5) # ป้องกัน Rate limit

                    # 3. จัดการสถานะไม้ที่ถืออยู่ (Active Position Management)
                    if active_trade and primary_indicators:
                        cur_price = primary_indicators['price']
                        entry = active_trade['entry_price']
                        diff_pips = (cur_price - entry) / 0.00010
                        trailing_sl_pips = active_trade.get('trailing_sl_pips', 1.0 if active_trade.get('be_locked', False) else -20.0)

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
                                    notifier.notify_breakeven("Deriv", active_trade['symbol'], cur_price, entry + 0.00010, diff_pips)
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
                                        notifier.notify_trailing("Deriv", active_trade['symbol'], cur_price, cur_price - (15.0 * 0.00010), diff_pips)
                                    except Exception:
                                        pass

                        # ตรวจสอบจุดปิดไม้: ชนเส้น Trailing SL หรือหมดเวลา 15 นาที
                        hold_sec = time.time() - active_trade.get('start_time', time.time())
                        is_sl = diff_pips <= trailing_sl_pips
                        is_timeout = hold_sec >= 900 and not (diff_pips >= 30.0)
                        is_be_hit = is_sl and active_trade.get('be_locked', False)

                        if is_be_hit or is_sl or is_timeout:
                            profit_usd = (diff_pips * 0.10) # 0.01 lot pip value ~$0.10
                            profit_thb = profit_usd * usd_thb_rate
                            
                            if is_be_hit:
                                status_title = "SL-BREAKEVEN CLOSED"
                                icon_str = "🛡️"
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
                                        notifier.notify_tp("Deriv", active_trade['symbol'], cur_price, diff_pips, profit_usd, "USD")
                                    except Exception:
                                        pass
                            else:
                                memory["losses"] = memory.get("losses", 0) + 1
                                current_oversold = memory.get("learned_params", {}).get("rsi_oversold", 35.0)
                                if current_oversold > 28.0:
                                    memory["learned_params"]["rsi_oversold"] = round(current_oversold - 0.5, 1)
                                if notifier:
                                    try:
                                        notifier.notify_sl("Deriv", active_trade['symbol'], cur_price, diff_pips, profit_usd, "USD", is_breakeven=is_be_hit)
                                    except Exception:
                                        pass

                            memory["net_profit_usd"] = memory.get("net_profit_usd", 0.0) + profit_usd
                            memory["net_profit_thb"] = memory.get("net_profit_thb", 0.0) + profit_thb
                            save_memory(memory)
                            
                            active_trade = None
                            save_state(None) # ล้างสถานะไม้ในไฟล์

                    # 4. สแกนหาจังหวะเปิดไม้ใหม่ (เมื่อไม่มีไม้ค้าง)
                    elif not active_trade and primary_indicators:
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
                        
                        is_pullback = price <= lower_bb and rsi <= effective_oversold and not is_squeezed
                        is_reversal = has_pattern and (rsi <= 45) and not is_squeezed
                        
                        if (is_pullback or is_reversal) and not is_news_freeze():
                            trigger_name = "Candle_Reversal" if is_reversal and not is_pullback else "Pullback_Oversold"
                            
                            # ปรึกษา Groq AI
                            is_ai_approved = await ask_groq_ai_sentiment(PRIMARY_SYMBOL, price, rsi, trigger_name)
                            if is_ai_approved:
                                active_trade = {
                                    "contract_id": f"DEMO-{int(time.time())}",
                                    "symbol": PRIMARY_SYMBOL,
                                    "type": "BUY 0.01 Lot (Demo)",
                                    "entry_price": price,
                                    "stake": STAKE_USD,
                                    "entry_time": get_thai_time(),
                                    "start_time": time.time(),
                                    "be_locked": False,
                                    "trailing_sl_pips": -20.0
                                }
                                save_state(active_trade) # บันทึกลง active_state_deriv.json ทันที
                                
                                print_highlight_box(
                                    f"BUY ORDER EXECUTED - {PRIMARY_SYMBOL}",
                                    [
                                        ("Engine / Account", f"Deriv Forex (Demo: {TARGET_DEMO_ACCOUNT})"),
                                        ("Symbol", PRIMARY_SYMBOL),
                                        ("Entry Price", f"{price:.5f}"),
                                        ("Size / Stake", f"0.01 Lot (~${STAKE_USD:.2f} USD)"),
                                        ("Strategy Trigger", trigger_name),
                                        ("RSI / BB-Width", f"{rsi:.1f} / {bb_width:.5f}")
                                    ],
                                    icon="🟢"
                                )
                                
                                if notifier:
                                    try:
                                        notifier.notify_buy(
                                            "Deriv", PRIMARY_SYMBOL, price, STAKE_USD,
                                            price + 0.0030, price - 0.0020, trigger_name,
                                            f"บัญชี Demo: {TARGET_DEMO_ACCOUNT}"
                                        )
                                    except Exception:
                                        pass

                    # 5. พิมพ์ตารางสถานะ Quant Terminal
                    if scan_rows:
                        print_quant_table(get_thai_time(), scan_rows, account_info, memory)

                    await asyncio.sleep(60) # พัก 60 วินาทีเพื่อ Low-CPU 100%

        except Exception as e:
            log(f"⚠️ เกิดข้อผิดพลาดใน Deriv WebSocket: {e}. รอเชื่อมต่อใหม่ใน 10 วินาที...")
            await asyncio.sleep(10)

if __name__ == "__main__":
    print("=" * 65)
    print(f"🏛️ DERIV FOREX QUANT ENGINE STARTING (DEMO: {TARGET_DEMO_ACCOUNT})")
    print("=" * 65)
    asyncio.run(deriv_engine())
