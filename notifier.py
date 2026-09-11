"""
LINE Notifier Module for TradingBot (AG 2.0 Dual-Engine)
รองรับทั้ง LINE Messaging API และ LINE Notify (Token)
แจ้งเตือนแบบ Real-Time สำหรับ Binance และ Deriv ปลอดภัย 100% Non-Blocking
"""

import os
import sys
import json
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
import requests
from dotenv import load_dotenv

# โหลด .env จาก directory ของ notifier.py หรือ parent directory
_current_dir = Path(__file__).resolve().parent
_env_path = _current_dir / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()

# Logger setup
logger = logging.getLogger("notifier")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Configuration
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_NOTIFY_URL = "https://notify-api.line.me/api/notify"
DEFAULT_TIMEOUT_SEC = 5  # Timeout สูงสุด 5 วินาที ป้องกันบอทค้าง


def get_thai_time() -> str:
    """ส่งคืนวันเวลาปัจจุบันใน Timezone ประเทศไทย (UTC+7)"""
    tz_thai = timezone(timedelta(hours=7))
    return datetime.now(tz_thai).strftime("%Y-%m-%d %H:%M:%S")


def _get_credentials():
    """ดึง credentials จาก environment"""
    messaging_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    user_id = os.getenv("LINE_USER_ID", "").strip()
    notify_token = (os.getenv("LINE_NOTIFY_TOKEN") or os.getenv("LINE_TOKEN") or "").strip()
    return messaging_token, user_id, notify_token


def _post_to_line_sync(message: str, timeout: int = DEFAULT_TIMEOUT_SEC) -> bool:
    """ฟังก์ชันส่งข้อความแบบ synchronous รองรับทั้ง Notify และ Messaging API"""
    if not message:
        return False

    if len(message) > 4900:
        message = message[:4900] + "\n... (ข้อความถูกตัดเนื่องจากยาวเกินไป)"

    messaging_token, user_id, notify_token = _get_credentials()
    success = False

    # 1. พยายามส่งผ่าน LINE Notify ก่อน (หากมี Token)
    if notify_token and "your_" not in notify_token:
        try:
            headers = {
                "Authorization": f"Bearer {notify_token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            res = requests.post(LINE_NOTIFY_URL, headers=headers, data={"message": f"\n{message}"}, timeout=timeout)
            if res.status_code == 200:
                logger.info("✅ [LINE-NOTIFY] ส่งข้อความสำเร็จ")
                success = True
            else:
                logger.warning(f"⚠️ [LINE-NOTIFY] ส่งไม่สำเร็จ: Status {res.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ [LINE-NOTIFY ERROR] {e}")

    # 2. หากยังไม่สำเร็จ และมี LINE Messaging API ให้ส่งผ่าน Messaging API
    if not success and messaging_token and user_id and "your_" not in messaging_token:
        try:
            headers = {
                "Authorization": f"Bearer {messaging_token}",
                "Content-Type": "application/json"
            }
            payload = {
                "to": user_id,
                "messages": [{"type": "text", "text": message}]
            }
            res = requests.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=timeout)
            if res.status_code == 200:
                logger.info("✅ [LINE-BOT] ส่งข้อความสำเร็จ")
                success = True
            else:
                logger.warning(f"⚠️ [LINE-BOT] ส่งไม่สำเร็จ: Status {res.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ [LINE-BOT ERROR] {e}")

    return success


def send_line(message: str, async_send: bool = True, timeout: int = DEFAULT_TIMEOUT_SEC) -> bool:
    """
    ฟังก์ชันหลักสำหรับส่งข้อความไปยัง LINE ผู้ใช้
    :param message: ข้อความที่ต้องการส่ง
    :param async_send: เริ่มต้นเป็น True ส่งแบบ background thread (non-blocking 100%)
    :param timeout: timeout ไม่เกิน 5 วินาที
    """
    messaging_token, user_id, notify_token = _get_credentials()
    if not notify_token and (not messaging_token or not user_id):
        return False

    if async_send:
        t = threading.Thread(target=_post_to_line_sync, args=(message, timeout), daemon=True)
        t.start()
        return True
    else:
        return _post_to_line_sync(message, timeout=timeout)


def send_line_message(message: str, async_send: bool = True) -> bool:
    """Alias for send_line"""
    return send_line(message, async_send=async_send)


# ==========================================
# 🔔 TRADE NOTIFICATION HELPERS
# ==========================================

