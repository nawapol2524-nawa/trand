# Risk Engine & Capital Preservation Model
**Version**: 1.1.0  
**Status**: ACTIVE & FROZEN

---

## 1. Core Risk Mandates

1. **Risk per Trade**: Maximum $1.0\%$ of account equity per trade.
2. **Maximum Daily Loss**: Maximum $5.0\%$ drawdown from daily opening balance (UTC midnight reset).
3. **Maximum Consecutive Losses**: $5$ consecutive losses trigger a mandatory 1-hour trading halt.
4. **Maximum Concurrent Open Positions**: $3$ total positions across all symbols.
5. **Maximum Exposure per Symbol**: $5.0\%$ of equity.
6. **Emergency Kill Switch**: Environment variable `EMERGENCY_KILL_SWITCH=true` immediately halts all order creation and triggers position liquidation if configured.
7. **AI Independence**: The AI layer has **ZERO authority** to override, loosen, or modify any risk parameter.

---

## 2. Dynamic Position Sizing Formula

$$\text{Risk Amount (\$) } = \text{Account Equity} \times \text{Risk Per Trade Pct (0.01)}$$

$$\text{Stop Distance (Points) } = \max(\text{ATRMultiplier} \times \text{ATR}_{14},\; \text{MinSL}_{\text{symbol}})$$

$$\text{Lot Size } = \frac{\text{Risk Amount}}{\text{Stop Distance} \times \text{Point Value}}$$

* The calculated lot size is clamped to `[min_volume, max_volume]` and rounded to the broker's `volume_step`.
* If the calculated lot size is below `min_volume`, the trade is **REJECTED** (no over-leveraging permitted).

### ATR Multiplier & Minimum SL Floor (v1.1.0)

| Symbol | ATR Multiplier | Min SL (pips) | Pip Size |
|--------|---------------|---------------|----------|
| EURUSD | 2.5x | 12 | 0.0001 |
| GBPUSD | 2.5x | 15 | 0.0001 |
| USDJPY | 2.5x | 12 | 0.01 |
| XAUUSD | 2.0x | 200 | 0.01 |

The SL distance is the **maximum** of `ATR × Multiplier` and `MinSL × PipSize`. This prevents market noise from triggering stop-outs during low-volatility M5 sessions.

---

## 3. Cooldown Filter (v1.1.0)

After any trade closes (TP or SL), the bot waits **6 M5 bars (30 minutes)** before allowing a new trade on the same symbol. This prevents:
- Re-entering at the same price level immediately after being stopped out
- Chasing the market after a profitable trade closes

---

## 4. Daily Reset Cycle
* Timezone: Strictly **UTC midnight** (`00:00:00 UTC`).
* Account daily starting balance is snapshotted at UTC midnight.
* Daily cumulative PnL includes both realized and floating PnL.

---

## 5. Target R:R 1:1.2 & Break-Even Enforcement (Steady Profit & Capital Preservation)
To maximize win rate, bank consistent profits, and enforce capital preservation:
* **Default Target R:R**: `1:1.2` (`rr_ratio = 1.2`)
* **ATR Multipliers**: 
  - Stop Loss: `2.5x ATR`
  - Take Profit: `3.0x ATR` ($3.0 / 2.5 = 1.2\text{ R:R}$)
* **Break-Even / Risk-Free Rule (+1.0R)**:
  - When floating profit reaches $+1.0R$ ($\text{profit distance} \ge \text{sl\_distance}$), the Stop Loss is **immediately amended to Entry Price** on the broker.
  - Position becomes completely **risk-free**, protecting seed capital against sudden market reversals while letting price run toward the 1.2R target.

