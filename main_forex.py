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
# 📊 TECHNICAL INDICATORS
# ==========================================
def calculate_bb_rsi(candles, period=20, std_dev=2.0, rsi_period=14):
    """คำนวณ Bollinger Bands และ RSI จากแท่งเทียนแบบไม่พึ่งพา pandas-ta"""
    closes = [c['close'] for c in candles]
    if len(closes) < max(period, rsi_period) + 2:
        return None

    # Bollinger Bands
    recent = closes[-period:]
    sma = sum(recent) / period
    variance = sum((x - sma) ** 2 for x in recent) / period
    std = variance ** 0.5
    upper_bb = sma + (std * std_dev)
    lower_bb = sma - (std * std_dev)

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

    return {
        'price': closes[-1],
        'sma': sma,
        'upper_bb': upper_bb,
        'lower_bb': lower_bb,
        'rsi': rsi
    }

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

    lines = [
        "=" * 60,
        f"📊 DERIV FOREX ENGINE (100% FREE CLOUD API)",
        f"🕒 เวลาไทย: {now} | สถานะ: {market_state}",
        "=" * 60,
        f"👤 บัญชี: {account_info.get('loginid', 'N/A')} ({account_info.get('currency', 'USD')})",
        f"💰 ยอดเงินคงเหลือ: ${bal_usd:,.2f} USD (≈ {bal_thb:,.2f} บาท)",
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
        lines.append(f"💤 [สถานะไม้] ไม่มีไม้ออเดอร์ค้าง (สแตนด์บายสไนเปอร์งบ ${STAKE_USD:.2f} ≈ {STAKE_USD*usd_thb_rate:.2f} บาท)")

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

                if "error" in auth_res:
                    log(f"❌ Authorization Failed: {auth_res['error'].get('message')}")
                    await asyncio.sleep(15)
                    continue

                auth_data = auth_res.get("authorize", {})
                account_info = {
                    "loginid": auth_data.get("loginid", "DEMO"),
                    "currency": auth_data.get("currency", "USD"),
                    "balance": float(auth_data.get("balance", 0.0)),
                    "email": auth_data.get("email", "")
                }
                log(f"✅ ล็อกอิน Deriv สำเร็จ! บัญชี: {account_info['loginid']} | ยอดเงิน: ${account_info['balance']:,.2f} USD")

                # Main Loop สำหรับการดึงข้อมูลและเทรด
                while True:
                    # 1. ตรวจสอบวันหยุดเสาร์-อาทิตย์ สำหรับตลาด Forex
                    utcnow = datetime.utcnow()
                    if utcnow.weekday() == 5 or (utcnow.weekday() == 6 and utcnow.hour < 21):
                        update_status_file(account_info, active_trade, None, market_state="⏸️ ตลาด Forex ปิดสุดสัปดาห์ (Standby)")
                        await asyncio.sleep(60)
                        continue

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
                        # ตรวจสอบว่าสัญญาหมดอายุหรือปิดหรือยัง
                        poc_req = {"proposal_open_contract": 1, "contract_id": active_trade["contract_id"]}
                        await ws.send(json.dumps(poc_req))
                        poc_res = json.loads(await ws.recv())
                        contract = poc_res.get("proposal_open_contract", {})

                        if contract.get("is_expired") or contract.get("is_sold"):
                            profit_usd = float(contract.get("profit", 0.0))
                            profit_thb = profit_usd * usd_thb_rate
                            status_str = "🎉 WIN" if profit_usd >= 0 else "🛑 LOSS"

                            log(f"{status_str} ปิดไม้ {active_trade['symbol']} | กำไร: ${profit_usd:+,.2f} USD (≈ {profit_thb:+,.2f} บาท)")
                            
                            # อัปเดต Memory การเรียนรู้ (RL Dynamic Tuning)
                            memory["total_trades"] = memory.get("total_trades", 0) + 1
                            if profit_usd >= 0:
                                memory["wins"] = memory.get("wins", 0) + 1
                                # รางวัล: ตลาดเข้าตามสัญญาณดี รักษาค่าไว้
                            else:
                                memory["losses"] = memory.get("losses", 0) + 1
                                # บทลงโทษ: ปรับความเข้มงวดของ RSI ให้รัดกุมขึ้น
                                current_oversold = memory.get("learned_params", {}).get("rsi_oversold", 35.0)
                                if current_oversold > 28.0:
                                    memory["learned_params"]["rsi_oversold"] = round(current_oversold - 0.5, 1)

                            memory["net_profit_usd"] = memory.get("net_profit_usd", 0.0) + profit_usd
                            memory["net_profit_thb"] = memory.get("net_profit_thb", 0.0) + profit_thb
                            save_memory(memory)
                            active_trade = None

                    # 4. สแกนหาจังหวะเข้าเทรด Pullback Sniper
                    elif indicators:
                        price = indicators['price']
                        rsi = indicators['rsi']
                        lower_bb = indicators['lower_bb']
                        upper_bb = indicators['upper_bb']
                        learned_oversold = memory.get("learned_params", {}).get("rsi_oversold", 35.0)
                        learned_overbought = memory.get("learned_params", {}).get("rsi_overbought", 65.0)

                        # สัญญาณ BUY (Pullback Oversold)
                        if price <= lower_bb and rsi <= learned_oversold:
                            log(f"🎯 [ENTRY TRIGGER] พบสัญญาณ BUY {PRIMARY_SYMBOL}! (Price: {price:.5f} <= LowerBB, RSI: {rsi:.1f})")
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
                                    "entry_time": get_thai_time()
                                }
                                log(f"✅ เปิดไม้สำเร็จ! Contract ID: {active_trade['contract_id']} งบ: ${STAKE_USD:.2f} USD (≈ {STAKE_USD*usd_thb_rate:.2f} บาท)")

                    # 5. อัปเดตไฟล์สถานะ
                    update_status_file(account_info, active_trade, indicators, market_state="🟢 เฝ้าระวังสไนเปอร์ 24 ชม.")
                    await asyncio.sleep(25)

        except Exception as e:
            log(f"⚠️ เกิดข้อผิดพลาดใน Deriv WebSocket: {e}. รอเชื่อมต่อใหม่ใน 10 วินาที...")
            await asyncio.sleep(10)

if __name__ == "__main__":
    print("=" * 60)
    print("🏛️ DERIV FOREX ENGINE STARTING...")
    print("=" * 60)
    asyncio.run(deriv_engine())
