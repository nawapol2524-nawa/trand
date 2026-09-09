import os
import sys
import time
import json
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# ⚙️ CONFIGURATION & CONSTANTS
# ==========================================
DERIV_TOKEN = os.getenv("DERIV_API_TOKEN")
APP_ID = os.getenv("DERIV_APP_ID", "1089") # Official default testing app_id
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"

SYMBOLS = ["frxEURUSD", "frxGBPUSD", "frxUSDJPY"]
PRIMARY_SYMBOL = "frxEURUSD"
TIMEFRAME_SEC = 900 # 15m (15 * 60)
STAKE_USD = 2.0     # เงินเดิมพันต่อไม้ ~2.00 USD (~68 บาท สำหรับงบไมโคร)

MEMORY_FILE = "agent_memory_deriv.json"
STATUS_FILE = "status_log_deriv.txt"
TRADE_LOG_FILE = "trade_log_deriv.txt"
STATE_FILE = "active_state_deriv.json"

# ตรวจสอบการเปิดใช้งาน
ENABLE_DERIV = os.getenv("ENABLE_DERIV", "true").lower() in ("true", "1", "yes")

# อัตราแลกเปลี่ยน USD/THB เริ่มต้น (อัปเดตแบบเรียลไทม์)
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
# 🧠 REINFORCEMENT LEARNING MEMORY
# ==========================================
def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
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

# ==========================================
# 📰 NEWS AVOIDANCE SYSTEM
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
    """คำนวณ Bollinger Bands, BandWidth, EMA50 และ RSI จากแท่งเทียนแบบไม่พึ่งพา pandas-ta"""
    closes = [c['close'] for c in candles]
    if len(closes) < max(period, rsi_period, 50) + 2:
        return None

    # Bollinger Bands
    recent = closes[-period:]
    sma = sum(recent) / period
    variance = sum((x - sma) ** 2 for x in recent) / period
    std = variance ** 0.5
    upper_bb = sma + (std * std_dev)
    lower_bb = sma - (std * std_dev)
    bb_width = (upper_bb - lower_bb) / sma if sma > 0 else 0.0

    # EMA 50 (Trend Filter)
    alpha = 2.0 / (50 + 1)
    ema50 = closes[0]
    for p in closes[1:]:
        ema50 = (p * alpha) + (ema50 * (1 - alpha))

    # RSI (14)
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

    # 🕯️ Candlestick Patterns Analysis (Last 3 Candles)
    curr = candles[-1]
    prev = candles[-2]
    prev2 = candles[-3]
    
    body = abs(curr['close'] - curr['open'])
    candle_range = curr['high'] - curr['low']
    lower_wick = min(curr['open'], curr['close']) - curr['low']
    upper_wick = curr['high'] - max(curr['open'], curr['close'])
    
    prev_body = abs(prev['close'] - prev['open'])
    prev2_body = abs(prev2['close'] - prev2['open'])

    # 1. Hammer (Bullish Reversal)
    is_hammer = (lower_wick >= 2 * body) and (upper_wick <= candle_range * 0.1) and (body > 0)
    
    # 2. Bullish Engulfing
    is_bullish_engulfing = (prev['close'] < prev['open']) and (curr['close'] > curr['open']) and (curr['open'] <= prev['close']) and (curr['close'] >= prev['open']) and (body > prev_body)
    
    # 3. Morning Star
    is_morning_star = (prev2['close'] < prev2['open']) and (prev_body < (prev2_body * 0.3)) and (curr['close'] > curr['open']) and (curr['close'] > (prev2['close'] + prev2['open']) / 2)

    has_bullish_pattern = is_hammer or is_bullish_engulfing or is_morning_star

    return {
        'price': closes[-1],
        'sma': sma,
        'has_bullish_pattern': has_bullish_pattern,
        'upper_bb': upper_bb,
        'lower_bb': lower_bb,
        'bb_width': bb_width,
        'ema50': ema50,
        'rsi': rsi
    }


# ==========================================
# 🤖 GROQ AI SECOND OPINION ENGINE
# ==========================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