def notify_trade_entry(market: str, symbol: str, side: str, price: float,
                       tp: float = None, sl: float = None, reason: str = "",
                       contract_id = None, async_send: bool = True) -> bool:
    """แจ้งเตือนเมื่อเปิดไม้ใหม่"""
    side_icon = "🟢 BUY" if "buy" in str(side).lower() or "call" in str(side).lower() else "🔴 SELL"
    tp_str = f"{tp:,.5f}" if isinstance(tp, (int, float)) else (str(tp) if tp else "ตามสัญญาณ")
    sl_str = f"{sl:,.5f}" if isinstance(sl, (int, float)) else (str(sl) if sl else "ตามสัญญาณ")
    price_str = f"{price:,.5f}" if isinstance(price, (int, float)) else str(price)

    msg = (
        f"🚀 [TRADE ENTRY] เปิดไม้ใหม่\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ ตลาด: {market}\n"
        f"💎 สินทรัพย์: {symbol}\n"
        f"⚡ คำสั่ง: {side_icon}\n"
        f"💵 ราคาเข้า: {price_str}\n"
        f"🎯 Take Profit (TP): {tp_str}\n"
        f"🛑 Stop Loss (SL): {sl_str}\n"
    )
    if contract_id:
        msg += f"🎫 สัญญา (Contract ID): #{contract_id}\n"
    if reason:
        msg += f"💡 เหตุผลเข้า: {reason}\n"
    msg += f"⏰ เวลา: {get_thai_time()}"

    return send_line(msg, async_send=async_send)


def notify_buy(engine: str, symbol: str, price: float, size: float = 0, tp: float = None, sl: float = None, reason: str = "", extra_info: str = "", contract_id = None, async_send: bool = True) -> bool:
    """Alias for notify_trade_entry with detailed parameters"""
    reason_full = reason
    if extra_info:
        reason_full = f"{reason} | {extra_info}" if reason else extra_info
    return notify_trade_entry(market=engine, symbol=symbol, side="BUY", price=price, tp=tp, sl=sl, reason=reason_full, contract_id=contract_id, async_send=async_send)


def notify_trade_close(market: str, symbol: str, pnl_usd: float,
                       pnl_thb: float = None, is_win: bool = None,
                       win_rate: float = None, details: str = "",
                       contract_id = None, async_send: bool = True) -> bool:
    """แจ้งเตือนเมื่อปิดไม้เทรด (TP / SL)"""
    if is_win is None:
        is_win = (pnl_usd is not None and pnl_usd >= 0)

    header = "🎉 [TRADE CLOSED] ปิดไม้กำไร (WIN)!" if is_win else "🛑 [TRADE CLOSED] ปิดไม้ตัดขาดทุน (LOSS)"
    result_str = "WIN ✅" if is_win else "LOSS ❌"
    
    usd_str = f"{pnl_usd:+,.2f} USD" if isinstance(pnl_usd, (int, float)) else str(pnl_usd)
    thb_str = f"{pnl_thb:+,.2f} บาท" if isinstance(pnl_thb, (int, float)) else ("-" if pnl_thb is None else str(pnl_thb))

    msg = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ ตลาด: {market}\n"
        f"💎 สินทรัพย์: {symbol}\n"
        f"📊 สถานะ: {result_str}\n"
        f"💵 กำไร/ขาดทุน: {usd_str}\n"
        f"🇹🇭 กำไร/ขาดทุน (THB): {thb_str}\n"
    )
    if contract_id:
        msg += f"🎫 สัญญา (Contract ID): #{contract_id}\n"
    if win_rate is not None:
        msg += f"🎯 Win Rate รวม: {win_rate:.1f}%\n"
    if details:
        msg += f"📝 รายละเอียด: {details}\n"
    msg += f"⏰ เวลา: {get_thai_time()}"

    return send_line(msg, async_send=async_send)


def notify_tp(engine: str, symbol: str, exit_price: float, pnl_pct: float = 0.0, pnl_amount: float = 0.0, currency: str = "USDT", lesson: str = "", contract_id = None, async_send: bool = True) -> bool:
    """Alias for notify_trade_close for Take Profit"""
    details = f"ราคาปิด: {exit_price:,.5f} ({pnl_pct:+.2f}%)"
    if lesson:
        details += f" | AI: {lesson}"
    thb_val = pnl_amount * 34.0 if currency in ("USD", "USDT") else None
    return notify_trade_close(market=engine, symbol=symbol, pnl_usd=pnl_amount, pnl_thb=thb_val, is_win=True, details=details, contract_id=contract_id, async_send=async_send)


def notify_sl(engine: str, symbol: str, exit_price: float, pnl_pct: float = 0.0, pnl_amount: float = 0.0, currency: str = "USDT", is_breakeven: bool = False, lesson: str = "", contract_id = None, async_send: bool = True) -> bool:
    """Alias for notify_trade_close for Stop Loss / Breakeven"""
    tag = "SL-Breakeven เสมอตัว" if is_breakeven else "Stop Loss"
    details = f"{tag} ราคาปิด: {exit_price:,.5f} ({pnl_pct:+.2f}%)"
    if lesson:
        details += f" | AI: {lesson}"
    thb_val = pnl_amount * 34.0 if currency in ("USD", "USDT") else None
    return notify_trade_close(market=engine, symbol=symbol, pnl_usd=pnl_amount, pnl_thb=thb_val, is_win=is_breakeven or pnl_amount >= 0, details=details, contract_id=contract_id, async_send=async_send)


