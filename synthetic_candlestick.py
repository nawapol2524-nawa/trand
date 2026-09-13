"""
================================================================================
🕯️ AG 2.0 DERIV SYNTHETIC CANDLESTICK PATTERN & RISK INTELLIGENCE ENGINE
================================================================================
โมดูลวิเคราะห์แท่งเทียนเฉพาะทางสำหรับ Deriv Synthetic Volatility Indices (24/7)
- ตรวจจับรูปแบบแท่งเทียนกลับตัวฝั่งขาขึ้น (Bullish Reversal / Pin Bar / Hammer / Engulfing / Sweep)
- คำนวณคะแนนคุณภาพแท่งเทียน (Pattern Quality Score: 0 - 100)
- คำนวณจุดตัดขาดทุนแบบ Dynamic Wick-Based Stop Loss แนบหลังปลายไส้เทียน
- คำนวณอัตราส่วนผลตอบแทนต่อความเสี่ยง (Estimated Risk:Reward Ratio)
- ตรวจจับสัญญาณจังหวะทำกำไรล่วงหน้า (Early Bearish Exit on Upper BB Rejection)
================================================================================
"""

def detect_single_candle_patterns(curr, prev=None, prev2=None, prior_swing_low=None, lower_bb=0.0, upper_bb=0.0):
    """
    วิเคราะห์แท่งเทียนเดี่ยวและกลุ่มแท่งเทียน 2-3 แท่งอย่างละเอียด
    คืนค่า dict ข้อมูลการตรวจจับและสัดส่วนโครงสร้างแท่งเทียน
    """
    open_p = float(curr['open'])
    high_p = float(curr['high'])
    low_p = float(curr['low'])
    close_p = float(curr['close'])

    candle_range = max(high_p - low_p, 1e-8)
    body = abs(close_p - open_p)
    body_ratio = body / candle_range

    lower_wick = min(open_p, close_p) - low_p
    upper_wick = high_p - max(open_p, close_p)
    lower_wick_ratio = lower_wick / candle_range
    upper_wick_ratio = upper_wick / candle_range

    is_bullish_close = close_p > open_p
    is_bearish_close = close_p < open_p

    # 1. 🔨 Hammer / DragonFly Doji
    # หางล่างยาวอย่างน้อย 55% ของแท่ง, หางบนสั้น <= 18%, ปิดในกรอบบน 40%
    is_hammer = (
        (lower_wick_ratio >= 0.55) and
        (upper_wick_ratio <= 0.18) and
        (close_p >= low_p + (0.60 * candle_range))
    )

    # 2. 📍 Pin Bar Rejection (ปฏิเสธราคาต่ำอย่างรุนแรง)
    # หางล่าง >= 50% ของแท่งเทียน และปฏิเสธโซนแนวรับหรือแตะ Lower BB
    touches_lower_bb = (low_p <= lower_bb * 1.0008) if lower_bb > 0 else False
    is_pin_bar = (
        (lower_wick_ratio >= 0.50) and
        (upper_wick_ratio <= 0.25) and
        (close_p >= low_p + (0.50 * candle_range))
    )

    # 3. 🌊 Liquidity Sweep (Brad Goh SMC Step 4)
    # ราคาแทงทะลุ Swing Low ก่อนหน้า (กวาด Stop Loss) แล้วดีดกลับขึ้นมาปิดเหนือ Swing Low เดิม
    is_liquidity_sweep = False
    if prior_swing_low is not None and prior_swing_low > 0:
        is_liquidity_sweep = (low_p < prior_swing_low) and (close_p > prior_swing_low)

    # 4. 🟢 Bullish Engulfing (แท่งเขียวกลืนกินแท่งแดงก่อนหน้า)
    is_bullish_engulfing = False
    if prev:
        prev_open = float(prev['open'])
        prev_close = float(prev['close'])
        prev_body = abs(prev_close - prev_open)
        is_prev_bearish = prev_close < prev_open

        if is_prev_bearish and is_bullish_close:
            # ตัวแท่งเขียวครอบคลุมแท่งแดงก่อนหน้า
            engulfs_body = (close_p >= prev_open) and (open_p <= prev_close + (0.1 * prev_body))
            is_bullish_engulfing = engulfs_body and (body >= prev_body * 0.95)

    # 5. ⭐ Morning Star (การกลับตัว 3 แท่ง: แดงใหญ่ -> เล็กตรงกลาง -> เขียวใหญ่)
    is_morning_star = False
    if prev and prev2:
        p2_open = float(prev2['open'])
        p2_close = float(prev2['close'])
        p2_body = abs(p2_close - p2_open)
        p1_body = abs(float(prev['close']) - float(prev['open']))

        p2_is_bearish = p2_close < p2_open
        p1_is_small = p1_body < (p2_body * 0.45)
        curr_strong_bullish = is_bullish_close and (close_p > (p2_close + p2_open) / 2)

        is_morning_star = p2_is_bearish and p1_is_small and curr_strong_bullish

    # 6. 🔻 Bearish Reversal Exit Patterns (สำหรับเตือนปิดทำกำไรฝั่ง Buy)
    # Shooting Star / Bearish Pin Bar ที่โซน Upper BB
    touches_upper_bb = (high_p >= upper_bb * 0.9992) if upper_bb > 0 else False
    is_shooting_star = (
        (upper_wick_ratio >= 0.50) and
        (lower_wick_ratio <= 0.20) and
        (close_p <= high_p - (0.50 * candle_range))
    )

    is_bearish_engulfing = False
    if prev:
        prev_open = float(prev['open'])
        prev_close = float(prev['close'])
        prev_body = abs(prev_close - prev_open)
        if (prev_close > prev_open) and is_bearish_close:
            is_bearish_engulfing = (close_p <= prev_open) and (body >= prev_body * 0.95)

    bearish_exit = (is_shooting_star or is_bearish_engulfing) and touches_upper_bb

    return {
        'open': open_p,
        'high': high_p,
        'low': low_p,
        'close': close_p,
        'range': candle_range,
        'body': body,
        'body_ratio': body_ratio,
        'lower_wick': lower_wick,
        'upper_wick': upper_wick,
        'lower_wick_ratio': lower_wick_ratio,
        'upper_wick_ratio': upper_wick_ratio,
        'is_hammer': is_hammer,
        'is_pin_bar': is_pin_bar,
        'is_liquidity_sweep': is_liquidity_sweep,
        'is_bullish_engulfing': is_bullish_engulfing,
        'is_morning_star': is_morning_star,
        'touches_lower_bb': touches_lower_bb,
        'is_shooting_star': is_shooting_star,
        'is_bearish_engulfing': is_bearish_engulfing,
        'bearish_exit': bearish_exit
    }


