# Data Pipeline Architecture

## 1. Raw to Clean Data Flow
```text
[Raw M1 Parquets] ➔ [DataValidator] ➔ [UTC Timestamp Normalization] ➔ [Multi-Timeframe Resampler] ➔ [data/clean/ Parquet Lake]
```

## 2. Validation Stages
1. **Schema & Types:** Columns `epoch`, `open`, `high`, `low`, `close` verified as non-null floats/ints.
2. **Mathematical Integrity:** Strict validation of OHLC bounds:
   $$\text{low} \le \min(\text{open}, \text{close}) \le \max(\text{open}, \text{close}) \le \text{high}$$
3. **Monotonicity & Continuity:** Consecutive epoch checks; duplicate rejection; weekend gap recognition.
4. **Timeframe Aggregation Rules:**
   - Bar Start Epoch convention: $T_{\text{bin}} = \lfloor \text{epoch} / \Delta T \rfloor \times \Delta T$
   - $\text{open} = \text{first}(\text{open})$, $\text{high} = \max(\text{high})$, $\text{low} = \min(\text{low})$, $\text{close} = \text{last}(\text{close})$.

## 3. Dataset Manifest
Persisted at `data/clean/dataset_manifest.json` with SHA-256 hashes, timestamps, and row counts.