async def ask_groq_ai_sentiment(symbol, price, rsi, pattern_name):
    if not GROQ_API_KEY:
        return True
        
    try:
        import requests
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        
        prompt = f"You are a strict Forex quantitative analyst. A technical BUY signal was triggered for {symbol}.\n"
        prompt += f"Price: {price:.5f}, RSI: {rsi:.1f}, Pattern: {pattern_name}, Timeframe: 15m.\n"
        prompt += "Is this a highly probable setup? Reply ONLY with 'YES' or 'NO'."
        
        data = {
            "model": "openai/gpt-oss-120b",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 10,
            "temperature": 0.1
        }
        
        res = requests.post(url, headers=headers, json=data, timeout=10)
        if res.status_code == 200:
            content = res.json()['choices'][0]['message']['content'].strip().upper()
            if "NO" in content:
                log(f"🧠 [GROQ AI] ปฏิเสธการเข้าเทรด! (AI บอกว่าไม่ปลอดภัย)")
                return False
            log(f"🧠 [GROQ AI] อนุมัติการเข้าเทรด! (AI คอนเฟิร์ม YES)")
            return True
        else:
            return True
    except Exception:
        return True
# ==========================================
# ☁️ STATUS DASHBOARD WRITER
# ==========================================
def update_status_file(account_info, active_trade, indicators, market_state="🟢 เทรดปกติ"):
    now = get_thai_time()
    total_trades = memory.get("total_trades", 0)
    wins = memory.get("wins", 0)
    losses = memory.get("losses", 0)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    net_usd = memory.get("net_profit_usd", 0.0)
    net_thb = memory.get("net_profit_thb", 0.0)
    
    bal_usd = account_info.get("balance", 0.0)
    bal_thb = bal_usd * usd_thb_rate

    ind_text = "รอโหลดแท่งเทียน..."
    if indicators:
        ind_text = (f"ราคา: {indicators['price']:.5f} | "
                    f"RSI: {indicators['rsi']:.1f} | "
                    f"BB-Lower: {indicators['lower_bb']:.5f} | "
                    f"BB-Upper: {indicators['upper_bb']:.5f}")

    learned = memory.get("learned_params", {})
    rl_info = f"RSI_Oversold={learned.get('rsi_oversold', 35):.1f} | RSI_Overbought={learned.get('rsi_overbought', 65):.1f}"

    curr = account_info.get("currency", "USD")
    raw_bal = float(account_info.get("balance", 0.0))
    if curr == "USC":
        bal_text = f"{raw_bal:,.2f} USC (≈ ${(raw_bal/100.0):,.2f} USD / {(raw_bal/100.0)*usd_thb_rate:,.2f} บาท)"
        standby_text = "สแตนด์บายสไนเปอร์ 0.01 Cent Lot (งบ 100 บาท ~ 280 USC)"
    else:
        bal_text = f"${raw_bal:,.2f} USD (≈ {raw_bal*usd_thb_rate:,.2f} บาท)"
        standby_text = f"สแตนด์บายสไนเปอร์งบ ${STAKE_USD:.2f} ≈ {STAKE_USD*usd_thb_rate:.2f} บาท"

    lines = [
        "=" * 60,
        f"📊 DERIV FOREX ENGINE (100% FREE CLOUD API)",
        f"🕒 เวลาไทย: {now} | สถานะ: {market_state}",
        "=" * 60,
        f"👤 บัญชี: {account_info.get('loginid', 'N/A')} ({curr})",
        f"💰 ยอดเงินคงเหลือ: {bal_text}",
        f"📈 สินทรัพย์หลัก: {PRIMARY_SYMBOL} (Timeframe: 15m)",
        f"🎯 สัญญาณปัจจุบัน: {ind_text}",
        f"🧠 AI RL Memory: {rl_info}",
        f"📊 สถิติการเทรด: ทั้งหมด {total_trades} ไม้ | ชนะ {wins} | แพ้ {losses} | Win Rate: {win_rate:.1f}%",
        f"💵 กำไร/ขาดทุนสุทธิ: ${net_usd:+,.2f} USD (≈ {net_thb:+,.2f} บาท)",
        "-" * 60
    ]

    if active_trade:
        trade_usd = active_trade.get("stake", STAKE_USD)
        trade_thb = trade_usd * usd_thb_rate
        lines.append(f"🔥 [ไม้ที่ถืออยู่] {active_trade.get('symbol')} ({active_trade.get('type')})")
        lines.append(f"   - เงินลงทุน: ${trade_usd:.2f} USD (≈ {trade_thb:.2f} บาท)")
        lines.append(f"   - ราคาเข้า: {active_trade.get('entry_price', 0):.5f}")
        lines.append(f"   - Contract ID: {active_trade.get('contract_id', 'N/A')}")
    else:
        lines.append(f"💤 [สถานะไม้] ไม่มีไม้ออเดอร์ค้าง ({standby_text})")

    lines.append("=" * 60)
    full_text = "\n".join(lines)
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            f.write(full_text + "\n")
    except Exception:
        pass