def calculate_pattern_quality_score(candle_data, rsi=50.0, lower_bb=0.0):
    """
    คำนวณคะแนนคุณภาพของแพทเทิร์นแท่งเทียน (0 - 100 คะแนน)
    - ป้องกันการรับมีด (Falling Knives): หากเป็นแท่งแดงตัน ไม่ให้คะแนน
    - ให้คะแนนสูงเมื่อมีไส้ปฏิเสธชัดเจน + ทะลุ Lower BB + RSI โอเวอร์โซลด์
    """
    score = 0.0

    low_p = candle_data['low']
    close_p = candle_data['close']
    open_p = candle_data['open']
    lower_wick_ratio = candle_data['lower_wick_ratio']
    body_ratio = candle_data['body_ratio']
    is_bullish_close = close_p >= open_p

    # 1. คะแนนจากความยาวไส้ล่าง (Rejection Wick Score) สูงสุด 35 คะแนน
    if lower_wick_ratio >= 0.65:
        score += 35.0
    elif lower_wick_ratio >= 0.50:
        score += 25.0
    elif lower_wick_ratio >= 0.35:
        score += 15.0

    # 2. คะแนนจากลักษณะเฉพาะของแพทเทิร์น สูงสุด 30 คะแนน
    if candle_data['is_liquidity_sweep'] and (candle_data['is_pin_bar'] or candle_data['is_hammer']):
        score += 30.0
    elif candle_data['is_liquidity_sweep']:
        score += 20.0
    elif candle_data['is_hammer']:
        score += 22.0
    elif candle_data['is_pin_bar']:
        score += 20.0
    elif candle_data['is_bullish_engulfing']:
        score += 24.0
    elif candle_data['is_morning_star']:
        score += 22.0

    # 3. คะแนนความสอดคล้องกับ Lower BB (Support Confluence) สูงสุด 20 คะแนน
    if lower_bb > 0:
        if low_p <= lower_bb:
            # ไส้แทงหลุด Lower BB แล้วเด้งกลับขึ้นมาปิดเหนือ Lower BB (Perfect Rejection)
            if close_p >= lower_bb:
                score += 20.0
            else:
                score += 10.0
        elif low_p <= lower_bb * 1.001:
            score += 8.0

    # 4. คะแนนจาก RSI Confluence สูงสุด 15 คะแนน
    if rsi <= 30.0:
        score += 15.0
    elif rsi <= 35.0:
        score += 10.0
    elif rsi <= 40.0:
        score += 5.0

    # 5. หักคะแนนหากเป็นแท่งแดงทิ้งดิ่งไม่มีไส้ล่าง (Falling Knife Penalty)
    if not is_bullish_close and (body_ratio >= 0.70) and (lower_wick_ratio <= 0.15):
        score = max(0.0, score - 50.0)

    # โบนัสปิดแท่งเขียว (+5 คะแนน)
    if is_bullish_close and score >= 30.0:
        score = min(100.0, score + 5.0)

    return round(min(100.0, max(0.0, score)), 1)


