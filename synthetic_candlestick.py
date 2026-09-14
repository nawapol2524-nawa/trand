"""
================================================================================
🕯️ AG 2.0 DERIV SYNTHETIC DUAL-DIRECTION CANDLESTICK PATTERN & RISK ENGINE
================================================================================
โมดูลวิเคราะห์แท่งเทียนเฉพาะทางสำหรับ Deriv Synthetic Volatility Indices (24/7)
- รองรับการเทรด 2 ฝั่งเต็มรูปแบบ:
  * ฝั่งซื้อ (MULTUP / Long): Bullish Reversal / Pin Bar / Hammer / Engulfing / Sweep
  * ฝั่งขาย (MULTDOWN / Short): Bearish Reversal / Shooting Star / Bearish Pin Bar / Engulfing / Sweep
- คำนวณคะแนนคุณภาพแท่งเทียน (Pattern Quality Score: 0 - 100) ป้องกัน Falling Knife & Rocket Chasing
- คำนวณจุดตัดขาดทุนแบบ Dynamic Wick-Based Stop Loss แนบหลังปลายไส้เทียนทั้ง 2 ฝั่ง
- คำนวณอัตราส่วนผลตอบแทนต่อความเสี่ยง (Estimated Risk:Reward Ratio)
- ตรวจจับสัญญาณทำกำไรล่วงหน้า (Early Exit) เมื่อเกิด Reversal ตรงข้ามที่ขอบ Bollinger Bands
================================================================================
"""