def notify_breakeven(market: str, symbol: str, current_price: float = 0.0, new_sl: float = 0.0, pnl_pct: float = 0.0, contract_id = None, async_send: bool = True) -> bool:
    """แจ้งเตือนเมื่อระบบขยับ Stop Loss บังหน้าทุน (Auto-Breakeven)"""
    new_sl_str = f"{new_sl:,.5f}" if isinstance(new_sl, (int, float)) else str(new_sl)
    cur_str = f"{current_price:,.5f}" if isinstance(current_price, (int, float)) else str(current_price)

    msg = (
        f"🛡️ [AUTO BREAKEVEN] เลื่อนจุดคุ้มทุน\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ ตลาด: {market}\n"
        f"💎 สินทรัพย์: {symbol}\n"
        f"💵 ราคาปัจจุบัน: {cur_str} (+{pnl_pct:.2f}%)\n"
        f"🔒 SL ใหม่ (จุดคุ้มทุน): {new_sl_str}\n"
    )
    if contract_id:
        msg += f"🎫 สัญญา (Contract ID): #{contract_id}\n"
    msg += (
        f"✨ ล็อกกำไร/กันทุนเรียบร้อย ไม้นี้ไร้ความเสี่ยง 100%!\n"
        f"⏰ เวลา: {get_thai_time()}"
    )

    return send_line(msg, async_send=async_send)


def notify_trailing(market: str, symbol: str, current_price: float, new_sl: float, pnl_pct: float = 0.0, contract_id = None, async_send: bool = True) -> bool:
    """แจ้งเตือนเมื่อขยับ Dynamic Trailing Stop ตามกำไร"""
    new_sl_str = f"{new_sl:,.5f}" if isinstance(new_sl, (int, float)) else str(new_sl)
    cur_str = f"{current_price:,.5f}" if isinstance(current_price, (int, float)) else str(current_price)

    msg = (
        f"🚀 [DYNAMIC TRAILING RUN] เลื่อน SL ตามกำไร\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ ตลาด: {market}\n"
        f"💎 สินทรัพย์: {symbol}\n"
        f"💵 ราคาปัจจุบัน: {cur_str} (+{pnl_pct:.2f}%)\n"
        f"🎯 Trailing SL ใหม่: {new_sl_str}\n"
    )
    if contract_id:
        msg += f"🎫 สัญญา (Contract ID): #{contract_id}\n"
    msg += (
        f"🌟 Let Profit Run ต่อเนื่อง!\n"
        f"⏰ เวลา: {get_thai_time()}"
    )

    return send_line(msg, async_send=async_send)


def notify_ai_evaluation(market: str, symbol: str, decision: str, reason: str, fg_index: str = "", async_send: bool = True) -> bool:
    """แจ้งเตือนผลวิเคราะห์ Groq AI v3"""
    status_icon = "✅" if "YES" in decision.upper() or "APPROVE" in decision.upper() else "🚫"
    msg = (
        f"🧠 [AI EVALUATION] Groq v3 Sentiment\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ ตลาด: {market}\n"
        f"💎 สินทรัพย์: {symbol}\n"
        f"{status_icon} ผลประเมิน: {decision}\n"
        f"📰 เหตุผล: {reason}\n"
    )
    if fg_index:
        msg += f"📊 Fear & Greed: {fg_index}\n"
    msg += f"⏰ เวลา: {get_thai_time()}"

    return send_line(msg, async_send=async_send)


def notify_system(title: str, message: str, async_send: bool = True) -> bool:
    """แจ้งเตือนสถานะระบบ"""
    msg = (
        f"🔔 [SYSTEM ALERT] {title}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📋 รายละเอียด: {message}\n"
        f"⏰ เวลา: {get_thai_time()}"
    )

    return send_line(msg, async_send=async_send)


if __name__ == "__main__":
    print("--- [ทดสอบโมดูล Notifier] ---")
    status = notify_system(
        title="ระบบแจ้งเตือน LINE ออนไลน์",
        message="โมดูล notifier.py ติดตั้งและพร้อมส่งสัญญาณแจ้งเตือนทุกคำสั่งเทรดแล้วครับ 🚀"
    )
    print(f"ผลการทดสอบ: {'สำเร็จ (OK)' if status else 'สแตนด์บาย (รอใส่ Token)'}")
