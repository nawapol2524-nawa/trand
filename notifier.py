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
GDRIVE_WEBHOOK_URL = os.getenv("GDRIVE_WEBHOOK_URL", "https://script.google.com/macros/s/AKfycbwuEpWM7wxVRxfDHM2IC0z0S605XfNCTBxIIn8tXmrCZ7BKCBPiLp-BWHC9x1zkYwilrw/exec").strip()
NOTIFICATIONS_FILE = "trade_notifications.txt"
DEFAULT_TIMEOUT_SEC = 15  # Timeout สำหรับ Google Drive Webhook
_notif_lock = threading.Lock()


def get_thai_time() -> str:
    """ส่งคืนวันเวลาปัจจุบันใน Timezone ประเทศไทย (UTC+7)"""
    tz_thai = timezone(timedelta(hours=7))
    return datetime.now(tz_thai).strftime("%Y-%m-%d %H:%M:%S")


def _post_to_gdrive_sync(message: str, timeout: int = DEFAULT_TIMEOUT_SEC) -> bool:
    """
    ฟังก์ชันบันทึกข้อความแจ้งเตือนลงไฟล์ trade_notifications.txt
    และส่งซิงค์ขึ้น Google Drive ทันทีแบบ 100% Real-Time
    (แทนที่ LINE Bot ถาวรเพื่อตัดปัญหา Rate Limit 429 และเก็บสถิติยาวนาน)
    """
    if not message:
        return False

    timestamp = get_thai_time()
    header_line = "═" * 60
    entry = f"[{timestamp}]\n{message.strip()}\n{header_line}\n\n"

    # 1. เขียนต่อท้ายลงไฟล์ท้องถิ่น trade_notifications.txt
    with _notif_lock:
        try:
            with open(NOTIFICATIONS_FILE, "a", encoding="utf-8") as f:
                f.write(entry)

            # ควบคุมขนาดไฟล์ไม่ให้เกิน 2,000 บรรทัดล่าสุดเพื่อความเบาเร็ว
            with open(NOTIFICATIONS_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            if len(lines) > 2000:
                lines = lines[-2000:]
                with open(NOTIFICATIONS_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines)
            content_to_send = "".join(lines)
        except Exception as e:
            logger.warning(f"⚠️ [GDRIVE-NOTIFIER FILE ERROR] {e}")
            content_to_send = entry

    # 2. ส่งเนื้อหาข้อความแจ้งเตือนขึ้น Google Drive ผ่าน Webhook
    if GDRIVE_WEBHOOK_URL and "your_" not in GDRIVE_WEBHOOK_URL:
        try:
            resp = requests.post(
                GDRIVE_WEBHOOK_URL,
                json={"filename": "trade_notifications.txt", "content": content_to_send},
                timeout=timeout
            )
            if resp.status_code == 200:
                logger.info("☁️ [GDRIVE-NOTIFIER] บันทึกแจ้งเตือนลง trade_notifications.txt บน Google Drive สำเร็จ!")
                return True
            else:
                logger.warning(f"⚠️ [GDRIVE-NOTIFIER] Google Drive ตอบกลับ Status {resp.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ [GDRIVE-NOTIFIER ERROR] ส่งขึ้น Google Drive ขัดข้อง: {e}")

    return False


def send_line(message: str, async_send: bool = True, timeout: int = DEFAULT_TIMEOUT_SEC) -> bool:
    """
    ฟังก์ชันหลักสำหรับส่งข้อความแจ้งเตือน (ส่งตรงเข้า Google Drive: trade_notifications.txt)
    :param message: ข้อความที่ต้องการแจ้งเตือน
    :param async_send: ส่งแบบ background thread (non-blocking 100%)
    :param timeout: timeout สูงสุด
    """
    if not message:
        return False

    if async_send:
        t = threading.Thread(target=_post_to_gdrive_sync, args=(message, timeout), daemon=True)
        t.start()
        return True
    else:
        return _post_to_gdrive_sync(message, timeout=timeout)


def send_line_message(message: str, async_send: bool = True) -> bool:
    """Alias for send_line -> บันทึกขึ้น Google Drive"""
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