def analyze_candlestick_setup(candles, lower_bb, upper_bb, pip_size, rsi=50.0):
    """
    ฟังก์ชันหลักในการประมวลผลแท่งเทียนสำหรับ Deriv Synthetic Engine:
    - วิเคราะห์แท่งเทียนล่าสุด ย้อนหลัง 1-3 แท่ง
    - สแกนหา Prior Swing Low ย้อนหลัง 10 แท่ง
    - คำนวณ Pattern Quality Score (0 - 100)
    - คำนวณ Dynamic Stop Loss และ Risk:Reward คาดการณ์
    """
    if not candles or len(candles) < 12:
        return {
            'has_setup': False,
            'pattern_name': 'None',
            'quality_score': 0.0,
            'dynamic_sl_pips': 20.0,
            'estimated_rr': 1.0,
            'bearish_exit': False,
            'candle_low': 0.0,
            'details': {}
        }

    curr = candles[-1]
    prev = candles[-2]
    prev2 = candles[-3]

    # หา Prior Swing Low ย้อนหลัง 10 แท่ง (ไม่รวมแท่งปัจจุบัน)
    prior_lows = [float(c['low']) for c in candles[-11:-1]]
    prior_swing_low = min(prior_lows) if prior_lows else float(curr['low'])

    # ตรวจจับแพทเทิร์น
    cd = detect_single_candle_patterns(
        curr,
        prev=prev,
        prev2=prev2,
        prior_swing_low=prior_swing_low,
        lower_bb=lower_bb,
        upper_bb=upper_bb
    )

    # คำนวณคะแนนคุณภาพ
    score = calculate_pattern_quality_score(cd, rsi=rsi, lower_bb=lower_bb)

    # กำหนดชื่อแพทเทิร์นที่ชัดเจน
    if cd['is_liquidity_sweep'] and (cd['is_pin_bar'] or cd['is_hammer']):
        pattern_name = f"Sweep+Pin ({score:.0f}%)"
    elif cd['is_liquidity_sweep'] and cd['is_bullish_engulfing']:
        pattern_name = f"Sweep+Engulf ({score:.0f}%)"
    elif cd['is_bullish_engulfing']:
        pattern_name = f"Engulf ({score:.0f}%)"
    elif cd['is_liquidity_sweep']:
        pattern_name = f"LiqSweep ({score:.0f}%)"
    elif cd['is_hammer']:
        pattern_name = f"Hammer ({score:.0f}%)"
    elif cd['is_pin_bar']:
        pattern_name = f"PinBar ({score:.0f}%)"
    elif cd['is_morning_star']:
        pattern_name = f"MornStar ({score:.0f}%)"
    elif score >= 50.0:
        pattern_name = f"RejWick ({score:.0f}%)"
    else:
        pattern_name = "None"

    # คำนวณ Dynamic Wick-Based Stop Loss
    cur_price = float(curr['close'])
    candle_low = float(curr['low'])

    # วาง SL ไว้ใต้จุดต่ำสุดของแท่งเทียน (พร้อมบัฟเฟอร์ 1.5 - 2 pips)
    buffer_price = 2.0 * pip_size
    sl_price = candle_low - buffer_price
    sl_distance = max(cur_price - sl_price, pip_size)
    dynamic_sl_pips = round(sl_distance / pip_size, 1)

    # จำกัดกรอบ SL ให้อยู่ในช่วงที่เหมาะสมและปลอดภัย (ขั้นต่ำ 6 pips, สูงสุดไม่เกิน 25 pips)
    dynamic_sl_pips = max(6.0, min(dynamic_sl_pips, 25.0))

    # คำนวณ Estimated Risk:Reward Ratio เทียบกับ Upper BB
    if upper_bb > cur_price:
        tp_distance = upper_bb - cur_price
        tp_pips = tp_distance / pip_size
        estimated_rr = round(tp_pips / dynamic_sl_pips, 2)
    else:
        estimated_rr = 1.0

    # เกณฑ์การตัดสินว่ามี Setup คุณภาพสูง:
    # 1. มี Pattern ชัดเจน และ Score >= 65
    # 2. หรือเป็น Liquidity Sweep ที่มีคะแนน >= 55
    has_setup = (score >= 65.0) or (cd['is_liquidity_sweep'] and score >= 55.0)

    return {
        'has_setup': has_setup,
        'pattern_name': pattern_name,
        'quality_score': score,
        'dynamic_sl_pips': dynamic_sl_pips,
        'estimated_rr': estimated_rr,
        'bearish_exit': cd['bearish_exit'],
        'candle_low': candle_low,
        'details': cd
    }
