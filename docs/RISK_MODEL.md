# Institutional Risk & Capital Protection Model

## 1. Absolute Veto Principles
The Risk Engine operates as an independent gatekeeper between the Decision Engine and the Execution Layer. Every proposed trade must receive unconditional approval (`RiskDecision.APPROVE`).

## 2. Hard Risk Limits
1. **Maximum Risk Per Trade:** 1.0% of current equity.
2. **Maximum Daily Loss Limit:** \$2.00 hard threshold.
3. **UTC Calendar Day Reset:** Automatically unlatches kill switch and zeroes daily loss on UTC midnight transition, even if 0 trades were executed.
4. **Maximum Concurrent Open Positions:** Maximum 2 positions across all symbols.
5. **Currency Exposure Cap:** Prevents concentrated exposure (e.g. maximum 1 active long USD exposure across EURUSD, GBPUSD, USDJPY).
6. **Per-Symbol Spread Gate:** Distinct maximum spread limits per instrument (Forex <= 1.8-2.2 pips, Gold <= 35.0 pips).

## 3. Dynamic Position Sizing Formula
$$\text{Position Size (Lots)} = \text{clamp}\left(\text{round}\left(\frac{\text{Equity} \times \text{Risk}\%}{\text{SL\_Pips} \times \text{Pip\_Value\_per\_Lot}}, \text{Step}\right), \text{Min\_Lot}, \text{Max\_Lot}\right)$$
Before dispatch, required margin is verified against available free margin.