def detect_single_candle_patterns(curr, prev=None, prev2=None, prior_swing_low=None, prior_swing_high=None, lower_bb=0.0, upper_bb=0.0):
    """
    วิเคราะห์แท่งเทียนเดี่ยวและกลุ่มแท่งเทียน 2-3 แท่งอย่างละเอียด ทั้งฝั่ง Bullish และ Bearish
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

    # ----------------------------------------------------
    # 🟢 1. BULLISH PATTERNS (สำหรับ MULTUP / BUY)
    # ----------------------------------------------------
    # 1.1 🔨 Hammer / DragonFly Doji
    is_hammer = (
        (lower_wick_ratio >= 0.55) and
        (upper_wick_ratio <= 0.18) and
        (close_p >= low_p + (0.60 * candle_range))
    )

    # 1.2 📍 Bullish Pin Bar Rejection
    touches_lower_bb = (low_p <= lower_bb * 1.0008) if lower_bb > 0 else False
    is_pin_bar = (
        (lower_wick_ratio >= 0.50) and
        (upper_wick_ratio <= 0.25) and
        (close_p >= low_p + (0.50 * candle_range))
    )

    # 1.3 🌊 Bullish Liquidity Sweep (SMC Step 4)
    is_liquidity_sweep = False
    if prior_swing_low is not None and prior_swing_low > 0:
        is_liquidity_sweep = (low_p < prior_swing_low) and (close_p > prior_swing_low)

    # 1.4 🟢 Bullish Engulfing
    is_bullish_engulfing = False
    if prev:
        prev_open = float(prev['open'])
        prev_close = float(prev['close'])
        prev_body = abs(prev_close - prev_open)
        is_prev_bearish = prev_close < prev_open

        if is_prev_bearish and is_bullish_close:
            engulfs_body = (close_p >= prev_open) and (open_p <= prev_close + (0.1 * prev_body))
            is_bullish_engulfing = engulfs_body and (body >= prev_body * 0.95)

    # 1.5 ⭐ Morning Star
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

    # ----------------------------------------------------
    # 🔴 2. BEARISH PATTERNS (สำหรับ MULTDOWN / SELL)
    # ----------------------------------------------------
    # 2.1 🌠 Shooting Star
    touches_upper_bb = (high_p >= upper_bb * 0.9992) if upper_bb > 0 else False
    is_shooting_star = (
        (upper_wick_ratio >= 0.55) and
        (lower_wick_ratio <= 0.18) and
        (close_p <= high_p - (0.60 * candle_range))
    )

    # 2.2 📍 Bearish Pin Bar Rejection (ปฏิเสธราคาสูง)
    is_bearish_pin_bar = (
        (upper_wick_ratio >= 0.50) and
        (lower_wick_ratio <= 0.25) and
        (close_p <= high_p - (0.50 * candle_range))
    )

    # 2.3 🌊 Bearish Liquidity Sweep (SMC Top Sweep)
    is_bearish_sweep = False
    if prior_swing_high is not None and prior_swing_high > 0:
        is_bearish_sweep = (high_p > prior_swing_high) and (close_p < prior_swing_high)

    # 2.4 🔴 Bearish Engulfing
    is_bearish_engulfing = False
    if prev:
        prev_open = float(prev['open'])
        prev_close = float(prev['close'])
        prev_body = abs(prev_close - prev_open)
        is_prev_bullish = prev_close > prev_open

        if is_prev_bullish and is_bearish_close:
            engulfs_bear = (close_p <= prev_open) and (open_p >= prev_close - (0.1 * prev_body))
            is_bearish_engulfing = engulfs_bear and (body >= prev_body * 0.95)

    # 2.5 🌆 Evening Star
    is_evening_star = False
    if prev and prev2:
        p2_open = float(prev2['open'])
        p2_close = float(prev2['close'])
        p2_body = abs(p2_close - p2_open)
        p1_body = abs(float(prev['close']) - float(prev['open']))

        p2_is_bullish = p2_close > p2_open
        p1_is_small = p1_body < (p2_body * 0.45)
        curr_strong_bearish = is_bearish_close and (close_p < (p2_close + p2_open) / 2)

        is_evening_star = p2_is_bullish and p1_is_small and curr_strong_bearish

    # ----------------------------------------------------
    # 🏁 3. REVERSAL EXIT SIGNALS
    # ----------------------------------------------------
    bearish_exit = (is_shooting_star or is_bearish_engulfing or is_bearish_pin_bar or is_bearish_sweep) and touches_upper_bb
    bullish_exit = (is_hammer or is_bullish_engulfing or is_pin_bar or is_liquidity_sweep) and touches_lower_bb

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
        'is_bearish_pin_bar': is_bearish_pin_bar,
        'is_bearish_sweep': is_bearish_sweep,
        'is_bearish_engulfing': is_bearish_engulfing,
        'is_evening_star': is_evening_star,
        'touches_upper_bb': touches_upper_bb,
        'bearish_exit': bearish_exit,
        'bullish_exit': bullish_exit
    }


def calculate_pattern_quality_score(candle_data, rsi=50.0, lower_bb=0.0):
    """
    คำนวณคะแนนคุณภาพของแพทเทิร์นขาขึ้น Bullish (0 - 100 คะแนน)
    - ป้องกัน Falling Knife: หากเป็นแท่งแดงตัน ไม่ให้คะแนน
    """
    score = 0.0
    low_p = candle_data['low']
    close_p = candle_data['close']
    open_p = candle_data['open']
    lower_wick_ratio = candle_data['lower_wick_ratio']
    body_ratio = candle_data['body_ratio']
    is_bullish_close = close_p >= open_p

    if lower_wick_ratio >= 0.65:
        score += 35.0
    elif lower_wick_ratio >= 0.50:
        score += 25.0
    elif lower_wick_ratio >= 0.35:
        score += 15.0

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

    if lower_bb > 0:
        if low_p <= lower_bb:
            if close_p >= lower_bb:
                score += 20.0
            else:
                score += 10.0
        elif low_p <= lower_bb * 1.001:
            score += 8.0

    if rsi <= 30.0:
        score += 15.0
    elif rsi <= 35.0:
        score += 10.0
    elif rsi <= 40.0:
        score += 5.0

    # ป้องกัน Falling Knife
    if not is_bullish_close and (body_ratio >= 0.70) and (lower_wick_ratio <= 0.15):
        score = max(0.0, score - 50.0)

    if is_bullish_close and score >= 30.0:
        score = min(100.0, score + 5.0)

    return round(min(100.0, max(0.0, score)), 1)


def calculate_bearish_quality_score(candle_data, rsi=50.0, upper_bb=0.0):
    """
    คำนวณคะแนนคุณภาพของแพทเทิร์นขาลง Bearish (0 - 100 คะแนน)
    - ป้องกัน Rocket Chasing: หากเป็นแท่งเขียวตัน ไม่ให้คะแนน
    - ให้คะแนนสูงเมื่อมีไส้บนปฏิเสธราคาชัดเจน + ทะลุ Upper BB + RSI โอเวอร์บ็อต
    """
    score = 0.0
    high_p = candle_data['high']
    close_p = candle_data['close']
    open_p = candle_data['open']
    upper_wick_ratio = candle_data['upper_wick_ratio']
    body_ratio = candle_data['body_ratio']
    is_bearish_close = close_p <= open_p

    # 1. ความยาวไส้บน (Rejection Upper Wick)
    if upper_wick_ratio >= 0.65:
        score += 35.0
    elif upper_wick_ratio >= 0.50:
        score += 25.0
    elif upper_wick_ratio >= 0.35:
        score += 15.0

    # 2. ลักษณะแพทเทิร์นขาลง
    if candle_data['is_bearish_sweep'] and (candle_data['is_shooting_star'] or candle_data['is_bearish_pin_bar']):
        score += 30.0
    elif candle_data['is_bearish_sweep']:
        score += 20.0
    elif candle_data['is_shooting_star']:
        score += 22.0
    elif candle_data['is_bearish_pin_bar']:
        score += 20.0
    elif candle_data['is_bearish_engulfing']:
        score += 24.0
    elif candle_data['is_evening_star']:
        score += 22.0

    # 3. Upper BB Confluence
    if upper_bb > 0:
        if high_p >= upper_bb:
            if close_p <= upper_bb:
                score += 20.0
            else:
                score += 10.0
        elif high_p >= upper_bb * 0.999:
            score += 8.0

    # 4. RSI Overbought Confluence
    if rsi >= 70.0:
        score += 15.0
    elif rsi >= 65.0:
        score += 10.0
    elif rsi >= 60.0:
        score += 5.0

    # ป้องกันการไล่ราคาเขียวแท่งตัน (Rocket Chasing Penalty)
    if not is_bearish_close and (body_ratio >= 0.70) and (upper_wick_ratio <= 0.15):
        score = max(0.0, score - 50.0)

    if is_bearish_close and score >= 30.0:
        score = min(100.0, score + 5.0)

    return round(min(100.0, max(0.0, score)), 1)


def analyze_candlestick_setup(candles, lower_bb, upper_bb, pip_size, rsi=50.0):
    """
    ฟังก์ชันหลักในการประมวลผลแท่งเทียน 2 ทิศทาง (MULTUP & MULTDOWN):
    - สแกนหา Prior Swing Low & Prior Swing High ย้อนหลัง 10 แท่ง
    - คำนวณ Pattern Quality Score ของทั้ง 2 ฝั่ง
    - คำนวณ Dynamic Wick-Based Stop Loss และ Risk:Reward คาดการณ์
    """
    if not candles or len(candles) < 12:
        return {
            'has_setup': False,
            'has_bullish_setup': False,
            'has_bearish_setup': False,
            'setup_direction': 'NONE',
            'pattern_name': 'None',
            'quality_score': 0.0,
            'dynamic_sl_pips': 20.0,
            'estimated_rr': 1.0,
            'bearish_exit': False,
            'bullish_exit': False,
            'details': {}
        }

    curr = candles[-1]
    prev = candles[-2]
    prev2 = candles[-3]

    prior_lows = [float(c['low']) for c in candles[-11:-1]]
    prior_swing_low = min(prior_lows) if prior_lows else float(curr['low'])

    prior_highs = [float(c['high']) for c in candles[-11:-1]]
    prior_swing_high = max(prior_highs) if prior_highs else float(curr['high'])

    cd = detect_single_candle_patterns(
        curr,
        prev=prev,
        prev2=prev2,
        prior_swing_low=prior_swing_low,
        prior_swing_high=prior_swing_high,
        lower_bb=lower_bb,
        upper_bb=upper_bb
    )

    # คำนวณคะแนนทั้งสองฝั่ง
    bullish_score = calculate_pattern_quality_score(cd, rsi=rsi, lower_bb=lower_bb)
    bearish_score = calculate_bearish_quality_score(cd, rsi=rsi, upper_bb=upper_bb)

    cur_price = float(curr['close'])
    candle_low = float(curr['low'])
    candle_high = float(curr['high'])

    # 1. Bullish Setup Naming & SL/RR
    if cd['is_liquidity_sweep'] and (cd['is_pin_bar'] or cd['is_hammer']):
        b_name = f"Sweep+Pin ({bullish_score:.0f}%)"
    elif cd['is_liquidity_sweep'] and cd['is_bullish_engulfing']:
        b_name = f"Sweep+Engulf ({bullish_score:.0f}%)"
    elif cd['is_bullish_engulfing']:
        b_name = f"Engulf ({bullish_score:.0f}%)"
    elif cd['is_liquidity_sweep']:
        b_name = f"LiqSweep ({bullish_score:.0f}%)"
    elif cd['is_hammer']:
        b_name = f"Hammer ({bullish_score:.0f}%)"
    elif cd['is_pin_bar']:
        b_name = f"PinBar ({bullish_score:.0f}%)"
    elif cd['is_morning_star']:
        b_name = f"MornStar ({bullish_score:.0f}%)"
    elif bullish_score >= 50.0:
        b_name = f"RejWick ({bullish_score:.0f}%)"
    else:
        b_name = "None"

    # Bullish SL ใต้ Low + buffer 2 pips
    b_sl_dist = max(cur_price - (candle_low - 2.0 * pip_size), pip_size)
    bullish_sl_pips = round(max(6.0, min(b_sl_dist / pip_size, 25.0)), 1)
    if upper_bb > cur_price:
        bullish_rr = round((upper_bb - cur_price) / pip_size / bullish_sl_pips, 2)
    else:
        bullish_rr = 1.0

    # 2. Bearish Setup Naming & SL/RR
    if cd['is_bearish_sweep'] and (cd['is_shooting_star'] or cd['is_bearish_pin_bar']):
        s_name = f"BearSweep+Pin ({bearish_score:.0f}%)"
    elif cd['is_bearish_sweep'] and cd['is_bearish_engulfing']:
        s_name = f"BearSweep+Engulf ({bearish_score:.0f}%)"
    elif cd['is_bearish_engulfing']:
        s_name = f"BearEngulf ({bearish_score:.0f}%)"
    elif cd['is_bearish_sweep']:
        s_name = f"BearSweep ({bearish_score:.0f}%)"
    elif cd['is_shooting_star']:
        s_name = f"ShootStar ({bearish_score:.0f}%)"
    elif cd['is_bearish_pin_bar']:
        s_name = f"BearPin ({bearish_score:.0f}%)"
    elif cd['is_evening_star']:
        s_name = f"EveStar ({bearish_score:.0f}%)"
    elif bearish_score >= 50.0:
        s_name = f"BearRej ({bearish_score:.0f}%)"
    else:
        s_name = "None"

    # Bearish SL เหนือ High + buffer 2 pips
    s_sl_dist = max((candle_high + 2.0 * pip_size) - cur_price, pip_size)
    bearish_sl_pips = round(max(6.0, min(s_sl_dist / pip_size, 25.0)), 1)
    if lower_bb > 0 and cur_price > lower_bb:
        bearish_rr = round((cur_price - lower_bb) / pip_size / bearish_sl_pips, 2)
    else:
        bearish_rr = 1.0

    has_bullish_setup = (bullish_score >= 60.0) or (cd['is_liquidity_sweep'] and bullish_score >= 55.0)
    has_bearish_setup = (bearish_score >= 60.0) or (cd['is_bearish_sweep'] and bearish_score >= 55.0)

    # เลือกลำดับความสำคัญ
    if has_bullish_setup and (bullish_score >= bearish_score):
        setup_direction = 'BUY'
        dominant_pattern = b_name
        chosen_score = bullish_score
        chosen_sl = bullish_sl_pips
        chosen_rr = bullish_rr
    elif has_bearish_setup:
        setup_direction = 'SELL'
        dominant_pattern = s_name
        chosen_score = bearish_score
        chosen_sl = bearish_sl_pips
        chosen_rr = bearish_rr
    else:
        setup_direction = 'NONE'
        dominant_pattern = b_name if bullish_score >= bearish_score else s_name
        chosen_score = max(bullish_score, bearish_score)
        chosen_sl = bullish_sl_pips if bullish_score >= bearish_score else bearish_sl_pips
        chosen_rr = bullish_rr if bullish_score >= bearish_score else bearish_rr

    return {
        'has_setup': has_bullish_setup or has_bearish_setup,
        'has_bullish_setup': has_bullish_setup,
        'has_bearish_setup': has_bearish_setup,
        'setup_direction': setup_direction,
        'pattern_name': dominant_pattern,
        'quality_score': chosen_score,
        'dynamic_sl_pips': chosen_sl,
        'estimated_rr': chosen_rr,
        'bullish_name': b_name,
        'bearish_name': s_name,
        'bullish_score': bullish_score,
        'bearish_score': bearish_score,
        'bullish_sl_pips': bullish_sl_pips,
        'bearish_sl_pips': bearish_sl_pips,
        'bullish_rr': bullish_rr,
        'bearish_rr': bearish_rr,
        'bearish_exit': cd['bearish_exit'],
        'bullish_exit': cd['bullish_exit'],
        'details': cd
    }
