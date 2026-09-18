# Quantitative Feature Dictionary

**System Architecture:** Multi-Timeframe Causal Feature Engine  
**Standard Guarantee:** Zero Future Lookahead. All features are computed strictly from completed bars prior to or at current decision epoch.

---

## 1. Feature Specifications

| Feature Name | Category | Formula / Definition | Timeframe | Lookback | Input | Timestamp Behavior | Leakage Mitigation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `ret_1` | Returns | $\ln(C_t / C_{t-1})$ | Base (M15) | 1 bar | Close | Causal shift 1 | Computed on completed close only |
| `ret_5` | Returns | $\ln(C_t / C_{t-5})$ | Base (M15) | 5 bars | Close | Causal shift 5 | Strict past lookback |
| `ret_15` | Returns | $\ln(C_t / C_{t-15})$ | Base (M15) | 15 bars | Close | Causal shift 15 | Strict past lookback |
| `realized_vol_20`| Volatility | $\text{std}(\text{ret}_1)_{20}$ | Base (M15) | 20 bars | `ret_1` | Rolling backward | No future returns included |
| `dist_ema_20` | Trend | $(C_t - \text{EMA}_{20}(C)) / C_t$ | Base (M15) | 20 bars | Close | Exponential decay | Evaluated at bar close $t$ |
| `dist_ema_50` | Trend | $(C_t - \text{EMA}_{50}(C)) / C_t$ | Base (M15) | 50 bars | Close | Exponential decay | Evaluated at bar close $t$ |
| `dist_ema_200`| Trend | $(C_t - \text{EMA}_{200}(C)) / C_t$ | Base (M15) | 200 bars | Close | Exponential decay | Evaluated at bar close $t$ |
| `ema_spread_20_50`| Trend | $(\text{EMA}_{20} - \text{EMA}_{50}) / C_t$ | Base (M15) | 50 bars | Close | Dual EMA diff | Normalized by current price |
| `atr_14` | Volatility | $\text{SMA}_{14}(\text{TR})$ | Base (M15) | 14 bars | High, Low, Close | Causal True Range | Prior close used for gap |
| `norm_atr_14` | Volatility | $\text{ATR}_{14} / C_t$ | Base (M15) | 14 bars | ATR, Close | Scale-invariant | Normalized across price levels |
| `bb_bandwidth`| Volatility | $(U_{20} - L_{20}) / \text{SMA}_{20}$ | Base (M15) | 20 bars | Close | Standard 2.0 std | Standard deviation strictly causal |
| `bb_pct_b` | Oscillator | $(C_t - L_{20}) / (U_{20} - L_{20})$ | Base (M15) | 20 bars | Close | Bollinger %B | Relative position in band |
| `rsi_14` | Momentum | $100 - (100 / (1 + RS_{14}))$ | Base (M15) | 14 bars | Close diffs | Wilders-smoothed | Strictly backwards |
| `macd_hist` | Momentum | $(\text{MACD}_{12,26} - \text{Signal}_9) / C_t$ | Base (M15) | 35 bars | Close | Dual EMA oscillator | Normalized by price |
| `adx_14` | Trend Strength | Directional Movement Index | Base (M15) | 14 bars | High, Low, Close | Smoothed DX | Zero future lookahead |
| `candle_body_ratio` | Price Action | $|C_t - O_t| / (H_t - L_t)$ | Base (M15) | 1 bar | OHLC | Intrabar structure | Evaluated once bar is closed |
| `candle_upper_wick_ratio` | Price Action | $(H_t - \max(O_t, C_t)) / \text{Range}$ | Base (M15) | 1 bar | OHLC | Selling pressure | Evaluated once bar is closed |
| `candle_lower_wick_ratio` | Price Action | $(\min(O_t, C_t) - L_t) / \text{Range}$ | Base (M15) | 1 bar | OHLC | Buying rejection | Evaluated once bar is closed |
| `range_pos_20`| Support/Resist | $(C_t - \min_{20}(L)) / (\max_{20}(H) - \min_{20}(L))$ | Base (M15) | 20 bars | High, Low, Close | Donchian channel pos | Strict 20-bar window |
| `regime_code` | Market Regime | Discrete code: Up(1), Down(-1), Range(0), HighVol(2), LowVol(-2), Uncertain(3) | Base (M15) | Multi | ADX, EMAs, ATR | Rule-based baseline | Mutually exclusive |
| `h1_dist_ema_50` | Multi-Timeframe | $(C_{\text{H1}} - \text{EMA}_{50}(C_{\text{H1}})) / C$ | Higher (H1) | 50 H1 bars | H1 Close | **Available at $T_{\text{start}} + 3600$** | **Strict `direction=backward` merge** |
| `h1_trend_bull` | Multi-Timeframe | $C_{\text{H1}} > \text{EMA}_{50}(C_{\text{H1}})$ | Higher (H1) | 50 H1 bars | H1 Close | **Available at $T_{\text{start}} + 3600$** | Bar completion invariant |
| `is_london_session` | Session | Indicator (1/0) if 07:00 <= UTC < 16:00 | Temporal | Instant | UTC Hour | Deterministic | Exact UTC calculation |
| `is_ny_session` | Session | Indicator (1/0) if 12:00 <= UTC < 21:00 | Temporal | Instant | UTC Hour | Deterministic | Exact UTC calculation |
| `is_london_ny_overlap` | Session | Indicator (1/0) if 12:00 <= UTC < 16:00 | Temporal | Instant | UTC Hour | Peak liquidity window | Exact UTC calculation |
| `econ_is_blackout` | Economic Context | Indicator (1/0) for 15m pre/post blackout | Macro | Event window | Scheduled Epoch | Pre-event countdown | Strict event schedule |
| `econ_surprise` | Macroeconomic | $\text{Actual} - \text{Forecast}$ | Macro | Post-release | Actual Release | **Visible ONLY after publication** | Guaranteed no pre-release leak |
| `news_sentiment` | News Context | Exponentially decaying NLP score | News | 6-hour decay | Headline NLP | Causal timestamp filter | Published articles only |
