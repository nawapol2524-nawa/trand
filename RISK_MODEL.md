# Risk Engine & Capital Preservation Model
**Version**: 1.0.0  
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

$$\text{Stop Distance (Points) } = \text{ATRMultiplier} \times \text{ATR}_{14}$$

$$\text{Lot Size } = \frac{\text{Risk Amount}}{\text{Stop Distance} \times \text{Point Value}}$$

* The calculated lot size is clamped to `[min_volume, max_volume]` and rounded to the broker's `volume_step`.
* If the calculated lot size is below `min_volume`, the trade is **REJECTED** (no over-leveraging permitted).

---

## 3. Daily Reset Cycle
* Timezone: Strictly **UTC midnight** (`00:00:00 UTC`).
* Account daily starting balance is snapshotted at UTC midnight.
* Daily cumulative PnL includes both realized and floating PnL.
