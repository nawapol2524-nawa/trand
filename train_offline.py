import json
import time
import os
import sys
import ccxt
import pandas as pd
import numpy as np

# ==========================================
# ⚙️ CONFIGURATION & TARGET SYMBOLS
# ==========================================
DEFAULT_SYMBOLS = ['SOL/USDT', 'BTC/USDT', 'NEAR/USDT', 'AVAX/USDT', 'GALA/USDT', 'VET/USDT']
TIMEFRAME = '15m'
CANDLE_LIMIT = 500  # ดึง 500 แท่งย้อนหลังต่อเหรียญ (~5 วันล่าสุด)
MEMORY_FILE = 'agent_memory_multi.json'

def get_exchange():
    return ccxt.binance({
        'enableRateLimit': True,
        'timeout': 15000
    })

def calculate_indicators(df):
    """
    คำนวณ Indicator ครบวงจรสำหรับ Brad Goh SMC & Breakout:
    - ATR (14)
    - RSI (14)
    - ADX, +DI, -DI (14)
    - Bollinger Bands: SMA20, Lower BB, Upper BB (20, 2)
    - 1h EMA200 Proxy on 15m (span=200)
    - Candlestick Anatomy: Pin Bar, Hammer, Candlestick Range
    - Liquidity Sweep: ตรวจจับราคากวาด Low 10 แท่งก่อนหน้าแล้วดึงกลับ
    """
    df = df.copy()
    
    # ATR (14)
    df['tr0'] = abs(df['high'] - df['low'])
    df['tr1'] = abs(df['high'] - df['close'].shift())
    df['tr2'] = abs(df['low'] - df['close'].shift())
    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=14).mean()

    # RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # ADX (14)
    df['up_move'] = df['high'] - df['high'].shift()
    df['down_move'] = df['low'].shift() - df['low']
    df['+dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
    df['-dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)
    df['+di'] = 100 * (df['+dm'].ewm(alpha=1/14, adjust=False).mean() / df['atr'])
    df['-di'] = 100 * (df['-dm'].ewm(alpha=1/14, adjust=False).mean() / df['atr'])
    dx = 100 * abs(df['+di'] - df['-di']) / (df['+di'] + df['-di'])
    df['adx'] = dx.ewm(alpha=1/14, adjust=False).mean()

    # Bollinger Bands (20, 2) - รองรับ Brad Goh Upper BB TP Exit
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['bb_lower'] = df['sma20'] - (2 * df['std20'])
    df['bb_upper'] = df['sma20'] + (2 * df['std20'])

    # 1h EMA200 Proxy on 15m
    df['ema_trend'] = df['close'].ewm(span=200, adjust=False).mean()

    # 🕯️ Candlestick Anatomy for Pin Bar & Liquidity Sweep (Brad Goh SMC)
    body = abs(df['close'] - df['open'])
    candle_range = df['high'] - df['low']
    lower_wick = df[['open', 'close']].min(axis=1) - df['low']
    upper_wick = df['high'] - df[['open', 'close']].max(axis=1)

    df['is_pin_bar'] = (lower_wick >= 0.55 * candle_range) & (upper_wick <= 0.25 * candle_range) & (candle_range > 0)
    df['is_hammer'] = (lower_wick >= 2 * body) & (upper_wick <= candle_range * 0.1) & (body > 0)

    # 🌊 Brad Goh Step 4: Liquidity Sweep (ราคากวาด Low 10 แท่งก่อนหน้าแล้วดึงกลับขึ้น)
    prior_low_10 = df['low'].shift(1).rolling(window=10).min()
    df['is_liquidity_sweep'] = (df['low'] < prior_low_10) & (df['close'] > prior_low_10)

    return df

def simulate_strategy(df, min_vol_ratio, min_adx, rsi_oversold):
    """
    จำลองการเทรดแบบครบวงจรรวมกลยุทธ์ Brad Goh SMC:
    - กลยุทธ์ 1: Trend Breakout ยืนยัน Vol & ADX
    - กลยุทธ์ 2: Pullback / Extreme Confluence (RSI <= rsi_oversold แตะ BB Lower)
    - กลยุทธ์ 3: Brad Goh SMC Reversal (Liquidity Sweep + Pin Bar Rejection)
    - การปิดออเดอร์:
      1. TP เป้าหมาย (2.5 ATR)
      2. SL ป้องกันทุน (1.5 ATR)
      3. Auto-Breakeven (+0.40%)
      4. Trailing Stop (+1.50%)
      5. Upper BB Exit: ปิดทำกำไรทันทีเมื่อราคาแตะ Upper BB และมีกำไร (Brad Goh SMC Rule)
    """
    trades = []
    in_pos = False
    entry_price = 0.0
    tp = 0.0
    sl = 0.0
    be_set = False

    for i in range(25, len(df)):
        row = df.iloc[i]
        price = row['close']
        high = row['high']
        low = row['low']
        atr = row['atr']
        rsi = row['rsi']
        adx = row['adx']
        vol = row['volume']
        bb_lower = row['bb_lower']
        bb_upper = row['bb_upper']
        ema_trend = row['ema_trend']
        is_pin_bar = row['is_pin_bar']
        is_hammer = row['is_hammer']
        is_liquidity_sweep = row['is_liquidity_sweep']
        
        # ปริมาณซื้อขายและราคา High ย้อนหลัง 10 แท่ง
        prev_high = df['high'].iloc[i-11:i-1].max()
        avg_vol = df['volume'].iloc[i-11:i-1].mean()
        vol_ratio = (vol / avg_vol) if avg_vol > 0 else 1.0

        if in_pos:
            pnl_pct = (price - entry_price) / entry_price
            
            # Auto-Breakeven at +0.40%
            if not be_set and pnl_pct >= 0.004:
                sl = entry_price * 1.0005
                be_set = True

            # Trailing Stop at +1.50%
            if pnl_pct >= 0.015:
                trailing = price * 0.99
                if trailing > sl:
                    sl = trailing

            # 🛡️ Exit Check:
            # 1. Stop Loss Hit
            if price <= sl:
                trades.append({'pnl': (sl - entry_price) / entry_price, 'type': 'LOSS', 'reason': 'SL'})
                in_pos = False
            # 2. Take Profit Hit (Fixed ATR Target)
            elif price >= tp:
                trades.append({'pnl': (tp - entry_price) / entry_price, 'type': 'WIN', 'reason': 'TP'})
                in_pos = False
            # 3. Brad Goh SMC Upper BB TP Exit (แตะ Upper BB ในขณะที่มีกำไร)
            elif price >= bb_upper and pnl_pct > 0:
                trades.append({'pnl': (price - entry_price) / entry_price, 'type': 'WIN', 'reason': 'UPPER_BB'})
                in_pos = False

        else:
            # Candlestick anatomy filter
            c_range = high - low
            wyckoff_valid = False
            if c_range > 0:
                clv = (price - low) / c_range
                uwr = (high - max(row['open'], price)) / c_range
                wyckoff_valid = (clv >= 0.65) and (uwr <= 0.35)

            # Strategy 1: Trend Breakout
            strat1 = (price > ema_trend) and (price > prev_high) and (vol_ratio >= min_vol_ratio) and (50 <= rsi <= 75) and (adx >= min_adx) and wyckoff_valid
            
            # Strategy 2: Pullback / Extreme Confluence (ปรับตาม rsi_oversold จาก Grid Search)
            strat2 = (price <= bb_lower * 1.002) and (rsi <= rsi_oversold)

            # Strategy 3: Brad Goh SMC Reversal (Liquidity Sweep + Pin Bar / Hammer Rejection)
            strat3 = is_liquidity_sweep and (is_pin_bar or is_hammer) and (rsi <= 48.0)

            if strat1 or strat2 or strat3:
                in_pos = True
                entry_price = price
                tp = entry_price + (2.5 * atr)
                sl = entry_price - (1.5 * atr)
                be_set = False

    return trades

def calculate_quant_sharpe(trades):
    """
    คำนวณคะแนนด้วย Quant Sharpe Score:
    Quant Sharpe Score = (WinRate * NetPnL) / (MaxDrawdown + 1)
    - WinRate (%): สัดส่วนไม้ชนะ 0 - 100%
    - NetPnL (%): ผลตอบแทนสุทธิรวม %
    - MaxDrawdown (%): ค่า Drawdown สูงสุดจากยอดสะสม (Peak)
    """
    if not trades:
        return 0.0, 0.0, 0.0, 0.0

    pnls = [t['pnl'] for t in trades]
    wins = sum(1 for t in trades if t['pnl'] > 0)
    win_rate = (wins / len(trades)) * 100.0
    net_pnl = sum(pnls) * 100.0

    cum_pnl = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum_pnl += p * 100.0
        if cum_pnl > peak:
            peak = cum_pnl
        dd = peak - cum_pnl
        if dd > max_dd:
            max_dd = dd

    # สูตร Quant Sharpe Score
    score = (win_rate * net_pnl) / (max_dd + 1.0)
    return score, win_rate, net_pnl, max_dd

def run_training_cycle(symbols=None, candle_limit=CANDLE_LIMIT):
    """
    ฟังก์ชันหลักสำหรับรันรอบ AI Retraining:
    - รองรับการเรียกใช้งานแบบ Standalone ผ่าน CLI
    - หรือ Import เข้าไปรันใน Thread / Supervisor ได้อย่างปลอดภัย
    - ทำ Grid Search พารามิเตอร์ SMC:
        * min_volume_ratio: [1.15, 1.25, 1.35, 1.45]
        * min_adx: [12.0, 14.0, 16.0, 18.0]
        * rsi_oversold: [28.0, 32.0, 35.0, 38.0]
    - คำนวณ Quant Sharpe Score
    - บันทึกลง agent_memory_multi.json แบบ Atomic
    """
    target_symbols = symbols or DEFAULT_SYMBOLS
    print("=" * 70, flush=True)
    print("🧠 RL OFFLINE PRE-TRAINING & BACKTESTING ENGINE (BRAD GOH SMC)", flush=True)
    print("=" * 70, flush=True)
    print(f"📊 พารามิเตอร์ Grid Search (64 Combinations ต่อเหรียญ):", flush=True)
    print(f"  • min_volume_ratio : [1.15, 1.25, 1.35, 1.45]", flush=True)
    print(f"  • min_adx          : [12.0, 14.0, 16.0, 18.0]", flush=True)
    print(f"  • rsi_oversold     : [28.0, 32.0, 35.0, 38.0]", flush=True)
    print(f"  • Target Strategy  : Liquidity Sweep, Pin Bar Rejection, Upper BB Exit", flush=True)
    print(f"  • Score Function   : (WinRate * NetPnL) / (MaxDrawdown + 1)", flush=True)
    print("-" * 70, flush=True)

    exchange = get_exchange()

    # โหลด memory เดิม
    mem = {}
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                mem = json.load(f)
        except Exception:
            mem = {}

    print(f"\n📡 กำลังดาวน์โหลดข้อมูลสด M15 จาก Binance Public API ({len(target_symbols)} เหรียญ)...", flush=True)
    results_summary = []

    vol_grid = [1.15, 1.25, 1.35, 1.45]
    adx_grid = [12.0, 14.0, 16.0, 18.0]
    rsi_grid = [28.0, 32.0, 35.0, 38.0]

    for sym in target_symbols:
        try:
            time.sleep(0.3)
            bars = exchange.fetch_ohlcv(sym, timeframe=TIMEFRAME, limit=candle_limit)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = calculate_indicators(df).dropna()

            best_score = -999999.0
            best_params = {"min_volume_ratio": 1.25, "min_adx": 14.0, "rsi_oversold": 32.0}
            best_stats = {"trades": 0, "win_rate": 0.0, "total_pnl": 0.0, "max_dd": 0.0, "score": 0.0}

            # Grid Search 64 Combinations (4 x 4 x 4)
            for vol_param in vol_grid:
                for adx_param in adx_grid:
                    for rsi_param in rsi_grid:
                        trades = simulate_strategy(df, vol_param, adx_param, rsi_param)
                        if len(trades) >= 3:
                            score, win_rate, net_pnl, max_dd = calculate_quant_sharpe(trades)
                            if score > best_score:
                                best_score = score
                                best_params = {
                                    "min_volume_ratio": vol_param,
                                    "min_adx": adx_param,
                                    "rsi_oversold": rsi_param
                                }
                                best_stats = {
                                    "trades": len(trades),
                                    "win_rate": win_rate,
                                    "total_pnl": net_pnl,
                                    "max_dd": max_dd,
                                    "score": score
                                }

            # หากจำนวนไม้น้อยกว่า 3 ในทุก Combination ให้ใช้ค่า default ที่ดีที่สุด
            if best_stats["trades"] == 0 and len(df) > 50:
                trades = simulate_strategy(df, 1.25, 14.0, 32.0)
                if trades:
                    score, win_rate, net_pnl, max_dd = calculate_quant_sharpe(trades)
                    best_stats = {
                        "trades": len(trades),
                        "win_rate": win_rate,
                        "total_pnl": net_pnl,
                        "max_dd": max_dd,
                        "score": score
                    }

            # อัปเดต Memory ของเหรียญ
            if sym not in mem:
                mem[sym] = {
                    "total_trades": best_stats["trades"],
                    "wins": int(best_stats["trades"] * (best_stats["win_rate"] / 100.0)),
                    "losses": best_stats["trades"] - int(best_stats["trades"] * (best_stats["win_rate"] / 100.0)),
                    "learned_params": best_params,
                    "reflections": []
                }
            else:
                mem[sym]["learned_params"] = best_params

            results_summary.append({
                "symbol": sym,
                "vol": best_params["min_volume_ratio"],
                "adx": best_params["min_adx"],
                "rsi_os": best_params["rsi_oversold"],
                "trades": best_stats["trades"],
                "win_rate": best_stats["win_rate"],
                "pnl": best_stats["total_pnl"],
                "max_dd": best_stats["max_dd"],
                "score": best_stats["score"]
            })

            print(
                f"✅ {sym:10s} | Vol: {best_params['min_volume_ratio']:.2f}x | "
                f"ADX: {best_params['min_adx']:.1f} | RSI_OS: {best_params['rsi_oversold']:.1f} | "
                f"WinRate: {best_stats['win_rate']:5.1f}% | ไม้: {best_stats['trades']:2d} | "
                f"PnL: {best_stats['total_pnl']:+6.2f}% | MaxDD: {best_stats['max_dd']:4.2f}% | "
                f"Score: {best_stats['score']:6.2f}",
                flush=True
            )

        except Exception as e:
            print(f"⚠️ {sym} error: {e}", flush=True)

    # บันทึกผลลัพธ์ลง agent_memory_multi.json แบบ Atomic (.tmp + replace) ป้องกันไฟล์เสียหาย
    try:
        tmp_file = MEMORY_FILE + ".tmp"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, MEMORY_FILE)
        print("\n" + "=" * 70, flush=True)
        print("🎯 บันทึกผลลัพธ์ AI Retraining (Brad Goh SMC) ลง agent_memory_multi.json สำเร็จ 100%!", flush=True)
        print("=" * 70, flush=True)
    except Exception as e:
        print(f"❌ ไม่สามารถบันทึก {MEMORY_FILE}: {e}", flush=True)

    return results_summary

if __name__ == '__main__':
    run_training_cycle()
