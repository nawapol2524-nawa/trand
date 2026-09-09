import json
import time
import os
import ccxt
import pandas as pd
import numpy as np

# ==========================================
# ⚙️ CONFIGURATION & TARGET SYMBOLS
# ==========================================
SYMBOLS = ['SOL/USDT', 'BTC/USDT', 'NEAR/USDT', 'AVAX/USDT', 'GALA/USDT', 'VET/USDT']
TIMEFRAME = '15m'
CANDLE_LIMIT = 500  # ดึง 500 แท่งย้อนหลังต่อเหรียญ (~5 วันล่าสุด)
MEMORY_FILE = 'agent_memory_multi.json'

print("=" * 65)
print("🧠 RL OFFLINE PRE-TRAINING & BACKTESTING ENGINE")
print("=" * 65)

exchange = ccxt.binance({
    'enableRateLimit': True,
    'timeout': 15000
})

def calculate_indicators(df):
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

    # Bollinger Bands (20, 2)
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['bb_lower'] = df['sma20'] - (2 * df['std20'])

    # 1h EMA200 Proxy on 15m (4 * 200 = 800 periods)
    df['ema_trend'] = df['close'].ewm(span=200, adjust=False).mean()

    return df

def simulate_strategy(df, min_vol_ratio, min_adx):
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
        ema_trend = row['ema_trend']
        
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

            # Trailing Stop at +1.5%
            if pnl_pct >= 0.015:
                trailing = price * 0.99
                if trailing > sl:
                    sl = trailing

            # Exit Check
            if price >= tp:
                trades.append({'pnl': (tp - entry_price) / entry_price, 'type': 'WIN'})
                in_pos = False
            elif price <= sl:
                trades.append({'pnl': (sl - entry_price) / entry_price, 'type': 'LOSS'})
                in_pos = False

        else:
            # Candlestick anatomy filter
            c_range = high - low
            wyckoff_valid = False
            if c_range > 0:
                clv = (price - low) / c_range
                uwr = (high - max(row['open'], price)) / c_range
                wyckoff_valid = (clv >= 0.65) and (uwr <= 0.35)

            # Strategy 1: Breakout
            strat1 = (price > ema_trend) and (price > prev_high) and (vol_ratio >= min_vol_ratio) and (50 <= rsi <= 75) and (adx >= min_adx) and wyckoff_valid
            
            # Strategy 2: Pullback
            strat2 = (price <= bb_lower * 1.002) and (rsi <= 40)

            if strat1 or strat2:
                in_pos = True
                entry_price = price
                tp = entry_price + (2.5 * atr)
                sl = entry_price - (1.5 * atr)
                be_set = False

    return trades

def optimize():
    # โหลด memory เดิม
    mem = {}
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                mem = json.load(f)
        except Exception:
            pass

    print(f"\n📡 กำลังดาวน์โหลดข้อมูลสด M15 จาก Binance Public API...")
    results_summary = []

    for sym in SYMBOLS:
        try:
            time.sleep(0.5)
            bars = exchange.fetch_ohlcv(sym, timeframe=TIMEFRAME, limit=CANDLE_LIMIT)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = calculate_indicators(df).dropna()

            best_score = -999999
            best_params = {"min_volume_ratio": 1.30, "min_adx": 14.0}
            best_stats = {"trades": 0, "win_rate": 0.0, "total_pnl": 0.0}

            # Grid search
            for vol_param in [1.15, 1.25, 1.35, 1.45]:
                for adx_param in [12.0, 14.0, 16.0, 18.0]:
                    trades = simulate_strategy(df, vol_param, adx_param)
                    if len(trades) >= 3:
                        pnls = [t['pnl'] for t in trades]
                        wins = sum(1 for t in trades if t['pnl'] > 0)
                        win_rate = (wins / len(trades)) * 100
                        tot_pnl = sum(pnls) * 100
                        losses = [t['pnl'] for t in trades if t['pnl'] < 0]
                        max_loss = abs(min(losses)) * 100 if losses else 0.5
                        
                        # Score function: Reward higher win rate and net pnl, penalize drawdowns
                        score = (win_rate * tot_pnl) / (max_loss + 1.0)
                        if score > best_score:
                            best_score = score
                            best_params = {"min_volume_ratio": vol_param, "min_adx": adx_param}
                            best_stats = {"trades": len(trades), "win_rate": win_rate, "total_pnl": tot_pnl}

            if sym not in mem:
                mem[sym] = {
                    "total_trades": best_stats["trades"],
                    "wins": int(best_stats["trades"] * (best_stats["win_rate"] / 100)),
                    "losses": best_stats["trades"] - int(best_stats["trades"] * (best_stats["win_rate"] / 100)),
                    "learned_params": best_params,
                    "reflections": []
                }
            else:
                mem[sym]["learned_params"] = best_params

            results_summary.append({
                "symbol": sym,
                "vol": best_params["min_volume_ratio"],
                "adx": best_params["min_adx"],
                "trades": best_stats["trades"],
                "win_rate": best_stats["win_rate"],
                "pnl": best_stats["total_pnl"]
            })
            print(f"✅ {sym:10s} | Vol: {best_params['min_volume_ratio']}x | ADX: {best_params['min_adx']} | WinRate: {best_stats['win_rate']:.1f}% | ไม้: {best_stats['trades']} | PnL: {best_stats['total_pnl']:+.2f}%")

        except Exception as e:
            print(f"⚠️ {sym} error: {e}")

    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 65)
    print("🎯 ปรับแต่งและบันทึกโมเดล AI RL ลง agent_memory_multi.json สำเร็จ!")
    print("=" * 65)

if __name__ == '__main__':
    optimize()