# ==========================================
# 🌐 WEBSOCKET ENGINE
# ==========================================
async def deriv_engine():
    try:
        import websockets
    except ImportError:
        log("❌ ไม่พบแพ็กเกจ websockets! กรุณาติดตั้งผ่าน requirements.txt")
        return

    if not DERIV_TOKEN or "your_" in DERIV_TOKEN:
        log("⚠️ ไม่พบ DERIV_API_TOKEN ใน .env เข้าสู่โหมดสแตนด์บาย...")
        account_dummy = {"loginid": "DEMO-UNSET", "currency": "USD", "balance": 0.0}
        update_status_file(account_dummy, None, None, market_state="⏸️ สแตนด์บาย (รอใส่ Token)")
        while True:
            await asyncio.sleep(60)

    log("🚀 กำลังเชื่อมต่อ Deriv WebSocket API...")
    account_info = {"loginid": "Connecting...", "currency": "USD", "balance": 0.0}
    active_trade = None

    while True:
        try:
            async with websockets.connect(DERIV_WS_URL, ping_interval=20, ping_timeout=20) as ws:
                log("🔌 เชื่อมต่อ WebSocket สำเร็จ! กำลังยืนยันสิทธิ์ด้วย Token...")
                auth_req = {"authorize": DERIV_TOKEN}
                await ws.send(json.dumps(auth_req))
                auth_res = json.loads(await ws.recv())

                is_live_account = False
                if "error" in auth_res:
                    err_msg = auth_res['error'].get('message', 'Unknown error')
                    log(f"⚠️ การยืนยันสิทธิ์ด้วย Token ไม่สำเร็จ ({err_msg})")
                    log("💡 สลับเข้าสู่โหมด [Live Forex AI Training Engine] (ดึงกราฟสดตลาดโลก 24 ชม. จำลองบัญชี Cent 100 บาท / 280 USC เพื่อเทรน AI)")
                    account_info = {
                        "loginid": "DERIV-SIM-CENT",
                        "currency": "USC",
                        "balance": 280.0, # จำลองบัญชี Cent งบ 100 บาท (~280 USC)
                        "email": "local_ai_training"
                    }
                else:
                    is_live_account = True
                    auth_data = auth_res.get("authorize", {})
                    account_info = {
                        "loginid": auth_data.get("loginid", "DEMO"),
                        "currency": auth_data.get("currency", "USD"),
                        "balance": float(auth_data.get("balance", 0.0)),
                        "email": auth_data.get("email", "")
                    }
                    log(f"✅ ล็อกอิน Deriv สำเร็จ! บัญชี: {account_info['loginid']} | ยอดเงิน: ${account_info['balance']:,.2f} USD")

                # Main Loop สำหรับการดึงข้อมูลและเทรด
                loop_count = 0
                while True:
                    # 1. ตรวจสอบวันหยุดเสาร์-อาทิตย์ และช่วง Rollover Spread Blackout
                    utcnow = datetime.utcnow()
                    thai_dt = utcnow + timedelta(hours=7)
                    thai_minute = thai_dt.hour * 60 + thai_dt.minute
                    is_weekend = utcnow.weekday() == 5 or (utcnow.weekday() == 6 and utcnow.hour < 21)
                    is_rollover = (3 * 60 + 45) <= thai_minute <= (6 * 60 + 15)

                    if is_weekend:
                        update_status_file(account_info, active_trade, None, market_state="⏸️ ตลาด Forex ปิดสุดสัปดาห์ (Standby)")
                        await asyncio.sleep(60)
                        continue
                    elif is_rollover:
                        update_status_file(account_info, active_trade, None, market_state="⏸️ Rollover Spread Freeze (03:45-06:15 น. เลี่ยงสเปรดถ่าง)")
                        await asyncio.sleep(60)
                        continue

                    # 1.5 ขอข้อมูลแท่งเทียน H1 (1 Hour) เพื่อดูเทรนด์ใหญ่ (MTF)
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
                    
                    is_h1_bull = False
                    if len(h1_candles) > 50:
                        h1_closes = [c['close'] for c in h1_candles]
                        h1_ema50 = h1_closes[0]
                        alpha = 2.0 / (51)
                        for p in h1_closes[1:]:
                            h1_ema50 = (p * alpha) + (h1_ema50 * (1 - alpha))
                        is_h1_bull = h1_closes[-1] > h1_ema50

                    # 2. ขอข้อมูลแท่งเทียน M15 ของ EUR/USD
                    candle_req = {
                        "ticks_history": PRIMARY_SYMBOL,
                        "adjust_start_time": 1,
                        "count": 100,
                        "end": "latest",
                        "style": "candles",
                        "granularity": TIMEFRAME_SEC
                    }
                    await ws.send(json.dumps(candle_req))
                    candle_res = json.loads(await ws.recv())

                    candles = candle_res.get("candles", [])
                    indicators = calculate_bb_rsi(
                        candles,
                        period=memory.get("learned_params", {}).get("bb_period", 20),
                        std_dev=memory.get("learned_params", {}).get("bb_std", 2.0)
                    )

                    # 3. ตรวจสอบสถานะไม้ที่ถืออยู่ (ถ้ามี)
                    if active_trade:
                        if is_live_account:
                            # ตรวจสอบว่าสัญญาหมดอายุหรือปิดหรือยังบน Deriv
                            poc_req = {"proposal_open_contract": 1, "contract_id": active_trade["contract_id"]}
                            await ws.send(json.dumps(poc_req))
                            poc_res = json.loads(await ws.recv())
                            contract = poc_res.get("proposal_open_contract", {})

                            if contract.get("is_expired") or contract.get("is_sold"):
                                profit_usd = float(contract.get("profit", 0.0))
                                profit_thb = profit_usd * usd_thb_rate
                                status_str = "🎉 WIN" if profit_usd >= 0 else "🛑 LOSS"

                                log(f"{status_str} ปิดไม้ {active_trade['symbol']} | กำไร: ${profit_usd:+,.2f} USD (≈ {profit_thb:+,.2f} บาท)")
                                
                                memory["total_trades"] = memory.get("total_trades", 0) + 1
                                if profit_usd >= 0:
                                    memory["wins"] = memory.get("wins", 0) + 1
                                else:
                                    memory["losses"] = memory.get("losses", 0) + 1
                                    current_oversold = memory.get("learned_params", {}).get("rsi_oversold", 35.0)
                                    if current_oversold > 28.0:
                                        memory["learned_params"]["rsi_oversold"] = round(current_oversold - 0.5, 1)

                                memory["net_profit_usd"] = memory.get("net_profit_usd", 0.0) + profit_usd
                                memory["net_profit_thb"] = memory.get("net_profit_thb", 0.0) + profit_thb
                                save_memory(memory)
                                active_trade = None
                        else:
                            # โหมดจำลองบัญชี Cent (คำนวณจากราคา Real-time ของตลาดโลก)
                            cur_price = indicators['price']
                            entry = active_trade['entry_price']
                            diff_pips = (cur_price - entry) / 0.00010
                            
                            # Trailing SL Tracking
                            trailing_sl_pips = active_trade.get('trailing_sl_pips', 1.0 if active_trade.get('be_locked', False) else -20.0)
                            
                            # Auto-Breakeven เมื่อกำไรแตะ +15 pips
                            if diff_pips >= 15.0 and not active_trade.get('be_locked', False):
                                active_trade['be_locked'] = True
                                trailing_sl_pips = 1.0
                                active_trade['trailing_sl_pips'] = trailing_sl_pips
                                log(f"🛡️ [AUTO-BREAKEVEN] {active_trade['symbol']} กำไรแตะ +{diff_pips:.1f} pips! ขยับ SL ล็อกต้นทุน (+1.0 pip)")

                            # Dynamic Trailing TP (Let Profit Run) เมื่อกำไรเกิน 30 pips ไม่ยอมปิด แต่ขยับ SL ตามห่างๆ 15 pips
                            if diff_pips >= 30.0:
                                new_trailing_sl = diff_pips - 15.0
                                if new_trailing_sl > trailing_sl_pips:
                                    trailing_sl_pips = new_trailing_sl
                                    active_trade['trailing_sl_pips'] = trailing_sl_pips
                                    log(f"🚀 [TRAILING RUN] {active_trade['symbol']} ทะลุเป้า TP กำไร +{diff_pips:.1f} pips! ไม่ขายหมู ขยับ SL ตามมาที่ +{trailing_sl_pips:.1f} pips")

                            # ตรวจสอบจุดออก: ชนเส้น Trailing SL / หมดเวลา 15 นาที (ถ้ายังไม่เข้าโหมด Trailing Run)
                            hold_sec = time.time() - active_trade.get('start_time', time.time())
                            is_sl = diff_pips <= trailing_sl_pips
                            is_timeout = hold_sec >= 900 and not (diff_pips >= 30.0)
                            
                            is_tp = False # ปิดการตั้งเป้าตายตัวไปเลย ปล่อยให้ชน Trailing SL เอา
                            is_be_hit = is_sl and active_trade.get('be_locked', False)

                            if is_tp or is_be_hit or is_sl or is_timeout:
                                profit_usc = diff_pips * 0.10
                                profit_thb = (profit_usc / 100.0) * usd_thb_rate
                                if is_be_hit:
                                    status_str = "🛡️ SL-BREAKEVEN"
                                elif profit_usc >= 0:
                                    status_str = "🎉 WIN"
                                else:
                                    status_str = "🛑 LOSS"
                                
                                log(f"{status_str} [SIM CENT] ปิดไม้ {active_trade['symbol']} ({diff_pips:+.1f} pips) | กำไร: {profit_usc:+.2f} USC (≈ {profit_thb:+.2f} บาท)")
                                account_info['balance'] = round(account_info['balance'] + profit_usc, 2)
                                
                                memory["total_trades"] = memory.get("total_trades", 0) + 1
                                if profit_usc >= 0:
                                    memory["wins"] = memory.get("wins", 0) + 1
                                else:
                                    memory["losses"] = memory.get("losses", 0) + 1
                                    current_oversold = memory.get("learned_params", {}).get("rsi_oversold", 35.0)
                                    if current_oversold > 28.0:
                                        memory["learned_params"]["rsi_oversold"] = round(current_oversold - 0.5, 1)

                                memory["net_profit_usd"] = memory.get("net_profit_usd", 0.0) + (profit_usc / 100.0)
                                memory["net_profit_thb"] = memory.get("net_profit_thb", 0.0) + profit_thb
                                save_memory(memory)
                                active_trade = None

                    # 4. สแกนหาจังหวะเข้าเทรด Pullback Sniper
                    elif indicators:
                        price = indicators['price']
                        rsi = indicators['rsi']
                        lower_bb = indicators['lower_bb']
                        upper_bb = indicators['upper_bb']
                        bb_width = indicators.get('bb_width', 0.001)
                        ema50 = indicators.get('ema50', price)
                        learned_oversold = memory.get("learned_params", {}).get("rsi_oversold", 35.0)

                        # Dynamic Adaptive RSI: ถ้ากราฟเป็นขาลงแรง (ราคา < EMA50) ปรับเกณฑ์ Oversold ลงเหลือ 25 ป้องกันช้อนมีดบิน
                        if price < ema50 * 0.9990:
                            effective_oversold = min(learned_oversold, 25.0)
                        else:
                            effective_oversold = learned_oversold

                        # Squeeze Filter: งดเข้าเมื่อ BB แคบจัด (bb_width < 0.0006)
                        is_squeezed = bb_width < 0.0006

                        # สัญญาณ BUY (Pullback Oversold OR Candlestick Reversal)
                        has_pattern = indicators.get('has_bullish_pattern', False)
                        
                        is_pullback = price <= lower_bb and rsi <= effective_oversold and not is_squeezed
                        is_reversal = has_pattern and (rsi <= 45) and not is_squeezed
                        
                        if is_pullback or is_reversal:
                            trigger_name = "Candle_Reversal" if is_reversal and not is_pullback else "Pullback_Oversold"
                            log(f"🎯 [ENTRY TRIGGER] พบสัญญาณ BUY {PRIMARY_SYMBOL}! [{trigger_name}] (Price: {price:.5f}, RSI: {rsi:.1f}, BBWidth: {bb_width:.5f}, Pattern: {has_pattern})")
                            if is_live_account:
                                buy_req = {
                                    "buy": 1,
                                    "price": STAKE_USD,
                                    "parameters": {
                                        "amount": STAKE_USD,
                                        "basis": "stake",
                                        "contract_type": "CALL",
                                        "currency": account_info.get("currency", "USD"),
                                        "duration": 15,
                                        "duration_unit": "m",
                                        "symbol": PRIMARY_SYMBOL
                                    }
                                }
                                await ws.send(json.dumps(buy_req))
                                buy_res = json.loads(await ws.recv())

                                if "error" in buy_res:
                                    log(f"⚠️ ซื้อสัญญาไม่สำเร็จ: {buy_res['error'].get('message')}")
                                else:
                                    buy_data = buy_res.get("buy", {})
                                    active_trade = {
                                        "contract_id": buy_data.get("contract_id"),
                                        "symbol": PRIMARY_SYMBOL,
                                        "type": "BUY (CALL)",
                                        "entry_price": price,
                                        "stake": STAKE_USD,
                                        "entry_time": get_thai_time(),
                                        "start_time": time.time()
                                    }
                                    log(f"✅ เปิดไม้สำเร็จ! Contract ID: {active_trade['contract_id']} งบ: ${STAKE_USD:.2f} USD")
                            else:
                                # โหมดจำลองบัญชี Cent 100 บาท (0.01 Cent lot)
                                active_trade = {
                                    "contract_id": f"SIM-{int(time.time())}",
                                    "symbol": PRIMARY_SYMBOL,
                                    "type": "BUY 0.01 Cent Lot",
                                    "entry_price": price,
                                    "stake": 0.01,
                                    "entry_time": get_thai_time(),
                                    "start_time": time.time(),
                                    "be_locked": False
                                }
                                log(f"✅ [SIM CENT] เปิดไม้ 0.01 Cent Lot สำเร็จ! ราคาเข้า: {price:.5f} (งบ 100 บาท ~ 280 USC)")

                    # 5. อัปเดตไฟล์สถานะ
                    update_status_file(account_info, active_trade, indicators, market_state="🟢 เฝ้าระวังสไนเปอร์ 24 ชม.")
                    loop_count += 1
                    if loop_count % 3 == 0 and indicators:
                        mode_tag = "Live" if is_live_account else "Sim Cent 100บ."
                        log(f"👀 [EUR/USD 15m] ราคา: {indicators['price']:.5f} | RSI: {indicators['rsi']:.1f} | BB-Lower: {indicators['lower_bb']:.5f} | สถานะ: {mode_tag}")
                    await asyncio.sleep(25)

        except Exception as e:
            log(f"⚠️ เกิดข้อผิดพลาดใน Deriv WebSocket: {e}. รอเชื่อมต่อใหม่ใน 10 วินาที...")
            await asyncio.sleep(10)

if __name__ == "__main__":
    print("=" * 60)
    print("🏛️ DERIV FOREX ENGINE STARTING...")
    print("=" * 60)
    asyncio.run(deriv_engine())
