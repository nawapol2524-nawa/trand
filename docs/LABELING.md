# Target & Labeling Methodology

## 1. Primary Concept: Net Return After Cost
Unlike naive systems that classify every positive bar as a `BUY`, institutional models account for market friction:
$$\text{Cost} = \text{Spread} + \text{Commission} + \text{Estimated Slippage}$$

For a long trade entered at $C_t$ and evaluated over horizon $H$:
$$\text{net\_return}_{\text{buy}} = \frac{C_{t+H} - C_t - \text{Cost}}{C_t}$$

For a short trade entered at $C_t$:
$$\text{net\_return}_{\text{sell}} = \frac{C_t - C_{t+H} - \text{Cost}}{C_t}$$

## 2. Triple-Barrier Target Labeling
We employ Marcos López de Prado’s Triple-Barrier Method:
1. **Upper Barrier (Take-Profit):** $C_t + \text{PT}_{\text{price}}$
2. **Lower Barrier (Stop-Loss):** $C_t - \text{SL}_{\text{price}}$
3. **Temporal Barrier (Expiration):** $t + H$

### Discrete Target Classes:
- **`0` (HOLD):** Neither profit target achieved without stopping out, or market noise dominates.
- **`1` (BUY):** Price touches Take-Profit barrier before Stop-Loss barrier within horizon $H$.
- **`2` (SELL):** Price touches Short Take-Profit barrier before Stop-Loss barrier within horizon $H$.

## 3. Boundary Masking
The final $H$ bars of any historical series are explicitly truncated to avoid right-edge lookahead contamination where full forward windows cannot be evaluated.
