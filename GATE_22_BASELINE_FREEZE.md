# GATE 22 — BASELINE IMMUTABILITY & SPECIFICATION FREEZE
**Authority:** Institutional Quantitative Systems Audit & Software Quality Engineering  
**Baseline Git Commit:** `d25bc7007c14d7269c78cb88c6a5a0e9d9b8a6eb`  
**Freeze Timestamp:** 2026-09-18T17:48:00+07:00 (UTC 10:48:00)  
**Status:** **`FROZEN_IMMUTABLE`**

---

## 1. Frozen Code & Artifact State

All components of the Gate 21 Verified Baseline are hereby frozen. Under Gate 22 research protocols, **no research modifications or feature/model selection decisions may utilize the Frozen Test holdout set**.

### 1.1 Cryptographic Artifact Checksums (SHA-256)

| Artifact Component | File Path | SHA-256 Checksum |
|--------------------|-----------|------------------|
| **Clean Dataset (EUR/USD M15)** | `data/clean/frxEURUSD_M15.parquet` | `589e88bde33761ff1a426b0430fc8559cc40d41278a30a734b3c8670df6bd801` |
| **Clean Dataset (GBP/USD M15)** | `data/clean/frxGBPUSD_M15.parquet` | `40600dda987d1b449e1d769fdcc38827d5b5e8a21682c4ca1e0acd898c5eda3e` |
| **Clean Dataset (USD/JPY M15)** | `data/clean/frxUSDJPY_M15.parquet` | `f0cf8c79d0ed48664361a819f5ab5b204a8470118b2f0c082a3e353aafb3351c` |
| **Clean Dataset (Gold M15)** | `data/clean/frxXAUUSD_M15.parquet` | `1594c08117b1b07880418a06dea4ae307187eec41e3799ddf77dfffcdf4e6a14` |
| **Feature Pipeline** | `ai_forex_bot/features/builder.py` | `5baf0b0aed5db319612501771434dd2253aa1750a5b7e9935f74fec7688a44d0` |
| **Labeling Engine** | `ai_forex_bot/labels/labeler.py` | `3f295420182cef64b3b9cad525ec0af4a6fcd3fc91ca624ee5f40de9917e37c9` |
| **Purged Splitter** | `ai_forex_bot/data/market/split.py` | `fa007f1ac52b6d7942cf10600a4547f18bc80eadb7cf8a7f127753f3ea095721` |
| **Symbol Specification** | `configs/symbols.yaml` | `90605f37bcd6123d39f340c02b8ee995e778df2c0b798c34cacaaecbc2c681d4` |
| **System Configuration** | `configs/system.yaml` | `efda63e7989b58ec1cff7d58028d8a77809c7336198bfd4e01ff89063ad938a5` |

---

## 2. Frozen Test Boundaries & Dataset Sizing

For `frxEURUSD` M15 (24,195 clean, labeled bars):
- **Train Fold:** Rows `[0, 16931]` (16,932 bars) | `2025-09-18 21:15:00 UTC` to `2026-06-02 13:15:00 UTC`
- **Purge Train Boundary:** 4 bars purged (`2026-06-02 13:30:00 UTC` to `2026-06-02 14:15:00 UTC`)
- **Validation Fold:** Rows `[16936, 20560]` (3,625 bars) | `2026-06-02 14:30:00 UTC` to `2026-07-27 08:30:00 UTC`
- **Purge Val Boundary:** 4 bars purged (`2026-07-27 08:45:00 UTC` to `2026-07-27 09:30:00 UTC`)
- **Frozen Test Fold (IMMUTABLE):** Rows `[20565, 24194]` (3,630 bars) | `2026-07-27 09:45:00 UTC` to `2026-09-18 09:45:00 UTC`

---

## 3. Frozen Baseline Results (Gate 21 Reference)

| Model | Balanced Acc | Macro F1 | Brier Macro | Trades | Net PnL ($) | Profit Factor | Max DD (%) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Majority Class** | 0.3333 | 0.3235 | 0.0384 | 0 | $0.00 | N/A | 0.00% |
| **Empirical Prior** | 0.3585 | 0.3378 | 0.0420 | 0 | $0.00 | N/A | 0.00% |
| **Simple Trend** | 0.4078 | 0.0459 | 0.4698 | 24 | -$111.61 | 0.43 | 15.53% |
| **Simple Momentum**| 0.3299 | 0.0372 | 0.4729 | 77 | +$182.24 | 1.49 | 8.48% |
| **Logistic Regression**| 0.3502 | 0.3512 | 0.0354 | 0 | $0.00 | N/A | 0.00% |
| **Random Forest** | 0.3514 | 0.3562 | 0.0339 | 0 | $0.00 | N/A | 0.00% |
| **HistGradientBoosting**| 0.3333 | 0.3235 | 0.0363 | 0 | $0.00 | N/A | 0.00% |

---

## 4. Research Invariants for Gate 22

1. **Frozen Test Sanctity:**
   The 3,630 bars of the Frozen Test holdout set must NOT be inspected, used for feature selection, label redesign, threshold tuning, or model selection.
2. **Research Fold Scope:**
   All exploratory investigations, feature ablations, model comparisons, and hyperparameter trials will be executed strictly on:
   - The **Purged Validation Fold** (3,625 bars), and/or
   - The **Purged Walk-Forward Slices** (sliding train/validation windows across the training+validation historical span).
3. **Consumption Protocol:**
   The Frozen Test set will be evaluated exactly once at the conclusion of Gate 22, to report final out-of-sample performance for candidate architectures chosen entirely prior to test exposure.
